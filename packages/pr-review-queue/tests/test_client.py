from __future__ import annotations

import io
import json

import pytest

from pr_review_queue.client import ClientError, fetch_snapshot, render_markdown, validate_snapshot


def snapshot(reviews=None):
    return {
        "reviewer": "reviewer",
        "generated_at": "2026-06-11T00:00:00Z",
        "reviews": reviews or [],
    }


def review(review_type="fresh", new_commits=None):
    return {
        "repository": "acme/repo",
        "number": 42,
        "title": "Improve the thing",
        "url": "https://github.com/acme/repo/pull/42",
        "author": "author",
        "created_at": "2026-06-01T00:00:00Z",
        "updated_at": "2026-06-10T00:00:00Z",
        "review_type": review_type,
        "has_new_commits_since_review": new_commits,
        "last_reviewed_at": None,
    }


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_fetch_snapshot_sets_bearer_header():
    seen = {}

    def opener(request, timeout):
        seen["authorization"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return Response(snapshot())

    assert fetch_snapshot("https://example.test", "secret", opener) == snapshot()
    assert seen == {"authorization": "Bearer secret", "timeout": 30}


def test_validate_snapshot_rejects_invalid_review():
    with pytest.raises(ClientError, match="valid number"):
        validate_snapshot(snapshot([{**review(), "number": "42"}]))


def test_validate_snapshot_rejects_invalid_commit_flag():
    with pytest.raises(ClientError, match="has_new_commits_since_review"):
        validate_snapshot(snapshot([{**review(), "has_new_commits_since_review": "yes"}]))


def test_render_empty_queue():
    rendered = render_markdown(snapshot())
    assert "No pending reviews for @reviewer" in rendered


def test_render_groups_and_same_commit_note():
    rendered = render_markdown(snapshot([review("rereview", False), review("fresh")]))
    assert "## Re-reviews (1)" in rendered
    assert "same head commit" in rendered
    assert "## Fresh requests (1)" in rendered


def test_missing_environment_is_reported(monkeypatch):
    monkeypatch.delenv("GITHUB_PR_LAMBDA_URL", raising=False)
    monkeypatch.delenv("GITHUB_PR_LAMBDA_TOKEN", raising=False)
    with pytest.raises(ClientError, match="GITHUB_PR_LAMBDA_URL"):
        fetch_snapshot(opener=lambda *_args, **_kwargs: io.BytesIO())
