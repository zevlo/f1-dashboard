variable "project_name" {
  description = "Short project identifier used as a resource name prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "kinesis_shard_count" {
  description = "Number of open shards on the ingestion Kinesis stream (provisioned mode)."
  type        = number
  default     = 1
}

variable "poller_enabled" {
  description = "Set false to pause the poller schedule (DISABLED) without tearing down resources. Use to idle the stack between uses; the transformer goes quiet too since nothing flows into Kinesis."
  type        = bool
  default     = true
}

variable "poller_schedule_expression" {
  description = "EventBridge schedule expression that triggers the poller Lambda. EventBridge floors at 60s; the Lambda loops internally to achieve sub-minute polling."
  type        = string
  default     = "rate(1 minute)"
}

variable "poller_internal_loop_count" {
  description = "OpenF1 poll cycles per Lambda invocation. With a ~5s sleep between cycles, 12 gives true 5s cadence."
  type        = number
  default     = 12
}

variable "poller_memory_size" {
  description = "Memory (MB) for the poller Lambda. Also scales CPU."
  type        = number
  default     = 256
}

variable "poller_timeout" {
  description = "Poller Lambda timeout in seconds. Must exceed (loop_count * 5s) + fetch margin."
  type        = number
  default     = 70

  validation {
    condition     = var.poller_timeout >= 60
    error_message = "poller_timeout must be at least 60s to fit the internal loop."
  }
}

variable "replay_session_key" {
  description = "DEPRECATED in v2. Replays are client-side now. Var kept only for backwards-compat defaults — ignored by the poller."
  type        = string
  default     = ""
}

variable "replay_speed" {
  description = "DEPRECATED in v2. Replays are client-side now. Var kept only for backwards-compat defaults — ignored by the poller."
  type        = number
  default     = 1
}

variable "drivers_table_name" {
  description = "Name of the DynamoDB Drivers table. The poller upserts all 20 drivers when it discovers a session."
  type        = string
}

variable "drivers_table_arn" {
  description = "ARN of the DynamoDB Drivers table. Used to scope the poller's write IAM."
  type        = string
}

variable "tags" {
  description = "Common resource tags merged into every tagged resource."
  type        = map(string)
  default     = {}
}
