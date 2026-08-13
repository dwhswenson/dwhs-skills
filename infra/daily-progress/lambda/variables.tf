variable "repository_name" {
  description = "Name of the public ECR repository for the daily-progress Lambda image."
  type        = string
  default     = "daily-progress-lambdacron"
}

variable "image_tag" {
  description = "Tag applied to the published image."
  type        = string
  default     = "latest"
}

variable "platform" {
  description = "Target container platform."
  type        = string
  default     = "linux/amd64"
}

variable "tags" {
  description = "Additional tags for the public ECR repository."
  type        = map(string)
  default     = {}
}
