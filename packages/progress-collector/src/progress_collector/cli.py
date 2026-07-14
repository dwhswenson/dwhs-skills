"""Collect today's progress from GitHub, Linear, and Google Calendar."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time

from .config import CalendarConfig, GitHubConfig, LinearConfig
from .core import collect_all, default_collectors
from .models import CollectionDocument, TimeRange


class CLIConfigurationError(ValueError):
    """Raised when the requested CLI collection cannot be configured."""


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an ISO 8601 date or datetime") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _default_time_range(now: datetime) -> TimeRange:
    start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    return TimeRange(start, now, "UTC")


def _selected_sources(args: argparse.Namespace) -> tuple[str, ...]:
    requested = (
        ("github", args.github),
        ("linear", args.linear),
        ("google_calendar", args.calendar),
    )
    selected = tuple(source for source, enabled in requested if enabled)
    return selected or tuple(source for source, _ in requested)


def _configs(sources: Sequence[str]) -> dict[str, object]:
    configs: dict[str, object] = {}
    config_types = {
        "github": GitHubConfig,
        "linear": LinearConfig,
        "google_calendar": CalendarConfig,
    }
    for source in sources:
        try:
            configs[source] = config_types[source].from_env()
        except ValueError as exc:
            label = {"google_calendar": "calendar"}.get(source, source)
            raise CLIConfigurationError(f"Unable to configure {label}: {exc}") from exc
    return configs


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _category(kind: str, details: object) -> str:
    details = details if isinstance(details, Mapping) else {}
    if kind == "github.create":
        ref_type = details.get("ref_type")
        return f"{ref_type.capitalize()} created" if isinstance(ref_type, str) else "Created"
    if kind == "github.delete":
        ref_type = details.get("ref_type")
        return f"{ref_type.capitalize()} deleted" if isinstance(ref_type, str) else "Deleted"
    labels = {
        "github.pullrequest": "Pull request",
        "github.pullrequestreview": "Pull request review",
        "github.pullrequestreviewcomment": "Pull request review comment",
        "github.push": "Commits pushed",
    }
    if kind == "github.push":
        return labels[kind]
    prefix, _, action = kind.rpartition(".")
    if prefix in labels:
        if not action:
            return labels[prefix]
        return f"{labels[prefix]} {action}"
    return kind.removeprefix("github.").replace(".", " ").replace("_", " ").capitalize()


def render_table(document: CollectionDocument) -> str:
    """Render collected activities as a compact Markdown table."""
    rows: list[tuple[str, str, str, str, str]] = []
    for source, result in document.sources.items():
        if result.status == "error":
            message = (result.error or {}).get("message", "Collection failed")
            rows.append((source, "—", "error", message, ""))
        elif not result.items:
            rows.append((source, "—", result.status, "No progress found", ""))
        else:
            rows.extend(
                (
                    source,
                    item.occurred_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"),
                    _category(item.kind, item.details),
                    item.title,
                    item.url or "",
                )
                for item in result.items
            )
    headers = ("Source", "When", "Activity", "Progress", "Link")
    lines = [
        " | ".join(headers),
        " | ".join("---" for _ in headers),
        *(" | ".join(_cell(value) for value in row) for row in rows),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github", action="store_true", help="collect GitHub activity")
    parser.add_argument("--linear", action="store_true", help="collect Linear activity")
    parser.add_argument("--calendar", action="store_true", help="collect Google Calendar events")
    parser.add_argument("--json", action="store_true", help="print the collected JSON document")
    parser.add_argument(
        "--start", type=_parse_datetime, help="ISO 8601 start (default: today at 00:00 UTC)"
    )
    parser.add_argument("--end", type=_parse_datetime, help="ISO 8601 end (default: now)")
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    default_range = _default_time_range(now)
    try:
        time_range = TimeRange(
            args.start or default_range.start, args.end or default_range.end, "UTC"
        )
    except ValueError as exc:
        parser.error(str(exc))
    sources = _selected_sources(args)
    try:
        configs = _configs(sources)
    except CLIConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    document = collect_all(
        time_range,
        configs,
        (collector for collector in default_collectors() if collector.source in sources),
    )
    output = document.to_json() if args.json else render_table(document)
    print(output, end="" if args.json else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
