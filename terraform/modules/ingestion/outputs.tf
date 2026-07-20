output "kinesis_stream_name" {
  description = "Name of the ingestion Kinesis stream."
  value       = aws_kinesis_stream.telemetry.name
}

output "kinesis_stream_arn" {
  description = "ARN of the ingestion Kinesis stream."
  value       = aws_kinesis_stream.telemetry.arn
}

output "poller_function_name" {
  description = "Name of the poller Lambda function."
  value       = aws_lambda_function.poller.function_name
}

output "poller_function_arn" {
  description = "ARN of the poller Lambda function."
  value       = aws_lambda_function.poller.arn
}

output "poller_role_arn" {
  description = "ARN of the poller Lambda IAM role."
  value       = aws_iam_role.poller.arn
}

output "poller_dlq_url" {
  description = "URL of the SQS DLQ for failed poller invocations."
  value       = aws_sqs_queue.poller_dlq.id
}

output "poller_dlq_arn" {
  description = "ARN of the poller SQS DLQ."
  value       = aws_sqs_queue.poller_dlq.arn
}

output "eventbridge_rule_name" {
  description = "Name of the EventBridge schedule rule."
  value       = aws_cloudwatch_event_rule.poller_schedule.name
}

output "poller_log_group_name" {
  description = "CloudWatch Logs group auto-created for the poller Lambda."
  value       = "/aws/lambda/${aws_lambda_function.poller.function_name}"
}
