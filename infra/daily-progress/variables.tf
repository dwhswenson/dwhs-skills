variable "aws_region" {
  description = "AWS region for S3, Secrets Manager, private ECR, Lambda, EventBridge, and SNS resources."
  type        = string
}

variable "aws_endpoint_url" {
  description = "Optional AWS-compatible endpoint used by local infrastructure tests."
  type        = string
  default     = null

  validation {
    condition     = try(startswith(var.aws_endpoint_url, "http://") || startswith(var.aws_endpoint_url, "https://"), var.aws_endpoint_url == null)
    error_message = "aws_endpoint_url must be null or an HTTP(S) URL."
  }
}

variable "schedule_expression" {
  description = "UTC EventBridge schedule expression. The default is 4 AM CST / 5 AM CDT."
  type        = string
  default     = "cron(0 10 * * ? *)"

  validation {
    condition     = length(trimspace(var.schedule_expression)) > 0
    error_message = "schedule_expression must be non-empty."
  }
}

variable "collection_timezone" {
  description = "IANA timezone used to determine the previous complete calendar day."
  type        = string
  default     = "America/Chicago"

  validation {
    condition     = length(trimspace(var.collection_timezone)) > 0
    error_message = "collection_timezone must be non-empty."
  }
}

variable "bucket_name" {
  description = "Optional explicit S3 bucket name. When null, AWS generates a unique name with a daily-progress- prefix."
  type        = string
  default     = null

  validation {
    condition     = try(length(trimspace(var.bucket_name)) > 0, var.bucket_name == null)
    error_message = "bucket_name must be null or a non-empty string."
  }
}

variable "object_prefix" {
  description = "S3 key prefix beneath which YYYY-MM-DD/progress.json objects are written."
  type        = string
  default     = "progress"

  validation {
    condition     = length(trim(var.object_prefix, "/")) > 0
    error_message = "object_prefix must contain characters other than slashes."
  }
}

variable "secret_name" {
  description = "Optional name for the Secrets Manager secret container."
  type        = string
  default     = null

  validation {
    condition     = try(length(trimspace(var.secret_name)) > 0, var.secret_name == null)
    error_message = "secret_name must be null or a non-empty string."
  }
}

variable "topic_name" {
  description = "FIFO SNS topic name for lambdacron result messages."
  type        = string
  default     = "daily-progress-results.fifo"

  validation {
    condition     = endswith(var.topic_name, ".fifo")
    error_message = "topic_name must end with .fifo."
  }
}

variable "lambda_env" {
  description = "Additional Lambda environment variables. Daily-progress variables override conflicting keys."
  type        = map(string)
  default     = {}
}

variable "lambda_timeout" {
  description = "Scheduled Lambda timeout in seconds."
  type        = number
  default     = 300

  validation {
    condition     = var.lambda_timeout >= 1 && var.lambda_timeout <= 900
    error_message = "lambda_timeout must be between 1 and 900 seconds."
  }
}

variable "lambda_memory_size" {
  description = "Scheduled Lambda memory size in MB."
  type        = number
  default     = 512

  validation {
    condition     = var.lambda_memory_size >= 128 && var.lambda_memory_size <= 10240
    error_message = "lambda_memory_size must be between 128 and 10240 MB."
  }
}

variable "lambda_name" {
  description = "Name for the scheduled Lambda."
  type        = string
  default     = "daily-progress-collector"
}

variable "lambda_image_command" {
  description = "Optional override for the scheduled Lambda image command."
  type        = list(string)
  default     = null
}

variable "lambda_public_repo_url" {
  description = "Public ECR repository URL containing the published daily-progress image."
  type        = string
}

variable "lambda_public_tag" {
  description = "Tag of the public daily-progress image to republish."
  type        = string
  default     = "latest"
}

variable "lambda_private_repository_name" {
  description = "Private ECR repository used for the republished Lambda image."
  type        = string
  default     = "daily-progress-local"
}

variable "lambda_enable_kms_encryption" {
  description = "Enable KMS encryption on the private ECR repository."
  type        = bool
  default     = false
}

variable "lambda_kms_key_arn" {
  description = "KMS key ARN used when private ECR KMS encryption is enabled."
  type        = string
  default     = null
}

variable "tags" {
  description = "Additional tags for created resources."
  type        = map(string)
  default     = {}
}
