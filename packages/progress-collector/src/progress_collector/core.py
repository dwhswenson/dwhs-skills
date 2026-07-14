"""Collector orchestration and extension point."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from .models import CollectionDocument, SourceResult, TimeRange


class Collector(Protocol):
    source: str

    def collect(self, time_range: TimeRange, config: Any | None = None) -> SourceResult: ...


class CollectionFailed(RuntimeError):
    """Raised by strict collection after every configured source has been attempted."""

    def __init__(self, document: CollectionDocument):
        super().__init__("One or more progress sources failed")
        self.document = document


def default_collectors() -> tuple[Collector, ...]:
    from .calendar import GoogleCalendarCollector
    from .github import GitHubCollector
    from .linear import LinearCollector

    return (GitHubCollector(), LinearCollector(), GoogleCalendarCollector())


def collect_all(
    time_range: TimeRange,
    configs: Mapping[str, Any] | None = None,
    collectors: Iterable[Collector] | None = None,
    *,
    strict: bool = False,
) -> CollectionDocument:
    """Collect each source independently with only its own configuration."""
    results: dict[str, SourceResult] = {}
    configured_sources = configs or {}
    for collector in collectors or default_collectors():
        try:
            result = collector.collect(time_range, configured_sources.get(collector.source))
        except Exception:
            # Collectors are expected to map provider failures themselves. This is a final
            # guard that deliberately avoids emitting exception text, which may contain secrets.
            result = SourceResult(
                collector.source,
                "error",
                error={"code": "unexpected_error", "message": "Collection failed"},
            )
        results[collector.source] = result
    document = CollectionDocument(time_range=time_range, sources=results)
    if strict and any(result.status == "error" for result in results.values()):
        raise CollectionFailed(document)
    return document
