from __future__ import annotations

import json
import sys
import types

from progress_collector.auth_cli import main
from progress_collector.auth_config import AuthConfigStore


def test_linear_login_saves_validated_token_without_echoing_it(tmp_path, monkeypatch, capsys):
    config = tmp_path / "auth.json"
    monkeypatch.setattr("progress_collector.auth_cli.getpass.getpass", lambda _: "linear-secret")
    monkeypatch.setattr(
        "progress_collector.auth_cli.LinearTransport.execute",
        lambda *_: {"viewer": {"id": "viewer"}},
    )

    assert main(["linear", "login", "--config", str(config)]) == 0
    assert AuthConfigStore(config).source("linear") == {"token": "linear-secret"}
    assert "linear-secret" not in capsys.readouterr().out


def test_github_login_saves_validated_fine_grained_token_without_echoing_it(
    tmp_path, monkeypatch, capsys
):
    config = tmp_path / "auth.json"
    monkeypatch.setattr("progress_collector.auth_cli.getpass.getpass", lambda _: "github-secret")
    monkeypatch.setattr("progress_collector.auth_cli._validate_github_token", lambda _: None)

    assert main(["--config", str(config), "github", "login"]) == 0
    assert AuthConfigStore(config).source("github") == {"token": "github-secret"}
    assert "github-secret" not in capsys.readouterr().out


def test_github_login_can_explicitly_copy_a_gh_credential(tmp_path, monkeypatch):
    config = tmp_path / "auth.json"
    monkeypatch.setattr(
        "progress_collector.auth_cli.subprocess.run",
        lambda *_, **__: types.SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(
        "progress_collector.auth_cli._github_token_from_gh", lambda: "github-secret"
    )
    monkeypatch.setattr("progress_collector.auth_cli._validate_github_token", lambda _: None)

    assert main(["--config", str(config), "github", "login", "--use-gh"]) == 0
    assert AuthConfigStore(config).source("github") == {"token": "github-secret"}


def test_google_login_saves_refresh_credentials_and_explicit_calendars(tmp_path, monkeypatch):
    config = tmp_path / "auth.json"
    client = tmp_path / "client.json"
    client.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client.apps.googleusercontent.com",
                    "client_secret": "client-secret",
                    "token_uri": "https://oauth.example.test/token",
                }
            }
        )
    )

    class Flow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            assert path == str(client)
            assert scopes
            return cls()

        def run_local_server(self, **kwargs):
            assert kwargs["host"] == "127.0.0.1"
            assert kwargs["port"] == 8765
            assert kwargs["open_browser"] is False
            return types.SimpleNamespace(refresh_token="refresh-secret")

    package = types.ModuleType("google_auth_oauthlib")
    module = types.ModuleType("google_auth_oauthlib.flow")
    module.InstalledAppFlow = Flow
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", package)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", module)

    assert (
        main(
            [
                "google",
                "login",
                "--config",
                str(config),
                "--client-secrets",
                str(client),
                "--calendar",
                "primary",
                "--calendar",
                "work@example.test",
                "--no-browser",
                "--port",
                "8765",
            ]
        )
        == 0
    )
    assert AuthConfigStore(config).source("google_calendar") == {
        "calendar_ids": ["primary", "work@example.test"],
        "client_id": "client.apps.googleusercontent.com",
        "client_secret": "client-secret",
        "refresh_token": "refresh-secret",
        "token_uri": "https://oauth.example.test/token",
    }


def test_status_never_prints_stored_secret(tmp_path, capsys):
    config = tmp_path / "auth.json"
    AuthConfigStore(config).save_source("linear", {"token": "linear-secret"})

    assert main(["status", "--config", str(config)]) == 0
    output = capsys.readouterr().out
    assert "linear: configured" in output
    assert "linear-secret" not in output
