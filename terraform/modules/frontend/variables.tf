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
  description = "Custom hostname for the dashboard (e.g. f1.zevlo.net). Empty string leaves CloudFront on its default *.cloudfront.net domain."
  type        = string
  default     = ""
}

variable "zone_id" {
  description = "Route 53 hosted zone ID where the dashboard A-record (alias to CloudFront) is created. Ignored when domain_name is empty."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate presented by CloudFront for domain_name. Required when domain_name is set."
  type        = string
  default     = ""
}
