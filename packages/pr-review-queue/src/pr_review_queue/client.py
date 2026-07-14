"""Command-line client and Markdown renderer for the review queue Lambda."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


class ClientError(RuntimeError):
    """Raised when the review queue cannot be retrieved or validated."""


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ClientError(f"Missing required environment variable: {name}")
    return value


def validate_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ClientError("The Lambda returned a non-object JSON response")
    if not isinstance(payload.get("reviewer"), str):
        raise ClientError("The Lambda response is missing reviewer")
    if not isinstance(payload.get("generated_at"), str):
        raise ClientError("The Lambda response is missing generated_at")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise ClientError("The Lambda response is missing the reviews list")

    required = {
        "repository": str,
        "number": int,
        "title": str,
        "url": str,
        "author": str,
        "created_at": str,
        "updated_at": str,
        "review_type": str,
    }
    for review in reviews:
        if not isinstance(review, dict):
            raise ClientError("The Lambda returned an invalid review entry")
        for key, expected_type in required.items():
            if not isinstance(review.get(key), expected_type):
                raise ClientError(f"A review entry is missing valid {key}")
        if review["review_type"] not in {"fresh", "rereview"}:
            raise ClientError("A review entry has an invalid review_type")
        new_commits = review.get("has_new_commits_since_review")
        if new_commits is not None and not isinstance(new_commits, bool):
            raise ClientError("A review entry has invalid has_new_commits_since_review")
        last_reviewed_at = review.get("last_reviewed_at")
        if last_reviewed_at is not None and not isinstance(last_reviewed_at, str):
            raise ClientError("A review entry has invalid last_reviewed_at")
    return payload


def fetch_snapshot(
    url: str | None = None,
    token: str | None = None,
    opener: Any = urllib.request.urlopen,
) -> dict[str, Any]:
    endpoint = url or _required_env("GITHUB_PR_LAMBDA_URL")
    bearer = token or _required_env("GITHUB_PR_LAMBDA_TOKEN")
    request = urllib.request.Request(
        endpoint,
        headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            message = error_payload["error"]["message"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            message = f"HTTP {exc.code}"
        raise ClientError(f"Review queue request failed: {message}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError("Unable to retrieve a valid review queue response") from exc
    return validate_snapshot(payload)


def _review_lines(review: dict[str, Any]) -> list[str]:
    lines = [
        f"- [{review['title']}]({review['url']}) - "
        f"`{review['repository']}#{review['number']}` by @{review['author']}",
        f"  Created: {review['created_at']} | Updated: {review['updated_at']}",
    ]
    if review["review_type"] == "rereview":
        if review.get("has_new_commits_since_review") is False:
            lines.append("  Re-review requested at the same head commit as your last review.")
        elif review.get("has_new_commits_since_review") is True:
            lines.append("  New commits were added after your last review.")
    return lines


def render_markdown(snapshot: dict[str, Any]) -> str:
    reviews = snapshot["reviews"]
    if not reviews:
        return (
            "# Pending GitHub PR Reviews\n\n"
            f"No pending reviews for @{snapshot['reviewer']}.\n\n"
            f"Last refreshed: {snapshot['generated_at']}"
        )

    lines = [
        "# Pending GitHub PR Reviews",
        "",
        f"Reviewer: @{snapshot['reviewer']} | Refreshed: {snapshot['generated_at']}",
    ]
    groups = (
        ("Re-reviews", [review for review in reviews if review["review_type"] == "rereview"]),
        ("Fresh requests", [review for review in reviews if review["review_type"] == "fresh"]),
    )
    for heading, group in groups:
        if not group:
            continue
        lines.extend(["", f"## {heading} ({len(group)})", ""])
        for review in group:
            lines.extend(_review_lines(review))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the raw validated JSON snapshot")
    args = parser.parse_args()
    try:
        snapshot = fetch_snapshot()
    except ClientError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print(render_markdown(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
