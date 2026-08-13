output "image_uri" {
  description = "Tagged public ECR image URI."
  value       = module.lambda_image_public.image_uri
}

output "repository_arn" {
  description = "ARN of the public ECR repository."
  value       = module.lambda_image_public.repository_arn
}

output "repository_url" {
  description = "URL of the public ECR repository."
  value       = module.lambda_image_public.repository_uri
}
