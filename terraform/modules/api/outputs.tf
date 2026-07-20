output "api_base_url" {
  description = "Base invoke URL for the REST API (stage v1). Append route paths, e.g. /sessions, /drivers/{driverNumber}. Custom domain when configured, else the raw execute-api URL."
  value       = local.enable_rest_domain ? "https://${var.rest_domain_name}/v1" : aws_api_gateway_stage.this.invoke_url
}

output "rest_api_id" {
  description = "ID of the REST API."
  value       = aws_api_gateway_rest_api.api.id
}

output "rest_api_name" {
  description = "Name of the REST API (ApiName dimension in CloudWatch metrics)."
  value       = aws_api_gateway_rest_api.api.name
}

output "stage_name" {
  description = "Deployment stage name."
  value       = aws_api_gateway_stage.this.stage_name
}

output "api_sessions_function_name" {
  description = "Name of the api-sessions Lambda function."
  value       = aws_lambda_function.api_sessions.function_name
}

output "api_sessions_function_arn" {
  description = "ARN of the api-sessions Lambda function."
  value       = aws_lambda_function.api_sessions.arn
}

output "api_drivers_function_name" {
  description = "Name of the api-drivers Lambda function (bulk + per-driver)."
  value       = aws_lambda_function.api_drivers.function_name
}

output "api_drivers_function_arn" {
  description = "ARN of the api-drivers Lambda function."
  value       = aws_lambda_function.api_drivers.arn
}

output "api_replay_function_name" {
  description = "Name of the api-replay Lambda function (bulk session fetch for client-side playback)."
  value       = aws_lambda_function.api_replay.function_name
}

output "api_replay_function_arn" {
  description = "ARN of the api-replay Lambda function."
  value       = aws_lambda_function.api_replay.arn
}

# ----------------------------------------------------------------------------
# WebSocket outputs
# ----------------------------------------------------------------------------
output "websocket_url" {
  description = "WebSocket connect URL. Connect with ?sessionId=<session_key>. Custom domain when configured, else the raw execute-api URL."
  value       = local.enable_ws_domain ? "wss://${var.ws_domain_name}/${aws_apigatewayv2_stage.ws.name}" : "wss://${aws_apigatewayv2_api.ws.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${aws_apigatewayv2_stage.ws.name}"
}

output "websocket_api_id" {
  description = "ID of the WebSocket API."
  value       = aws_apigatewayv2_api.ws.id
}

output "websocket_stage_name" {
  description = "Deployment stage name of the WebSocket API."
  value       = aws_apigatewayv2_stage.ws.name
}

output "connections_table_name" {
  description = "Name of the WebSocket Connections DynamoDB table."
  value       = aws_dynamodb_table.connections.name
}

output "ws_connect_function_name" {
  description = "Name of the ws-connect Lambda function."
  value       = aws_lambda_function.ws_connect.function_name
}

output "ws_disconnect_function_name" {
  description = "Name of the ws-disconnect Lambda function."
  value       = aws_lambda_function.ws_disconnect.function_name
}

output "ws_push_function_name" {
  description = "Name of the ws-push fanout Lambda function."
  value       = aws_lambda_function.ws_push.function_name
}

output "ws_agent_function_name" {
  description = "Name of the ws-agent Lambda function (Bedrock AgentCore relay)."
  value       = aws_lambda_function.ws_agent.function_name
}

output "ws_agent_function_arn" {
  description = "ARN of the ws-agent Lambda function."
  value       = aws_lambda_function.ws_agent.arn
}
