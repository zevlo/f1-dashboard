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

variable "table_names" {
  description = "Map of logical name -> DynamoDB table name, from the storage module. The API reads sessions/drivers/positions/laps/race_control."
  type = object({
    sessions     = string
    drivers      = string
    positions    = string
    car_data     = string
    laps         = string
    race_control = string
  })
}

variable "table_arns" {
  description = "Map of logical name -> DynamoDB table ARN, from the storage module. Used to scope IAM."
  type = object({
    sessions     = string
    drivers      = string
    positions    = string
    car_data     = string
    laps         = string
    race_control = string
  })
}

variable "cors_allow_origin" {
  description = "Value returned in the Access-Control-Allow-Origin header on every response. Defaults to permissive for MVP (public read APIs)."
  type        = string
  default     = "*"
}

variable "stream_arns" {
  description = "Map of logical name -> DynamoDB Stream ARN (NEW_IMAGE), from the storage module. Each stream drives the ws-push fanout Lambda."
  type = object({
    positions    = string
    car_data     = string
    laps         = string
    race_control = string
  })
}

variable "api_memory_size" {
  description = "Memory (MB) for the API Lambda functions."
  type        = number
  default     = 256
}

variable "api_timeout" {
  description = "Timeout (seconds) for the API Lambda functions."
  type        = number
  default     = 10
}

# ----------------------------------------------------------------------------
# Custom domains — optional. When set together with zone_id + cert ARN, the
# REST and WebSocket APIs are exposed on friendly hostnames instead of the
# raw execute-api URLs. Empty strings leave the default endpoints in place.
# ----------------------------------------------------------------------------
variable "rest_domain_name" {
  description = "Custom hostname for the REST API (e.g. api.f1.zevlo.net). Empty disables the REST custom domain."
  type        = string
  default     = ""
}

variable "ws_domain_name" {
  description = "Custom hostname for the WebSocket API (e.g. ws.f1.zevlo.net). Empty disables the WebSocket custom domain."
  type        = string
  default     = ""
}

variable "zone_id" {
  description = "Route 53 hosted zone ID where the API A-records are created. Required when any custom domain is set."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate presented by the API custom domains. Required when any custom domain is set."
  type        = string
  default     = ""
}

variable "agent_model_id" {
  description = "Bedrock model ID for the Race Engineer agent (e.g. amazon.nova-pro-v1:0). Used by the ws-agent Lambda."
  type        = string
  default     = "amazon.nova-pro-v1:0"
}

variable "agent_enabled" {
  description = "When false, ws-agent Lambda is created but always returns a stubbed reply. Lets us ship the agent scaffolding without paying for Bedrock invoke until ready."
  type        = bool
  default     = false
}
