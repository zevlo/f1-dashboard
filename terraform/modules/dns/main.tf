locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    Module      = "dns"
    ManagedBy   = "terraform"
  })

  # Parent zone = domain_name with the first label stripped (f1.zevlo.net -> zevlo.net).
  # Must already exist as a public Route 53 hosted zone in this account.
  labels           = split(".", var.domain_name)
  parent_zone_name = join(".", slice(local.labels, 1, length(local.labels)))

  rest_domain_name = "api.${var.domain_name}"
  ws_domain_name   = "ws.${var.domain_name}"
}

# ----------------------------------------------------------------------------
# Parent hosted zone lookup — the registered domain's public Route 53 zone.
# ----------------------------------------------------------------------------
data "aws_route53_zone" "parent" {
  name         = local.parent_zone_name
  private_zone = false
}

# ----------------------------------------------------------------------------
# ACM certificate — one cert covering dashboard + api + ws. Must be in
# us-east-1 for CloudFront; both API Gateways are also in us-east-1.
# ----------------------------------------------------------------------------
resource "aws_acm_certificate" "this" {
  domain_name               = var.domain_name
  subject_alternative_names = [local.rest_domain_name, local.ws_domain_name]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = local.common_tags
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.this.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id         = data.aws_route53_zone.parent.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}
