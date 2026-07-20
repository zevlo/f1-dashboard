output "kinesis_stream_name" {
  description = "Name of the ingestion Kinesis stream."
  value       = module.ingestion.kinesis_stream_name
}

output "kinesis_stream_arn" {
  description = "ARN of the ingestion Kinesis stream."
  value       = module.ingestion.kinesis_stream_arn
}

output "poller_function_name" {
  description = "Name of the poller Lambda function."
  value       = module.ingestion.poller_function_name
}

output "poller_function_arn" {
  description = "ARN of the poller Lambda function."
  value       = module.ingestion.poller_function_arn
}

output "poller_dlq_url" {
  description = "URL of the SQS DLQ for failed poller invocations."
  value       = module.ingestion.poller_dlq_url
}

output "poller_dlq_arn" {
  description = "ARN of the poller SQS DLQ."
  value       = module.ingestion.poller_dlq_arn
}

output "replay_cursor_parameter_name" {
  description = "DEPRECATED in v2: replays are client-side, no server cursor. Kept as null so downstream tooling that still references this output doesn't crash."
  value       = null
}

output "eventbridge_rule_name" {
  description = "Name of the EventBridge schedule rule."
  value       = module.ingestion.eventbridge_rule_name
}

output "poller_log_group_name" {
  description = "CloudWatch Logs group auto-created for the poller Lambda."
  value       = module.ingestion.poller_log_group_name
}

# ----------------------------------------------------------------------------
# Storage module outputs
# ----------------------------------------------------------------------------
output "dynamodb_table_names" {
  description = "Map of logical name -> DynamoDB table name for all six telemetry tables (incl. Drivers)."
  value       = module.storage.table_names
}

output "positions_stream_arn" {
  description = "ARN of the Positions table DynamoDB Stream (NEW_IMAGE). Consumed by the WebSocket push Lambda in Week 3."
  value       = module.storage.positions_stream_arn
}

# ----------------------------------------------------------------------------
# Processing module outputs
# ----------------------------------------------------------------------------
output "transformer_function_name" {
  description = "Name of the transformer Lambda function."
  value       = module.processing.transformer_function_name
}

output "transformer_function_arn" {
  description = "ARN of the transformer Lambda function."
  value       = module.processing.transformer_function_arn
}

output "transformer_dlq_url" {
  description = "URL of the SQS DLQ for failed transformer batches."
  value       = module.processing.transformer_dlq_url
}

output "transformer_event_source_mapping_uuid" {
  description = "UUID of the Kinesis -> transformer EventSource Mapping."
  value       = module.processing.event_source_mapping_uuid
}

# ----------------------------------------------------------------------------
# API module outputs
# ----------------------------------------------------------------------------
output "api_base_url" {
  description = "Base invoke URL for the REST API (stage v1). Append route paths, e.g. /sessions, /drivers/{driverNumber}."
  value       = module.api.api_base_url
}

output "api_rest_api_id" {
  description = "ID of the REST API."
  value       = module.api.rest_api_id
}

output "api_sessions_function_name" {
  description = "Name of the api-sessions Lambda function."
  value       = module.api.api_sessions_function_name
}

output "api_drivers_function_name" {
  description = "Name of the api-drivers Lambda function (bulk + per-driver)."
  value       = module.api.api_drivers_function_name
}

output "api_replay_function_name" {
  description = "Name of the api-replay Lambda function (bulk session fetch for client-side playback)."
  value       = module.api.api_replay_function_name
}

# ----------------------------------------------------------------------------
# WebSocket outputs
# ----------------------------------------------------------------------------
output "websocket_url" {
  description = "WebSocket connect URL (stage v1). Connect with ?sessionId=<session_key>."
  value       = module.api.websocket_url
}

output "connections_table_name" {
  description = "Name of the WebSocket Connections DynamoDB table."
  value       = module.api.connections_table_name
}

output "ws_agent_function_name" {
  description = "Name of the ws-agent Lambda function (Bedrock AgentCore relay). Returns stubbed replies until agent_enabled=true (Phase 5)."
  value       = module.api.ws_agent_function_name
}

# ----------------------------------------------------------------------------
# Frontend module outputs
# ----------------------------------------------------------------------------
output "frontend_bucket_name" {
  description = "S3 bucket hosting the React build."
  value       = module.frontend.bucket_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID (for cache invalidation in CI)."
  value       = module.frontend.cloudfront_distribution_id
}

output "cloudfront_url" {
  description = "HTTPS URL for the deployed dashboard."
  value       = module.frontend.cloudfront_url
}

# ----------------------------------------------------------------------------
# Monitoring module outputs
# ----------------------------------------------------------------------------
output "monitoring_dashboard_name" {
  description = "Name of the CloudWatch pipeline dashboard."
  value       = module.monitoring.dashboard_name
}

output "alerts_topic_arn" {
  description = "ARN of the monitoring alerts SNS topic."
  value       = module.monitoring.sns_topic_arn
}

# ----------------------------------------------------------------------------
# DNS / custom domain outputs
# ----------------------------------------------------------------------------
output "dashboard_url" {
  description = "Friendly HTTPS URL for the dashboard (custom domain)."
  value       = module.frontend.dashboard_url
}

output "rest_api_custom_domain" {
  description = "Custom domain for the REST API (empty when custom domains are disabled)."
  value       = module.dns.rest_domain
}

output "ws_custom_domain" {
  description = "Custom domain for the WebSocket API (empty when custom domains are disabled)."
  value       = module.dns.ws_domain
}
