"""Build canonical snapshots of authored GitHub pull requests that need follow-up."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

ACTIONABLE_REVIEW_STATES = frozenset({"CHANGES_REQUESTED", "COMMENTED"})
STATUS_PRIORITY = {
    "needs_author_action": 0,
    "needs_review_request": 1,
    "partially_reviewed": 2,
    "awaiting_review": 3,
}


class GitHubError(RuntimeError):
    """Raised when GitHub cannot provide a valid authored pull request queue."""


def _isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _latest_reviews(reviews: Iterable[Any], head_sha: str) -> list[dict[str, Any]]:
    latest_by_reviewer: dict[str, Any] = {}
    for review in reviews:
        try:
            submitted_at = review.submitted_at
            state = review.state.upper()
        except (AttributeError, TypeError) as exc:
            raise GitHubError("GitHub returned incomplete pull request review details") from exc

        if state == "PENDING" or submitted_at is None:
            continue
        try:
            reviewer = review.user.login
        except AttributeError as exc:
            raise GitHubError("GitHub returned incomplete pull request review details") from exc
        if not isinstance(reviewer, str) or not reviewer:
            raise GitHubError("GitHub returned incomplete pull request review details")
        if not isinstance(submitted_at, datetime):
            raise GitHubError("GitHub returned incomplete pull request review details")

        key = reviewer.casefold()
        existing = latest_by_reviewer.get(key)
        if existing is None or submitted_at > existing.submitted_at:
            latest_by_reviewer[key] = review

    records = []
    for review in latest_by_reviewer.values():
        commit_id = review.commit_id if isinstance(review.commit_id, str) else None
        has_new_commits = commit_id != head_sha if commit_id is not None else None
        records.append(
            {
                "reviewer": review.user.login,
                "state": review.state.upper(),
                "submitted_at": _isoformat(review.submitted_at),
                "commit_id": commit_id,
                "has_new_commits_since_review": has_new_commits,
            }
        )
    return sorted(
        records,
        key=lambda record: (record["submitted_at"], record["reviewer"].casefold()),
    )


def _review_requests(pull: Any) -> tuple[list[str], list[str]]:
    try:
        users, teams = pull.get_review_requests()
        reviewer_logins = [user.login for user in users]
        team_slugs = [team.slug for team in teams]
    except (AttributeError, TypeError, ValueError) as exc:
        raise GitHubError("GitHub returned incomplete review request details") from exc

    if not all(isinstance(login, str) and login for login in reviewer_logins):
        raise GitHubError("GitHub returned incomplete review request details")
    if not all(isinstance(slug, str) and slug for slug in team_slugs):
        raise GitHubError("GitHub returned incomplete review request details")
    return sorted(reviewer_logins, key=str.casefold), sorted(team_slugs, key=str.casefold)


def _pull_request_record(pull: Any) -> dict[str, Any] | None:
    try:
        repository = pull.base.repo.full_name
        head_sha = pull.head.sha
        created_at = pull.created_at
        updated_at = pull.updated_at
    except AttributeError as exc:
        raise GitHubError("GitHub returned incomplete pull request details") from exc

    if not isinstance(repository, str) or not isinstance(head_sha, str):
        raise GitHubError("GitHub returned incomplete pull request details")
    if not isinstance(created_at, datetime) or not isinstance(updated_at, datetime):
        raise GitHubError("GitHub returned incomplete pull request details")

    requested_reviewers, requested_teams = _review_requests(pull)
    latest_reviews = _latest_reviews(pull.get_reviews(), head_sha)
    requested_reviewer_keys = {reviewer.casefold() for reviewer in requested_reviewers}
    for review in latest_reviews:
        review["awaits_author_action"] = (
            review["state"] in ACTIONABLE_REVIEW_STATES
            and review["reviewer"].casefold() not in requested_reviewer_keys
        )

    has_requests = bool(requested_reviewers or requested_teams)
    has_reviews = bool(latest_reviews)
    if any(review["awaits_author_action"] for review in latest_reviews):
        status = "needs_author_action"
    elif not has_requests and not has_reviews:
        status = "needs_review_request"
    elif has_requests and not has_reviews:
        status = "awaiting_review"
    elif has_requests:
        status = "partially_reviewed"
    else:
        return None

    try:
        number = pull.number
        title = pull.title
        url = pull.html_url
    except AttributeError as exc:
        raise GitHubError("GitHub returned incomplete pull request details") from exc
    if not isinstance(number, int) or not isinstance(title, str) or not isinstance(url, str):
        raise GitHubError("GitHub returned incomplete pull request details")

    return {
        "repository": repository,
        "number": number,
        "title": title,
        "url": url,
        "created_at": _isoformat(created_at),
        "updated_at": _isoformat(updated_at),
        "status": status,
        "requested_reviewers": requested_reviewers,
        "requested_teams": requested_teams,
        "latest_reviews": latest_reviews,
    }


def build_snapshot(github_token: str, client: Any | None = None) -> dict[str, Any]:
    """Return actionable, open pull requests authored by the authenticated user."""

    owned_client = client is None
    if owned_client:
        from github import Auth, Github

        client = Github(
            auth=Auth.Token(github_token),
            per_page=100,
            timeout=20,
            user_agent="authored-pr-queue",
        )

    try:
        login = client.get_user().login
        if not isinstance(login, str) or not login:
            raise GitHubError("GitHub returned an invalid authenticated user")
        query = f"is:pr is:open archived:false draft:false author:{login}"
        issues = client.search_issues(query, sort="updated", order="asc")
        records = []
        for issue in issues:
            pull = issue.as_pull_request()
            if pull.draft:
                continue
            if record := _pull_request_record(pull):
                records.append(record)
    except GitHubError:
        raise
    except Exception as exc:
        raise GitHubError("Unable to retrieve the authored pull request queue") from exc
    finally:
        if owned_client:
            client.close()

    records.sort(key=lambda record: (STATUS_PRIORITY[record["status"]], record["updated_at"]))
    return {
        "author": login,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "pull_requests": records,
    }


def serialize_snapshot(snapshot: dict[str, Any]) -> str:
    """Serialize a snapshot in the stable, newline-terminated dashboard format."""

    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
