"""ASGI tests for the hello-upstream catalog package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
import uuid
from pathlib import Path

import jwt
import pytest
import yaml
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "server.py"
IDENTITY_PATH = ROOT / "keystone_identity.py"
MANIFEST_PATH = ROOT / "keystone-service.yaml"
POLICY_PATH = ROOT / "policy.example.yaml"

REFERENCE_IDENTITY_SHA256 = "50058263846b41b5c9a88e303b6e9ac6768297d8f7f6564f4a4c0da247b4429f"
REFERENCE_IDENTITY_SOURCE = (
    "keystone-codes/keystone-mcp@f73310df8634a19406bf21972e023af9a3b44ac0:"
    "examples/keystone-identity/python/keystone_identity.py"
)

TEST_BEARER = "hello-test-bearer-token-" + "a" * 16
TEST_SECRET = "hello-test-identity-secret-" + "b" * 16
TEST_AUDIENCE = "hello-upstream"
WRONG_BEARER = "wrong-bearer-token-" + "z" * 20

SEARCH_SCHEMA_CANONICAL = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query text"},
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "default": 5,
            "description": "How many results to return",
        },
        "filter": {"type": "string", "enum": ["all", "mine"]},
    },
    "required": ["query", "filter"],
}


def _load_server_module(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("HELLO_BEARER_TOKEN", TEST_BEARER)
    monkeypatch.setenv("HELLO_IDENTITY_SECRET", TEST_SECRET)
    monkeypatch.setenv("HELLO_IDENTITY_AUDIENCE", TEST_AUDIENCE)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    module_name = f"_hello_server_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_identity_token(
    *,
    secret: str = TEST_SECRET,
    audience: str = TEST_AUDIENCE,
    mcp_target: str,
    sub: str = "ann@example.com",
) -> str:
    now = int(time.time())
    claims = {
        "iss": "http://localhost:8080",
        "aud": audience,
        "sub": sub,
        "sub_type": "human",
        "roles": ["member"],
        "rbac": "enforce",
        "auth_method": "google",
        "interactive": True,
        "task_id": "t_test",
        "mcp_method": "tools/call",
        "mcp_target": mcp_target,
        "iat": now,
        "exp": now + 300,
        "email": sub,
    }
    return jwt.encode(
        claims,
        secret,
        algorithm="HS256",
        headers={"typ": "keystone-identity+jwt"},
    )


def _parse_mcp_body(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line.removeprefix("data:").strip())
    raise AssertionError(f"unexpected MCP response body: {raw[:200]!r}")


@pytest.fixture
def hello_server(monkeypatch: pytest.MonkeyPatch):
    return _load_server_module(monkeypatch)


@pytest.fixture
async def client(hello_server):
    transport = ASGITransport(app=hello_server.app)
    async with LifespanManager(hello_server.app):
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def _mcp_request(
    client: AsyncClient,
    *,
    method: str = "POST",
    rpc_method: str | None = "tools/list",
    params: dict | None = None,
    bearer: str | None = TEST_BEARER,
    identity: str | None = None,
) -> tuple[int, dict | None]:
    headers = {"Accept": "application/json, text/event-stream"}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if identity is not None:
        headers["X-Keystone-Identity"] = identity
    if method == "POST":
        headers["Content-Type"] = "application/json"
        body = {"jsonrpc": "2.0", "id": 1, "method": rpc_method, "params": params or {}}
        response = await client.post("/mcp", headers=headers, json=body)
    else:
        response = await client.request(method, "/mcp", headers=headers)
    if response.status_code == 401:
        return response.status_code, response.json()
    payload = _parse_mcp_body(response.text) if response.text else None
    return response.status_code, payload


@pytest.mark.asyncio
async def test_healthz_is_open(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_mcp_requires_bearer(client: AsyncClient) -> None:
    for method in ("GET", "DELETE"):
        status, body = await _mcp_request(client, method=method, rpc_method=None, bearer=None)
        assert status == 401
        assert body == {"error": "unauthorized"}

    status, body = await _mcp_request(client, bearer=None)
    assert status == 401
    assert body == {"error": "unauthorized"}

    status, body = await _mcp_request(client, bearer=WRONG_BEARER)
    assert status == 401
    assert body == {"error": "unauthorized"}


@pytest.mark.asyncio
async def test_list_tools_with_bearer_only(client: AsyncClient) -> None:
    status, payload = await _mcp_request(client, rpc_method="tools/list", identity=None)
    assert status == 200
    assert payload is not None
    tools = payload["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["greet", "search", "whoami"]
    search = next(tool for tool in tools if tool["name"] == "search")
    assert search["inputSchema"] == SEARCH_SCHEMA_CANONICAL


@pytest.mark.asyncio
async def test_call_without_identity_is_rejected(client: AsyncClient) -> None:
    status, payload = await _mcp_request(
        client,
        rpc_method="tools/call",
        params={"name": "greet", "arguments": {"name": "Ann"}},
        identity=None,
    )
    assert status == 200
    assert payload is not None
    result = payload["result"]
    assert result.get("isError") is True
    assert "identity rejected" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_forged_author_email_is_rejected(client: AsyncClient) -> None:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TEST_BEARER}",
        "X-Author-Email": "boss@example.com",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "greet", "arguments": {"name": "Ann"}},
    }
    response = await client.post("/mcp", headers=headers, json=body)
    payload = _parse_mcp_body(response.text)
    result = payload["result"]
    assert result.get("isError") is True
    assert "identity rejected" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_valid_assertion_greets_subject(client: AsyncClient) -> None:
    token = _make_identity_token(mcp_target="greet")
    status, payload = await _mcp_request(
        client,
        rpc_method="tools/call",
        params={"name": "greet", "arguments": {"name": "Ann"}},
        identity=token,
    )
    assert status == 200
    text = payload["result"]["content"][0]["text"]
    assert text == "Hello, Ann! You are ann@example.com."


@pytest.mark.asyncio
async def test_wrong_audience_or_secret_rejected(client: AsyncClient) -> None:
    bad_audience = _make_identity_token(mcp_target="greet", audience="other-upstream")
    status, payload = await _mcp_request(
        client,
        rpc_method="tools/call",
        params={"name": "greet", "arguments": {"name": "Ann"}},
        identity=bad_audience,
    )
    assert payload["result"].get("isError") is True

    bad_secret = _make_identity_token(mcp_target="greet", secret=TEST_SECRET + "-wrong")
    status, payload = await _mcp_request(
        client,
        rpc_method="tools/call",
        params={"name": "greet", "arguments": {"name": "Ann"}},
        identity=bad_secret,
    )
    assert payload["result"].get("isError") is True


@pytest.mark.asyncio
async def test_assertion_for_other_tool_rejected(client: AsyncClient) -> None:
    token = _make_identity_token(mcp_target="search")
    status, payload = await _mcp_request(
        client,
        rpc_method="tools/call",
        params={"name": "greet", "arguments": {"name": "Ann"}},
        identity=token,
    )
    assert payload["result"].get("isError") is True
    assert "identity rejected" in payload["result"]["content"][0]["text"]


def test_config_requires_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_server_module(monkeypatch)
    monkeypatch.delenv("HELLO_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("HELLO_IDENTITY_SECRET", "x" * 31)
    with pytest.raises(SystemExit) as exc:
        module.load_config()
    assert exc.value.code == 2


def test_identity_module_is_unmodified_copy() -> None:
    digest = hashlib.sha256(IDENTITY_PATH.read_bytes()).hexdigest()
    assert digest == REFERENCE_IDENTITY_SHA256
    assert REFERENCE_IDENTITY_SOURCE.startswith("keystone-codes/keystone-mcp@")


def test_manifest_tools_match_server(hello_server) -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    manifest_tools = manifest["mcp"]["tools"]
    server_tools = [tool.name for tool in hello_server._TOOLS]
    assert manifest_tools == server_tools
    allowed = policy["roles"]["hello_user"]["allow"]
    assert allowed == [f"hello_{name}" for name in manifest_tools]
