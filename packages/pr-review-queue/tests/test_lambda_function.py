from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pr_review_queue import lambda_function as module


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


def test_write_snapshot_uses_fixed_private_object_contract():
    class S3:
        call = None

        def put_object(self, **kwargs):
            self.call = kwargs

    s3 = S3()
    module.write_snapshot("dashboard-data", '{"reviews": []}\n', s3_client=s3)
    assert s3.call == {
        "Bucket": "dashboard-data",
        "Key": "pr-review-queue/current.json",
        "Body": b'{"reviews": []}\n',
        "ContentType": "application/json",
    }


@pytest.fixture
def handler_env(monkeypatch):
    monkeypatch.setenv("GITHUB_PR_SECRET_ID", "review-secret")
    monkeypatch.setenv("DATA_BUCKET", "dashboard-data")


def event(token="invoke-token", method="GET"):
    return {
        "requestContext": {"http": {"method": method}},
        "headers": {"Authorization": f"Bearer {token}"},
    }


def test_handler_writes_exact_success_body_to_s3(handler_env):
    snapshot = {"reviewer": "reviewer", "generated_at": "now", "reviews": []}
    secret = {"github_token": "gh", "invoke_token": "invoke-token"}
    with (
        patch.object(module, "load_secret", return_value=secret),
        patch.object(module, "build_snapshot", return_value=snapshot),
        patch.object(module, "write_snapshot") as write,
    ):
        response = module.lambda_handler(event(), None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == snapshot
    write.assert_called_once_with("dashboard-data", response["body"])


def test_handler_rejects_bad_token_without_calling_github(handler_env):
    secret = {"github_token": "gh", "invoke_token": "invoke-token"}
    with (
        patch.object(module, "load_secret", return_value=secret),
        patch.object(module, "build_snapshot") as build,
    ):
        response = module.lambda_handler(event("wrong"), None)
    assert response["statusCode"] == 401
    build.assert_not_called()


def test_handler_rejects_non_get_before_loading_secret():
    with patch.object(module, "load_secret") as load:
        response = module.lambda_handler(event(method="POST"), None)
    assert response["statusCode"] == 405
    load.assert_not_called()


def test_handler_does_not_write_after_github_failure(handler_env):
    secret = {"github_token": "gh", "invoke_token": "invoke-token"}
    with (
        patch.object(module, "load_secret", return_value=secret),
        patch.object(
            module,
            "build_snapshot",
            side_effect=module.GitHubError("GitHub unavailable"),
        ),
        patch.object(module, "write_snapshot") as write,
    ):
        response = module.lambda_handler(event(), None)
    assert response["statusCode"] == 502
    write.assert_not_called()


def test_handler_fails_when_s3_write_fails(handler_env):
    secret = {"github_token": "gh", "invoke_token": "invoke-token"}
    with (
        patch.object(module, "load_secret", return_value=secret),
        patch.object(module, "build_snapshot", return_value={"reviews": []}),
        patch.object(module, "write_snapshot", side_effect=module.SnapshotError("S3 unavailable")),
    ):
        response = module.lambda_handler(event(), None)
    assert response["statusCode"] == 500
    assert json.loads(response["body"])["error"]["code"] == "snapshot_error"


def test_load_secret_caches_valid_json():
    module._SECRET_CACHE.clear()

    class Secrets:
        calls = 0

        def get_secret_value(self, **kwargs):
            self.calls += 1
            assert kwargs == {"SecretId": "secret-id"}
            return {"SecretString": '{"github_token":"gh","invoke_token":"invoke"}'}

    secrets = Secrets()
    expected = {"github_token": "gh", "invoke_token": "invoke"}
    assert module.load_secret("secret-id", secrets) == expected
    assert module.load_secret("secret-id", secrets) == expected
    assert secrets.calls == 1
