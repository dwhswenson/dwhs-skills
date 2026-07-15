from __future__ import annotations

import json

import pytest

from authored_pr_queue import cli as module


def pull_request(number: int, status: str) -> dict:
    return {
        "repository": "acme/repo",
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/acme/repo/pull/{number}",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
        "status": status,
        "requested_reviewers": ["waiting"] if status != "needs_review_request" else [],
        "requested_teams": [],
        "latest_reviews": [
            {
                "reviewer": "reviewer",
                "state": "CHANGES_REQUESTED",
                "submitted_at": "2026-07-01T12:00:00Z",
                "commit_id": "old",
                "has_new_commits_since_review": True,
                "awaits_author_action": status == "needs_author_action",
            }
        ],
    }


def snapshot() -> dict:
    return {
        "author": "author",
        "generated_at": "2026-07-03T00:00:00Z",
        "pull_requests": [
            pull_request(1, "needs_author_action"),
            pull_request(2, "needs_review_request"),
            pull_request(3, "partially_reviewed"),
            pull_request(4, "awaiting_review"),
        ],
    }


def configured_cli(monkeypatch):
    monkeypatch.setenv("GITHUB_PR_GITHUB_TOKEN", "gh")
    monkeypatch.setattr(module, "build_snapshot", lambda _token: snapshot())


def test_main_renders_all_status_groups_by_default(monkeypatch, capsys):
    configured_cli(monkeypatch)

    assert module.main([]) == 0

    captured = capsys.readouterr()
    assert "# Actionable Authored GitHub PRs" in captured.out
    assert "## Needs your action (1)" in captured.out
    assert "## Needs a review request (1)" in captured.out
    assert "## Partially reviewed (1)" in captured.out
    assert "## Awaiting review (1)" in captured.out
    assert "Awaiting you: @reviewer requested changes" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    ("status", "expected_number"),
    [
        ("needs-author-action", 1),
        ("needs-review-request", 2),
        ("partially-reviewed", 3),
        ("awaiting-review", 4),
    ],
)
def test_status_selects_each_status(monkeypatch, capsys, status, expected_number):
    configured_cli(monkeypatch)

    assert module.main(["--status", status, "--json"]) == 0

    captured = capsys.readouterr()
    selected = json.loads(captured.out)["pull_requests"]
    assert [record["number"] for record in selected] == [expected_number]
    assert captured.err == ""


def test_repeated_status_selects_multiple_statuses(monkeypatch, capsys):
    configured_cli(monkeypatch)

    assert module.main(
        ["--status", "needs-author-action", "--status", "awaiting-review", "--json"]
    ) == 0

    captured = capsys.readouterr()
    assert [record["number"] for record in json.loads(captured.out)["pull_requests"]] == [1, 4]


def test_output_writes_the_selected_snapshot(monkeypatch, tmp_path, capsys):
    configured_cli(monkeypatch)
    output = tmp_path / "authored-prs.json"

    assert module.main(["--status", "partially-reviewed", "--output", str(output), "--json"]) == 0

    captured = capsys.readouterr()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["author"] == "author"
    assert [record["number"] for record in written["pull_requests"]] == [3]
    assert json.loads(captured.out) == written
    assert captured.err == ""


def test_main_reports_missing_environment(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_PR_GITHUB_TOKEN", raising=False)

    assert module.main([]) == 1

    captured = capsys.readouterr()
    assert "GITHUB_PR_GITHUB_TOKEN" in captured.err


def test_main_reports_github_failure(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_PR_GITHUB_TOKEN", "gh")

    def fail(_token):
        raise module.GitHubError("GitHub unavailable")

    monkeypatch.setattr(module, "build_snapshot", fail)

    assert module.main([]) == 1

    captured = capsys.readouterr()
    assert "GitHub unavailable" in captured.err


def test_main_reports_output_failure(monkeypatch, tmp_path, capsys):
    configured_cli(monkeypatch)
    output = tmp_path / "authored-prs.json"

    def fail(_path, _body):
        raise module.LocalOutputError("disk unavailable")

    monkeypatch.setattr(module, "_write_snapshot", fail)

    assert module.main(["--output", str(output)]) == 1

    captured = capsys.readouterr()
    assert "disk unavailable" in captured.err


def test_invalid_status_is_rejected():
    with pytest.raises(SystemExit) as exc_info:
        module.main(["--status", "unknown"])

    assert exc_info.value.code == 2
