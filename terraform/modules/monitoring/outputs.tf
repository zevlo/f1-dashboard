output "sns_topic_arn" {
  description = "ARN of the alerts SNS topic (alarm + ok actions)."
  value       = aws_sns_topic.alerts.arn
}

output "dashboard_name" {
  description = "Name of the CloudWatch pipeline dashboard."
  value       = aws_cloudwatch_dashboard.pipeline.dashboard_name
}
