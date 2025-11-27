data "archive_file" "rollback_lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../mlops_pipeline/rollback_lambda"
  output_path = "${path.module}/rollback_lambda.zip"
}

resource "aws_lambda_function" "rollback_lambda" {
  function_name    = "ManualRollbackLambda-${var.project_name}"
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  role             = aws_iam_role.lambda_deployment_role.arn
  filename         = data.archive_file.rollback_lambda_zip.output_path
  source_code_hash = data.archive_file.rollback_lambda_zip.output_base64sha256
  timeout          = 60

  environment {
    variables = {
      ENDPOINT_NAME = "real-estate-endpoint-${var.project_name}"
    }
  }
}

output "rollback_lambda_name" {
  value = aws_lambda_function.rollback_lambda.function_name
}