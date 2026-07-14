from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from progress_collector import GitHubConfig, TimeRange
from progress_collector.github import GitHubCollector


def period():
    return TimeRange(
        datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC), "America/Chicago"
    )


class FakeClient:
    def __init__(self, events):
        self.events = events

    def get_user(self):
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
    result = GitHubCollector(client=FakeClient(events)).collect(period(), GitHubConfig("token"))
    assert result.status == "ok"
    assert [item.kind for item in result.items] == [
        "github.push",
        "github.pullrequest.opened",
        "github.watch.started",
    ]
    assert result.items[0].details["commit_count"] == 2
    assert result.items[1].url.endswith("/pull/2")
    assert result.items[2].details["event_type"] == "WatchEvent"
    assert result.items[0].details["is_public"] is False


def test_github_excludes_end_boundary_and_skips_unconfigured():
    outside = event("late", "PushEvent", {}, 2)
    outside.created_at = datetime(2026, 7, 2, tzinfo=UTC)
    result = GitHubCollector(client=FakeClient([outside])).collect(period(), GitHubConfig("token"))
    assert result.items == ()
    assert GitHubCollector().collect(period()).status == "skipped"
