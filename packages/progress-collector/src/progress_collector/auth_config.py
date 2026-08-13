"""Portable, local storage for progress-collector authentication credentials."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

AUTH_CONFIG_ENV = "PROGRESS_COLLECTOR_AUTH_CONFIG_FILE"
SCHEMA_VERSION = 1
_SOURCES = {"github", "linear", "google_calendar"}


class AuthConfigError(ValueError):
    """Raised when an auth configuration cannot be safely used."""


def default_auth_config_path() -> Path:
    return Path(user_config_path("progress-collector")) / "auth.json"


def resolve_auth_config_path(config_file: str | Path | None = None) -> Path:
    if config_file is not None:
        return Path(config_file).expanduser()
    if configured := os.environ.get(AUTH_CONFIG_ENV):
        return Path(configured).expanduser()
    return default_auth_config_path()


class AuthConfigStore:
    """Versioned portable credential store with strict POSIX file permissions."""

    def __init__(self, config_file: str | Path | None = None):
        self.path = resolve_auth_config_path(config_file)

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists() and not self.path.is_symlink():
            return {}
        self._validate_private_directory(self.path.parent)
        self._validate_private_file(self.path)
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthConfigError("Auth configuration is unreadable or invalid JSON") from exc
        if not isinstance(document, dict) or document.get("version") != SCHEMA_VERSION:
            raise AuthConfigError("Unsupported auth configuration schema")
        sources = document.get("sources")
        if not isinstance(sources, dict) or any(source not in _SOURCES for source in sources):
            raise AuthConfigError("Auth configuration has invalid sources")
        return {source: self._validate_source(source, value) for source, value in sources.items()}

    def source(self, source: str) -> dict[str, Any] | None:
        return self.load().get(source)

    def save_source(self, source: str, values: dict[str, Any]) -> None:
        if source not in _SOURCES:
            raise AuthConfigError("Unsupported auth source")
        sources = self.load()
        sources[source] = self._validate_source(source, values)
        self._write(sources)

    def remove_source(self, source: str) -> bool:
        if source not in _SOURCES:
            raise AuthConfigError("Unsupported auth source")
        sources = self.load()
        if source not in sources:
            return False
        del sources[source]
        self._write(sources)
        return True

    def _write(self, sources: dict[str, dict[str, Any]]) -> None:
        directory = self.path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._validate_private_directory(directory)
        if self.path.exists() or self.path.is_symlink():
            self._validate_private_file(self.path)
        document = {"version": SCHEMA_VERSION, "sources": sources}
        try:
            descriptor, temporary_name = tempfile.mkstemp(prefix=".auth-", dir=directory)
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                os.chmod(temporary, 0o600)
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise AuthConfigError("Unable to write auth configuration") from exc

    @staticmethod
    def _validate_private_directory(path: Path) -> None:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise AuthConfigError("Auth configuration directory is inaccessible") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise AuthConfigError("Auth configuration directory must be private (mode 700)")

    @staticmethod
    def _validate_private_file(path: Path) -> None:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise AuthConfigError("Auth configuration is inaccessible") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise AuthConfigError("Auth configuration must be a regular file")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise AuthConfigError("Auth configuration must be private (mode 600)")

    @staticmethod
    def _validate_source(source: str, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise AuthConfigError("Auth configuration source must be an object")
        required: dict[str, tuple[str, ...]] = {
            "github": ("token",),
            "linear": ("token",),
            "google_calendar": ("calendar_ids", "client_id", "client_secret", "refresh_token"),
        }
        keys = required[source]
        credential_keys = tuple(key for key in keys if key != "calendar_ids")
        if any(not isinstance(value.get(key), str) or not value[key] for key in credential_keys):
            raise AuthConfigError(f"Auth configuration has invalid {source} credentials")
        if source == "google_calendar":
            calendar_ids = value.get("calendar_ids")
            if (
                not isinstance(calendar_ids, list)
                or not calendar_ids
                or not all(isinstance(item, str) and item for item in calendar_ids)
            ):
                raise AuthConfigError("Auth configuration has invalid Google calendar IDs")
            token_uri = value.get("token_uri", "https://oauth2.googleapis.com/token")
            if not isinstance(token_uri, str) or not token_uri:
                raise AuthConfigError("Auth configuration has invalid Google token URI")
            return {
                "calendar_ids": calendar_ids,
                "client_id": value["client_id"],
                "client_secret": value["client_secret"],
                "refresh_token": value["refresh_token"],
                "token_uri": token_uri,
            }
        return {"token": value["token"]}
