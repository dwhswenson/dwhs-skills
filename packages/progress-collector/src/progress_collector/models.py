"""Public data model and JSON serialization helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def isoformat(value: datetime) -> str:
    """Serialize an aware datetime as a canonical UTC timestamp."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TimeRange:
    """A half-open time interval interpreted with an IANA timezone."""

    start: datetime
    end: datetime
    timezone: str

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        if self.end.tzinfo is None or self.end.utcoffset() is None:
            raise ValueError("end must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("start must be before end")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"timezone must be an IANA timezone: {self.timezone}") from exc

    def to_dict(self) -> dict[str, str]:
        return {
            "start": isoformat(self.start),
            "end": isoformat(self.end),
            "timezone": self.timezone,
        }


@dataclass(frozen=True)
class Activity:
    """A source-normalized activity record."""

    id: str
    kind: str
    occurred_at: datetime
    title: str
    url: str | None = None
    links: tuple[Mapping[str, str], ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "occurred_at": isoformat(self.occurred_at),
            "title": self.title,
            "links": [dict(link) for link in self.links],
            "details": dict(self.details),
        }
        if self.url is not None:
            body["url"] = self.url
        return body


@dataclass(frozen=True)
class SourceResult:
    """The success, absence, or failure state of a single source."""

    source: str
    status: str
    items: tuple[Activity, ...] = ()
    error: Mapping[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
        }
        if self.error is not None:
            body["error"] = dict(self.error)
        return body


@dataclass(frozen=True)
class CollectionDocument:
    """The persisted JSON-friendly result of one collection attempt."""

    time_range: TimeRange
    sources: Mapping[str, SourceResult]
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "collected_at": isoformat(self.collected_at),
            "range": self.time_range.to_dict(),
            "sources": {name: result.to_dict() for name, result in self.sources.items()},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
