from __future__ import annotations

from datetime import UTC, datetime

from progress_collector import CalendarConfig, TimeRange
from progress_collector.calendar import GoogleCalendarCollector


def period():
    return TimeRange(
        datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC), "America/Chicago"
    )


class Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class Events:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return Request(self.payload)


class Service:
    def __init__(self, payload):
        self.event_api = Events(payload)

    def events(self):
        return self.event_api


def test_calendar_expands_events_and_reports_rsvp_and_all_day():
    service = Service(
        {
            "items": [
                {
                    "id": "meeting",
                    "summary": "Standup",
                    "htmlLink": "https://calendar/event",
                    "start": {"dateTime": "2026-07-01T09:00:00-05:00"},
                    "end": {"dateTime": "2026-07-01T09:30:00-05:00"},
                    "attendees": [{"self": True, "responseStatus": "accepted"}],
                    "conferenceData": {
                        "entryPoints": [
                            {"uri": "https://meet.google.com/x", "label": "Google Meet"}
                        ]
                    },
                    "organizer": {"email": "host@example.test"},
                },
                {
                    "id": "holiday",
                    "summary": "Holiday",
                    "start": {"date": "2026-07-01"},
                    "end": {"date": "2026-07-02"},
                },
            ]
        }
    )
    config = CalendarConfig(("primary",), credentials=object())
    result = GoogleCalendarCollector(service=service).collect(period(), config)
    assert result.status == "ok"
    meeting = next(item for item in result.items if item.id == "primary:meeting")
    holiday = next(item for item in result.items if item.id == "primary:holiday")
    assert meeting.details["is_accepted"] is True
    assert meeting.details["response_status"] == "accepted"
    assert holiday.details["all_day"] is True
    assert service.event_api.calls[0]["singleEvents"] is True
    assert service.event_api.calls[0]["calendarId"] == "primary"


def test_calendar_marks_unknown_rsvp():
    service = Service(
        {
            "items": [
                {
                    "id": "e",
                    "start": {"dateTime": "2026-07-01T10:00:00Z"},
                    "end": {"dateTime": "2026-07-01T11:00:00Z"},
                }
            ]
        }
    )
    result = GoogleCalendarCollector(service=service).collect(
        period(), CalendarConfig(("work",), credentials=object())
    )
    assert result.items[0].details["is_accepted"] is None
    assert result.items[0].details["response_status"] == "unknown"
