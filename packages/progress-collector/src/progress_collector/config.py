"""Credential configuration. Config objects are deliberately never serialized."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class GitHubConfig:
    token: str

    @classmethod
    def from_env(cls) -> GitHubConfig:
        return cls(token=_required("PROGRESS_COLLECTOR_GITHUB_TOKEN"))


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
