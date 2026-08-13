from __future__ import annotations

import stat

import pytest

from progress_collector import CalendarConfig, LinearConfig
from progress_collector.auth_config import AuthConfigError, AuthConfigStore


def google_values():
    return {
        "calendar_ids": ["primary", "work@example.test"],
        "client_id": "client.apps.googleusercontent.com",
        "client_secret": "secret",
        "refresh_token": "refresh",
    }


def test_store_writes_private_portable_document(tmp_path):
    path = tmp_path / "private" / "auth.json"
    store = AuthConfigStore(path)
    store.save_source("linear", {"token": "linear-secret"})
    store.save_source("google_calendar", google_values())

    copied = tmp_path / "copied.json"
    copied.write_bytes(path.read_bytes())
    copied.chmod(0o600)
    assert AuthConfigStore(copied).source("linear") == {"token": "linear-secret"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_defaults_prefer_environment_over_auth_config(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    path.parent.chmod(0o700)
    store = AuthConfigStore(path)
    store.save_source("linear", {"token": "stored"})
    store.save_source("google_calendar", google_values())
    monkeypatch.setenv("PROGRESS_COLLECTOR_LINEAR_TOKEN", "environment")

    assert LinearConfig.from_defaults(path).token == "environment"
    assert CalendarConfig.from_defaults(path).refresh_token == "refresh"


def test_store_rejects_insecure_or_symlinked_config(tmp_path):
    insecure = tmp_path / "auth.json"
    insecure.write_text('{"version": 1, "sources": {}}')
    insecure.chmod(0o644)
    with pytest.raises(AuthConfigError, match="mode 600"):
        AuthConfigStore(insecure).load()

    target = tmp_path / "target.json"
    target.write_text('{"version": 1, "sources": {}}')
    target.chmod(0o600)
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)
    with pytest.raises(AuthConfigError, match="regular file"):
        AuthConfigStore(linked).load()

    linked_directory = tmp_path / "linked-directory"
    linked_directory.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(AuthConfigError, match="directory"):
        AuthConfigStore(linked_directory / "auth.json").save_source(
            "linear", {"token": "linear-secret"}
        )


def test_from_defaults_uses_environment_selected_config_path(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    path.parent.chmod(0o700)
    AuthConfigStore(path).save_source("linear", {"token": "stored"})
    monkeypatch.setenv("PROGRESS_COLLECTOR_AUTH_CONFIG_FILE", str(path))
    monkeypatch.delenv("PROGRESS_COLLECTOR_LINEAR_TOKEN", raising=False)
    assert LinearConfig.from_defaults().token == "stored"
