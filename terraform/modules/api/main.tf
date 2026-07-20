locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    Module      = "api"
    ManagedBy   = "terraform"
  })

  # resource path -> (resource_id, lambda invoke_arn). Drives the GET methods,
  # integrations, and CORS set below via for_each, so adding a route is one line.
  get_endpoints = {
    sessions_list = { resource_id = aws_api_gateway_resource.sessions_root.id, lambda_arn = aws_lambda_function.api_sessions.invoke_arn }
    session_item  = { resource_id = aws_api_gateway_resource.session_item.id, lambda_arn = aws_lambda_function.api_sessions.invoke_arn }
    positions     = { resource_id = aws_api_gateway_resource.positions.id, lambda_arn = aws_lambda_function.api_sessions.invoke_arn }
    race_control  = { resource_id = aws_api_gateway_resource.race_control.id, lambda_arn = aws_lambda_function.api_sessions.invoke_arn }
    laps          = { resource_id = aws_api_gateway_resource.laps.id, lambda_arn = aws_lambda_function.api_sessions.invoke_arn }
    drivers_bulk  = { resource_id = aws_api_gateway_resource.drivers_bulk.id, lambda_arn = aws_lambda_function.api_drivers.invoke_arn }
    driver_item   = { resource_id = aws_api_gateway_resource.driver_item.id, lambda_arn = aws_lambda_function.api_drivers.invoke_arn }
    replay        = { resource_id = aws_api_gateway_resource.replay.id, lambda_arn = aws_lambda_function.api_replay.invoke_arn }
  }

  # Name of the Connections-table GSI used by ws-push to find viewers of a session.
  connections_session_index = "by_session"

  # Custom domains are gated only on the hostname literals so count/conditions
  # are evaluable at plan time. The cert ARN + zone ID are hard dependencies
  # passed through (always provided by the dns module when domains are set).
  enable_rest_domain = var.rest_domain_name != ""
  enable_ws_domain   = var.ws_domain_name != ""
}

# ----------------------------------------------------------------------------
# IAM — shared assume-role policy
# ----------------------------------------------------------------------------
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ----------------------------------------------------------------------------
# api-sessions Lambda — reads DynamoDB
# ----------------------------------------------------------------------------
resource "aws_iam_role" "api_sessions" {
  name               = "${local.name_prefix}-api-sessions"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "api_sessions_permissions" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  statement {
    sid    = "DynamoDBReads"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
    ]
    # Read-only on the four tables this Lambda queries. CarData is excluded —
    # no REST route reads it (live car_data arrives over WebSocket instead).
    resources = [
      var.table_arns.sessions,
      var.table_arns.positions,
      var.table_arns.laps,
      var.table_arns.race_control,
    ]
  }
}

resource "aws_iam_role_policy" "api_sessions" {
  name   = "${local.name_prefix}-api-sessions"
  role   = aws_iam_role.api_sessions.id
  policy = data.aws_iam_policy_document.api_sessions_permissions.json
}

