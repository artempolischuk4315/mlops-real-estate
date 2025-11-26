data "archive_file" "lambda_api_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda_api_wrapper/"
  output_path = "${path.module}/lambda_api_wrapper.zip"

  excludes    = ["__pycache__", "*.pyc"]
}

resource "aws_iam_role" "lambda_api_role" {
  name = "LambdaApiWrapperRole-${var.project_name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_policy" "lambda_api_policy" {
  name        = "LambdaApiWrapperPolicy-${var.project_name}"
  description = "Access to SageMaker invoke and S3 logging"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["sagemaker:InvokeEndpoint"],
        Resource = [
            "arn:aws:sagemaker:${var.aws_region}:${var.account_id}:endpoint/real-estate-endpoint-${var.project_name}",
            "arn:aws:sagemaker:${var.aws_region}:${var.account_id}:endpoint/*"
        ]
      },
      {
        Effect = "Allow",
        Action = [
          "s3:PutObject",
          "s3:GetObject"
        ],
        Resource = "${aws_s3_bucket.target_bucket.arn}/monitoring/*"
      },
      {
        Effect = "Allow",
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_api_attach" {
  role       = aws_iam_role.lambda_api_role.name
  policy_arn = aws_iam_policy.lambda_api_policy.arn
}

resource "aws_lambda_function" "api_wrapper_lambda" {
  function_name    = "ApiWrapperLambda-${var.project_name}"
  filename         = data.archive_file.lambda_api_zip.output_path
  source_code_hash = data.archive_file.lambda_api_zip.output_base64sha256
  handler          = "main.lambda_handler"
  runtime          = "python3.11"
  role             = aws_iam_role.lambda_api_role.arn
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      ENDPOINT_NAME     = "real-estate-endpoint-${var.project_name}"

      MONITORING_BUCKET = aws_s3_bucket.target_bucket.id
      MONITORING_PREFIX = "monitoring/predictions/"
    }
  }
}

output "api_lambda_arn" {
  value = aws_lambda_function.api_wrapper_lambda.arn
}