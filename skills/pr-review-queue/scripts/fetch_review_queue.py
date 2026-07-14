#!/usr/bin/env python3
"""Fetch and display pending GitHub pull request reviews."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "packages" / "pr-review-queue" / "src"),
)

from pr_review_queue.client import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
