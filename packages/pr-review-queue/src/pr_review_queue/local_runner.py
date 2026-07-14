"""Local CLI runner for the review queue snapshot."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from .client import render_markdown
from .snapshot import GitHubError, build_snapshot, serialize_snapshot


class LocalConfigurationError(RuntimeError):
    """Raised when local runner configuration is missing or invalid."""


class LocalOutputError(RuntimeError):
    """Raised when the local snapshot cannot be written."""


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise LocalConfigurationError(f"Missing required environment variable: {name}")
    return value


def _write_snapshot(path: Path, snapshot_body: str) -> None:
    try:
        path.write_text(snapshot_body, encoding="utf-8")
    except OSError as exc:
        raise LocalOutputError(f"Unable to write snapshot to {path}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the raw validated JSON snapshot")
    parser.add_argument("--output", type=Path, help="write the canonical JSON snapshot to a file")
    args = parser.parse_args(argv)

    try:
        github_token = _required_env("GITHUB_PR_GITHUB_TOKEN")
        snapshot = build_snapshot(github_token)
        snapshot_body = serialize_snapshot(snapshot)
        if args.output is not None:
            _write_snapshot(args.output, snapshot_body)
    except LocalConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except GitHubError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except LocalOutputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(snapshot_body, end="")
    else:
        print(render_markdown(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
