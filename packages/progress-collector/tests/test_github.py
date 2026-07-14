from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from progress_collector import GitHubConfig, TimeRange
from progress_collector.github import GitHubCollector


def period():
    return TimeRange(
        datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC), "America/Chicago"
    )


class FakeClient:
    def __init__(self, events):
        self.events = events
        self.requested_logins = []

    def get_user(self, login=None):
        if login is None:
            return SimpleNamespace(login="me")
        self.requested_logins.append(login)
        return SimpleNamespace(get_events=lambda: self.events)


def event(identifier, kind, payload, hour=1):
    return SimpleNamespace(
        id=identifier,
        type=kind,
        created_at=datetime(2026, 7, 1, hour, tzinfo=UTC),
        repo=SimpleNamespace(name="acme/repo"),
        payload=payload,
        public=False,
    )


def test_github_normalizes_push_pr_comment_and_unknown_events():
    events = [
        event(
            "push",
            "PushEvent",
            {"size": 2, "ref": "refs/heads/main", "commits": [{"sha": "a", "message": "one"}]},
        ),
        event(
            "pr",
            "PullRequestEvent",
            {
                "action": "opened",
                "pull_request": {
                    "title": "Improve thing",
                    "html_url": "https://github.com/acme/repo/pull/2",
                    "number": 2,
                },
            },
        ),
        event("other", "WatchEvent", {"action": "started"}),
    ]
    client = FakeClient(events)
    result = GitHubCollector(client=client).collect(period(), GitHubConfig("token"))
    assert result.status == "ok"
    assert client.requested_logins == ["me"]
    assert [item.kind for item in result.items] == [
        "github.push",
        "github.pullrequest.opened",
        "github.watch.started",
    ]
    assert result.items[0].details["commit_count"] == 2
    assert result.items[1].url.endswith("/pull/2")
    assert result.items[1].title == "Opened pull request: Improve thing"
    assert result.items[2].details["event_type"] == "WatchEvent"
    assert result.items[0].details["is_public"] is False


def test_github_excludes_end_boundary_and_skips_unconfigured():
    outside = event("late", "PushEvent", {}, 2)
    outside.created_at = datetime(2026, 7, 2, tzinfo=UTC)
    result = GitHubCollector(client=FakeClient([outside])).collect(period(), GitHubConfig("token"))
    assert result.items == ()
    assert GitHubCollector().collect(period()).status == "skipped"


def test_github_uses_specific_titles_for_create_pr_review_and_empty_push():
    events = [
        event("create", "CreateEvent", {"ref_type": "repository", "ref": None}),
        event("merge", "PullRequestEvent", {"action": "merged", "number": 3}),
        event(
            "review",
            "PullRequestReviewEvent",
            {
                "action": "created",
                "review": {
                    "state": "APPROVED",
                    "html_url": "https://github.com/acme/repo/pull/3#pullrequestreview-4",
                },
            },
        ),
        event("push", "PushEvent", {"size": 0, "ref": "refs/heads/main"}),
    ]
    result = GitHubCollector(client=FakeClient(events)).collect(period(), GitHubConfig("token"))
    assert [item.title for item in result.items] == [
        "Created repository acme/repo",
        "Merged pull request in acme/repo",
        "Approved pull request in acme/repo",
        "Pushed to main in acme/repo",
    ]
    assert result.items[1].url == "https://github.com/acme/repo/pull/3"
    assert result.items[2].url == "https://github.com/acme/repo/pull/3#pullrequestreview-4"


def test_github_config_uses_standard_environment_token(monkeypatch):
    monkeypatch.delenv("PROGRESS_COLLECTOR_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "standard-token")
    assert GitHubConfig.from_env().token == "standard-token"


def test_github_config_falls_back_to_gh_auth_token(monkeypatch):
    for name in ("PROGRESS_COLLECTOR_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("progress_collector.config._github_token_from_gh", lambda: "gh-token")
    assert GitHubConfig.from_env().token == "gh-token"


def test_github_config_errors_without_any_authentication(monkeypatch):
    for name in ("PROGRESS_COLLECTOR_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("progress_collector.config._github_token_from_gh", lambda: None)
    with pytest.raises(ValueError, match="Missing GitHub authentication"):
        GitHubConfig.from_env()
