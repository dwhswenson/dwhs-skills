# progress-collector

`progress-collector` produces a versioned JSON document of a user's progress from GitHub,
Linear, and selected Google Calendars. It is a library only: callers decide when to collect and
where to persist the result.

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from progress_collector import GitHubConfig, TimeRange, collect_all

timezone = ZoneInfo("America/Chicago")
time_range = TimeRange(
    datetime(2026, 7, 14, tzinfo=timezone),
    datetime(2026, 7, 15, tzinfo=timezone),
    "America/Chicago",
)
snapshot = collect_all(time_range, {"github": GitHubConfig.from_env()})
print(snapshot.to_json())
```

Each configured source is collected independently. A failed source is represented by a safe,
structured error while successful sources remain available; use `strict=True` to raise a
`CollectionFailed` exception after all sources have been attempted.

Each source collector is also usable independently with
`collector.collect(time_range, config=None)`. A config passed to `collect` overrides that
collector's optional constructor config; no collector receives another source's credentials.

## Source configuration

- `GitHubConfig`: an authenticated token, or `PROGRESS_COLLECTOR_GITHUB_TOKEN`.
- `LinearConfig`: a personal API key or bearer token, or
  `PROGRESS_COLLECTOR_LINEAR_TOKEN` plus optional
  `PROGRESS_COLLECTOR_LINEAR_AUTHORIZATION_SCHEME`.
- `CalendarConfig`: injected Google credentials, or pre-provisioned OAuth credentials from
  `PROGRESS_COLLECTOR_GOOGLE_CLIENT_ID`, `PROGRESS_COLLECTOR_GOOGLE_CLIENT_SECRET`,
  `PROGRESS_COLLECTOR_GOOGLE_REFRESH_TOKEN`, and comma-separated
  `PROGRESS_COLLECTOR_GOOGLE_CALENDAR_IDS`.

No interactive OAuth flow or credential persistence is performed by this package.

## GitHub limitation

GitHub collection uses the authenticated user's REST activity feed rather than GraphQL. It gives
the broadest activity coverage but only contains up to 300 events from the last 30 days and may be
delayed. Historical reporting beyond that window must consume previously persisted collection JSON
or use a future dedicated backfill collector.
