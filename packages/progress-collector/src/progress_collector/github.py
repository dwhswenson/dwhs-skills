"""GitHub REST activity-feed collector, implemented with PyGithub."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from .config import GitHubConfig
from .links import dedupe_links, link
from .models import Activity, SourceResult, TimeRange


class GitHubCollector:
    source = "github"

    def __init__(self, config: GitHubConfig | None = None, *, client: Any | None = None):
        self._config = config
        self._client = client

    def collect(self, time_range: TimeRange, config: GitHubConfig | None = None) -> SourceResult:
        config = config or self._config
        if config is None:
            return SourceResult(self.source, "skipped")
        if not isinstance(config, GitHubConfig):
            return SourceResult(
                self.source,
                "error",
                error={"code": "invalid_config", "message": "Invalid GitHub configuration"},
            )

        owned_client = self._client is None
        client = self._client
        try:
            if client is None:
                from github import Auth, Github

                client = Github(
                    auth=Auth.Token(config.token),
                    per_page=100,
                    timeout=20,
                    user_agent="progress-collector",
                )
            authenticated_user = client.get_user()
            login = getattr(authenticated_user, "login", None)
            if not isinstance(login, str) or not login:
                raise ValueError("GitHub user is missing a login")
            # AuthenticatedUser.get_events() points to GitHub's global /events feed. Resolve the
            # authenticated login to a NamedUser so the request is /users/{login}/events instead.
            user = client.get_user(login)
            items = [
                _activity(event)
                for event in user.get_events()
                if _in_range(_event_time(event), time_range.start, time_range.end)
            ]
            items.sort(key=lambda item: item.occurred_at)
            return SourceResult(self.source, "ok", tuple(items))
        except Exception:
            return SourceResult(
                self.source,
                "error",
                error={"code": "github_error", "message": "Unable to collect GitHub activity"},
            )
        finally:
            if owned_client and client is not None:
                client.close()


def _in_range(value: datetime, start: datetime, end: datetime) -> bool:
    return start <= value < end


def _event_time(event: Any) -> datetime:
    value = getattr(event, "created_at", None)
    if not isinstance(value, datetime):
        raise ValueError("GitHub event is missing created_at")
    return value


def _payload(event: Any) -> dict[str, Any]:
    value = getattr(event, "payload", None)
    if isinstance(value, dict):
        return value
    raw = getattr(event, "raw_data", None)
    if isinstance(raw, dict) and isinstance(raw.get("payload"), dict):
        return raw["payload"]
    return {}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, SimpleNamespace):
        return vars(value)
    return {}


def _repository(event: Any) -> tuple[str | None, str | None]:
    repo = getattr(event, "repo", None)
    name = getattr(repo, "name", None)
    if not isinstance(name, str):
        name = _mapping(_payload(event).get("repository")).get("full_name")
    if not isinstance(name, str):
        return None, None
    return name, f"https://github.com/{name}"


def _subject(payload: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = _mapping(payload.get(name))
        if value:
            return value
    return {}


def _activity(event: Any) -> Activity:
    payload = _payload(event)
    event_type = str(getattr(event, "type", "UnknownEvent"))
    event_id = str(getattr(event, "id", f"github:{event_type}:{_event_time(event).isoformat()}"))
    repository, repository_url = _repository(event)
    action = payload.get("action") if isinstance(payload.get("action"), str) else None
    subject = _subject(payload, "pull_request", "issue", "comment", "release")
    title = _title(event_type, action, repository, subject, payload)
    url = subject.get("html_url") if isinstance(subject.get("html_url"), str) else repository_url
    if url == repository_url and event_type.startswith("PullRequest"):
        number = payload.get("number")
        if isinstance(number, int) and repository_url:
            url = f"{repository_url}/pull/{number}"
    links = [
        link(repository_url, repository, "repository"),
        link(subject.get("html_url"), subject.get("title"), "subject"),
    ]
    details: dict[str, Any] = {"event_type": event_type, "repository": repository}
    if action:
        details["action"] = action
    is_public = getattr(event, "public", None)
    if isinstance(is_public, bool):
        details["is_public"] = is_public

    if event_type in {"CreateEvent", "DeleteEvent"}:
        details.update(
            {
                key: payload[key]
                for key in ("ref", "ref_type", "full_ref")
                if isinstance(payload.get(key), str)
            }
        )
    if event_type == "PushEvent":
        commits = [
            {key: commit[key] for key in ("sha", "message") if isinstance(commit.get(key), str)}
            for commit in payload.get("commits", [])
            if isinstance(commit, dict)
        ]
        details.update(
            {
                "ref": payload.get("ref"),
                "commit_count": payload.get("size", len(commits)),
                "commits": commits,
            }
        )
    if subject:
        details["subject"] = {
            key: subject[key]
            for key in ("id", "number", "title", "html_url", "state")
            if isinstance(subject.get(key), (str, int))
        }
    comment = _mapping(payload.get("comment"))
    if comment:
        links.append(link(comment.get("html_url"), "Comment", "comment"))
    review = _mapping(payload.get("review"))
    if review:
        details["review_state"] = review.get("state")
        links.append(link(review.get("html_url"), "Review", "review"))
        review_url = review.get("html_url")
        if event_type == "PullRequestReviewEvent" and isinstance(review_url, str):
            url = review_url
    return Activity(
        event_id,
        _kind(event_type, action),
        _event_time(event),
        title,
        url,
        dedupe_links(links),
        details,
    )


def _kind(event_type: str, action: str | None) -> str:
    return f"github.{event_type.removesuffix('Event').lower()}" + (f".{action}" if action else "")


def _title(
    event_type: str,
    action: str | None,
    repository: str | None,
    subject: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    subject_title = subject.get("title") if isinstance(subject.get("title"), str) else None
    subject_suffix = (
        f": {subject_title}" if subject_title else f" in {repository or 'a repository'}"
    )
    if event_type == "PushEvent":
        count = payload.get("size", 0)
        ref = _short_ref(payload.get("ref"))
        destination = f" to {ref}" if ref else ""
        if isinstance(count, int) and count > 0:
            return (
                f"Pushed {count} commit{'s' if count != 1 else ''}{destination}"
                f" in {repository or 'a repository'}"
            )
        return f"Pushed{destination} in {repository or 'a repository'}"
    if event_type == "CreateEvent":
        ref_type = payload.get("ref_type")
        ref = payload.get("ref")
        if ref_type == "repository":
            return f"Created repository {repository or ''}".rstrip()
        if isinstance(ref_type, str) and isinstance(ref, str):
            return f"Created {ref_type} {ref!r} in {repository or 'a repository'}"
        return f"Created in {repository or 'a repository'}"
    if event_type == "DeleteEvent":
        ref_type = payload.get("ref_type")
        ref = payload.get("ref")
        if isinstance(ref_type, str) and isinstance(ref, str):
            return f"Deleted {ref_type} {ref!r} in {repository or 'a repository'}"
        return f"Deleted from {repository or 'a repository'}"
    if event_type == "PullRequestEvent":
        verb = {
            "opened": "Opened pull request",
            "closed": "Closed pull request",
            "merged": "Merged pull request",
            "reopened": "Reopened pull request",
        }.get(action or "", "Updated pull request")
        return f"{verb}{subject_suffix}"
    if event_type == "PullRequestReviewEvent":
        state = _mapping(payload.get("review")).get("state")
        verb = {
            "APPROVED": "Approved pull request",
            "CHANGES_REQUESTED": "Requested changes on pull request",
            "COMMENTED": "Commented on pull request",
        }.get(state, "Submitted pull request review")
        return f"{verb}{subject_suffix}"
    if subject_title:
        verb = action.replace("_", " ") if action else event_type.removesuffix("Event")
        return f"{verb.capitalize()}: {subject_title}"
    return f"{event_type.removesuffix('Event')} activity in {repository or 'a repository'}"


def _short_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for prefix in ("refs/heads/", "refs/tags/"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return value
