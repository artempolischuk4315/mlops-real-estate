resource "aws_cloudwatch_metric_alarm" "data_drift_alarm" {
  alarm_name          = "DataDriftDetected-${var.project_name}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "DriftScore"
  namespace           = "MLOps/RealEstate"
  period              = "60"
  statistic           = "Maximum"
  threshold           = "0.3"
  alarm_description   = "Alarm when data drift score exceeds 0.3"
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "high_error_rate" {
  alarm_name          = "HighErrorRate-${var.project_name}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "60"
  statistic           = "Sum"
  threshold           = "1"
  alarm_description   = "Triggers if Inference Lambda fails even once"

  dimensions = {
    FunctionName = aws_lambda_function.api_wrapper_lambda.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "high_prediction_value" {
  alarm_name          = "HighPredictionValue-${var.project_name}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "AveragePrediction"
  namespace           = "RealEstate/Inference"
  period              = "60"
  statistic           = "Average"
  threshold           = "800"
  alarm_description   = "Triggers if model predicts unusually high prices (> 800)"
  treat_missing_data  = "notBreaching"

  dimensions = {
    EndpointName = "real-estate-endpoint-${var.project_name}"
  }
}