data "archive_file" "api_sessions" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/api-sessions"
  output_path = "${path.module}/build/api-sessions.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "api_sessions" {
  function_name = "${local.name_prefix}-api-sessions"
  role          = aws_iam_role.api_sessions.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.api_sessions.output_path
  source_code_hash = data.archive_file.api_sessions.output_base64sha256

  memory_size = var.api_memory_size
  timeout     = var.api_timeout

  environment {
    variables = {
      SESSIONS_TABLE     = var.table_names.sessions
      POSITIONS_TABLE    = var.table_names.positions
      LAPS_TABLE         = var.table_names.laps
      RACE_CONTROL_TABLE = var.table_names.race_control
      LOG_LEVEL          = "INFO"
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# api-drivers Lambda — bulk GET /sessions/{key}/drivers from DDB (v2),
# with /drivers/{n} OpenF1 proxy fallback for one-off lookups.
# ----------------------------------------------------------------------------
resource "aws_iam_role" "api_drivers" {
  name               = "${local.name_prefix}-api-drivers"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "api_drivers_permissions" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  statement {
    sid    = "DriversRead"
    effect = "Allow"
    actions = [
      "dynamodb:Query",
      "dynamodb:GetItem",
    ]
    resources = [var.table_arns.drivers]
  }
}

resource "aws_iam_role_policy" "api_drivers" {
  name   = "${local.name_prefix}-api-drivers"
  role   = aws_iam_role.api_drivers.id
  policy = data.aws_iam_policy_document.api_drivers_permissions.json
}

data "archive_file" "api_drivers" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/api-drivers"
  output_path = "${path.module}/build/api-drivers.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "api_drivers" {
  function_name = "${local.name_prefix}-api-drivers"
  role          = aws_iam_role.api_drivers.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.api_drivers.output_path
  source_code_hash = data.archive_file.api_drivers.output_base64sha256

  memory_size = var.api_memory_size
  timeout     = var.api_timeout

  environment {
    variables = {
      OPENF1_BASE_URL = "https://api.openf1.org/v1"
      DRIVERS_TABLE   = var.table_names.drivers
      LOG_LEVEL       = "INFO"
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# api-replay Lambda — bulk GET /sessions/{key}/replay (v2). Reads positions,
# laps, race-control in one call so the frontend can do client-side playback.
# ----------------------------------------------------------------------------
resource "aws_iam_role" "api_replay" {
  name               = "${local.name_prefix}-api-replay"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "api_replay_permissions" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  statement {
    sid    = "TelemetryRead"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
    ]
    resources = [
      var.table_arns.sessions,
      var.table_arns.drivers,
      var.table_arns.positions,
      var.table_arns.laps,
      var.table_arns.race_control,
      var.table_arns.car_data,
    ]
  }
}

resource "aws_iam_role_policy" "api_replay" {
  name   = "${local.name_prefix}-api-replay"
  role   = aws_iam_role.api_replay.id
  policy = data.aws_iam_policy_document.api_replay_permissions.json
}

data "archive_file" "api_replay" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/api-replay"
  output_path = "${path.module}/build/api-replay.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "api_replay" {
  function_name = "${local.name_prefix}-api-replay"
  role          = aws_iam_role.api_replay.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.api_replay.output_path
  source_code_hash = data.archive_file.api_replay.output_base64sha256

  # Bulk reads can return a few MB for a full session — give it more memory
  # + a longer timeout than the per-route API Lambdas.
  memory_size = 512
  timeout     = 30

  environment {
    variables = {
      SESSIONS_TABLE     = var.table_names.sessions
      DRIVERS_TABLE      = var.table_names.drivers
      POSITIONS_TABLE    = var.table_names.positions
      LAPS_TABLE         = var.table_names.laps
      RACE_CONTROL_TABLE = var.table_names.race_control
      CAR_DATA_TABLE     = var.table_names.car_data
      LOG_LEVEL          = "INFO"
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# REST API Gateway — resources, GET (Lambda proxy), OPTIONS (MOCK for CORS)
# ----------------------------------------------------------------------------
resource "aws_api_gateway_rest_api" "api" {
  name        = "${local.name_prefix}-api"
  description = "F1 telemetry REST API — session/driver queries from DynamoDB + OpenF1."

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = local.common_tags
}

# /sessions
resource "aws_api_gateway_resource" "sessions_root" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "sessions"
}

# /sessions/{sessionId}
resource "aws_api_gateway_resource" "session_item" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.sessions_root.id
  path_part   = "{sessionId}"
}

# /sessions/{sessionId}/positions
resource "aws_api_gateway_resource" "positions" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.session_item.id
  path_part   = "positions"
}

# /sessions/{sessionId}/race-control
resource "aws_api_gateway_resource" "race_control" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.session_item.id
  path_part   = "race-control"
}

# /sessions/{sessionId}/laps
resource "aws_api_gateway_resource" "laps" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.session_item.id
  path_part   = "laps"
}

# /sessions/{sessionId}/drivers — bulk fetch all 20 drivers in one call (v2)
resource "aws_api_gateway_resource" "drivers_bulk" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.session_item.id
  path_part   = "drivers"
}

# /sessions/{sessionId}/replay — bulk fetch positions/laps/race-control for client-side playback (v2)
resource "aws_api_gateway_resource" "replay" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.session_item.id
  path_part   = "replay"
}

