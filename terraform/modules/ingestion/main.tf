locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    Module      = "ingestion"
    ManagedBy   = "terraform"
  })
}

# ----------------------------------------------------------------------------
# Kinesis Data Stream — ingestion buffer between OpenF1 poller and transformer
# ----------------------------------------------------------------------------
resource "aws_kinesis_stream" "telemetry" {
  name             = "${local.name_prefix}-telemetry"
  shard_count      = var.kinesis_shard_count
  retention_period = 24

  shard_level_metrics = [
    "IncomingBytes",
    "IncomingRecords",
    "WriteProvisionedThroughputExceeded",
  ]

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# SQS DLQ — catches EventBridge events that exhaust retries
# ----------------------------------------------------------------------------
resource "aws_sqs_queue" "poller_dlq" {
  name                      = "${local.name_prefix}-poller-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.common_tags
}

data "aws_iam_policy_document" "poller_dlq_policy" {
  statement {
    sid     = "AllowEventBridgeSendMessage"
    effect  = "Allow"
    actions = ["sqs:SendMessage"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    resources = [aws_sqs_queue.poller_dlq.arn]
  }
}

resource "aws_sqs_queue_policy" "poller_dlq" {
  queue_url = aws_sqs_queue.poller_dlq.id
  policy    = data.aws_iam_policy_document.poller_dlq_policy.json
}

# ----------------------------------------------------------------------------
# IAM role + policy for the poller Lambda (least privilege)
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

resource "aws_iam_role" "poller" {
  name               = "${local.name_prefix}-poller"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "poller_permissions" {
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
    sid    = "KinesisPuts"
    effect = "Allow"
    actions = [
      "kinesis:PutRecord",
      "kinesis:PutRecords",
      "kinesis:DescribeStreamSummary",
    ]
    resources = [aws_kinesis_stream.telemetry.arn]
  }

  statement {
    sid       = "SqsDLQ"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.poller_dlq.arn]
  }

  statement {
    sid    = "DriversWrite"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:DescribeTable",
    ]
    resources = [var.drivers_table_arn]
  }
}

resource "aws_iam_role_policy" "poller" {
  name   = "${local.name_prefix}-poller"
  role   = aws_iam_role.poller.id
  policy = data.aws_iam_policy_document.poller_permissions.json
}

# ----------------------------------------------------------------------------
# Poller Lambda — packaged via archive_file from ../../../lambdas/poller
# ----------------------------------------------------------------------------
data "archive_file" "poller" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/poller"
  output_path = "${path.module}/build/poller.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "poller" {
  function_name = "${local.name_prefix}-poller"
  role          = aws_iam_role.poller.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.poller.output_path
  source_code_hash = data.archive_file.poller.output_base64sha256

  memory_size = var.poller_memory_size
  timeout     = var.poller_timeout

  environment {
    variables = {
      OPENF1_BASE_URL  = "https://api.openf1.org/v1"
      STREAM_NAME      = aws_kinesis_stream.telemetry.name
      STREAM_ARN       = aws_kinesis_stream.telemetry.arn
      DLQ_URL          = aws_sqs_queue.poller_dlq.id
      DRIVERS_TABLE    = var.drivers_table_name
      LOOP_COUNT       = tostring(var.poller_internal_loop_count)
      LOG_LEVEL        = "INFO"
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# EventBridge rule + target — fires poller on schedule
# ----------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "poller_schedule" {
  name                = "${local.name_prefix}-poller-schedule"
  schedule_expression = var.poller_schedule_expression
  state               = var.poller_enabled ? "ENABLED" : "DISABLED"
  description         = "Triggers the OpenF1 poller Lambda on a fixed schedule."
  tags                = local.common_tags
}

resource "aws_cloudwatch_event_target" "poller" {
  rule = aws_cloudwatch_event_rule.poller_schedule.name
  arn  = aws_lambda_function.poller.arn

  retry_policy {
    maximum_retry_attempts    = 2
    maximum_event_age_in_seconds = 600
  }

  dead_letter_config {
    arn = aws_sqs_queue.poller_dlq.arn
  }
}

resource "aws_lambda_permission" "eventbridge_invoke_poller" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.poller.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.poller_schedule.arn
}
