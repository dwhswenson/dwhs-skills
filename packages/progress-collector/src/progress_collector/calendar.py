"""Google Calendar collector for explicitly selected calendars."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import CalendarConfig
from .links import dedupe_links, link
from .models import Activity, SourceResult, TimeRange, isoformat


class GoogleCalendarCollector:
    source = "google_calendar"

    def __init__(self, config: CalendarConfig | None = None, *, service: Any | None = None):
        self._config = config
        self._service = service

    def collect(self, time_range: TimeRange, config: CalendarConfig | None = None) -> SourceResult:
        config = config or self._config
        if config is None:
            return SourceResult(self.source, "skipped")
        if not isinstance(config, CalendarConfig):
            return SourceResult(
                self.source,
                "error",
                error={"code": "invalid_config", "message": "Invalid Calendar configuration"},
            )
        try:
            service = self._service or _service(config)
            items: list[Activity] = []
            for calendar_id in config.calendar_ids:
                items.extend(_calendar_events(service, calendar_id, time_range))
            items.sort(key=lambda item: item.occurred_at)
            return SourceResult(self.source, "ok", tuple(items))
        except Exception:
            return SourceResult(
                self.source,
                "error",
                error={
                    "code": "calendar_error",
                    "message": "Unable to collect Google Calendar events",
                },
            )


def _service(config: CalendarConfig) -> Any:
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=config.resolved_credentials(), cache_discovery=False)


def _calendar_events(service: Any, calendar_id: str, time_range: TimeRange) -> list[Activity]:
    token: str | None = None
    events: list[Activity] = []
    while True:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=isoformat(time_range.start),
                timeMax=isoformat(time_range.end),
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=token,
            )
            .execute()
        )
        for event in response.get("items", []):
            if isinstance(event, dict):
                events.append(_activity(event, calendar_id, time_range.timezone))
        token = response.get("nextPageToken")
        if not isinstance(token, str) or not token:
            return events


def _event_start(event: dict[str, Any], timezone: str) -> tuple[datetime, bool]:
    start = event.get("start", {})
    if isinstance(start.get("dateTime"), str):
        return datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")), False
    if isinstance(start.get("date"), str):
        return datetime.fromisoformat(start["date"]).replace(tzinfo=ZoneInfo(timezone)), True
    raise ValueError("Calendar event is missing start")


def _event_end(event: dict[str, Any], timezone: str) -> datetime | None:
    end = event.get("end", {})
    if isinstance(end.get("dateTime"), str):
        return datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
    if isinstance(end.get("date"), str):
        return datetime.fromisoformat(end["date"]).replace(tzinfo=ZoneInfo(timezone))
    return None


def _activity(event: dict[str, Any], calendar_id: str, timezone: str) -> Activity:
    start, all_day = _event_start(event, timezone)
    end = _event_end(event, timezone)
    self_attendee = next(
        (item for item in event.get("attendees", []) if item.get("self") is True), None
    )
    response_status = (
        self_attendee.get("responseStatus") if isinstance(self_attendee, dict) else None
    )
    links = [link(event.get("htmlLink"), "Calendar event", "event")]
    conference = event.get("conferenceData", {})
    for entry in conference.get("entryPoints", []) if isinstance(conference, dict) else []:
        if isinstance(entry, dict):
            links.append(link(entry.get("uri"), entry.get("label"), "conference"))
    details: dict[str, Any] = {
        "calendar_id": calendar_id,
        "start": isoformat(start),
        "all_day": all_day,
        "response_status": response_status or "unknown",
        "is_accepted": response_status == "accepted" if response_status else None,
    }
    if end is not None:
        details["end"] = isoformat(end)
    if isinstance(event.get("location"), str):
        details["location"] = event["location"]
    organizer = event.get("organizer")
    if isinstance(organizer, dict) and isinstance(organizer.get("email"), str):
        details["organizer"] = organizer["email"]
    return Activity(
        id=f"{calendar_id}:{event.get('id', isoformat(start))}",
        kind="google_calendar.event",
        occurred_at=start.astimezone(UTC),
        title=event.get("summary") if isinstance(event.get("summary"), str) else "(Untitled event)",
        url=event.get("htmlLink") if isinstance(event.get("htmlLink"), str) else None,
        links=dedupe_links(links),
        details=details,
    )
