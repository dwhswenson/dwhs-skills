"""Credential configuration. Config objects are deliberately never serialized."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any

from .auth_config import AuthConfigStore


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _github_token_from_gh() -> str | None:
    """Return the active GitHub CLI token, without exposing command failures."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    token = result.stdout.strip()
    return token or None


@dataclass(frozen=True)
class GitHubConfig:
    token: str

    @classmethod
    def from_env(cls) -> GitHubConfig:
        for name in ("PROGRESS_COLLECTOR_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
            if token := os.environ.get(name):
                return cls(token=token)
        if token := _github_token_from_gh():
            return cls(token=token)
        raise ValueError(
            "Missing GitHub authentication: set PROGRESS_COLLECTOR_GITHUB_TOKEN, "
            "GITHUB_TOKEN, or GH_TOKEN, or run gh auth login"
        )

    @classmethod
    def from_defaults(cls, config_file: str | os.PathLike[str] | None = None) -> GitHubConfig:
        names = ("PROGRESS_COLLECTOR_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")
        if any(os.environ.get(name) for name in names):
            return cls.from_env()
        if stored := AuthConfigStore(config_file).source("github"):
            return cls(token=stored["token"])
        return cls.from_env()


@dataclass(frozen=True)
class LinearConfig:
    token: str
    authorization_scheme: str | None = None

    @classmethod
    def from_env(cls) -> LinearConfig:
        return cls(
            token=_required("PROGRESS_COLLECTOR_LINEAR_TOKEN"),
            authorization_scheme=os.environ.get("PROGRESS_COLLECTOR_LINEAR_AUTHORIZATION_SCHEME"),
        )

    @classmethod
    def from_defaults(cls, config_file: str | os.PathLike[str] | None = None) -> LinearConfig:
        if os.environ.get("PROGRESS_COLLECTOR_LINEAR_TOKEN"):
            return cls.from_env()
        if stored := AuthConfigStore(config_file).source("linear"):
            return cls(token=stored["token"])
        return cls.from_env()


@dataclass(frozen=True)
class CalendarConfig:
    calendar_ids: tuple[str, ...]
    credentials: Any | None = None
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    token_uri: str = "https://oauth2.googleapis.com/token"

    def __post_init__(self) -> None:
        if not self.calendar_ids:
            raise ValueError("calendar_ids must not be empty")
        if self.credentials is None and not (
            self.client_id and self.client_secret and self.refresh_token
        ):
            raise ValueError(
                "provide credentials or OAuth client_id, client_secret, and refresh_token"
            )

    @classmethod
    def from_env(cls) -> CalendarConfig:
        calendar_ids = tuple(
            value.strip()
            for value in _required("PROGRESS_COLLECTOR_GOOGLE_CALENDAR_IDS").split(",")
            if value.strip()
        )
        return cls(
            calendar_ids=calendar_ids,
            client_id=_required("PROGRESS_COLLECTOR_GOOGLE_CLIENT_ID"),
            client_secret=_required("PROGRESS_COLLECTOR_GOOGLE_CLIENT_SECRET"),
            refresh_token=_required("PROGRESS_COLLECTOR_GOOGLE_REFRESH_TOKEN"),
            token_uri=os.environ.get(
                "PROGRESS_COLLECTOR_GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"
            ),
        )

    @classmethod
    def from_defaults(cls, config_file: str | os.PathLike[str] | None = None) -> CalendarConfig:
        names = (
            "PROGRESS_COLLECTOR_GOOGLE_CALENDAR_IDS",
            "PROGRESS_COLLECTOR_GOOGLE_CLIENT_ID",
            "PROGRESS_COLLECTOR_GOOGLE_CLIENT_SECRET",
            "PROGRESS_COLLECTOR_GOOGLE_REFRESH_TOKEN",
            "PROGRESS_COLLECTOR_GOOGLE_TOKEN_URI",
        )
        if any(os.environ.get(name) for name in names):
            return cls.from_env()
        if stored := AuthConfigStore(config_file).source("google_calendar"):
            return cls(
                calendar_ids=tuple(stored["calendar_ids"]),
                client_id=stored["client_id"],
                client_secret=stored["client_secret"],
                refresh_token=stored["refresh_token"],
                token_uri=stored["token_uri"],
            )
        return cls.from_env()

    def resolved_credentials(self) -> Any:
        if self.credentials is not None:
            return self.credentials
        from google.oauth2.credentials import Credentials

        return Credentials(
            token=None,
            refresh_token=self.refresh_token,
            token_uri=self.token_uri,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=["https://www.googleapis.com/auth/calendar.events.readonly"],
        )
