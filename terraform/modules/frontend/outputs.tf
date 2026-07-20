output "bucket_name" {
  description = "Name of the S3 bucket hosting the React build."
  value       = aws_s3_bucket.site.id
}

output "bucket_arn" {
  description = "ARN of the frontend S3 bucket."
  value       = aws_s3_bucket.site.arn
}

output "cloudfront_distribution_id" {
  description = "ID of the CloudFront distribution (used for cache invalidation in CI)."
  value       = aws_cloudfront_distribution.site.id
}

output "cloudfront_domain_name" {
  description = "CloudFront domain name for the dashboard (e.g. d123.cloudfront.net)."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "cloudfront_url" {
  description = "HTTPS URL for the deployed dashboard."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "dashboard_url" {
  description = "Friendly HTTPS URL for the dashboard (custom domain when wired, else the raw CloudFront URL)."
  value       = local.use_custom_domain ? "https://${var.domain_name}" : "https://${aws_cloudfront_distribution.site.domain_name}"
}
