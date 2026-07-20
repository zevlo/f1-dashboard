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

variable "domain_name" {
  description = "Apex hostname for this deployment (the dashboard, e.g. f1.zevlo.net). The REST API is exposed at api.<domain_name> and the WebSocket API at ws.<domain_name>. The parent zone (the registered apex, e.g. zevlo.net) must already exist as a public Route 53 hosted zone in this account."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]+([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$", var.domain_name))
    error_message = "domain_name must be a fully-qualified lowercase hostname with at least two labels, e.g. f1.zevlo.net."
  }
}
