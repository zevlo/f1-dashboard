variable "project_name" {
  description = "Short project identifier used as a resource name prefix across all modules."
  type        = string
  default     = "f1-telemetry"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.project_name))
    error_message = "project_name must be 2-31 chars, lowercase letters, digits, hyphens, and start with a letter."
  }
}

variable "environment" {
  description = "Deployment environment name (e.g., dev, staging, prod)."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,20}$", var.environment))
    error_message = "environment must be lowercase letters, digits, hyphens; start with a letter; max 21 chars."
  }
}

variable "region" {
  description = "AWS region for every resource in this environment."
  type        = string
  default     = "us-east-1"
}

variable "kinesis_shard_count" {
  description = "Number of open shards on the ingestion Kinesis stream (provisioned mode). Each shard gives 1 MB/s write and 2 MB/s read. 20 cars x 5s polling is far under 1 shard."
  type        = number
  default     = 1

  validation {
    condition     = var.kinesis_shard_count >= 1
    error_message = "kinesis_shard_count must be at least 1."
  }
}

variable "poller_schedule_expression" {
  description = "EventBridge schedule expression that triggers the poller Lambda. EventBridge has a hard 60-second minimum granularity, so the Lambda loops internally (12 x 5s) to achieve true 5s polling."
  type        = string
  default     = "rate(1 minute)"
}

variable "poller_enabled" {
  description = "Set false to pause the poller schedule when the dashboard is idle (toggles the EventBridge rule between ENABLED and DISABLED). Default true = normal operation. Override with -var=\"poller_enabled=false\" or in a local *.tfvars file (gitignored)."
  type        = bool
  default     = true
}

variable "replay_session_key" {
  description = "DEPRECATED in v2 (kept for back-compat). Replays are now client-side. The poller ignores this — it always runs in live mode (auto-discover latest active session)."
  type        = string
  default     = ""
}

variable "replay_speed" {
  description = "DEPRECATED in v2 (kept for back-compat). Replays are now client-side with a local clock driven by the frontend."
  type        = number
  default     = 1

  validation {
    condition     = var.replay_speed > 0
    error_message = "replay_speed must be greater than 0."
  }
}

variable "agent_enabled" {
  description = "When true, the ws-agent Lambda invokes Bedrock for chat replies (charges apply). When false (Phase 2 default), it returns a stubbed reply without calling Bedrock. Flip to true in Phase 5 once AgentCore is wired."
  type        = bool
  default     = false
}

variable "agent_model_id" {
  description = "Bedrock foundation model ID backing the Race Engineer agent. Default is Amazon Nova Pro (fully AWS-native per project decision)."
  type        = string
  default     = "amazon.nova-pro-v1:0"
}

variable "tags" {
  description = "Common resource tags merged into every tagged resource."
  type        = map(string)
  default     = {}
}

variable "alarm_email" {
  description = "Email address subscribed to the monitoring alerts SNS topic. Empty string skips the subscription (requires manual confirmation when set)."
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Apex hostname for this deployment (the dashboard, e.g. f1.zevlo.net). The REST API is exposed at api.<domain_name> and the WebSocket API at ws.<domain_name>. The parent zone (e.g. zevlo.net) must already exist as a public Route 53 hosted zone in this account. Empty string disables all custom domains."
  type        = string
  default     = "f1.zevlo.net"

  validation {
    condition     = can(regex("^([a-z0-9]+([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$", var.domain_name))
    error_message = "domain_name must be a fully-qualified lowercase hostname with at least two labels, e.g. f1.zevlo.net."
  }
}
