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

variable "kinesis_stream_arn" {
  description = "ARN of the ingestion Kinesis stream the transformer consumes."
  type        = string
}

variable "table_names" {
  description = "Map of logical name -> DynamoDB table name, from the storage module."
  type = object({
    sessions     = string
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
    positions    = string
    car_data     = string
    laps         = string
    race_control = string
  })
}

variable "transformer_memory_size" {
  description = "Memory (MB) for the transformer Lambda. Also scales CPU."
  type        = number
  default     = 256
}

variable "transformer_timeout" {
  description = "Transformer Lambda timeout in seconds."
  type        = number
  default     = 60
}

variable "batch_size" {
  description = "Number of Kinesis records per transformer invocation. 100 is well under the 10MB payload cap for ~3KB telemetry envelopes."
  type        = number
  default     = 100
}
