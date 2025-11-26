# ==========================================
# 1. IAM ROLES (SageMaker & Deployment)
# ==========================================

resource "aws_iam_role" "sagemaker_execution_role" {
  name = "SageMakerExecutionRole-${var.project_name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "sagemaker.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_full_access" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy_attachment" "sagemaker_s3_access" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role" "lambda_deployment_role" {
  name = "LambdaDeploymentRole-${var.project_name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "deployment_sagemaker_access" {
  role       = aws_iam_role.lambda_deployment_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy_attachment" "deployment_logs_access" {
  role       = aws_iam_role.lambda_deployment_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ==========================================
# 2. ECR & DOCKER BUILD
# ==========================================

resource "aws_ecr_repository" "training_repo" {
  name         = "sagemaker-custom-training-${var.project_name}"
  force_delete = true
}

# ==========================================
# 3. PIPELINE DEPLOY HELPER
# ==========================================

data "archive_file" "deploy_lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../mlops_pipeline/deploy_lambda"
  output_path = "${path.module}/deploy_lambda.zip"
}

resource "aws_lambda_function" "pipeline_deploy_helper" {
  function_name    = "PipelineDeployHelper-${var.project_name}"
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  role             = aws_iam_role.lambda_deployment_role.arn # Тепер ця роль оголошена вище!
  filename         = data.archive_file.deploy_lambda_zip.output_path
  source_code_hash = data.archive_file.deploy_lambda_zip.output_base64sha256
  timeout          = 60

  environment {
    variables = {
      PROJECT_NAME             = var.project_name
      MODEL_PACKAGE_GROUP_NAME = aws_sagemaker_model_package_group.model_group.model_package_group_name
    }
  }
}

# ==========================================
# 4. OTHER RESOURCES
# ==========================================

resource "aws_sagemaker_model_package_group" "model_group" {
  model_package_group_name = "RealEstateModelGroup-${var.project_name}"
}

data "archive_file" "sagemaker_source_code" {
  type        = "tar.gz"
  source_dir  = "${path.module}/../mlops_pipeline/scripts"
  output_path = "${path.module}/sourcedir.tar.gz"
}

resource "aws_s3_object" "sagemaker_code_upload" {
  bucket = aws_s3_bucket.target_bucket.id
  key    = "code/sourcedir.tar.gz"
  source = data.archive_file.sagemaker_source_code.output_path
  etag   = data.archive_file.sagemaker_source_code.output_md5
}

resource "null_resource" "install_sagemaker" {
  provisioner "local-exec" {
    command = "pip install --upgrade sagemaker"
  }
}

# Rule: Healthcheck every 2 minutes
resource "aws_cloudwatch_event_rule" "health_check" {
  name                = "EndpointHealthCheck"
  schedule_expression = "rate(2 minutes)"
}

resource "aws_cloudwatch_event_target" "heal_endpoint" {
  rule      = aws_cloudwatch_event_rule.health_check.name
  target_id = "HealEndpoint"
  arn       = aws_lambda_function.pipeline_deploy_helper.arn

  input = jsonencode({
     "endpoint_name": "real-estate-endpoint-${var.project_name}",
     # Тут треба вказати ARN моделі. Оскільки це складно отримати динамічно в Cron,
     # краще щоб Lambda сама шукала останню 'Approved' модель в Registry.
     # Але для спрощення можна передати фіксовану назву, якщо вона є.
     "role_arn": aws_iam_role.sagemaker_execution_role.arn
  })
}

data "external" "pipeline_definition" {
  program = [
    "python3",
    "${path.module}/../mlops_pipeline/pipeline.py",
    aws_iam_role.sagemaker_execution_role.arn,
    aws_s3_bucket.target_bucket.id,
    aws_lambda_function.pipeline_deploy_helper.arn,
    var.project_name,
    "http://${aws_lb.mlflow_lb.dns_name}",
    # ЗМІНА ТУТ: Використовуємо var.image_tag замість latest
    "${aws_ecr_repository.training_repo.repository_url}:${var.image_tag}",
    "s3://${aws_s3_bucket.target_bucket.id}/code/sourcedir.tar.gz"
  ]
  depends_on = [null_resource.install_sagemaker]
}

resource "aws_sagemaker_pipeline" "mlops_pipeline" {
  pipeline_name         = "RealEstatePipeline-${var.project_name}"
  pipeline_display_name = "real-estate-pipeline"
  role_arn              = aws_iam_role.sagemaker_execution_role.arn
  pipeline_definition   = data.external.pipeline_definition.result.definition
}

# ==========================================
# 5. S3 Trigger
# ==========================================

data "archive_file" "pipeline_trigger_zip" {
  type        = "zip"
  output_path = "${path.module}/pipeline_trigger.zip"
  source {
    content  = <<EOF
import boto3
import os
import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
sm = boto3.client("sagemaker")
PIPELINE_NAME = os.environ["PIPELINE_NAME"]
def lambda_handler(event, context):
    logger.info(f"Event: {event}")
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']
    input_data_uri = f"s3://{bucket}/{key}"
    response = sm.start_pipeline_execution(
        PipelineName=PIPELINE_NAME,
        PipelineExecutionDisplayName=f"Triggered-by-S3-Upload",
        PipelineParameters=[{'Name': 'InputData', 'Value': input_data_uri}]
    )
    return {"status": "started", "arn": response["PipelineExecutionArn"]}
EOF
    filename = "main.py"
  }
}

resource "aws_iam_policy" "sagemaker_invoke_lambda_policy" {
  name = "SageMakerInvokeLambdaPolicy-${var.project_name}"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = "lambda:InvokeFunction",
        Resource = aws_lambda_function.pipeline_deploy_helper.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_invoke_lambda_attach" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = aws_iam_policy.sagemaker_invoke_lambda_policy.arn
}

resource "aws_lambda_function" "pipeline_trigger" {
  function_name    = "PipelineTriggerLambda-${var.project_name}"
  handler          = "main.lambda_handler"
  runtime          = "python3.11"
  role             = aws_iam_role.lambda_deployment_role.arn
  filename         = data.archive_file.pipeline_trigger_zip.output_path
  source_code_hash = data.archive_file.pipeline_trigger_zip.output_base64sha256
  environment {
    variables = {
      PIPELINE_NAME = aws_sagemaker_pipeline.mlops_pipeline.pipeline_name
    }
  }
}

resource "aws_lambda_permission" "allow_s3_pipeline_trigger" {
  statement_id  = "AllowS3ToTriggerPipeline"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pipeline_trigger.arn
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.source_bucket.arn
}

resource "aws_s3_bucket_notification" "pipeline_trigger_notification" {
  bucket = aws_s3_bucket.source_bucket.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.pipeline_trigger.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "seed/"
    filter_suffix       = ".csv"
  }
  depends_on = [aws_lambda_permission.allow_s3_pipeline_trigger]
}