output "zone_id" {
  description = "ID of the parent Route 53 hosted zone (e.g. zevlo.net) where service records live."
  value       = data.aws_route53_zone.parent.zone_id
}

output "certificate_arn" {
  description = "ARN of the validated ACM certificate covering dashboard + api + ws subdomains."
  value       = aws_acm_certificate_validation.this.certificate_arn
}

output "dashboard_domain" {
  description = "CloudFront hostname (dashboard), e.g. f1.zevlo.net."
  value       = var.domain_name
}

output "rest_domain" {
  description = "REST API custom domain, e.g. api.f1.zevlo.net."
  value       = local.rest_domain_name
}

output "ws_domain" {
  description = "WebSocket API custom domain, e.g. ws.f1.zevlo.net."
  value       = local.ws_domain_name
}
