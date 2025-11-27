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

resource "aws_iam_policy" "lambda_registry_access" {
  name = "LambdaModelRegistryAccess-${var.project_name}"
  description = "Allows Lambda to list and describe models in Registry"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Action = [
        "sagemaker:ListModelPackages",
        "sagemaker:DescribeModelPackage",
        "sagemaker:ListModelPackageGroups"
      ],
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "registry_access_attach" {
  role       = aws_iam_role.lambda_deployment_role.name
  policy_arn = aws_iam_policy.lambda_registry_access.arn
}
# ---------------------------------------------

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
  role             = aws_iam_role.lambda_deployment_role.arn
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

# --- EventBridge Health Check ---
resource "aws_cloudwatch_event_rule" "health_check" {
  name                = "EndpointHealthCheck"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "heal_endpoint" {
  rule      = aws_cloudwatch_event_rule.health_check.name
  target_id = "HealEndpoint"
  arn       = aws_lambda_function.pipeline_deploy_helper.arn

  input = jsonencode({
     "endpoint_name": "real-estate-endpoint-${var.project_name}",
     "role_arn": aws_iam_role.sagemaker_execution_role.arn
  })
}

# --- Permission for EventBridge to Call Lambda ---
resource "aws_lambda_permission" "allow_health_check_trigger" {
  statement_id  = "AllowHealthCheckInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pipeline_deploy_helper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.health_check.arn
}
# -----------------------------------------------------

data "external" "pipeline_definition" {
  program = [
    "python3",
    "${path.module}/../mlops_pipeline/pipeline.py",
    aws_iam_role.sagemaker_execution_role.arn,
    aws_s3_bucket.target_bucket.id,
    aws_lambda_function.pipeline_deploy_helper.arn,
    var.project_name,
    "http://${aws_lb.mlflow_lb.dns_name}",
    "${aws_ecr_repository.training_repo.repository_url}:${var.image_tag}",
    "s3://${aws_s3_bucket.target_bucket.id}/code/sourcedir.tar.gz"
  ]
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

# --- Weekly Retrain Schedule ---
resource "aws_cloudwatch_event_rule" "weekly_retrain" {
  name                = "WeeklyRetrainTrigger-${var.project_name}"
  schedule_expression = "cron(0 0 ? * MON *)"
}

resource "aws_cloudwatch_event_target" "trigger_pipeline_weekly" {
  rule      = aws_cloudwatch_event_rule.weekly_retrain.name
  target_id = "TriggerPipelineWeekly"
  arn       = aws_lambda_function.pipeline_trigger.arn

  input = jsonencode({
    "Records": [{
      "s3": {
        "bucket": { "name": aws_s3_bucket.source_bucket.id },
        "object": { "key": "seed/real_estate.csv" }
      }
    }]
  })
}

resource "aws_lambda_permission" "allow_weekly_trigger" {
  statement_id  = "AllowWeeklyEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pipeline_trigger.arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_retrain.arn
}