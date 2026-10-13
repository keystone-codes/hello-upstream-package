#!/usr/bin/env python3
"""Replace the single ``image:`` line in keystone-service.yaml with a pinned digest."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "keystone-service.yaml"
IMAGE_LINE = re.compile(
    r"^(\s*image:\s*)ghcr\.io/keystone-codes/hello-upstream@sha256:[0-9a-f]{64}\s*$"
)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: pin_digest.py <sha256-digest>", file=sys.stderr)
        raise SystemExit(2)
    digest = sys.argv[1].removeprefix("sha256:")
    if len(digest) != 64 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        print(
            "digest must be 64 lowercase hex chars (optionally prefixed with sha256:)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    text = MANIFEST.read_text(encoding="utf-8")
    lines = text.splitlines()
    matches = [index for index, line in enumerate(lines) if IMAGE_LINE.match(line)]
    if len(matches) != 1:
        print(
            f"expected exactly one image: line in {MANIFEST}, found {len(matches)}", file=sys.stderr
        )
        raise SystemExit(1)

    index = matches[0]
    prefix = re.match(r"^(\s*image:\s*)", lines[index])
    assert prefix is not None
    lines[index] = f"{prefix.group(1)}ghcr.io/keystone-codes/hello-upstream@sha256:{digest}"
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
