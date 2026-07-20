output "table_names" {
  description = "Map of logical name -> DynamoDB table name for all six telemetry tables (incl. Drivers)."
  value = {
    sessions     = aws_dynamodb_table.sessions.name
    drivers      = aws_dynamodb_table.drivers.name
    positions    = aws_dynamodb_table.positions.name
    car_data     = aws_dynamodb_table.car_data.name
    laps         = aws_dynamodb_table.laps.name
    race_control = aws_dynamodb_table.race_control.name
  }
}

output "table_arns" {
  description = "Map of logical name -> DynamoDB table ARN for IAM scoping."
  value = {
    sessions     = aws_dynamodb_table.sessions.arn
    drivers      = aws_dynamodb_table.drivers.arn
    positions    = aws_dynamodb_table.positions.arn
    car_data     = aws_dynamodb_table.car_data.arn
    laps         = aws_dynamodb_table.laps.arn
    race_control = aws_dynamodb_table.race_control.arn
  }
}

output "positions_stream_arn" {
  description = "ARN of the DynamoDB Stream on the Positions table (NEW_IMAGE). Consumed by the WebSocket push Lambda in Week 3."
  value       = aws_dynamodb_table.positions.stream_arn
}

output "stream_arns" {
  description = "Map of logical name -> DynamoDB Stream ARN (NEW_IMAGE) for every table the ws-push Lambda fans out from."
  value = {
    positions    = aws_dynamodb_table.positions.stream_arn
    car_data     = aws_dynamodb_table.car_data.stream_arn
    laps         = aws_dynamodb_table.laps.stream_arn
    race_control = aws_dynamodb_table.race_control.stream_arn
  }
}

output "positions_gsi_name" {
  description = "Name of the per-driver GSI on the Positions table."
  value       = "by_driver"
}
