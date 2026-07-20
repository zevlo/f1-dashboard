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
