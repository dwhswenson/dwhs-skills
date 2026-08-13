"""Collect the previous day's progress and persist it to Amazon S3."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lambdacron.lambda_task import CronLambdaTask
from progress_collector import (
    CalendarConfig,
    CollectionDocument,
    GitHubConfig,
    LinearConfig,
    TimeRange,
    collect_all,
)

COLLECTED_RESULT_TYPE = "DAILY_PROGRESS_COLLECTED"
PARTIAL_RESULT_TYPE = "DAILY_PROGRESS_PARTIAL"
DEFAULT_TIMEZONE = "America/Chicago"
DEFAULT_PREFIX = "progress"
AUTH_DIRECTORY = Path("/tmp/progress-collector")


@dataclass(frozen=True)
class RuntimeConfig:
    """Configuration supplied to the scheduled Lambda through its environment."""

    bucket: str
    secret_id: str
    timezone: str = DEFAULT_TIMEZONE
    prefix: str = DEFAULT_PREFIX

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RuntimeConfig:
        source = os.environ if env is None else env
        bucket = source.get("DAILY_PROGRESS_BUCKET", "").strip()
        secret_id = source.get("PROGRESS_COLLECTOR_SECRET_ID", "").strip()
        timezone = source.get("DAILY_PROGRESS_TIMEZONE", DEFAULT_TIMEZONE).strip()
        prefix = source.get("DAILY_PROGRESS_PREFIX", DEFAULT_PREFIX).strip().strip("/")
        if not bucket:
            raise ValueError("DAILY_PROGRESS_BUCKET must be set")
        if not secret_id:
            raise ValueError("PROGRESS_COLLECTOR_SECRET_ID must be set")
        if not timezone:
            raise ValueError("DAILY_PROGRESS_TIMEZONE must be non-empty")
        if not prefix:
            raise ValueError("DAILY_PROGRESS_PREFIX must be non-empty")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("DAILY_PROGRESS_TIMEZONE must be an IANA timezone") from exc
        return cls(bucket=bucket, secret_id=secret_id, timezone=timezone, prefix=prefix)


def previous_day_time_range(now: datetime, timezone_name: str) -> tuple[date, TimeRange]:
    """Return the complete local calendar day preceding ``now``."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone_name must be an IANA timezone") from exc
    collection_date = now.astimezone(timezone).date() - timedelta(days=1)
    start = datetime.combine(collection_date, time.min, tzinfo=timezone)
    end = datetime.combine(collection_date + timedelta(days=1), time.min, tzinfo=timezone)
    return collection_date, TimeRange(start, end, timezone_name)


def object_key(prefix: str, collection_date: date) -> str:
    """Build the stable object key for a collection day."""
    normalized_prefix = prefix.strip().strip("/")
    if not normalized_prefix:
        raise ValueError("prefix must be non-empty")
    return f"{normalized_prefix}/{collection_date.isoformat()}/progress.json"


def write_auth_config(
    secret_id: str,
    secretsmanager_client: Any,
    *,
    directory: Path = AUTH_DIRECTORY,
) -> Path:
    """Fetch and securely materialize the portable progress-collector auth document."""
    response = secretsmanager_client.get_secret_value(SecretId=secret_id)
    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str):
        raise ValueError("Progress collector secret must contain SecretString JSON")
    try:
        document = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise ValueError("Progress collector secret contains invalid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("Progress collector secret must contain a JSON object")

    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "auth.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return path


def load_source_configs(auth_path: Path) -> dict[str, object]:
    """Load credentials for every progress source from the portable auth file."""
    return {
        "github": GitHubConfig.from_defaults(auth_path),
        "linear": LinearConfig.from_defaults(auth_path),
        "google_calendar": CalendarConfig.from_defaults(auth_path),
    }


def build_result(
    document: CollectionDocument,
    *,
    bucket: str,
    key: str,
    collection_date: date,
) -> dict[str, dict[str, Any]]:
    """Build a metadata-only lambdacron result without exposing activity or credentials."""
    failed_sources = sorted(
        source for source, result in document.sources.items() if result.status == "error"
    )
    result_type = PARTIAL_RESULT_TYPE if failed_sources else COLLECTED_RESULT_TYPE
    return {
        result_type: {
            "status": "partial" if failed_sources else "collected",
            "bucket": bucket,
            "key": key,
            "collection_date": collection_date.isoformat(),
            "collected_at": document.to_dict()["collected_at"],
            "source_item_counts": {
                source: len(result.items) for source, result in document.sources.items()
            },
            "failed_sources": failed_sources,
        }
    }


def collect_and_store(
    config: RuntimeConfig,
    *,
    secretsmanager_client: Any,
    s3_client: Any,
    now: datetime,
    collect: Callable[..., CollectionDocument] = collect_all,
    auth_directory: Path = AUTH_DIRECTORY,
) -> dict[str, dict[str, Any]]:
    """Collect all configured sources, persist the snapshot, and return result metadata."""
    collection_date, time_range = previous_day_time_range(now, config.timezone)
    auth_path = write_auth_config(
        config.secret_id,
        secretsmanager_client,
        directory=auth_directory,
    )
    try:
        configs = load_source_configs(auth_path)
    finally:
        auth_path.unlink(missing_ok=True)

    document = collect(time_range, configs, strict=False)
    key = object_key(config.prefix, collection_date)
    s3_client.put_object(
        Bucket=config.bucket,
        Key=key,
        Body=document.to_json().encode("utf-8"),
        ContentType="application/json",
    )
    return build_result(
        document,
        bucket=config.bucket,
        key=key,
        collection_date=collection_date,
    )


class DailyProgressTask(CronLambdaTask):
    """Lambdacron task that performs and stores one daily collection."""

    def __init__(
        self,
        *,
        secretsmanager_client: Any | None = None,
        s3_client: Any | None = None,
        now: Callable[[], datetime] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._secretsmanager_client = secretsmanager_client
        self._s3_client = s3_client
        self._now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def _aws_client(service: str) -> Any:
        import boto3

        return boto3.client(service)

    def _perform_task(self, event: Any, context: Any) -> dict[str, Any]:
        del event, context
        secretsmanager_client = self._secretsmanager_client or self._aws_client("secretsmanager")
        s3_client = self._s3_client or self._aws_client("s3")
        return collect_and_store(
            RuntimeConfig.from_env(),
            secretsmanager_client=secretsmanager_client,
            s3_client=s3_client,
            now=self._now(),
        )
