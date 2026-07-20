locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    Module      = "monitoring"
    ManagedBy   = "terraform"
  })
}

data "aws_region" "current" {}

# ----------------------------------------------------------------------------
# SNS — alarm fanout. Email subscription only when an address is configured
# (email endpoints require manual confirmation, so it's opt-in).
# ----------------------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ----------------------------------------------------------------------------
# Alarm: Lambda error rate > 5% (per function, metric math)
# ----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "lambda_error_rate" {
  for_each = var.lambda_function_names

  alarm_name          = "${local.name_prefix}-${each.key}-error-rate"
  alarm_description   = "Error rate for ${each.value} exceeded 5% over two 5-minute periods."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 5
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "error_rate"
    expression  = "IF(invocations > 0, errors / invocations * 100, 0)"
    label       = "Error rate (%)"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Errors"
      period      = 300
      stat        = "Sum"
      dimensions = {
        FunctionName = each.value
      }
    }
  }

  metric_query {
    id = "invocations"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Invocations"
      period      = 300
      stat        = "Sum"
      dimensions = {
        FunctionName = each.value
      }
    }
  }

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# Alarm: Kinesis iterator age > 60s (transformer falling behind the stream)
# ----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "kinesis_iterator_age" {
  alarm_name          = "${local.name_prefix}-kinesis-iterator-age"
  alarm_description   = "Kinesis consumer iterator age exceeded 60s — the transformer is falling behind."
  namespace           = "AWS/Kinesis"
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 60000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StreamName = var.kinesis_stream_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# Alarms: DynamoDB throttles > 0 (per table, read + write)
# ----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "dynamodb_read_throttles" {
  for_each = var.dynamodb_table_names

  alarm_name          = "${local.name_prefix}-${each.key}-read-throttles"
  alarm_description   = "Read throttle events on ${each.value}."
  namespace           = "AWS/DynamoDB"
  metric_name         = "ReadThrottleEvents"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = each.value
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "dynamodb_write_throttles" {
  for_each = var.dynamodb_table_names

  alarm_name          = "${local.name_prefix}-${each.key}-write-throttles"
  alarm_description   = "Write throttle events on ${each.value}."
  namespace           = "AWS/DynamoDB"
  metric_name         = "WriteThrottleEvents"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = each.value
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

# ----------------------------------------------------------------------------
# Dashboard — one row per pipeline layer
# ----------------------------------------------------------------------------
locals {
  lambda_names = values(var.lambda_function_names)
  table_names  = values(var.dynamodb_table_names)
  region       = data.aws_region.current.name

  dashboard_widgets = [
    # Row 1 — Lambda health
    {
      type = "metric", x = 0, y = 0, width = 8, height = 6
      properties = {
        title   = "Lambda invocations"
        region  = local.region
        stat    = "Sum"
        period  = 300
        metrics = [for name in local.lambda_names : ["AWS/Lambda", "Invocations", "FunctionName", name]]
      }
    },
    {
      type = "metric", x = 8, y = 0, width = 8, height = 6
      properties = {
        title   = "Lambda errors"
        region  = local.region
        stat    = "Sum"
        period  = 300
        metrics = [for name in local.lambda_names : ["AWS/Lambda", "Errors", "FunctionName", name]]
      }
    },
    {
      type = "metric", x = 16, y = 0, width = 8, height = 6
      properties = {
        title   = "Lambda duration (avg ms)"
        region  = local.region
        stat    = "Average"
        period  = 300
        metrics = [for name in local.lambda_names : ["AWS/Lambda", "Duration", "FunctionName", name]]
      }
    },

    # Row 2 — Kinesis
    {
      type = "metric", x = 0, y = 6, width = 12, height = 6
      properties = {
        title  = "Kinesis records in/out"
        region = local.region
        stat   = "Sum"
        period = 300
        metrics = [
          ["AWS/Kinesis", "IncomingRecords", "StreamName", var.kinesis_stream_name],
          ["AWS/Kinesis", "GetRecords.Records", "StreamName", var.kinesis_stream_name],
        ]
      }
    },
    {
      type = "metric", x = 12, y = 6, width = 12, height = 6
      properties = {
        title   = "Kinesis iterator age (ms)"
        region  = local.region
        stat    = "Maximum"
        period  = 60
        metrics = [["AWS/Kinesis", "GetRecords.IteratorAgeMilliseconds", "StreamName", var.kinesis_stream_name]]
      }
    },

    # Row 3 — DynamoDB
    {
      type = "metric", x = 0, y = 12, width = 12, height = 6
      properties = {
        title   = "DynamoDB consumed WCU"
        region  = local.region
        stat    = "Sum"
        period  = 300
        metrics = [for name in local.table_names : ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", name]]
      }
    },
    {
      type = "metric", x = 12, y = 12, width = 12, height = 6
      properties = {
        title  = "DynamoDB throttle events"
        region = local.region
        stat   = "Sum"
        period = 300
        metrics = concat(
          [for name in local.table_names : ["AWS/DynamoDB", "ReadThrottleEvents", "TableName", name]],
          [for name in local.table_names : ["AWS/DynamoDB", "WriteThrottleEvents", "TableName", name]],
        )
      }
    },

    # Row 4 — API delivery
    {
      type = "metric", x = 0, y = 18, width = 12, height = 6
      properties = {
        title  = "REST API requests / errors"
        region = local.region
        stat   = "Sum"
        period = 300
        metrics = [
          ["AWS/ApiGateway", "Count", "ApiName", var.rest_api_name, "Stage", var.rest_api_stage],
          ["AWS/ApiGateway", "4XXError", "ApiName", var.rest_api_name, "Stage", var.rest_api_stage],
          ["AWS/ApiGateway", "5XXError", "ApiName", var.rest_api_name, "Stage", var.rest_api_stage],
        ]
      }
    },
    {
      type = "metric", x = 12, y = 18, width = 12, height = 6
      properties = {
        title  = "WebSocket connects / messages"
        region = local.region
        stat   = "Sum"
        period = 300
        metrics = [
          ["AWS/ApiGateway", "ConnectCount", "ApiId", var.websocket_api_id, "Stage", var.websocket_stage],
          ["AWS/ApiGateway", "MessageCount", "ApiId", var.websocket_api_id, "Stage", var.websocket_stage],
        ]
      }
    },
  ]
}

resource "aws_cloudwatch_dashboard" "pipeline" {
  dashboard_name = "${local.name_prefix}-pipeline"
  dashboard_body = jsonencode({ widgets = local.dashboard_widgets })
}