# /drivers (intermediate — no GET, only its child)
resource "aws_api_gateway_resource" "drivers_root" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "drivers"
}

# /drivers/{driverNumber}
resource "aws_api_gateway_resource" "driver_item" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.drivers_root.id
  path_part   = "{driverNumber}"
}

# GET methods — Lambda proxy (AWS_PROXY); Lambda owns status + headers + body.
resource "aws_api_gateway_method" "get" {
  for_each      = local.get_endpoints
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = each.value.resource_id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get" {
  for_each                = local.get_endpoints
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = each.value.resource_id
  http_method             = aws_api_gateway_method.get[each.key].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = each.value.lambda_arn
}

# OPTIONS methods — MOCK integration returning CORS headers for preflight.
# Every GET endpoint also serves an OPTIONS on the same resource.
resource "aws_api_gateway_method" "options" {
  for_each      = local.get_endpoints
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = each.value.resource_id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "options" {
  for_each    = local.get_endpoints
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = each.value.resource_id
  # Reference the method resource (not a literal) so Terraform creates the
  # method before this integration — otherwise PutIntegration 404s with
  # "Invalid Method identifier" (AWS needs the method to exist first).
  http_method       = aws_api_gateway_method.options[each.key].http_method
  type              = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "options" {
  for_each        = local.get_endpoints
  rest_api_id     = aws_api_gateway_rest_api.api.id
  resource_id     = each.value.resource_id
  http_method     = "OPTIONS"
  status_code     = "200"
  response_models = { "application/json" = "Empty" }
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
  depends_on = [aws_api_gateway_method.options]
}

resource "aws_api_gateway_integration_response" "options" {
  for_each    = local.get_endpoints
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = each.value.resource_id
  http_method = "OPTIONS"
  status_code = "200"
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'${var.cors_allow_origin}'"
  }
  # Needs both the integration and the matching method response to exist first.
  depends_on = [
    aws_api_gateway_integration.options,
    aws_api_gateway_method_response.options,
  ]
}

# ----------------------------------------------------------------------------
# Deployment + stage — the triggers hash forces a redeploy when routes/CORS
# change. Separate stage resource avoids "stage already exists" conflicts under
# repeated CI applies.
# ----------------------------------------------------------------------------
resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode({
      endpoints = local.get_endpoints
      cors      = var.cors_allow_origin
    }))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.get,
    aws_api_gateway_integration_response.options,
  ]
}

resource "aws_api_gateway_stage" "this" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  deployment_id = aws_api_gateway_deployment.this.id
  stage_name    = "v1"
  tags          = local.common_tags
}

# ----------------------------------------------------------------------------
# Allow API Gateway to invoke each Lambda (any route on this API).
# ----------------------------------------------------------------------------
resource "aws_lambda_permission" "apigw_sessions" {
  statement_id  = "AllowAPIGatewayInvokeSessions"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_sessions.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_drivers" {
  statement_id  = "AllowAPIGatewayInvokeDrivers"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_drivers.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_replay" {
  statement_id  = "AllowAPIGatewayInvokeReplay"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_replay.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

# ============================================================================
# WEBSOCKET LAYER — real-time telemetry fanout
#
# Browser ──(wss ?sessionId)──► $connect ──put──► Connections[connection_id, session_key, ttl]
# Positions/CarData/Laps/RaceControl ──NEW_IMAGE──► ws-push ──query GSI by_session──► post_to_connection
# $disconnect ──delete──► Connections   (TTL + GoneException catch dropped clients)
# ============================================================================

data "aws_region" "current" {}

# ----------------------------------------------------------------------------
# Connections table — WebSocket connection state (delivery layer, not telemetry)
# PK connection_id for connect/disconnect; GSI by_session for the push fanout.
# TTL clears connections that drop without a $disconnect.
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "connections" {
  name         = "${local.name_prefix}-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connection_id"

  attribute {
    name = "connection_id"
    type = "S"
  }

  attribute {
    name = "session_key"
    type = "S"
  }

  global_secondary_index {
    name            = local.connections_session_index
    hash_key        = "session_key"
    projection_type = "KEYS_ONLY" # ws-push only needs connection_id back
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# WebSocket API (v2) + $connect/$disconnect routes + stage (auto-deploy)
# ----------------------------------------------------------------------------
resource "aws_apigatewayv2_api" "ws" {
  name                       = "${local.name_prefix}-ws"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
  tags                       = local.common_tags
}

resource "aws_apigatewayv2_integration" "ws_connect" {
  api_id           = aws_apigatewayv2_api.ws.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.ws_connect.invoke_arn
}

resource "aws_apigatewayv2_integration" "ws_disconnect" {
  api_id           = aws_apigatewayv2_api.ws.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.ws_disconnect.invoke_arn
}

resource "aws_apigatewayv2_integration" "ws_agent" {
  api_id           = aws_apigatewayv2_api.ws.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.ws_agent.invoke_arn
}

resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.ws_connect.id}"
}

resource "aws_apigatewayv2_route" "disconnect" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.ws_disconnect.id}"
}

