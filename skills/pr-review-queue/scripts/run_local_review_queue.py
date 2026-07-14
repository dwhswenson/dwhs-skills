#!/usr/bin/env python3
"""Run the review queue snapshot locally without AWS dependencies."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "packages" / "pr-review-queue" / "src"),
)

from pr_review_queue.local_runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
