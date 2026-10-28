# Changelog

## 1.0.2 - 2026-10-28

### Fixed

- `mcp` 1.28.1 -> 1.30.0, closing CVE-2026-59951, CVE-2026-116684, CVE-2026-116685, and CVE-2026-116686 in the pinned SDK.
- `requirements.txt` is reproducible again: a checked-in `requirements.in` replaces the `/tmp/hello-reqs.in` the header used to point at. The recompile also upgrades `certifi`, closing a CRITICAL Trivy finding (GHSA-6q48-6c7w-9gw2).

### Changed

- The release workflow scans the built image with Trivy (`CRITICAL`,`HIGH`, `ignore-unfixed`) before it is pushed.
- Dependabot now watches `pip`, `docker`, and `github-actions` updates.

## 1.0.1

### Fixed

- The manifest summary says three tools (`greet`, `search`, `whoami`); it said two.

### Changed

- CI lints the manifest with `keystonectl` 0.1.0 from PyPI.
- The release workflow checks the remote tag, not a local one.

## 1.0.0

### Added

- Catalog package for the hello-upstream demo MCP service (SDK 1.x).
- Mandatory bearer and signed `X-Keystone-Identity` on tool calls.
- `keystone-service.yaml`, example policy, CI, and release workflows.
