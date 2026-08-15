variables {
  aws_region             = "us-east-1"
  bucket_name            = "daily-progress-e2e"
  collection_timezone    = "America/Chicago"
  lambda_memory_size     = 256
  lambda_public_repo_url = "unused"
  lambda_timeout         = 30
  object_prefix          = "e2e"
  secret_name            = "daily-progress-e2e-auth"
}

run "setup_execution_role" {
  module {
    source = "./floci-tests/setup"
  }

  variables {
    aws_endpoint_url = var.aws_endpoint_url
    aws_region       = var.aws_region
  }
}

run "deploy_owned_infrastructure" {
  override_module {
    target = module.lambda_image_republish

    outputs = {
      lambda_image_uri_with_digest = "__PROBE_IMAGE_URI__"
    }
  }

  # Floci 1.6.0 does not implement the S3 ownership-controls API.
  override_resource {
    target = aws_s3_bucket_ownership_controls.progress
  }

  # Lambdacron currently declares an internal provider and cannot inherit the Floci endpoint.
  override_module {
    target = module.lambdacron

    outputs = {
      scheduled_lambda_arn       = "arn:aws:lambda:us-east-1:000000000000:function:daily-progress-e2e-probe"
      scheduled_lambda_role_arn  = "arn:aws:iam::000000000000:role/daily-progress-e2e-probe-role"
      scheduled_lambda_role_name = "daily-progress-e2e-probe-role"
      sns_topic_arn              = "arn:aws:sns:us-east-1:000000000000:daily-progress-e2e-results.fifo"
    }
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
    condition     = aws_iam_role_policy_attachment.scheduled_lambda_storage.role == run.setup_execution_role.role_name
    error_message = "The daily-progress storage policy must attach to the supplied execution role."
  }
}

run "invoke_probe" {
  module {
    source = "./floci-tests/verify"
  }

  variables {
    aws_endpoint_url    = var.aws_endpoint_url
    aws_region          = var.aws_region
    bucket_name         = run.deploy_owned_infrastructure.bucket_name
    collection_timezone = var.collection_timezone
    lambda_image_uri    = var.lambda_public_repo_url
    object_prefix       = var.object_prefix
    role_arn            = run.setup_execution_role.role_arn
    role_name           = run.setup_execution_role.role_name
    secret_arn          = run.deploy_owned_infrastructure.progress_collector_secret_arn
  }

  assert {
    condition = (
      jsondecode(output.invocation_result).status == "ok" &&
      jsondecode(output.invocation_result).secret_loaded
    )
    error_message = "The image-backed probe Lambda must load the Terraform-created secret."
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
      output.lambda_environment.DAILY_PROGRESS_BUCKET == "daily-progress-e2e" &&
      output.lambda_environment.DAILY_PROGRESS_PREFIX == "e2e" &&
      output.lambda_environment.PROGRESS_COLLECTOR_SECRET_ID == run.deploy_owned_infrastructure.progress_collector_secret_arn &&
      output.lambda_environment.SNS_TOPIC_ARN == output.sns_topic_arn
    )
    error_message = "The probe Lambda must receive the expected Terraform resource identifiers."
  }

  assert {
    condition = (
      output.schedule_expression == "cron(0 10 * * ? *)" &&
      output.schedule_target_arn == "arn:aws:lambda:us-east-1:000000000000:function:daily-progress-e2e-probe" &&
      length(jsondecode(output.invocation_result).sns_message_id) > 0
    )
    error_message = "The E2E fixture must wire EventBridge and publish a result to SNS."
  }
}
