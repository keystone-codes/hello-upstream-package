# Changelog

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
