resource "aws_ecr_repository" "monitoring_repo" {
  name                 = "monitoring-evidently-${var.project_name}"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_iam_role" "lambda_monitoring_role" {
  name = "LambdaMonitoringEvidentlyRole-${var.project_name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "monitoring_ecr_read" {
  role       = aws_iam_role.lambda_monitoring_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_s3_object" "monitoring_reference" {
  bucket = aws_s3_bucket.target_bucket.id
  key    = "monitoring/reference/reference_data.csv"
  source = "../monitoring/reference_data.csv"
  etag   = filemd5("../monitoring/reference_data.csv")
}

resource "aws_iam_policy" "lambda_monitoring_policy" {
  name = "LambdaMonitoringPolicy-${var.project_name}"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ],
        Resource = [
          aws_s3_bucket.target_bucket.arn,
          "${aws_s3_bucket.target_bucket.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "monitoring_policy_attach" {
  role       = aws_iam_role.lambda_monitoring_role.name
  policy_arn = aws_iam_policy.lambda_monitoring_policy.arn
}

resource "aws_lambda_function" "monitoring_evidently_lambda" {
  function_name = "MonitoringEvidentlyLambda-${var.project_name}"
  role          = aws_iam_role.lambda_monitoring_role.arn

  timeout       = 300
  memory_size   = 2048
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.monitoring_repo.repository_url}:${var.image_tag}"

  environment {
    variables = {
      MONITORING_BUCKET = aws_s3_bucket.target_bucket.id
      REFERENCE_KEY     = "monitoring/reference/reference_data.csv"
      MONITORING_PREFIX = "monitoring/predictions/"
      REPORT_PREFIX     = "monitoring/reports/"
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.monitoring_ecr_read,
    aws_iam_role_policy_attachment.monitoring_policy_attach
  ]
}

resource "aws_cloudwatch_event_rule" "monitoring_evidently_daily" {
  name                = "MonitoringEvidentlyDaily-${var.project_name}"
  schedule_expression = "cron(0 3 * * ? *)"
}

resource "aws_cloudwatch_event_target" "monitoring_evidently_target" {
  rule      = aws_cloudwatch_event_rule.monitoring_evidently_daily.name
  target_id = "MonitoringEvidentlyLambdaTarget"
  arn       = aws_lambda_function.monitoring_evidently_lambda.arn
}

resource "aws_lambda_permission" "allow_eventbridge_invoke_monitoring" {
  statement_id  = "AllowEventBridgeInvokeMonitoringEvidently"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.monitoring_evidently_lambda.arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.monitoring_evidently_daily.arn
}