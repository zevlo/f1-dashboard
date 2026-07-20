locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    Module      = "processing"
    ManagedBy   = "terraform"
  })
}

# ----------------------------------------------------------------------------
# SQS DLQ — catches Kinesis records that exhaust retries after batch failures
# ----------------------------------------------------------------------------
resource "aws_sqs_queue" "transformer_dlq" {
  name                      = "${local.name_prefix}-transformer-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.common_tags
}

# ----------------------------------------------------------------------------
# IAM role + least-privilege policy for the transformer Lambda
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

resource "aws_iam_role" "transformer" {
  name               = "${local.name_prefix}-transformer"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "transformer_permissions" {
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
    sid    = "KinesisReads"
    effect = "Allow"
    actions = [
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "kinesis:DescribeStream",
      "kinesis:DescribeStreamSummary",
      "kinesis:ListShards",
      "kinesis:ListStreams",
    ]
    resources = [var.kinesis_stream_arn]
  }

  statement {
    sid    = "DynamoDBWrites"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
    ]
    resources = [
      var.table_arns.sessions,
      var.table_arns.positions,
      var.table_arns.car_data,
      var.table_arns.laps,
      var.table_arns.race_control,
    ]
  }

  statement {
    sid       = "SqsDLQ"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.transformer_dlq.arn]
  }
}

resource "aws_iam_role_policy" "transformer" {
  name   = "${local.name_prefix}-transformer"
  role   = aws_iam_role.transformer.id
  policy = data.aws_iam_policy_document.transformer_permissions.json
}

# ----------------------------------------------------------------------------
# Transformer Lambda — packaged via archive_file from ../../../lambdas/transformer
# ----------------------------------------------------------------------------
data "archive_file" "transformer" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/transformer"
  output_path = "${path.module}/build/transformer.zip"
  excludes    = ["test_handler.py", "__pycache__"]
}

resource "aws_lambda_function" "transformer" {
  function_name = "${local.name_prefix}-transformer"
  role          = aws_iam_role.transformer.arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"

  filename         = data.archive_file.transformer.output_path
  source_code_hash = data.archive_file.transformer.output_base64sha256

  memory_size = var.transformer_memory_size
  timeout     = var.transformer_timeout

  environment {
    variables = {
      SESSIONS_TABLE     = var.table_names.sessions
      POSITIONS_TABLE    = var.table_names.positions
      CAR_DATA_TABLE     = var.table_names.car_data
      LAPS_TABLE         = var.table_names.laps
      RACE_CONTROL_TABLE = var.table_names.race_control
      LOG_LEVEL          = "INFO"
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# Kinesis → transformer EventSource Mapping
# ----------------------------------------------------------------------------
resource "aws_lambda_event_source_mapping" "transformer" {
  event_source_arn  = var.kinesis_stream_arn
  function_name     = aws_lambda_function.transformer.arn
  starting_position = "LATEST"
  batch_size        = var.batch_size
  enabled           = true

  # On repeated batch failures: bisect to isolate the bad record, then send
  # the metadata to the DLQ so we don't block the shard indefinitely.
  bisect_batch_on_function_error = true
  maximum_record_age_in_seconds  = 3600
  maximum_retry_attempts         = 3
  # 10 concurrent batches per shard. Sequential processing (~40 rec/s) can't
  # keep up with replay traffic (~235 rec/s, dominated by whole-session lap
  # re-fetches that dedupe as no-ops). Safe: writes are idempotent conditional
  # puts and Kinesis preserves per-partition-key ordering across batches.
  parallelization_factor         = 10

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.transformer_dlq.arn
    }
  }

  function_response_types = ["ReportBatchItemFailures"]
}