# Custom action route: client sends {action: "agent.ask", text: "...", ...}
# and the WebSocket API dispatches to the ws-agent Lambda.
resource "aws_apigatewayv2_route" "agent_ask" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "agent.ask"
  target    = "integrations/${aws_apigatewayv2_integration.ws_agent.id}"
}

resource "aws_apigatewayv2_stage" "ws" {
  api_id      = aws_apigatewayv2_api.ws.id
  name        = "v1"
  auto_deploy = true
  tags        = local.common_tags
}

# Allow the WebSocket API to invoke $connect/$disconnect Lambdas.
resource "aws_lambda_permission" "ws_connect" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_connect.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*"
}

resource "aws_lambda_permission" "ws_disconnect" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_disconnect.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*"
}

resource "aws_lambda_permission" "ws_agent" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_agent.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*"
}

# ----------------------------------------------------------------------------
# ws-connect Lambda — persist (connection_id, session_key, ttl) on $connect
# ----------------------------------------------------------------------------
data "archive_file" "ws_connect" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/ws-connect"
  output_path = "${path.module}/build/ws-connect.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "ws_connect" {
  function_name = "${local.name_prefix}-ws-connect"
  role          = aws_iam_role.ws_connect.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.ws_connect.output_path
  source_code_hash = data.archive_file.ws_connect.output_base64sha256

  memory_size = var.api_memory_size
  timeout     = var.api_timeout

  environment {
    variables = {
      CONNECTIONS_TABLE      = aws_dynamodb_table.connections.name
      CONNECTION_TTL_SECONDS = "7200"
      LOG_LEVEL              = "INFO"
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# ws-disconnect Lambda — delete the connection row on $disconnect
# ----------------------------------------------------------------------------
data "archive_file" "ws_disconnect" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/ws-disconnect"
  output_path = "${path.module}/build/ws-disconnect.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "ws_disconnect" {
  function_name = "${local.name_prefix}-ws-disconnect"
  role          = aws_iam_role.ws_disconnect.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.ws_disconnect.output_path
  source_code_hash = data.archive_file.ws_disconnect.output_base64sha256

  memory_size = var.api_memory_size
  timeout     = var.api_timeout

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.connections.name
      LOG_LEVEL         = "INFO"
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# ws-push Lambda — telemetry stream fanout (all four NEW_IMAGE streams)
# ----------------------------------------------------------------------------
data "archive_file" "ws_push" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/ws-push"
  output_path = "${path.module}/build/ws-push.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "ws_push" {
  function_name = "${local.name_prefix}-ws-push"
  role          = aws_iam_role.ws_push.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.ws_push.output_path
  source_code_hash = data.archive_file.ws_push.output_base64sha256

  memory_size = var.api_memory_size
  timeout     = var.api_timeout

  environment {
    variables = {
      CONNECTIONS_TABLE      = aws_dynamodb_table.connections.name
      SESSION_INDEX_NAME     = local.connections_session_index
      WEBSOCKET_API_ENDPOINT = "https://${aws_apigatewayv2_api.ws.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${aws_apigatewayv2_stage.ws.name}"
      LOG_LEVEL              = "INFO"
    }
  }

  tags = local.common_tags
}

# Telemetry DynamoDB Streams (NEW_IMAGE) -> ws-push. One mapping per table;
# ws-push dispatches on the source table name in the record's eventSourceARN.
# LATEST so a fresh deploy doesn't replay historical data through the socket.
resource "aws_lambda_event_source_mapping" "ws_push" {
  for_each = var.stream_arns

  event_source_arn  = each.value
  function_name     = aws_lambda_function.ws_push.arn
  starting_position = "LATEST"
  batch_size        = 100
  enabled           = true

  bisect_batch_on_function_error = true
  maximum_retry_attempts         = 3
  function_response_types        = ["ReportBatchItemFailures"]
}

# ----------------------------------------------------------------------------
# ws-agent Lambda — relays chat between browser and Bedrock AgentCore (v2).
# When agent_enabled is false (Phase 2 default), returns a stubbed reply.
# ----------------------------------------------------------------------------
data "archive_file" "ws_agent" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/ws-agent"
  output_path = "${path.module}/build/ws-agent.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "ws_agent" {
  function_name = "${local.name_prefix}-ws-agent"
  role          = aws_iam_role.ws_agent.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.ws_agent.output_path
  source_code_hash = data.archive_file.ws_agent.output_base64sha256

  memory_size = 512
  timeout     = 60

  environment {
    variables = {
      WEBSOCKET_API_ENDPOINT = "https://${aws_apigatewayv2_api.ws.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${aws_apigatewayv2_stage.ws.name}"
      CONNECTIONS_TABLE      = aws_dynamodb_table.connections.name
      AGENT_MODEL_ID         = var.agent_model_id
      AGENT_ENABLED          = tostring(var.agent_enabled)
      LOG_LEVEL              = "INFO"
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# IAM roles for the three WebSocket Lambdas (least privilege)
# ----------------------------------------------------------------------------
resource "aws_iam_role" "ws_connect" {
  name               = "${local.name_prefix}-ws-connect"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "ws_connect_permissions" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  statement {
    sid       = "ConnectionsWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.connections.arn]
  }
}

resource "aws_iam_role_policy" "ws_connect" {
  name   = "${local.name_prefix}-ws-connect"
  role   = aws_iam_role.ws_connect.id
  policy = data.aws_iam_policy_document.ws_connect_permissions.json
}

resource "aws_iam_role" "ws_disconnect" {
  name               = "${local.name_prefix}-ws-disconnect"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "ws_disconnect_permissions" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  statement {
    sid       = "ConnectionsDelete"
    effect    = "Allow"
    actions   = ["dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.connections.arn]
  }
}

resource "aws_iam_role_policy" "ws_disconnect" {
  name   = "${local.name_prefix}-ws-disconnect"
  role   = aws_iam_role.ws_disconnect.id
  policy = data.aws_iam_policy_document.ws_disconnect_permissions.json
}

resource "aws_iam_role" "ws_push" {
  name               = "${local.name_prefix}-ws-push"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "ws_push_permissions" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  # Required for the DynamoDB Streams event source mappings to poll the
  # telemetry streams (analogous to the transformer's Kinesis read perms).
  statement {
    sid    = "TelemetryStreamsRead"
    effect = "Allow"
    actions = [
      "dynamodb:GetShardIterator",
      "dynamodb:GetRecords",
      "dynamodb:DescribeStream",
      "dynamodb:ListStreams",
    ]
    resources = values(var.stream_arns)
  }

  statement {
    sid     = "ConnectionsRead"
    effect  = "Allow"
    actions = ["dynamodb:Query"]
    resources = [
      aws_dynamodb_table.connections.arn,
      "${aws_dynamodb_table.connections.arn}/index/*",
    ]
  }

  statement {
    sid       = "ConnectionsDeleteStale"
    effect    = "Allow"
    actions   = ["dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.connections.arn]
  }

  statement {
    sid       = "ManageConnections"
    effect    = "Allow"
    actions   = ["execute-api:ManageConnections"]
    resources = ["${aws_apigatewayv2_api.ws.execution_arn}/*"]
  }
}

resource "aws_iam_role_policy" "ws_push" {
  name   = "${local.name_prefix}-ws-push"
  role   = aws_iam_role.ws_push.id
  policy = data.aws_iam_policy_document.ws_push_permissions.json
}

# ----------------------------------------------------------------------------
# ws-agent IAM role — logs + WebSocket post_back + (when agent_enabled) Bedrock invoke
# ----------------------------------------------------------------------------
resource "aws_iam_role" "ws_agent" {
  name               = "${local.name_prefix}-ws-agent"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "ws_agent_permissions" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  # Required to post streamed tokens back to the calling connection.
  statement {
    sid       = "ManageConnections"
    effect    = "Allow"
    actions   = ["execute-api:ManageConnections"]
    resources = ["${aws_apigatewayv2_api.ws.execution_arn}/*"]
  }

  # Connection-table lookup so we can recover sessionKey/driverNumber context.
  statement {
    sid     = "ConnectionsRead"
    effect  = "Allow"
    actions = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.connections.arn,
      "${aws_dynamodb_table.connections.arn}/index/*",
    ]
  }

  # Bedrock model invoke (only honored when agent_enabled=true).
  # Scoped to the specific model ARN; wildcard region/account because
  # Bedrock model ARNs are account-scoped in us-east-1.
  statement {
    sid       = "BedrockInvoke"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModelWithResponseStream"]
    resources = ["arn:aws:bedrock:*::foundation-model/${var.agent_model_id}"]
  }
}

resource "aws_iam_role_policy" "ws_agent" {
  name   = "${local.name_prefix}-ws-agent"
  role   = aws_iam_role.ws_agent.id
  policy = data.aws_iam_policy_document.ws_agent_permissions.json
}

# ============================================================================
# CUSTOM DOMAINS — friendly hostnames for the REST and WebSocket APIs
#
# api.<domain> ──A(alias)──► REST regional domain   (base_path v1 preserves URL shape)
# ws.<domain>  ──A(alias)──► WebSocket regional domain (stage v1 preserved)
# ============================================================================

# ----------------------------------------------------------------------------
# REST custom domain (API Gateway v1, REGIONAL endpoint)
# ----------------------------------------------------------------------------
resource "aws_api_gateway_domain_name" "rest" {
  count                    = local.enable_rest_domain ? 1 : 0
  domain_name              = var.rest_domain_name
  regional_certificate_arn = var.acm_certificate_arn
  security_policy          = "TLS_1_2"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = local.common_tags
}

# base_path = "v1" keeps the URL shape identical to the raw invoke URL
# (https://api.<domain>/v1/sessions), so the frontend needs no changes.
resource "aws_api_gateway_base_path_mapping" "rest" {
  count       = local.enable_rest_domain ? 1 : 0
  api_id      = aws_api_gateway_rest_api.api.id
  stage_name  = aws_api_gateway_stage.this.stage_name
  domain_name = aws_api_gateway_domain_name.rest[0].domain_name
  base_path   = "v1"
}

resource "aws_route53_record" "rest" {
  count   = local.enable_rest_domain ? 1 : 0
  zone_id = var.zone_id
  name    = var.rest_domain_name
  type    = "A"

  alias {
    name                   = aws_api_gateway_domain_name.rest[0].regional_domain_name
    zone_id                = aws_api_gateway_domain_name.rest[0].regional_zone_id
    evaluate_target_health = false
  }
}

# ----------------------------------------------------------------------------
# WebSocket custom domain (API Gateway v2, REGIONAL endpoint)
# ----------------------------------------------------------------------------
resource "aws_apigatewayv2_domain_name" "ws" {
  count       = local.enable_ws_domain ? 1 : 0
  domain_name = var.ws_domain_name

  domain_name_configuration {
    certificate_arn = var.acm_certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = local.common_tags
}

# No api_mapping_key → root mapping. The stage name stays in the URL path
# (wss://ws.<domain>/v1), matching the existing wss://<api>.execute-api.../v1.
resource "aws_apigatewayv2_api_mapping" "ws" {
  count       = local.enable_ws_domain ? 1 : 0
  api_id      = aws_apigatewayv2_api.ws.id
  domain_name = aws_apigatewayv2_domain_name.ws[0].id
  stage       = aws_apigatewayv2_stage.ws.id
}

resource "aws_route53_record" "ws" {
  count   = local.enable_ws_domain ? 1 : 0
  zone_id = var.zone_id
  name    = var.ws_domain_name
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.ws[0].domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.ws[0].domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
