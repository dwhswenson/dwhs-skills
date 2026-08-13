from __future__ import annotations

import json
import stat
from datetime import UTC, datetime

import pytest

from progress_collector import Activity, CollectionDocument, SourceResult

from daily_progress import (
    COLLECTED_RESULT_TYPE,
    PARTIAL_RESULT_TYPE,
    RuntimeConfig,
    build_result,
    collect_and_store,
    object_key,
    previous_day_time_range,
    write_auth_config,
)


AUTH_DOCUMENT = {
    "version": 1,
    "sources": {
        "github": {"token": "github-secret"},
        "linear": {"token": "linear-secret"},
        "google_calendar": {
            "calendar_ids": ["primary"],
            "client_id": "client-id",
            "client_secret": "client-secret",
            "refresh_token": "refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    },
}


class FakeSecretsManager:
    def __init__(self, value=AUTH_DOCUMENT):
        self.value = value
        self.secret_ids = []

    def get_secret_value(self, *, SecretId):
        self.secret_ids.append(SecretId)
        return {"SecretString": json.dumps(self.value)}


class FakeS3:
    def __init__(self, error=None):
        self.error = error
        self.objects = []

    def put_object(self, **kwargs):
        if self.error:
            raise self.error
        self.objects.append(kwargs)
        return {"VersionId": "version-1"}


def document(time_range, *, github_status="ok", github_items=()):
    return CollectionDocument(
        time_range=time_range,
        collected_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        sources={
            "github": SourceResult(
                "github",
                github_status,
                tuple(github_items),
                error=(
                    {"code": "provider_error", "message": "Collection failed"}
                    if github_status == "error"
                    else None
                ),
            ),
            "linear": SourceResult("linear", "ok"),
            "google_calendar": SourceResult("google_calendar", "ok"),
        },
    )


def test_previous_chicago_day_uses_dst_aware_boundaries():
    collection_date, spring = previous_day_time_range(
        datetime(2026, 3, 9, 10, tzinfo=UTC), "America/Chicago"
    )
    assert collection_date.isoformat() == "2026-03-08"
    assert (spring.end.astimezone(UTC) - spring.start.astimezone(UTC)).total_seconds() == 23 * 3600

    collection_date, fall = previous_day_time_range(
        datetime(2026, 11, 2, 10, tzinfo=UTC), "America/Chicago"
    )
    assert collection_date.isoformat() == "2026-11-01"
    assert (fall.end.astimezone(UTC) - fall.start.astimezone(UTC)).total_seconds() == 25 * 3600


def test_previous_day_supports_arbitrary_timezone_and_rejects_naive_time():
    collection_date, time_range = previous_day_time_range(
        datetime(2026, 7, 17, 1, tzinfo=UTC), "Asia/Tokyo"
    )
    assert collection_date.isoformat() == "2026-07-16"
    assert time_range.timezone == "Asia/Tokyo"
    with pytest.raises(ValueError, match="timezone-aware"):
        previous_day_time_range(datetime(2026, 7, 17), "UTC")


def test_runtime_config_defaults_and_exact_object_key():
    config = RuntimeConfig.from_env(
        {
            "DAILY_PROGRESS_BUCKET": "daily-progress-test",
            "PROGRESS_COLLECTOR_SECRET_ID": "secret-id",
        }
    )
    assert config.timezone == "America/Chicago"
    assert config.prefix == "progress"
    collection_date, _ = previous_day_time_range(
        datetime(2026, 7, 17, 10, tzinfo=UTC), config.timezone
    )
    assert object_key(config.prefix, collection_date) == "progress/2026-07-16/progress.json"


def test_auth_secret_is_written_with_private_permissions(tmp_path):
    secret = FakeSecretsManager()
    path = write_auth_config("secret-id", secret, directory=tmp_path / "auth")
    assert json.loads(path.read_text()) == AUTH_DOCUMENT
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert secret.secret_ids == ["secret-id"]


@pytest.mark.parametrize(
    "response, message",
    [
        ({"SecretBinary": b"value"}, "SecretString"),
        ({"SecretString": "not-json"}, "invalid JSON"),
        ({"SecretString": "[]"}, "JSON object"),
    ],
)
def test_auth_secret_rejects_unsupported_values(tmp_path, response, message):
    class Client:
        def get_secret_value(self, **kwargs):
            return response

    with pytest.raises(ValueError, match=message):
        write_auth_config("secret-id", Client(), directory=tmp_path / "auth")


def test_collect_and_store_writes_complete_snapshot(tmp_path):
    s3 = FakeS3()
    seen = {}

    def collect(time_range, configs, *, strict):
        seen.update(time_range=time_range, configs=configs, strict=strict)
        item = Activity(
            id="event-1",
            kind="github.push",
            occurred_at=datetime(2026, 7, 16, 16, tzinfo=UTC),
            title="Pushed a commit",
        )
        return document(time_range, github_items=(item,))

    result = collect_and_store(
        RuntimeConfig("daily-progress-test", "secret-id"),
        secretsmanager_client=FakeSecretsManager(),
        s3_client=s3,
        now=datetime(2026, 7, 17, 10, tzinfo=UTC),
        collect=collect,
        auth_directory=tmp_path / "auth",
    )

    assert seen["strict"] is False
    assert set(seen["configs"]) == {"github", "linear", "google_calendar"}
    assert not (tmp_path / "auth" / "auth.json").exists()
    assert result == {
        COLLECTED_RESULT_TYPE: {
            "status": "collected",
            "bucket": "daily-progress-test",
            "key": "progress/2026-07-16/progress.json",
            "collection_date": "2026-07-16",
            "collected_at": "2026-07-17T10:00:00Z",
            "source_item_counts": {"github": 1, "linear": 0, "google_calendar": 0},
            "failed_sources": [],
        }
    }
    assert len(s3.objects) == 1
    stored = s3.objects[0]
    assert stored["Bucket"] == "daily-progress-test"
    assert stored["Key"] == "progress/2026-07-16/progress.json"
    assert stored["ContentType"] == "application/json"
    assert json.loads(stored["Body"])["sources"]["github"]["items"][0]["id"] == "event-1"


def test_partial_snapshot_is_persisted_with_metadata_only_result(tmp_path):
    s3 = FakeS3()

    def collect(time_range, configs, *, strict):
        return document(time_range, github_status="error")

    result = collect_and_store(
        RuntimeConfig("daily-progress-test", "secret-id"),
        secretsmanager_client=FakeSecretsManager(),
        s3_client=s3,
        now=datetime(2026, 7, 17, 10, tzinfo=UTC),
        collect=collect,
        auth_directory=tmp_path / "auth",
    )
    payload = result[PARTIAL_RESULT_TYPE]
    assert payload["failed_sources"] == ["github"]
    assert "sources" not in payload
    assert "github-secret" not in json.dumps(result)
    assert json.loads(s3.objects[0]["Body"])["sources"]["github"]["status"] == "error"


def test_empty_success_is_not_partial():
    _, time_range = previous_day_time_range(
        datetime(2026, 7, 17, 10, tzinfo=UTC), "America/Chicago"
    )
    result = build_result(
        document(time_range),
        bucket="bucket",
        key="progress/2026-07-16/progress.json",
        collection_date=time_range.start.date(),
    )
    assert list(result) == [COLLECTED_RESULT_TYPE]


def test_s3_failure_is_raised(tmp_path):
    def collect(time_range, configs, *, strict):
        return document(time_range)

    with pytest.raises(RuntimeError, match="S3 unavailable"):
        collect_and_store(
            RuntimeConfig("daily-progress-test", "secret-id"),
            secretsmanager_client=FakeSecretsManager(),
            s3_client=FakeS3(RuntimeError("S3 unavailable")),
            now=datetime(2026, 7, 17, 10, tzinfo=UTC),
            collect=collect,
            auth_directory=tmp_path / "auth",
        )
