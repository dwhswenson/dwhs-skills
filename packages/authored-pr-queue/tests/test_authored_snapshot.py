from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from authored_pr_queue import GitHubError, build_snapshot, serialize_snapshot


def timestamp(day: int) -> datetime:
    return datetime(2026, 7, day, tzinfo=UTC)


def review(login: str, state: str, day: int, commit_id: str | None = "head"):
    return SimpleNamespace(
        user=SimpleNamespace(login=login),
        state=state,
        submitted_at=timestamp(day),
        commit_id=commit_id,
    )


def pull(
    number: int,
    updated_day: int,
    *,
    draft: bool = False,
    requested_reviewers=(),
    requested_teams=(),
    reviews=(),
    head_sha: str = "head",
):
    return SimpleNamespace(
        number=number,
        title=f"PR {number}",
        html_url=f"https://github.com/acme/repo/pull/{number}",
        created_at=timestamp(1),
        updated_at=timestamp(updated_day),
        base=SimpleNamespace(repo=SimpleNamespace(full_name="acme/repo")),
        head=SimpleNamespace(sha=head_sha),
        draft=draft,
        get_reviews=lambda: list(reviews),
        get_review_requests=lambda: (
            [SimpleNamespace(login=login) for login in requested_reviewers],
            [SimpleNamespace(slug=slug) for slug in requested_teams],
        ),
    )


class FakeGitHub:
    def __init__(self, pulls):
        self.pulls = pulls
        self.search_call = None

    def get_user(self):
        return SimpleNamespace(login="author")

    def search_issues(self, query, sort, order):
        self.search_call = (query, sort, order)
        return [SimpleNamespace(as_pull_request=lambda pull=pull: pull) for pull in self.pulls]


def snapshot_for(*pulls):
    client = FakeGitHub(pulls)
    return build_snapshot("token", client=client), client


def test_build_snapshot_queries_authored_open_non_draft_prs():
    snapshot, client = snapshot_for(pull(1, 2))

    assert client.search_call == (
        "is:pr is:open archived:false draft:false author:author",
        "updated",
        "asc",
    )
    assert snapshot["author"] == "author"
    assert snapshot["pull_requests"][0]["status"] == "needs_review_request"


def test_build_snapshot_skips_drafts_even_if_github_returns_them():
    snapshot, _ = snapshot_for(pull(1, 2, draft=True))

    assert snapshot["pull_requests"] == []


def test_classifies_all_statuses_and_sorts_by_priority_then_oldest_update():
    snapshot, _ = snapshot_for(
        pull(1, 9, reviews=[review("feedback", "COMMENTED", 4, "old")], head_sha="head"),
        pull(2, 8),
        pull(3, 10, requested_reviewers=["waiting"]),
        pull(4, 7, requested_reviewers=["remaining"], reviews=[review("done", "APPROVED", 4)]),
        pull(5, 6, reviews=[review("changes", "CHANGES_REQUESTED", 5)]),
    )

    records = snapshot["pull_requests"]
    assert [(record["number"], record["status"]) for record in records] == [
        (5, "needs_author_action"),
        (1, "needs_author_action"),
        (2, "needs_review_request"),
        (4, "partially_reviewed"),
        (3, "awaiting_review"),
    ]


def test_excludes_settled_prs_without_requests_or_actionable_feedback():
    snapshot, _ = snapshot_for(pull(1, 2, reviews=[review("reviewer", "APPROVED", 2)]))

    assert snapshot["pull_requests"] == []


def test_direct_rerequest_clears_only_that_reviewers_feedback():
    snapshot, _ = snapshot_for(
        pull(
            1,
            3,
            requested_reviewers=["reviewer"],
            requested_teams=["maintainers"],
            reviews=[review("reviewer", "CHANGES_REQUESTED", 2, "old")],
            head_sha="new",
        )
    )

    record = snapshot["pull_requests"][0]
    assert record["status"] == "partially_reviewed"
    assert record["requested_reviewers"] == ["reviewer"]
    assert record["requested_teams"] == ["maintainers"]
    assert record["latest_reviews"] == [
        {
            "reviewer": "reviewer",
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-07-02T00:00:00Z",
            "commit_id": "old",
            "has_new_commits_since_review": True,
            "awaits_author_action": False,
        }
    ]


def test_team_request_does_not_clear_individual_feedback():
    snapshot, _ = snapshot_for(
        pull(
            1,
            3,
            requested_teams=["maintainers"],
            reviews=[review("reviewer", "COMMENTED", 2)],
        )
    )

    assert snapshot["pull_requests"][0]["status"] == "needs_author_action"


def test_uses_latest_submitted_review_per_reviewer_and_ignores_pending_reviews():
    snapshot, _ = snapshot_for(
        pull(
            1,
            3,
            requested_reviewers=["remaining"],
            reviews=[
                review("reviewer", "CHANGES_REQUESTED", 2, "old"),
                review("reviewer", "APPROVED", 3),
                SimpleNamespace(user=None, state="PENDING", submitted_at=None, commit_id=None),
                review("other", "COMMENTED", 1),
            ],
        )
    )

    record = snapshot["pull_requests"][0]
    assert record["status"] == "needs_author_action"
    assert [entry["reviewer"] for entry in record["latest_reviews"]] == ["other", "reviewer"]
    assert record["latest_reviews"][1]["state"] == "APPROVED"
    assert record["latest_reviews"][1]["awaits_author_action"] is False


def test_review_with_missing_commit_id_has_unknown_head_change_state():
    snapshot, _ = snapshot_for(
        pull(1, 2, reviews=[review("reviewer", "COMMENTED", 2, commit_id=None)])
    )

    assert snapshot["pull_requests"][0]["latest_reviews"][0]["has_new_commits_since_review"] is None


def test_invalid_pull_request_details_raise_github_error():
    incomplete = SimpleNamespace(
        draft=False,
        get_review_requests=lambda: ([], []),
        get_reviews=lambda: [],
    )

    with pytest.raises(GitHubError, match="incomplete pull request details"):
        snapshot_for(incomplete)


def test_serialize_snapshot_is_stable_and_newline_terminated():
    expected = '{\n  "a": {\n    "b": 2\n  },\n  "z": 1\n}\n'
    assert serialize_snapshot({"z": 1, "a": {"b": 2}}) == expected
