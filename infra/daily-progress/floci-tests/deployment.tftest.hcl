variables {
  aws_region             = "us-east-1"
  bucket_force_destroy   = true
  bucket_name            = "daily-progress-e2e"
  collection_timezone    = "America/Chicago"
  lambda_memory_size     = 256
  lambda_public_repo_url = "public.ecr.aws/example/daily-progress"
  lambda_timeout         = 30
  object_prefix          = "e2e"
  secret_name            = "daily-progress-e2e-auth"
  topic_name             = "daily-progress-e2e-results.fifo"
}

run "deploy_owned_infrastructure" {
  override_module {
    target = module.lambda_image_republish

    outputs = {
      lambda_image_uri_with_digest = "__PROBE_IMAGE_URI__"
    }
  }

  # Floci 2.1.0 does not implement the S3 ownership-controls API.
  override_resource {
    target = aws_s3_bucket_ownership_controls.progress
  }

  assert {
    condition = (
      aws_s3_bucket.progress.bucket == "daily-progress-e2e" &&
      aws_s3_bucket_versioning.progress.versioning_configuration[0].status == "Enabled" &&
      one(one(aws_s3_bucket_server_side_encryption_configuration.progress.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    )
    error_message = "The Floci deployment must create a versioned, encrypted progress bucket."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.progress.block_public_acls &&
      aws_s3_bucket_public_access_block.progress.block_public_policy &&
      aws_s3_bucket_public_access_block.progress.ignore_public_acls &&
      aws_s3_bucket_public_access_block.progress.restrict_public_buckets
    )
    error_message = "The Floci deployment must apply every supported public-access safeguard."
  }

  assert {
    condition     = aws_iam_role_policy_attachment.scheduled_lambda_storage.role == module.lambdacron.scheduled_lambda_role_name
    error_message = "The daily-progress storage policy must attach to lambdacron's execution role."
  }

  assert {
    condition = (
      module.lambdacron.schedule_rule_name == "daily-progress-collector-schedule" &&
      endswith(module.lambdacron.scheduled_lambda_arn, ":function:daily-progress-collector") &&
      endswith(module.lambdacron.sns_topic_arn, ":daily-progress-e2e-results.fifo")
    )
    error_message = "Lambdacron must create the scheduled Lambda, EventBridge rule, and FIFO result topic."
  }
}

run "invoke_probe" {
  module {
    source = "./floci-tests/invoke"
  }

  variables {
    aws_endpoint_url = var.aws_endpoint_url
    aws_region       = "us-east-1"
    lambda_name      = "daily-progress-collector"
    secret_arn       = run.deploy_owned_infrastructure.progress_collector_secret_arn
  }

  assert {
    condition = (
      jsondecode(output.invocation_result).status == "ok" &&
      jsondecode(output.invocation_result).secret_loaded &&
      length(jsondecode(output.invocation_result).sns_message_id) > 0
    )
    error_message = "The deployed lambdacron Lambda must read the secret and publish to SNS."
  }
}

run "verify_probe" {
  module {
    source = "./floci-tests/verify"
  }

  variables {
    aws_endpoint_url  = var.aws_endpoint_url
    aws_region        = "us-east-1"
    bucket_name       = run.deploy_owned_infrastructure.bucket_name
    invocation_result = run.invoke_probe.invocation_result
    lambda_name       = "daily-progress-collector"
    object_prefix     = "e2e"
    secret_arn        = run.deploy_owned_infrastructure.progress_collector_secret_arn
    sns_topic_arn     = run.deploy_owned_infrastructure.sns_topic_arn
  }

  assert {
    condition = (
      jsondecode(output.object_body).bucket == "daily-progress-e2e" &&
      jsondecode(output.object_body).prefix == "e2e" &&
      jsondecode(output.object_body).timezone == "America/Chicago" &&
      jsondecode(output.object_body).secret_loaded &&
      output.object_content_type == "application/json"
    )
    error_message = "The probe must write metadata-only verification JSON to the configured bucket."
  }

  assert {
    condition = (
      output.lambda_environment["DAILY_PROGRESS_BUCKET"] == "daily-progress-e2e" &&
      output.lambda_environment["DAILY_PROGRESS_PREFIX"] == "e2e" &&
      output.lambda_environment["DAILY_PROGRESS_TIMEZONE"] == "America/Chicago" &&
      output.lambda_environment["PROGRESS_COLLECTOR_SECRET_ID"] == output.secret_arn &&
      output.lambda_environment["SNS_TOPIC_ARN"] == output.sns_topic_arn
    )
    error_message = "The probe Lambda must receive the expected Terraform resource identifiers."
  }

  assert {
    condition     = endswith(output.lambda_arn, ":function:daily-progress-collector")
    error_message = "The verified Lambda must be the function deployed by lambdacron."
  }
}
