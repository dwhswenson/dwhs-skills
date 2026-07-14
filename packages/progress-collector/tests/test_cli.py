from __future__ import annotations

import json
from datetime import UTC, datetime

from progress_collector.cli import _default_time_range, _parse_datetime, main, render_table
from progress_collector.models import Activity, CollectionDocument, SourceResult, TimeRange


def document() -> CollectionDocument:
    period = TimeRange(
        datetime(2026, 7, 14, tzinfo=UTC), datetime(2026, 7, 15, tzinfo=UTC), "UTC"
    )
    return CollectionDocument(
        period,
        {
            "github": SourceResult(
                "github",
                "ok",
                (Activity("1", "github.push", period.start, "Pushed a change", "https://example.test"),),
            )
        },
        collected_at=period.start,
    )


def test_main_limits_sources_and_can_print_json(monkeypatch, capsys):
    seen = {}

    monkeypatch.setattr(
        "progress_collector.cli._configs", lambda sources: seen.update(sources=sources) or {}
    )
    monkeypatch.setattr("progress_collector.cli.collect_all", lambda *args: document())

    assert main(["--github", "--json", "--start", "2026-07-14", "--end", "2026-07-15"]) == 0
    assert seen["sources"] == ("github",)
    assert json.loads(capsys.readouterr().out)["sources"]["github"]["status"] == "ok"


def test_main_collects_all_sources_without_selection(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        "progress_collector.cli._configs", lambda sources: seen.update(sources=sources) or {}
    )
    monkeypatch.setattr("progress_collector.cli.collect_all", lambda *args: document())

    assert main(["--start", "2026-07-14", "--end", "2026-07-15"]) == 0
    assert seen["sources"] == ("github", "linear", "google_calendar")


def test_render_table_includes_empty_and_error_sources():
    period = TimeRange(
        datetime(2026, 7, 14, tzinfo=UTC), datetime(2026, 7, 15, tzinfo=UTC), "UTC"
    )
    table = render_table(
        CollectionDocument(
            period,
            {
                "linear": SourceResult("linear", "ok"),
                "github": SourceResult("github", "error", error={"message": "Not available"}),
            },
        )
    )
    assert "Source | When | Activity | Progress | Link" in table
    assert "No progress found" in table
    assert "Not available" in table


def test_render_table_uses_human_readable_github_categories():
    period = TimeRange(
        datetime(2026, 7, 14, tzinfo=UTC), datetime(2026, 7, 15, tzinfo=UTC), "UTC"
    )
    table = render_table(
        CollectionDocument(
            period,
            {
                "github": SourceResult(
                    "github",
                    "ok",
                    (
                        Activity(
                            "1",
                            "github.create",
                            period.start,
                            "Created repository acme/repo",
                            details={"ref_type": "repository"},
                        ),
                    ),
                )
            },
        )
    )
    assert "Repository created" in table


def test_iso_dates_and_datetimes_are_interpreted_as_utc():
    assert _parse_datetime("2026-07-14") == datetime(2026, 7, 14, tzinfo=UTC)
    assert _parse_datetime("2026-07-14T09:30") == datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    assert _parse_datetime("2026-07-14T09:30-05:00").isoformat() == "2026-07-14T09:30:00-05:00"


def test_default_range_starts_at_utc_midnight_and_ends_now():
    now = datetime(2026, 7, 14, 17, 30, tzinfo=UTC)
    assert _default_time_range(now) == TimeRange(
        datetime(2026, 7, 14, tzinfo=UTC), now, "UTC"
    )
