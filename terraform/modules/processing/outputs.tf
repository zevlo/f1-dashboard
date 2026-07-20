output "transformer_function_name" {
  description = "Name of the transformer Lambda function."
  value       = aws_lambda_function.transformer.function_name
}

output "transformer_function_arn" {
  description = "ARN of the transformer Lambda function."
  value       = aws_lambda_function.transformer.arn
}

output "transformer_role_arn" {
  description = "ARN of the transformer Lambda IAM role."
  value       = aws_iam_role.transformer.arn
}

output "transformer_dlq_url" {
  description = "URL of the SQS DLQ for failed transformer batches."
  value       = aws_sqs_queue.transformer_dlq.id
}

output "transformer_dlq_arn" {
  description = "ARN of the transformer SQS DLQ."
  value       = aws_sqs_queue.transformer_dlq.arn
}

output "event_source_mapping_uuid" {
  description = "UUID of the Kinesis -> transformer EventSource Mapping."
  value       = aws_lambda_event_source_mapping.transformer.id
}

output "transformer_log_group_name" {
  description = "CloudWatch Logs group auto-created for the transformer Lambda."
  value       = "/aws/lambda/${aws_lambda_function.transformer.function_name}"
}
