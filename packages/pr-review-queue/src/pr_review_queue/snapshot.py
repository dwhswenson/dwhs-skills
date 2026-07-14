"""Shared review queue snapshot generation logic."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any


class GitHubError(RuntimeError):
    """Raised when GitHub cannot provide a valid review queue."""


def _isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _latest_review(reviews: Iterable[Any], login: str) -> Any | None:
    submitted = [
        review
        for review in reviews
        if review.state.upper() != "PENDING"
        and review.submitted_at is not None
        and review.user is not None
        and review.user.login.casefold() == login.casefold()
    ]
    return max(submitted, key=lambda review: review.submitted_at, default=None)


def _review_record(pull: Any, login: str) -> dict[str, Any]:
    try:
        latest = _latest_review(pull.get_reviews(), login)
        repository = pull.base.repo.full_name
        author = pull.user.login
        head_sha = pull.head.sha
    except (AttributeError, TypeError, ValueError) as exc:
        raise GitHubError("GitHub returned incomplete pull request details") from exc

    if latest is None:
        review_type = "fresh"
        has_new_commits: bool | None = None
        last_reviewed_at: str | None = None
    else:
        review_type = "rereview"
        commit_id = latest.commit_id
        has_new_commits = commit_id != head_sha if isinstance(commit_id, str) else None
        last_reviewed_at = _isoformat(latest.submitted_at)

    return {
        "repository": repository,
        "number": pull.number,
        "title": pull.title,
        "url": pull.html_url,
        "author": author,
        "created_at": _isoformat(pull.created_at),
        "updated_at": _isoformat(pull.updated_at),
        "review_type": review_type,
        "has_new_commits_since_review": has_new_commits,
        "last_reviewed_at": last_reviewed_at,
    }


def build_snapshot(github_token: str, client: Any | None = None) -> dict[str, Any]:
    owned_client = client is None
    if owned_client:
        from github import Auth, Github

        client = Github(
            auth=Auth.Token(github_token),
            per_page=100,
            timeout=20,
            user_agent="pr-review-queue-lambda",
        )

    try:
        login = client.get_user().login
        query = f"is:pr is:open archived:false draft:false review-requested:{login}"
        issues = client.search_issues(query, sort="updated", order="asc")
        pulls = (issue.as_pull_request() for issue in issues)
        records = [_review_record(pull, login) for pull in pulls if not pull.draft]
    except GitHubError:
        raise
    except Exception as exc:
        raise GitHubError("Unable to retrieve the GitHub review queue") from exc
    finally:
        if owned_client:
            client.close()

    records.sort(key=lambda record: (record["review_type"] != "rereview", record["updated_at"]))
    return {
        "reviewer": login,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reviews": records,
    }


def serialize_snapshot(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
