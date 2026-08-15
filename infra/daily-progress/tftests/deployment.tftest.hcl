mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:user/test"
      user_id    = "AIDATEST"
    }
  }
}

override_module {
  target = module.lambda_image_republish

  outputs = {
    lambda_image_uri_with_digest = "123456789012.dkr.ecr.us-east-2.amazonaws.com/daily-progress@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
}

override_module {
  target = module.lambdacron

  outputs = {
    scheduled_lambda_arn       = "arn:aws:lambda:us-east-2:123456789012:function:daily-progress-collector"
    scheduled_lambda_role_arn  = "arn:aws:iam::123456789012:role/daily-progress-collector-role"
    scheduled_lambda_role_name = "daily-progress-collector-role"
    sns_topic_arn              = "arn:aws:sns:us-east-2:123456789012:daily-progress-results.fifo"
  }
}

variables {
  aws_region             = "us-east-2"
  bucket_name            = "daily-progress-test"
  lambda_public_repo_url = "public.ecr.aws/example/daily-progress"
  tags = {
    environment = "test"
  }
}

run "secure_storage_and_runtime_contract" {
  command = plan

  assert {
    condition     = aws_s3_bucket.progress.bucket == "daily-progress-test" && !aws_s3_bucket.progress.force_destroy
    error_message = "The progress bucket must use the configured name and remain protected from force deletion."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.progress.block_public_acls &&
      aws_s3_bucket_public_access_block.progress.block_public_policy &&
      aws_s3_bucket_public_access_block.progress.ignore_public_acls &&
      aws_s3_bucket_public_access_block.progress.restrict_public_buckets
    )
    error_message = "Every S3 public-access safeguard must remain enabled."
  }

  assert {
    condition     = aws_s3_bucket_ownership_controls.progress.rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "The progress bucket must enforce bucket-owner ownership."
  }

  assert {
    condition = one(
      one(aws_s3_bucket_server_side_encryption_configuration.progress.rule).apply_server_side_encryption_by_default
    ).sse_algorithm == "AES256"
    error_message = "The progress bucket must use SSE-S3 encryption."
  }

  assert {
    condition     = aws_s3_bucket_versioning.progress.versioning_configuration[0].status == "Enabled"
    error_message = "The progress bucket must retain object versions."
  }

  assert {
    condition     = aws_secretsmanager_secret.progress_collector.recovery_window_in_days == 30
    error_message = "The credential secret must retain its 30-day recovery window."
  }

  assert {
    condition = (
      toset(data.aws_iam_policy_document.scheduled_lambda_storage.statement[0].actions) == toset(["s3:PutObject"]) &&
      toset(data.aws_iam_policy_document.scheduled_lambda_storage.statement[1].actions) == toset(["secretsmanager:GetSecretValue"])
    )
    error_message = "The Lambda storage policy must remain limited to object writes and secret reads."
  }

  assert {
    condition = (
      aws_s3_bucket.progress.tags.managed_by == "daily-progress" &&
      aws_s3_bucket.progress.tags.environment == "test" &&
      aws_secretsmanager_secret.progress_collector.tags.environment == "test"
    )
    error_message = "Default and caller-supplied tags must be applied to owned resources."
  }

  assert {
    condition = (
      output.bucket_name == "daily-progress-test" &&
      output.lambda_republished_image_uri == "123456789012.dkr.ecr.us-east-2.amazonaws.com/daily-progress@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" &&
      output.scheduled_lambda_arn == "arn:aws:lambda:us-east-2:123456789012:function:daily-progress-collector" &&
      output.scheduled_lambda_role_arn == "arn:aws:iam::123456789012:role/daily-progress-collector-role" &&
      output.sns_topic_arn == "arn:aws:sns:us-east-2:123456789012:daily-progress-results.fifo"
    )
    error_message = "Deployment outputs must forward the owned and lambdacron resource identifiers."
  }
}

run "reject_empty_schedule" {
  command = plan

  variables {
    schedule_expression = " "
  }

  expect_failures = [var.schedule_expression]
}

run "reject_empty_timezone" {
  command = plan

  variables {
    collection_timezone = " "
  }

  expect_failures = [var.collection_timezone]
}

run "reject_empty_bucket_name" {
  command = plan

  variables {
    bucket_name = " "
  }

  expect_failures = [var.bucket_name]
}

run "reject_empty_object_prefix" {
  command = plan

  variables {
    object_prefix = "///"
  }

  expect_failures = [var.object_prefix]
}

run "reject_empty_secret_name" {
  command = plan

  variables {
    secret_name = " "
  }

  expect_failures = [var.secret_name]
}

run "reject_non_fifo_topic" {
  command = plan

  variables {
    topic_name = "daily-progress-results"
  }

  expect_failures = [var.topic_name]
}

run "reject_timeout_outside_lambda_limits" {
  command = plan

  variables {
    lambda_timeout = 901
  }

  expect_failures = [var.lambda_timeout]
}

run "reject_memory_outside_lambda_limits" {
  command = plan

  variables {
    lambda_memory_size = 127
  }

  expect_failures = [var.lambda_memory_size]
}
