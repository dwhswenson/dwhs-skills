"""Deterministic Lambda used to verify the locally deployed AWS wiring."""

from __future__ import annotations

import json
import os

import boto3


def handler(event, context):
    del event, context
    bucket = os.environ["DAILY_PROGRESS_BUCKET"]
    prefix = os.environ["DAILY_PROGRESS_PREFIX"]
    secret_id = os.environ["PROGRESS_COLLECTOR_SECRET_ID"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    secret = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    secret_loaded = secret.get("SecretString") == "daily-progress-e2e-sentinel"
    payload = {
        "bucket": bucket,
        "prefix": prefix,
        "secret_loaded": secret_loaded,
        "timezone": os.environ["DAILY_PROGRESS_TIMEZONE"],
    }

    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=f"{prefix}/probe.json",
        Body=json.dumps(payload, sort_keys=True).encode(),
        ContentType="application/json",
    )
    publish = boto3.client("sns").publish(
        TopicArn=topic_arn,
        Message=json.dumps({"status": "probe-complete"}),
        MessageGroupId="daily-progress-e2e",
    )
    return {
        "status": "ok",
        "secret_loaded": secret_loaded,
        "sns_message_id": publish["MessageId"],
    }
