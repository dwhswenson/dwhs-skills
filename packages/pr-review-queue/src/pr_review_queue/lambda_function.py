"""AWS Lambda handler for the pending GitHub pull request review queue."""

from __future__ import annotations

import hmac
import json
import os
from typing import Any

from .snapshot import GitHubError, build_snapshot, serialize_snapshot

SNAPSHOT_KEY = "pr-review-queue/current.json"
_SECRET_CACHE: dict[str, dict[str, str]] = {}


class ConfigurationError(RuntimeError):
    """Raised when Lambda configuration is missing or invalid."""


class SnapshotError(RuntimeError):
    """Raised when the dashboard snapshot cannot be written."""


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _aws_client(service: str) -> Any:
    import boto3

    return boto3.client(service)


def load_secret(secret_id: str, secrets_client: Any | None = None) -> dict[str, str]:
    if secret_id in _SECRET_CACHE:
        return _SECRET_CACHE[secret_id]

    client = secrets_client or _aws_client("secretsmanager")
    try:
        response = client.get_secret_value(SecretId=secret_id)
        payload = json.loads(response["SecretString"])
    except Exception as exc:
        raise ConfigurationError("Unable to load the configured secret") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError("The configured secret must contain a JSON object")
    for key in ("github_token", "invoke_token"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise ConfigurationError(f"The configured secret is missing {key}")

    secret = {"github_token": payload["github_token"], "invoke_token": payload["invoke_token"]}
    _SECRET_CACHE[secret_id] = secret
    return secret


def write_snapshot(
    bucket: str,
    snapshot_body: str,
    s3_client: Any | None = None,
) -> None:
    client = s3_client or _aws_client("s3")
    try:
        client.put_object(
            Bucket=bucket,
            Key=SNAPSHOT_KEY,
            Body=snapshot_body.encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as exc:
        raise SnapshotError("Unable to write the dashboard snapshot") from exc


def _method(event: dict[str, Any]) -> str:
    return str(
        ((event.get("requestContext") or {}).get("http") or {}).get("method")
        or event.get("httpMethod")
        or ""
    ).upper()


def _bearer_token(event: dict[str, Any]) -> str | None:
    headers = {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.casefold() != "bearer" or not token:
        return None
    return token


def _response(status: int, body: dict[str, Any] | str) -> dict[str, Any]:
    serialized = body if isinstance(body, str) else json.dumps(body)
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": serialized,
    }


def _error(status: int, code: str, message: str) -> dict[str, Any]:
    return _response(status, {"error": {"code": code, "message": message}})


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    if _method(event) != "GET":
        return _error(405, "method_not_allowed", "Only GET is supported")

    try:
        secret_id = _required_env("GITHUB_PR_SECRET_ID")
        bucket = _required_env("DATA_BUCKET")
        secret = load_secret(secret_id)
    except ConfigurationError as exc:
        return _error(500, "configuration_error", str(exc))

    supplied_token = _bearer_token(event)
    if supplied_token is None or not hmac.compare_digest(supplied_token, secret["invoke_token"]):
        return _error(401, "unauthorized", "Invalid bearer token")

    try:
        snapshot = build_snapshot(secret["github_token"])
    except GitHubError as exc:
        return _error(502, "github_error", str(exc))

    body = serialize_snapshot(snapshot)
    try:
        write_snapshot(bucket, body)
    except SnapshotError as exc:
        return _error(500, "snapshot_error", str(exc))
    return _response(200, body)
