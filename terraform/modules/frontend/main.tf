locals {
  name_prefix = "${var.project_name}-${var.environment}"

  # Wire a custom domain only when a hostname is set. The cert ARN and zone
  # ID are hard dependencies passed through (always provided by the dns module
  # when domain_name is non-empty). count/conditions use only this literal var
  # so Terraform can evaluate them at plan time.
  use_custom_domain = var.domain_name != ""

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    Module      = "frontend"
    ManagedBy   = "terraform"
  })
}

# ----------------------------------------------------------------------------
# S3 — private bucket; CloudFront OAC is the only read path
# ----------------------------------------------------------------------------
resource "aws_s3_bucket" "site" {
  bucket = "${local.name_prefix}-frontend"
  # Bucket only holds rebuildable Vite build artifacts (CI re-syncs on every
  # deploy). force_destroy lets `terraform destroy` purge versioned objects
  # between race weekends instead of hanging on BucketNotEmpty.
  force_destroy = true
  tags          = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ----------------------------------------------------------------------------
# CloudFront — SPA hosting (403/404 → index.html)
# ----------------------------------------------------------------------------
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.name_prefix}-frontend-oac"
  description                       = "OAC for ${local.name_prefix} React build"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "${local.name_prefix} frontend"
  price_class         = "PriceClass_100"

  # Present the ACM cert on the distribution when a custom domain is wired.
  aliases = local.use_custom_domain ? [var.domain_name] : []

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "s3"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
  }

  # Vite/React client-side routing — serve index.html for unknown paths.
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = !local.use_custom_domain
    acm_certificate_arn            = local.use_custom_domain ? var.acm_certificate_arn : null
    ssl_support_method             = local.use_custom_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_custom_domain ? "TLSv1.2_2021" : null
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# Dashboard DNS — A-record alias from domain_name -> CloudFront distribution.
# Lives here (not in the dns module) to avoid a circular dependency between
# the cert (needs the zone) and the alias record (needs the distribution).
# ----------------------------------------------------------------------------
resource "aws_route53_record" "dashboard" {
  count   = local.use_custom_domain ? 1 : 0
  zone_id = var.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

data "aws_iam_policy_document" "site_bucket" {
  statement {
    sid    = "AllowCloudFrontOAC"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_bucket.json
}
