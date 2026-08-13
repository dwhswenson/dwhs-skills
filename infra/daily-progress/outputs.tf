output "bucket_name" {
  description = "S3 bucket containing daily progress JSON snapshots."
  value       = aws_s3_bucket.progress.bucket
}

output "bucket_arn" {
  description = "ARN of the daily progress S3 bucket."
  value       = aws_s3_bucket.progress.arn
}

output "progress_collector_secret_arn" {
  description = "ARN of the Secrets Manager secret that must be populated with collect-progress-auth JSON."
  value       = aws_secretsmanager_secret.progress_collector.arn
}

output "lambda_republished_image_uri" {
  description = "Digest-qualified private ECR image URI used by the scheduled Lambda."
  value       = module.lambda_image_republish.lambda_image_uri_with_digest
}

output "scheduled_lambda_arn" {
  description = "ARN of the scheduled daily progress Lambda."
  value       = module.lambdacron.scheduled_lambda_arn
}

output "scheduled_lambda_role_arn" {
  description = "ARN of the scheduled Lambda execution role."
  value       = module.lambdacron.scheduled_lambda_role_arn
}

output "sns_topic_arn" {
  description = "ARN of the lambdacron result topic."
  value       = module.lambdacron.sns_topic_arn
}
