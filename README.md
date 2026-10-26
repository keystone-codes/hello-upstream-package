# hello-upstream (catalog package)

Demo MCP service for the Keystone service catalog: a deliberately “foreign” upstream
built on the **low-level MCP Python SDK 1.x**, not FastMCP. It exposes three tools,
uses no object storage, and exposes no public HTTP paths beyond `/mcp` and `/healthz`.

## Source

Server code is derived from
[keystone-mcp](https://github.com/keystone-codes/keystone-mcp) at
`f73310df8634a19406bf21972e023af9a3b44ac0` (`release/0.5.0`), paths:

- `examples/hello-upstream/server.py` (adapted — see below)
- `examples/keystone-identity/python/keystone_identity.py` (vendored byte-for-byte as
  `keystone_identity.py`)

## Catalog adaptations (vs the keystone-mcp example)

The upstream example in keystone-mcp can run without bearer or signed identity when
`HELLO_IDENTITY_SECRET` is unset. **Catalog packages must verify both** the Keystone
bearer token and `X-Keystone-Identity` (R8). This repository therefore:

- requires `HELLO_BEARER_TOKEN` and `HELLO_IDENTITY_SECRET` (each ≥ 32 bytes) at startup;
- wraps `/mcp` with a bearer check (`401` + `WWW-Authenticate: Bearer` on failure);
- verifies `X-Keystone-Identity` on every `tools/call` and rejects forged
  `X-Author-Email`;
- defaults `HELLO_IDENTITY_AUDIENCE` to `hello-upstream` (registry entry name / JWT `aud`).

## Tools

- **`greet(name)`** — plain-text greeting using the verified assertion `sub`.
- **`search(query, limit=5, filter)`** — demo search; `inputSchema` keeps optional
  `limit` before required `filter` on purpose.
- **`whoami()`** — JSON text of verified identity fields.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `HELLO_BEARER_TOKEN` | yes (≥ 32 bytes) | Bearer token Keystone-MCP sends as `Authorization: Bearer …` |
| `HELLO_IDENTITY_SECRET` | yes (≥ 32 bytes) | HS256 secret for `X-Keystone-Identity` (same value as Keystone registry `auth.identity_secret_env`) |
| `HELLO_IDENTITY_AUDIENCE` | no (default `hello-upstream`) | Registry entry `name` / JWT `aud` |
| `HELLO_PORT` | no (default `8081`) | HTTP listen port |

`keystonectl` writes bearer, identity secret, and audience into
`packages/hello-upstream.mcp.env` (K33).

## Running locally

```bash
uv sync
uv run pytest -q

python - <<'PY'
import secrets, pathlib
path = pathlib.Path("hello.env")
path.write_text(
    f"HELLO_BEARER_TOKEN={secrets.token_urlsafe(32)}\n"
    f"HELLO_IDENTITY_SECRET={secrets.token_urlsafe(32)}\n"
    f"HELLO_IDENTITY_AUDIENCE=hello-upstream\n",
    encoding="utf-8",
)
path.chmod(0o600)
PY

docker build -t hello-upstream:dev .
docker run --rm -p 127.0.0.1:8081:8081 --env-file ./hello.env hello-upstream:dev
```

```bash
curl -s localhost:8081/healthz
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8081/mcp   # 401
```

## Hashed runtime dependencies

Runtime packages are pinned in `requirements.txt` with `--hash` entries. Regenerate with:

```bash
uv pip compile --generate-hashes -o requirements.txt \
  <<< $'mcp==1.28.1\npyjwt==2.15.1\nuvicorn==0.54.0\nstarlette==1.8.0'
```

## Behind Keystone-MCP

Register an upstream with `auth.bearer_env: HELLO_BEARER_TOKEN` and
`auth.identity_secret_env: HELLO_IDENTITY_SECRET`, and set the registry entry `name`
to match `HELLO_IDENTITY_AUDIENCE` (default `hello-upstream`). Install with
`keystonectl service apply hello-upstream` once the package is in your catalog.

## Releasing

1. On a branch `release/<version>`, set `version` in `keystone-service.yaml` and
   `pyproject.toml` and add a `CHANGELOG.md` entry. Push the branch.
2. Run **Release image** on that branch:
   `gh workflow run release-image.yml --ref release/<version> -f version=<version>`.
   The pull request it opens carries the version change and the digest.
3. Merge the PR it opens that pins the multi-arch digest in `keystone-service.yaml`.
4. **Tag release** (`.github/workflows/tag-release.yml`) tags `v<version>` after digest
   verification.

See [Releasing a new version](https://github.com/keystone-codes/keystonectl/blob/main/docs/packaging-a-service.md#releasing-a-new-version)
in the keystonectl packaging guide.

Make the GHCR package public after the first publish so installs from clean hosts can
pull the image.
