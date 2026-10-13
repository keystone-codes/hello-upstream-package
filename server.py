"""hello-upstream catalog package: low-level MCP SDK 1.x demo service.

Source: ``keystone-codes/keystone-mcp`` at ``6b04a198101dac22815b17d5bcf55b0e1c6463d8``
(``release/0.5.0``), path ``examples/hello-upstream/server.py``. Adapted for the
Keystone service catalog: mandatory bearer and signed ``X-Keystone-Identity`` (P02).
"""

from __future__ import annotations

import hmac
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from keystone_identity import IdentityError, KeystoneIdentity, verify_keystone_identity

MIN_SECRET_BYTES = 32
DEFAULT_IDENTITY_AUDIENCE = "hello-upstream"
DEFAULT_PORT = 8081

GREET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Who to greet"},
    },
    "required": ["name"],
}

SEARCH_SCHEMA: dict[str, Any] = {
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

_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}

_TOOLS: list[types.Tool] = [
    types.Tool(name="greet", description="Greet someone by name.", inputSchema=GREET_SCHEMA),
    types.Tool(name="search", description="Search documents.", inputSchema=SEARCH_SCHEMA),
    types.Tool(
        name="whoami",
        description="Return the verified caller identity from X-Keystone-Identity.",
        inputSchema=_EMPTY_SCHEMA,
    ),
]


@dataclass(frozen=True)
class Config:
    bearer_token: str
    identity_secret: str
    identity_audience: str
    port: int


def load_config() -> Config:
    """Load required settings from the environment; exit 2 on validation errors."""
    errors: list[str] = []

    bearer = os.environ.get("HELLO_BEARER_TOKEN", "").strip()
    if len(bearer.encode("utf-8")) < MIN_SECRET_BYTES:
        errors.append("HELLO_BEARER_TOKEN is required")

    identity_secret = os.environ.get("HELLO_IDENTITY_SECRET", "").strip()
    if len(identity_secret.encode("utf-8")) < MIN_SECRET_BYTES:
        errors.append("HELLO_IDENTITY_SECRET is required")

    audience_raw = os.environ.get("HELLO_IDENTITY_AUDIENCE", DEFAULT_IDENTITY_AUDIENCE).strip()
    identity_audience = audience_raw or DEFAULT_IDENTITY_AUDIENCE

    port_raw = os.environ.get("HELLO_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(port_raw)
    except ValueError:
        errors.append("HELLO_PORT is required")
        port = DEFAULT_PORT

    if errors:
        for message in errors:
            print(f"config error: {message}", file=sys.stderr)
        raise SystemExit(2)

    return Config(
        bearer_token=bearer,
        identity_secret=identity_secret,
        identity_audience=identity_audience,
        port=port,
    )


def _headers_from_request(request: Any) -> dict[str, str]:
    if request is None:
        return {}
    return {k.lower(): v for k, v in request.headers.items()}


def _verify_tool_identity(
    headers: dict[str, str], tool_name: str, config: Config
) -> KeystoneIdentity:
    token = headers.get("x-keystone-identity")
    try:
        identity = verify_keystone_identity(
            token,
            secrets=[config.identity_secret],
            audience=config.identity_audience,
        )
    except IdentityError as exc:
        raise ValueError(f"identity rejected: {exc}") from exc
    if identity.mcp_target != tool_name:
        raise ValueError("identity rejected: mcp_target mismatch") from None
    return identity


def _greet(arguments: dict[str, Any], identity: KeystoneIdentity) -> str:
    name = arguments["name"]
    return f"Hello, {name}! You are {identity.sub}."


def _search(arguments: dict[str, Any]) -> str:
    query = arguments["query"]
    tool_filter = arguments["filter"]
    limit = arguments.get("limit") or 5
    lines = [f"{i + 1}. Result for '{query}' (filter={tool_filter})" for i in range(limit)]
    return "\n".join(lines)


def _whoami(identity: KeystoneIdentity) -> str:
    return json.dumps(
        {
            "verified": True,
            "sub": identity.sub,
            "sub_type": identity.sub_type,
            "roles": list(identity.roles),
            "auth_method": identity.auth_method,
            "interactive": identity.interactive,
            "client_id": identity.client_id,
            "mcp_target": identity.mcp_target,
        }
    )


def _run_tool(
    name: str,
    arguments: dict[str, Any],
    identity: KeystoneIdentity,
) -> list[types.ContentBlock]:
    if name == "greet":
        return [types.TextContent(type="text", text=_greet(arguments, identity))]
    if name == "search":
        return [types.TextContent(type="text", text=_search(arguments))]
    if name == "whoami":
        return [types.TextContent(type="text", text=_whoami(identity))]
    raise ValueError(f"unknown tool: {name}")


def _build_server(config: Config) -> Server:
    server: Server = Server("hello-upstream")

    if hasattr(server, "list_tools"):

        @server.list_tools()
        async def _list_tools() -> list[types.Tool]:
            return _TOOLS

        @server.call_tool()
        async def _call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
            request = server.request_context.request
            headers = _headers_from_request(request)
            identity = _verify_tool_identity(headers, name, config)
            return _run_tool(name, arguments, identity)

        return server

    async def _on_list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=_TOOLS)

    async def _on_call_tool(ctx: Any, params: Any) -> types.CallToolResult:
        headers = _headers_from_request(getattr(ctx, "request", None))
        try:
            identity = _verify_tool_identity(headers, params.name, config)
            content = _run_tool(params.name, params.arguments or {}, identity)
        except Exception as exc:  # noqa: BLE001 -- mirrors SDK 1.x auto-wrap
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(exc))],
                is_error=True,
            )
        return types.CallToolResult(content=content)

    return Server("hello-upstream", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


def _bearer_ok(auth_header: str, token: str) -> bool:
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    supplied = auth_header[len(prefix) :]
    if len(supplied) != len(token):
        return False
    return hmac.compare_digest(supplied, token)


class _McpEndpoint:
    """Hand the request to the streamable HTTP session manager."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)


class _BearerMcpEndpoint:
    """Bearer gate for ``/mcp``; ``/healthz`` stays on the outer app, unwrapped."""

    def __init__(self, inner: _McpEndpoint, bearer_token: str) -> None:
        self._inner = inner
        self._bearer_token = bearer_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {
                name.decode("latin-1").lower(): value.decode("latin-1")
                for name, value in scope.get("headers", [])
            }
            auth = headers.get("authorization", "")
            if not _bearer_ok(auth, self._bearer_token):
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self._inner(scope, receive, send)


async def _healthz(_request: Any) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@asynccontextmanager
async def _lifespan(_app: Starlette) -> AsyncIterator[None]:
    async with manager.run():
        yield


_config = load_config()
server = _build_server(_config)
manager = StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)

app = Starlette(
    routes=[
        Route(
            "/mcp",
            endpoint=_BearerMcpEndpoint(_McpEndpoint(), _config.bearer_token),
            methods=["GET", "POST", "DELETE"],
        ),
        Route("/healthz", endpoint=_healthz, methods=["GET"]),
    ],
    lifespan=_lifespan,
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_config.port)
