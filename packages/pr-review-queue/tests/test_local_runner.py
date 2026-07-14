from __future__ import annotations

import json

import pytest

from pr_review_queue import local_runner as module


def snapshot():
    return {
        "reviewer": "reviewer",
        "generated_at": "2026-06-11T00:00:00Z",
        "reviews": [],
    }


def test_main_reports_missing_environment(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_PR_GITHUB_TOKEN", raising=False)

    assert module.main([]) == 1

    captured = capsys.readouterr()
    assert "GITHUB_PR_GITHUB_TOKEN" in captured.err


def test_main_renders_markdown(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_PR_GITHUB_TOKEN", "gh")
    monkeypatch.setattr(module, "build_snapshot", lambda _token: snapshot())

    assert module.main([]) == 0

    captured = capsys.readouterr()
    assert "# Pending GitHub PR Reviews" in captured.out
    assert captured.err == ""


def test_main_prints_json(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_PR_GITHUB_TOKEN", "gh")
    monkeypatch.setattr(module, "build_snapshot", lambda _token: snapshot())

    assert module.main(["--json"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == snapshot()
    assert captured.err == ""


def test_main_writes_output_file(monkeypatch, tmp_path, capsys):
    payload = snapshot()
    monkeypatch.setenv("GITHUB_PR_GITHUB_TOKEN", "gh")
    monkeypatch.setattr(module, "build_snapshot", lambda _token: payload)

    output = tmp_path / "review-queue.json"
    assert module.main(["--output", str(output), "--json"]) == 0

    captured = capsys.readouterr()
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert json.loads(captured.out) == payload
    assert captured.err == ""


def test_main_reports_github_failure(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_PR_GITHUB_TOKEN", "gh")

    def fail(_token):
        raise module.GitHubError("GitHub unavailable")

    monkeypatch.setattr(module, "build_snapshot", fail)

    assert module.main([]) == 1

    captured = capsys.readouterr()
    assert "GitHub unavailable" in captured.err
