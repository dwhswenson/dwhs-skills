from __future__ import annotations

from datetime import UTC, datetime

from progress_collector import LinearConfig, TimeRange
from progress_collector.linear import HISTORY_QUERY, ISSUES_QUERY, VIEWER_QUERY, LinearCollector


def period():
    return TimeRange(
        datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC), "America/Chicago"
    )


class Transport:
    def execute(self, query, variables):
        if query == VIEWER_QUERY:
            return {"viewer": {"id": "me", "name": "Me"}}
        if query == ISSUES_QUERY:
            return {
                "issues": {
                    "nodes": [
                        {
                            "id": "issue-1",
                            "identifier": "ABC-1",
                            "title": "Improve thing",
                            "url": "https://linear.app/acme/issue/ABC-1",
                            "description": "PR https://github.com/acme/repo/pull/1",
                            "assignee": {"id": "me", "name": "Me"},
                            "state": {"name": "In Progress"},
                            "attachments": {
                                "nodes": [
                                    {"title": "PR", "url": "https://github.com/acme/repo/pull/1"}
                                ]
                            },
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        assert query == HISTORY_QUERY
        return {
            "issue": {
                "history": {
                    "nodes": [
                        {
                            "id": "move",
                            "createdAt": "2026-07-01T01:00:00Z",
                            "actor": {"id": "me", "name": "Me"},
                            "fromState": {"name": "Todo"},
                            "toState": {"name": "In Progress"},
                        },
                        {
                            "id": "assigned-change",
                            "createdAt": "2026-07-01T02:00:00Z",
                            "actor": {"id": "other", "name": "Other"},
                            "fromState": None,
                            "toState": None,
                        },
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }


def test_linear_marks_actor_and_assigned_records_and_extracts_links():
    result = LinearCollector(transport=Transport()).collect(period(), LinearConfig("key"))
    assert result.status == "ok"
    moved, assigned = result.items
    assert moved.details["record_type"] == "state_transition"
    assert moved.details["selection"] == "actor_and_assignee"
    assert moved.details["from_state"] == "Todo"
    assert assigned.details["record_type"] == "issue_change"
    assert assigned.details["selection"] == "assignee"
    assert [entry["url"] for entry in moved.links].count("https://github.com/acme/repo/pull/1") == 1
