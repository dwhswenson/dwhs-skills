from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from pr_review_queue import snapshot as module


class FakeGitHub:
    def __init__(self, pulls):
        self.pulls = pulls
        self.search_call = None

    def get_user(self):
        return SimpleNamespace(login="reviewer")

    def search_issues(self, query, sort, order):
        self.search_call = (query, sort, order)
        return [SimpleNamespace(as_pull_request=lambda pull=pull: pull) for pull in self.pulls]


def timestamp(day):
    return datetime(2026, 6, day, tzinfo=UTC)


def pr(number, updated_day, sha, reviews=None, draft=False):
    return SimpleNamespace(
        number=number,
        title=f"PR {number}",
        html_url=f"https://github.com/acme/repo/pull/{number}",
        user=SimpleNamespace(login="author"),
        created_at=timestamp(1),
        updated_at=timestamp(updated_day),
        head=SimpleNamespace(sha=sha),
        base=SimpleNamespace(repo=SimpleNamespace(full_name="acme/repo")),
        draft=draft,
        get_reviews=lambda: reviews or [],
    )


def review(commit_id, submitted_day=5, state="APPROVED", login="reviewer"):
    return SimpleNamespace(
        user=SimpleNamespace(login=login),
        state=state,
        submitted_at=timestamp(submitted_day),
        commit_id=commit_id,
    )


def test_build_snapshot_classifies_and_orders_reviews():
    fake = FakeGitHub(
        [
            pr(1, 10, "new", [review("old")]),
            pr(2, 9, "same", [review("same")]),
            pr(3, 8, "fresh"),
        ]
    )

    snapshot = module.build_snapshot("token", client=fake)

    assert fake.search_call == (
        "is:pr is:open archived:false draft:false review-requested:reviewer",
        "updated",
        "asc",
    )
    assert [item["number"] for item in snapshot["reviews"]] == [2, 1, 3]
    assert snapshot["reviews"][0]["review_type"] == "rereview"
    assert snapshot["reviews"][0]["has_new_commits_since_review"] is False
    assert snapshot["reviews"][1]["has_new_commits_since_review"] is True
    assert snapshot["reviews"][2]["review_type"] == "fresh"
    assert snapshot["reviews"][2]["last_reviewed_at"] is None


def test_pending_and_other_users_reviews_do_not_count():
    fake = FakeGitHub(
        [
            pr(
                1,
                10,
                "sha",
                [
                    review("sha", state="PENDING"),
                    review("sha", login="someone-else"),
                ],
            )
        ]
    )
    assert module.build_snapshot("token", client=fake)["reviews"][0]["review_type"] == "fresh"


def test_draft_is_skipped_even_if_search_returns_it():
    fake = FakeGitHub([pr(1, 10, "sha", draft=True)])
    assert module.build_snapshot("token", client=fake)["reviews"] == []
