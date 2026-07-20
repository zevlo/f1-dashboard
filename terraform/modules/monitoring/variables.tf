variable "project_name" {
  description = "Short project identifier used as a resource name prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "tags" {
  description = "Common resource tags merged into every tagged resource."
  type        = map(string)
  default     = {}
}

variable "lambda_function_names" {
  description = "Map of logical name -> Lambda function name for every function in the pipeline. Drives per-function error-rate alarms and dashboard widgets."
  type        = map(string)
}

variable "kinesis_stream_name" {
  description = "Name of the ingestion Kinesis stream."
  type        = string
}

variable "dynamodb_table_names" {
  description = "Map of logical name -> DynamoDB table name. Drives throttle alarms and capacity widgets."
  type        = map(string)
}

variable "rest_api_name" {
  description = "Name of the REST API (ApiName dimension in AWS/ApiGateway metrics)."
  type        = string
}

variable "rest_api_stage" {
  description = "Deployment stage of the REST API."
  type        = string
}

variable "websocket_api_id" {
  description = "ID of the WebSocket API (ApiId dimension in AWS/ApiGateway v2 metrics)."
  type        = string
}

variable "websocket_stage" {
  description = "Deployment stage of the WebSocket API."
  type        = string
}

variable "alarm_email" {
  description = "Email address subscribed to the alerts SNS topic. Empty string skips the subscription (topic is still created)."
  type        = string
  default     = ""
}
