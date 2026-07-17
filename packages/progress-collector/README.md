# progress-collector

`progress-collector` produces a versioned JSON document of a user's progress from GitHub,
Linear, and explicitly selected Google Calendars. Use `collect-progress` to collect data and
`collect-progress-auth` to set up or move authentication.

## Collect progress

`collect-progress` prints a Markdown table. With no source flags it collects every source; use
`--github`, `--linear`, or `--calendar` to limit the report. Use `--json` for the versioned JSON
document. The default range starts at the beginning of today in UTC and ends at the current time.

```shell
collect-progress --github --json
collect-progress --linear --calendar --start 2026-07-14 --end 2026-07-15
collect-progress --auth-config /secure/path/auth.json --json
```

Both range arguments accept an ISO 8601 date or datetime, with an optional offset. A date and a
datetime without an offset are interpreted as UTC; for example: `2026-07-14`,
`2026-07-14T09:30`, or `2026-07-14T09:30-05:00`.

Each configured source is collected independently. A failed source is represented by a safe,
structured error while successful sources remain available; use `strict=True` to raise a
`CollectionFailed` exception after all sources have been attempted.

## Interactive authentication

`collect-progress-auth` keeps credentials in a portable JSON file. By default it is
`auth.json` in the operating system's user config directory; run
`collect-progress-auth path` to print its exact location. The directory is mode `700` and the
file is mode `600`. Use `--config PATH` with any auth command to use a different file.

```shell
collect-progress-auth github login
collect-progress-auth linear login
collect-progress-auth status
```

GitHub login safely prompts for a dedicated fine-grained personal access token and validates that
it can read the authenticated user's activity feed before saving it. Create it for the intended
account with User **Events: Read** and no repository permissions unless another task needs them;
authorize it for an organization's SSO policy when required. `collect-progress-auth github login
--use-gh` remains available to copy an existing GitHub CLI credential, but is less suitable for an
agent because that OAuth credential can have broader scopes. Linear login safely prompts for a
[personal API key](https://linear.app/developers/graphql) and validates it before saving it.
Neither `status` nor any success/error output displays tokens.

### Google Calendar

Before running Google setup, create a Google Cloud project, enable the Google Calendar API, and
create a **Desktop application** OAuth client. Download its client JSON. The setup requests only
`calendar.events.readonly` and requires at least one explicit calendar ID (`primary` is valid).

```shell
collect-progress-auth google login \
  --client-secrets ~/Downloads/client_secret.json \
  --calendar primary \
  --calendar work@example.com
```

The command opens the system browser and uses the supported local loopback OAuth callback. It
stores the client metadata, selected calendar IDs, and refresh token; it does not store an access
token. Do not use a pasted authorization code or Google's deprecated out-of-band flow.

For a long-lived agent, do not leave an External Google OAuth app in **Testing**: Calendar refresh
tokens issued there expire after seven days. Use a production-published app, or a Workspace
Internal/Trusted app when every user belongs to that organization.

For a machine with no browser, bind a known loopback port on the remote host and forward it from
your workstation before opening the printed URL locally:

```shell
# workstation, in a second terminal
ssh -L 8765:127.0.0.1:8765 ec2-host

# EC2 host
collect-progress-auth google login \
  --client-secrets /secure/client_secret.json \
  --calendar primary --no-browser --port 8765
```

The callback stays on loopback; do not expose the port publicly.

To remove a stored credential, use `collect-progress-auth logout github`,
`collect-progress-auth logout linear`, or `collect-progress-auth logout google`.

## Portable auth file and unattended hosts

The auth file is deliberately transferable: it contains GitHub, Linear, and Google credentials
needed for collection. Treat it exactly like a password. Do not commit it, put it in an agent
workspace, or paste its contents into OpenClaw configuration. Revoking or rotating credentials
requires replacing the file on every host that received it.

Bootstrap on an interactive machine, copy the file over SSH, then install it as a private file
owned by the OpenClaw service account. For an `openclaw` service user:

```shell
# interactive machine
collect-progress-auth status
scp "$(collect-progress-auth path)" ec2-host:/tmp/progress-collector-auth.json

# EC2 host
sudo install -d -o openclaw -g openclaw -m 700 /etc/openclaw/progress-collector
sudo install -o openclaw -g openclaw -m 600 \
  /tmp/progress-collector-auth.json /etc/openclaw/progress-collector/auth.json
sudo rm /tmp/progress-collector-auth.json
```

Set only the path—not the credential contents—in the OpenClaw systemd service environment. Add a
drop-in such as `/etc/systemd/system/openclaw.service.d/progress-collector.conf`:

```ini
[Service]
Environment=PROGRESS_COLLECTOR_AUTH_CONFIG_FILE=/etc/openclaw/progress-collector/auth.json
```

Then reload and restart the service, and run collection through the same service user or agent:

```shell
sudo systemctl daemon-reload
sudo systemctl restart openclaw
collect-progress --json
```

OpenClaw's global `.env` can alternatively set only
`PROGRESS_COLLECTOR_AUTH_CONFIG_FILE`; keep the auth JSON outside the workspace and readable only
by the service user.

## Environment configuration and library use

An external secret manager can continue to inject the existing source-specific variables. A
complete environment configuration for a source takes precedence over the portable auth file.

- GitHub: `PROGRESS_COLLECTOR_GITHUB_TOKEN`, `GITHUB_TOKEN`, or `GH_TOKEN`.
  Resolution is exactly that order, then the portable auth file, then `gh auth token`. Set a
  dedicated fine-grained PAT in `GITHUB_TOKEN` on OpenClaw to override a copied auth-file or
  GitHub CLI credential.
- Linear: `PROGRESS_COLLECTOR_LINEAR_TOKEN`, plus optional
  `PROGRESS_COLLECTOR_LINEAR_AUTHORIZATION_SCHEME` for externally managed bearer tokens.
- Calendar: `PROGRESS_COLLECTOR_GOOGLE_CLIENT_ID`,
  `PROGRESS_COLLECTOR_GOOGLE_CLIENT_SECRET`, `PROGRESS_COLLECTOR_GOOGLE_REFRESH_TOKEN`, and
  comma-separated `PROGRESS_COLLECTOR_GOOGLE_CALENDAR_IDS`.

Set `PROGRESS_COLLECTOR_AUTH_CONFIG_FILE` to select a transferred file without changing CLI
arguments. `Config.from_env()` methods retain their strict environment-based behavior. Python
callers that want the same environment-then-auth-file resolution should explicitly use
`from_defaults()`:

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
snapshot = collect_all(time_range, {"github": GitHubConfig.from_defaults()})
print(snapshot.to_json())
```

Each source collector is also usable independently with
`collector.collect(time_range, config=None)`. A config passed to `collect` overrides that
collector's optional constructor config; no collector receives another source's credentials.

## GitHub limitation

GitHub collection uses the authenticated user's REST activity feed rather than GraphQL. When the
token belongs to that user, it includes both public and private events. It only contains up to 300
events from the last 30 days and may be delayed. Historical reporting beyond that window must
consume previously persisted collection JSON or use a future dedicated backfill collector.
