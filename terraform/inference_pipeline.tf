# terraform/inference_pipeline.tf

resource "aws_iam_role" "lambda_inference_role" {
  name = "LambdaInferenceRole-${var.project_name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_policy" "lambda_inference_policy" {
  name = "LambdaInferencePolicy-${var.project_name}"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["sagemaker:InvokeEndpoint"],
        Resource = "arn:aws:sagemaker:${var.aws_region}:${var.account_id}:endpoint/real-estate-endpoint-${var.project_name}"
      },
      {
        Effect = "Allow",
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow",
        Action = ["s3:PutObject", "s3:ListBucket", "s3:GetObject"],
        Resource = [
          aws_s3_bucket.target_bucket.arn,
          "${aws_s3_bucket.target_bucket.arn}/*"
        ]
      },
      {
        Effect = "Allow",
        Action = ["cloudwatch:PutMetricData"],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "inference_attach" {
  role       = aws_iam_role.lambda_inference_role.name
  policy_arn = aws_iam_policy.lambda_inference_policy.arn
}

data "archive_file" "lambda_inference_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda_api_wrapper/"
  output_path = "${path.module}/lambda_inference.zip"
}

resource "aws_lambda_function" "inference_lambda" {
  function_name    = "InferenceLambda-${var.project_name}"
  filename         = data.archive_file.lambda_inference_zip.output_path
  handler          = "main.lambda_handler"
  runtime          = "python3.11"
  role             = aws_iam_role.lambda_inference_role.arn
  source_code_hash = data.archive_file.lambda_inference_zip.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      ENDPOINT_NAME      = "real-estate-endpoint-${var.project_name}"
      MONITORING_BUCKET  = aws_s3_bucket.target_bucket.id
      MONITORING_PREFIX  = "monitoring/predictions/"
      METRICS_NAMESPACE  = "RealEstate/Inference"
    }
  }
}