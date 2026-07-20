terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket       = "f1-telemetry-tf-state"
    key          = "dev/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = "us-east-1"
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

# ----------------------------------------------------------------------------
# Modules
# ----------------------------------------------------------------------------

# DNS foundation — hosted zone lookup + ACM cert for the custom domains.
# Must apply before api/frontend, which mount the cert onto CloudFront and
# both API Gateways.
module "dns" {
  source = "../../modules/dns"

  project_name = var.project_name
  environment  = var.environment
  tags         = var.tags
  domain_name  = var.domain_name
}

module "ingestion" {
  source = "../../modules/ingestion"

  project_name               = var.project_name
  environment                = var.environment
  kinesis_shard_count        = var.kinesis_shard_count
  poller_enabled             = var.poller_enabled
  poller_schedule_expression = var.poller_schedule_expression
  # v2: no replay cursor — replays are client-side. Vars kept for back-compat defaults.
  replay_session_key = var.replay_session_key
  replay_speed       = var.replay_speed
  # Poller upserts drivers into the Drivers table on session discovery.
  drivers_table_name = module.storage.table_names.drivers
  drivers_table_arn  = module.storage.table_arns.drivers
  tags               = var.tags
}

module "storage" {
  source = "../../modules/storage"

  project_name = var.project_name
  environment  = var.environment
  tags         = var.tags
}

module "processing" {
  source = "../../modules/processing"

  project_name       = var.project_name
  environment        = var.environment
  tags               = var.tags
  kinesis_stream_arn = module.ingestion.kinesis_stream_arn
  table_names        = module.storage.table_names
  table_arns         = module.storage.table_arns
}

module "api" {
  source = "../../modules/api"

  project_name  = var.project_name
  environment   = var.environment
  tags          = var.tags
  table_names   = module.storage.table_names
  table_arns    = module.storage.table_arns
  stream_arns   = module.storage.stream_arns
  agent_enabled = var.agent_enabled
  agent_model_id = var.agent_model_id

  # Custom domain wiring (no-op when domain_name is empty).
  rest_domain_name    = module.dns.rest_domain
  ws_domain_name      = module.dns.ws_domain
  zone_id             = module.dns.zone_id
  acm_certificate_arn = module.dns.certificate_arn
  # Restrict CORS to the dashboard origin now that it has a fixed hostname.
  cors_allow_origin = "https://${var.domain_name}"
}

module "frontend" {
  source = "../../modules/frontend"

  project_name        = var.project_name
  environment         = var.environment
  tags                = var.tags
  domain_name         = module.dns.dashboard_domain
  zone_id             = module.dns.zone_id
  acm_certificate_arn = module.dns.certificate_arn
}

module "monitoring" {
  source = "../../modules/monitoring"

  project_name = var.project_name
  environment  = var.environment
  tags         = var.tags

  lambda_function_names = {
    poller        = module.ingestion.poller_function_name
    transformer   = module.processing.transformer_function_name
    api_sessions  = module.api.api_sessions_function_name
    api_drivers   = module.api.api_drivers_function_name
    api_replay    = module.api.api_replay_function_name
    ws_connect    = module.api.ws_connect_function_name
    ws_disconnect = module.api.ws_disconnect_function_name
    ws_push       = module.api.ws_push_function_name
    ws_agent      = module.api.ws_agent_function_name
  }

  kinesis_stream_name  = module.ingestion.kinesis_stream_name
  dynamodb_table_names = module.storage.table_names
  rest_api_name        = module.api.rest_api_name
  rest_api_stage       = module.api.stage_name
  websocket_api_id     = module.api.websocket_api_id
  websocket_stage      = module.api.websocket_stage_name
  alarm_email          = var.alarm_email
}
