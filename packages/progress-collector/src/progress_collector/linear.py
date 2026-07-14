"""Linear GraphQL collector for viewer activity and viewer-assigned work."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from .config import LinearConfig
from .links import dedupe_links, link, urls_in_text
from .models import Activity, SourceResult, TimeRange, isoformat


class LinearError(RuntimeError):
    """A safe-to-report Linear request or response error."""


class LinearTransport:
    """Minimal injectable GraphQL transport; Linear queries stay source-specific."""

    endpoint = "https://api.linear.app/graphql"

    def __init__(self, config: LinearConfig, opener: Any = urllib.request.urlopen):
        self.config = config
        self.opener = opener

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        authorization = (
            f"{self.config.authorization_scheme} {self.config.token}"
            if self.config.authorization_scheme
            else self.config.token
        )
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, urllib.error.HTTPError) as exc:
            raise LinearError("Linear request failed") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("errors")
            or not isinstance(payload.get("data"), dict)
        ):
            raise LinearError("Linear returned an invalid GraphQL response")
        return payload["data"]


VIEWER_QUERY = """
query Viewer { viewer { id name } }
"""

# The history connection is paged separately below. Keeping the issue query shallow avoids a
# GraphQL N+1 response shape and follows Linear's recommendation to filter/paginate collections.
ISSUES_QUERY = """
query Issues($after: String, $start: DateTime!, $end: DateTime!) {
  issues(first: 100, after: $after, orderBy: updatedAt,
    filter: { updatedAt: { gte: $start, lt: $end } }) {
    nodes {
      id identifier title url description updatedAt
      assignee { id name }
      state { id name type }
      attachments(first: 100) { nodes { id title url } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

HISTORY_QUERY = """
query IssueHistory($id: String!, $after: String) {
  issue(id: $id) {
    history(first: 100, after: $after) {
      nodes {
        id createdAt actor { id name }
        fromState { id name type } toState { id name type }
        fromAssignee { id name } toAssignee { id name }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


class LinearCollector:
    source = "linear"

    def __init__(self, config: LinearConfig | None = None, *, transport: Any | None = None):
        self._config = config
        self._transport = transport

    def collect(self, time_range: TimeRange, config: LinearConfig | None = None) -> SourceResult:
        config = config or self._config
        if config is None:
            return SourceResult(self.source, "skipped")
        if not isinstance(config, LinearConfig):
            return SourceResult(
                self.source,
                "error",
                error={"code": "invalid_config", "message": "Invalid Linear configuration"},
            )
        try:
            transport = self._transport or LinearTransport(config)
            viewer = transport.execute(VIEWER_QUERY, {}).get("viewer", {})
            viewer_id = viewer.get("id")
            if not isinstance(viewer_id, str):
                raise LinearError("Linear viewer is unavailable")
            items = list(_activities(transport, viewer_id, time_range))
            items.sort(key=lambda item: item.occurred_at)
            return SourceResult(self.source, "ok", tuple(items))
        except Exception:
            return SourceResult(
                self.source,
                "error",
                error={"code": "linear_error", "message": "Unable to collect Linear progress"},
            )


def _activities(transport: Any, viewer_id: str, time_range: TimeRange) -> Iterator[Activity]:
    start, end = isoformat(time_range.start), isoformat(time_range.end)
    after: str | None = None
    while True:
        body = transport.execute(ISSUES_QUERY, {"after": after, "start": start, "end": end})
        connection = body.get("issues", {})
        for issue in connection.get("nodes", []):
            if not isinstance(issue, dict):
                continue
            viewer_assigned = issue.get("assignee", {}).get("id") == viewer_id
            for history in _history(transport, issue["id"]):
                activity = _history_activity(history, issue, viewer_id, viewer_assigned, time_range)
                if activity is not None:
                    yield activity
        page = connection.get("pageInfo", {})
        after = page.get("endCursor")
        if not page.get("hasNextPage") or not isinstance(after, str):
            return


def _history(transport: Any, issue_id: str) -> Iterator[dict[str, Any]]:
    after: str | None = None
    while True:
        body = transport.execute(HISTORY_QUERY, {"id": issue_id, "after": after})
        connection = body.get("issue", {}).get("history", {})
        for node in connection.get("nodes", []):
            if isinstance(node, dict):
                yield node
        page = connection.get("pageInfo", {})
        after = page.get("endCursor")
        if not page.get("hasNextPage") or not isinstance(after, str):
            return


def _history_activity(
    history: dict[str, Any],
    issue: dict[str, Any],
    viewer_id: str,
    viewer_assigned: bool,
    time_range: TimeRange,
) -> Activity | None:
    created_at = datetime.fromisoformat(history["createdAt"].replace("Z", "+00:00"))
    if not time_range.start <= created_at < time_range.end:
        return None
    actor = history.get("actor") or {}
    actor_is_viewer = actor.get("id") == viewer_id
    if not actor_is_viewer and not viewer_assigned:
        return None
    from_state, to_state = history.get("fromState"), history.get("toState")
    state_transition = isinstance(from_state, dict) or isinstance(to_state, dict)
    selection = (
        "actor_and_assignee"
        if actor_is_viewer and viewer_assigned
        else "actor"
        if actor_is_viewer
        else "assignee"
    )
    links = [link(issue.get("url"), issue.get("identifier"), "issue")]
    for attachment in issue.get("attachments", {}).get("nodes", []):
        if isinstance(attachment, dict):
            links.append(link(attachment.get("url"), attachment.get("title"), "attachment"))
    links.extend(urls_in_text(issue.get("description"), "description"))
    details: dict[str, Any] = {
        "record_type": "state_transition" if state_transition else "issue_change",
        "selection": selection,
        "actor_is_viewer": actor_is_viewer,
        "is_assigned_to_viewer_at_collection": viewer_assigned,
        "issue": {
            key: issue[key]
            for key in ("id", "identifier", "title", "url")
            if isinstance(issue.get(key), str)
        },
        "actor": {key: actor[key] for key in ("id", "name") if isinstance(actor.get(key), str)},
    }
    if isinstance(issue.get("assignee"), dict):
        details["current_assignee"] = issue["assignee"].get("name")
    if isinstance(issue.get("state"), dict):
        details["current_state"] = issue["state"].get("name")
    if state_transition:
        details["from_state"] = from_state.get("name") if isinstance(from_state, dict) else None
        details["to_state"] = to_state.get("name") if isinstance(to_state, dict) else None
    title = (
        issue.get("title")
        if isinstance(issue.get("title"), str)
        else issue.get("identifier", "Linear issue")
    )
    if state_transition:
        title = f"Moved {title} to {details['to_state'] or 'a new state'}"
    return Activity(
        id=str(history.get("id", f"linear:{issue['id']}:{history['createdAt']}")),
        kind=f"linear.{details['record_type']}",
        occurred_at=created_at,
        title=title,
        url=issue.get("url") if isinstance(issue.get("url"), str) else None,
        links=dedupe_links(links),
        details=details,
    )
