locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    Module      = "storage"
    ManagedBy   = "terraform"
  })
}

# ----------------------------------------------------------------------------
# Sessions — one row per OpenF1 session (FP1/Quali/Race). Written sparsely by
# the transformer when the poller emits a `source: "session"` envelope.
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "sessions" {
  name         = "${local.name_prefix}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_key"

  attribute {
    name = "session_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# Drivers — one row per (session, driver_number). Bulk-fetched by the frontend
# on session load via GET /sessions/{key}/drivers so names/teams render
# immediately without per-driver lookups. Upserted by the poller when it
# discovers a session; treated as immutable mid-session.
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "drivers" {
  name         = "${local.name_prefix}-drivers"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_key"
  range_key    = "driver_number"

  attribute {
    name = "session_key"
    type = "S"
  }

  attribute {
    name = "driver_number"
    type = "N"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# Positions — one row per (session, sample timestamp, driver). High-frequency.
# Stream (NEW_IMAGE) feeds the WebSocket fanout Lambda in Week 3.
# GSI supports per-driver queries (Race Engineer agent + driver focus views).
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "positions" {
  name         = "${local.name_prefix}-positions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_key"
  range_key    = "ts_driver"

  attribute {
    name = "session_key"
    type = "S"
  }

  attribute {
    name = "ts_driver"
    type = "S"
  }

  attribute {
    name = "driver_number"
    type = "N"
  }

  global_secondary_index {
    name            = "by_driver"
    hash_key        = "driver_number"
    range_key       = "session_key"
    projection_type = "ALL"
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  point_in_time_recovery {
    enabled = true
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# CarData — one row per (session, driver, sample). High-frequency telemetry
# trace samples (speed, throttle, brake, gear, rpm, drs).
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "car_data" {
  name         = "${local.name_prefix}-car-data"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_driver"
  range_key    = "date"

  attribute {
    name = "session_driver"
    type = "S"
  }

  attribute {
    name = "date"
    type = "S"
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  point_in_time_recovery {
    enabled = true
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# Laps — one row per (session, driver, lap). Written as cars cross the line.
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "laps" {
  name         = "${local.name_prefix}-laps"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_driver"
  range_key    = "lap_number"

  attribute {
    name = "session_driver"
    type = "S"
  }

  attribute {
    name = "lap_number"
    type = "N"
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  point_in_time_recovery {
    enabled = true
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# RaceControl — one row per (session, timestamp). Flags, safety car, DRS.
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "race_control" {
  name         = "${local.name_prefix}-race-control"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_key"
  range_key    = "timestamp"

  attribute {
    name = "session_key"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  point_in_time_recovery {
    enabled = true
  }

  tags = local.common_tags
}
