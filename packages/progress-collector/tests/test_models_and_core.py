from __future__ import annotations

from datetime import UTC, datetime

import pytest

from progress_collector import TimeRange, collect_all
from progress_collector.core import CollectionFailed
from progress_collector.models import Activity, SourceResult


def period():
    return TimeRange(
        datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC), "America/Chicago"
    )


def test_document_is_stable_json():
    seen = {}

    class Collector:
        source = "example"

        def collect(self, time_range, config=None):
            seen["time_range"] = time_range
            seen["config"] = config
            return SourceResult(
                "example", "ok", (Activity("1", "example.did", period().start, "Did it"),)
            )

    document = collect_all(period(), {"example": "source-only-config"}, [Collector()])
    assert seen == {"time_range": period(), "config": "source-only-config"}
    assert document.to_dict()["range"]["timezone"] == "America/Chicago"
    assert document.to_dict()["sources"]["example"]["items"][0]["occurred_at"].endswith("Z")
    assert '"schema_version": 1' in document.to_json()


def test_invalid_range_and_timezone_are_rejected():
    with pytest.raises(ValueError, match="start must be before end"):
        TimeRange(datetime(2026, 7, 2, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC), "UTC")
    with pytest.raises(ValueError, match="IANA"):
        TimeRange(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC), "not-a-zone")


def test_source_errors_are_partial_or_strict():
    class Broken:
        source = "broken"

        def collect(self, _time_range, _config=None):
            raise RuntimeError("secret-token")

    document = collect_all(period(), collectors=[Broken()])
    assert document.to_dict()["sources"]["broken"]["error"]["message"] == "Collection failed"
    with pytest.raises(CollectionFailed) as exc:
        collect_all(period(), collectors=[Broken()], strict=True)
    assert exc.value.document.sources["broken"].status == "error"
