"""Set up portable authentication for progress-collector."""

from __future__ import annotations

import argparse
import getpass
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .auth_config import AuthConfigError, AuthConfigStore
from .config import LinearConfig, _github_token_from_gh
from .linear import VIEWER_QUERY, LinearTransport

GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"


def _store(config_file: str | None) -> AuthConfigStore:
    return AuthConfigStore(config_file)


def _save_google(args: argparse.Namespace) -> int:
    try:
        client = _desktop_client(Path(args.client_secrets))
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(
            args.client_secrets, [GOOGLE_CALENDAR_SCOPE]
        )
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=args.port,
            open_browser=not args.no_browser,
            authorization_prompt_message=(
                "Open this URL in a browser to authorize Google Calendar access:\n{url}\n"
            ),
        )
        if not credentials.refresh_token:
            raise ValueError("Google did not return a refresh token; revoke access and try again")
        _store(getattr(args, "config", None)).save_source(
            "google_calendar",
            {
                "calendar_ids": args.calendar,
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": credentials.refresh_token,
                "token_uri": client.get("token_uri", "https://oauth2.googleapis.com/token"),
            },
        )
    except Exception:
        print("Error: unable to configure Google Calendar", file=sys.stderr)
        return 1
    print("Google Calendar authentication saved.")
    return 0


def _desktop_client(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("client secrets file is unreadable or invalid JSON") from exc
    installed = document.get("installed") if isinstance(document, dict) else None
    if not isinstance(installed, dict):
        raise ValueError("client secrets must describe a Google Desktop application")
    required = ("client_id", "client_secret")
    if any(not isinstance(installed.get(key), str) or not installed[key] for key in required):
        raise ValueError("client secrets file is missing required Desktop client credentials")
    result: dict[str, str] = {key: installed[key] for key in required}
    if isinstance(installed.get("token_uri"), str) and installed["token_uri"]:
        result["token_uri"] = installed["token_uri"]
    return result


def _save_linear(args: argparse.Namespace) -> int:
    token = getpass.getpass("Linear personal API key: ").strip()
    if not token:
        print("Error: Linear API key must not be empty", file=sys.stderr)
        return 1
    try:
        viewer = LinearTransport(LinearConfig(token)).execute(VIEWER_QUERY, {}).get("viewer")
        if not isinstance(viewer, dict) or not isinstance(viewer.get("id"), str):
            raise ValueError("Linear did not return a viewer")
        _store(getattr(args, "config", None)).save_source("linear", {"token": token})
    except (AuthConfigError, ValueError, RuntimeError):
        print("Error: unable to validate the Linear API key", file=sys.stderr)
        return 1
    print("Linear authentication saved.")
    return 0


def _save_github(args: argparse.Namespace) -> int:
    if args.use_gh:
        token = _github_token_after_login()
    else:
        token = getpass.getpass("GitHub fine-grained personal access token: ").strip()
    if not token:
        print("Error: GitHub token must not be empty", file=sys.stderr)
        return 1
    try:
        _validate_github_token(token)
        _store(getattr(args, "config", None)).save_source("github", {"token": token})
    except (AuthConfigError, RuntimeError):
        print("Error: unable to validate or save GitHub authentication", file=sys.stderr)
        return 1
    print("GitHub authentication saved.")
    return 0


def _github_token_after_login() -> str | None:
    try:
        login = subprocess.run(["gh", "auth", "login"], check=False)
    except FileNotFoundError:
        print("Error: GitHub CLI (gh) is required for --use-gh", file=sys.stderr)
        return None
    if login.returncode:
        return None
    return _github_token_from_gh()


def _validate_github_token(token: str) -> None:
    """Verify that the token can read the authenticated user's activity feed."""
    from github import Auth, Github

    client = Github(auth=Auth.Token(token), per_page=1, timeout=20, user_agent="progress-collector")
    try:
        authenticated_user = client.get_user()
        login = getattr(authenticated_user, "login", None)
        if not isinstance(login, str) or not login:
            raise RuntimeError("GitHub user is missing a login")
        next(iter(client.get_user(login).get_events()), None)
    except Exception as exc:
        raise RuntimeError("GitHub token cannot read the activity feed") from exc
    finally:
        client.close()


def _status(args: argparse.Namespace) -> int:
    try:
        configured = _store(getattr(args, "config", None)).load()
    except AuthConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for source in ("github", "linear", "google_calendar"):
        print(f"{source}: {'configured' if source in configured else 'not configured'}")
    return 0


def _logout(args: argparse.Namespace) -> int:
    aliases = {"google": "google_calendar", "calendar": "google_calendar"}
    source = aliases.get(args.source, args.source)
    try:
        removed = _store(getattr(args, "config", None)).remove_source(source)
    except AuthConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{source}: {'removed' if removed else 'not configured'}")
    return 0


def _path(args: argparse.Namespace) -> int:
    print(_store(getattr(args, "config", None)).path)
    return 0


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", default=argparse.SUPPRESS, help="portable auth configuration file"
    )
    parser = argparse.ArgumentParser(description=__doc__, parents=[common])
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", parents=[common], help="show configured auth sources")
    status.set_defaults(handler=_status)
    path = commands.add_parser("path", parents=[common], help="print the auth config path")
    path.set_defaults(handler=_path)
    logout = commands.add_parser("logout", parents=[common], help="remove a stored source")
    logout.add_argument("source", choices=("github", "linear", "google", "calendar"))
    logout.set_defaults(handler=_logout)

    github = commands.add_parser("github", parents=[common], help="configure GitHub")
    github_commands = github.add_subparsers(dest="github_command", required=True)
    github_login = github_commands.add_parser(
        "login", parents=[common], help="save a fine-grained personal access token"
    )
    github_login.add_argument(
        "--use-gh", action="store_true", help="copy the active gh credential instead"
    )
    github_login.set_defaults(handler=_save_github)

    linear = commands.add_parser("linear", parents=[common], help="configure Linear")
    linear_commands = linear.add_subparsers(dest="linear_command", required=True)
    linear_login = linear_commands.add_parser(
        "login", parents=[common], help="save a personal API key"
    )
    linear_login.set_defaults(handler=_save_linear)

    google = commands.add_parser("google", parents=[common], help="configure Google Calendar")
    google_commands = google.add_subparsers(dest="google_command", required=True)
    google_login = google_commands.add_parser(
        "login", parents=[common], help="run Google Desktop OAuth"
    )
    google_login.add_argument(
        "--client-secrets", required=True, help="Google Desktop OAuth client JSON"
    )
    google_login.add_argument(
        "--calendar", action="append", required=True, help="calendar ID to collect"
    )
    google_login.add_argument(
        "--no-browser", action="store_true", help="print URL instead of opening browser"
    )
    google_login.add_argument("--port", type=int, default=0, help="loopback port (default: random)")
    google_login.set_defaults(handler=_save_google)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not hasattr(args, "config"):
        args.config = None
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
