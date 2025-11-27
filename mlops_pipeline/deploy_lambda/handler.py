import boto3
import time
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sm = boto3.client("sagemaker")


def get_latest_approved_model_package(model_package_group_name):
    try:
        response = sm.list_model_packages(
            ModelPackageGroupName=model_package_group_name,
            ModelApprovalStatus='Approved',
            SortBy='CreationTime',
            SortOrder='Descending',
            MaxResults=1
        )
        packages = response.get("ModelPackageSummaryList", [])
        if not packages:
            logger.error(f"No approved models found in group: {model_package_group_name}")
            return None

        return packages[0]["ModelPackageArn"]
    except Exception as e:
        logger.error(f"Failed to list model packages: {e}")
        return None


def lambda_handler(event, context):
    logger.info(f"Received event: {event}")

    passed_model_arn = event.get("model_package_arn")  # If present -  Deploy, if None - HealthCheck
    endpoint_name = event.get("endpoint_name")
    role_arn = event.get("role_arn")

    project_name = os.environ.get("PROJECT_NAME", "mlops-real-estate")
    model_group_name = os.environ.get("MODEL_PACKAGE_GROUP_NAME", f"RealEstateModelGroup-{project_name}")

    if not endpoint_name or not role_arn:
        raise ValueError("Missing endpoint_name or role_arn")

    current_status = "NotFound"
    try:
        resp = sm.describe_endpoint(EndpointName=endpoint_name)
        current_status = resp["EndpointStatus"]
        logger.info(f"Current Endpoint Status: {current_status}")
    except sm.exceptions.ClientError:
        logger.info("Endpoint not found.")

    if not passed_model_arn and current_status == "InService":
        logger.info("✅ HealthCheck: Endpoint is InService. No action needed.")
        return {"status": "healthy", "action": "none"}

    if current_status in ["Creating", "Updating", "SystemUpdating", "RollingBack"]:
        logger.info(f"⚠️ HealthCheck: Endpoint is busy ({current_status}). Skipping.")
        return {"status": "busy", "action": "skipped"}

    target_model_arn = passed_model_arn

    if not target_model_arn:
        logger.info("HealthCheck: Endpoint needs repair. Searching for latest Approved model...")
        target_model_arn = get_latest_approved_model_package(model_group_name)
        if not target_model_arn:
            raise ValueError("Cannot repair endpoint: No approved model found in Registry.")

    timestamp = int(time.time())
    model_name = f"model-{timestamp}"
    config_name = f"config-{timestamp}"

    logger.info(f"Creating SageMaker Model: {model_name}")
    sm.create_model(
        ModelName=model_name,
        PrimaryContainer={"ModelPackageName": target_model_arn},
        ExecutionRoleArn=role_arn
    )

    logger.info(f"Creating Endpoint Config: {config_name}")
    sm.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[{
            "VariantName": "AllTraffic",
            "ModelName": model_name,
            "InitialInstanceCount": 1,
            "InstanceType": "ml.m5.large"
        }]
    )

    alarm_name = f"HighErrorRate-{project_name}"
    deployment_config = {
        "BlueGreenUpdatePolicy": {
            "TrafficRoutingConfiguration": {
                "Type": "ALL_AT_ONCE",
                "WaitIntervalInSeconds": 300
            },
            "TerminationWaitInSeconds": 60,
            "MaximumExecutionTimeoutInSeconds": 1800
        },
        "AutoRollbackConfiguration": {
            "Alarms": [{"AlarmName": alarm_name}]
        }
    }

    if current_status == "InService":
        logger.info("🚀 Starting Deployment (Update)...")
        sm.update_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=config_name,
            DeploymentConfig=deployment_config
        )
        return {"status": "updating", "action": "deploy"}

    elif current_status in ["Failed", "OutOfService"]:
        logger.warning("🚑 Repairing Broken Endpoint (Delete & Create)...")
        sm.delete_endpoint(EndpointName=endpoint_name)
        time.sleep(20)  # Чекаємо видалення
        sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)
        return {"status": "recreating", "action": "repair"}

    else:  # NotFound
        logger.info("✨ Creating New Endpoint...")
        sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)
        return {"status": "creating", "action": "create"}