"""Local CLI for actionable GitHub pull requests authored by the current user."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .snapshot import (
    STATUS_PRIORITY,
    GitHubError,
    build_snapshot,
    serialize_snapshot,
)

STATUS_CHOICES = tuple(status.replace("_", "-") for status in STATUS_PRIORITY)
STATUS_HEADINGS = {
    "needs_author_action": "Needs your action",
    "needs_review_request": "Needs a review request",
    "partially_reviewed": "Partially reviewed",
    "awaiting_review": "Awaiting review",
}


class LocalConfigurationError(RuntimeError):
    """Raised when local CLI configuration is missing or invalid."""


class LocalOutputError(RuntimeError):
    """Raised when the selected snapshot cannot be written."""


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


def filter_snapshot(snapshot: dict[str, Any], statuses: Sequence[str]) -> dict[str, Any]:
    """Return a copy of *snapshot* limited to the selected dashed CLI statuses."""

    selected = {status.replace("-", "_") for status in statuses}
    if not selected:
        return {**snapshot, "pull_requests": list(snapshot["pull_requests"])}
    return {
        **snapshot,
        "pull_requests": [
            pull_request
            for pull_request in snapshot["pull_requests"]
            if pull_request["status"] in selected
        ],
    }


def _review_context(review: dict[str, Any]) -> str:
    state = "requested changes" if review["state"] == "CHANGES_REQUESTED" else "commented"
    context = f"@{review['reviewer']} {state} at {review['submitted_at']}"
    if review["has_new_commits_since_review"] is True:
        return f"{context}; new commits have been added."
    if review["has_new_commits_since_review"] is False:
        return f"{context}; no new commits have been added."
    return context


def _pull_request_lines(pull_request: dict[str, Any]) -> list[str]:
    lines = [
        f"- [{pull_request['title']}]({pull_request['url']}) - "
        f"`{pull_request['repository']}#{pull_request['number']}`",
        f"  Created: {pull_request['created_at']} | Updated: {pull_request['updated_at']}",
    ]
    if pull_request["requested_reviewers"]:
        reviewers = ", ".join(f"@{reviewer}" for reviewer in pull_request["requested_reviewers"])
        lines.append(f"  Requested reviewers: {reviewers}")
    if pull_request["requested_teams"]:
        teams = ", ".join(f"@{team}" for team in pull_request["requested_teams"])
        lines.append(f"  Requested teams: {teams}")

    actionable_reviews = [
        review for review in pull_request["latest_reviews"] if review["awaits_author_action"]
    ]
    if actionable_reviews:
        context = "; ".join(_review_context(review) for review in actionable_reviews)
        lines.append("  Awaiting you: " + context)
    elif pull_request["status"] == "needs_review_request":
        lines.append("  No review request is currently pending.")
    return lines


def render_markdown(snapshot: dict[str, Any]) -> str:
    """Render a selected authored pull request snapshot as grouped Markdown."""

    pull_requests = snapshot["pull_requests"]
    if not pull_requests:
        return (
            "# Actionable Authored GitHub PRs\n\n"
            f"No matching actionable pull requests for @{snapshot['author']}.\n\n"
            f"Last refreshed: {snapshot['generated_at']}"
        )

    lines = [
        "# Actionable Authored GitHub PRs",
        "",
        f"Author: @{snapshot['author']} | Refreshed: {snapshot['generated_at']}",
    ]
    for status in STATUS_PRIORITY:
        group = [pull_request for pull_request in pull_requests if pull_request["status"] == status]
        if not group:
            continue
        lines.extend(["", f"## {STATUS_HEADINGS[status]} ({len(group)})", ""])
        for pull_request in group:
            lines.extend(_pull_request_lines(pull_request))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--status",
        action="append",
        choices=STATUS_CHOICES,
        help="include one status; repeat to select multiple statuses",
    )
    parser.add_argument("--json", action="store_true", help="print the selected JSON snapshot")
    parser.add_argument("--output", type=Path, help="write the selected JSON snapshot to a file")
    args = parser.parse_args(argv)

    try:
        github_token = _required_env("GITHUB_PR_GITHUB_TOKEN")
        snapshot = filter_snapshot(build_snapshot(github_token), args.status or ())
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
