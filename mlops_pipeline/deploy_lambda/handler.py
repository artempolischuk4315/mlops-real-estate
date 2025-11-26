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

        latest_arn = packages[0]["ModelPackageArn"]
        logger.info(f"Found latest approved model: {latest_arn}")
        return latest_arn

    except Exception as e:
        logger.error(f"Failed to list model packages: {e}")
        return None


def lambda_handler(event, context):
    logger.info(f"Received event: {event}")

    model_package_arn = event.get("model_package_arn")
    endpoint_name = event.get("endpoint_name")
    role_arn = event.get("role_arn")

    project_name = os.environ.get("PROJECT_NAME", "mlops-real-estate")
    model_group_name = os.environ.get("MODEL_PACKAGE_GROUP_NAME", f"RealEstateModelGroup-{project_name}")

    if not model_package_arn:
        logger.info("model_package_arn not provided. Searching Registry...")
        model_package_arn = get_latest_approved_model_package(model_group_name)

        if not model_package_arn:
            raise ValueError("Could not find any Approved model in Registry to deploy.")

    if not endpoint_name or not role_arn:
        raise ValueError(f"Missing required parameters. Endpoint: {endpoint_name}, Role: {role_arn}")
    # ---------------------------

    timestamp = int(time.time())
    model_name = f"model-{timestamp}"
    config_name = f"config-{timestamp}"

    # 1. Create Model
    logger.info(f"Creating Model: {model_name}")
    sm.create_model(
        ModelName=model_name,
        PrimaryContainer={"ModelPackageName": model_package_arn},
        ExecutionRoleArn=role_arn
    )

    # 2. Create Endpoint Config
    logger.info(f"Creating Config: {config_name}")
    sm.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[{
            "VariantName": "AllTraffic",
            "ModelName": model_name,
            "InitialInstanceCount": 1,
            "InstanceType": "ml.m5.large"
        }]
    )

    # 3. Update or Create Endpoint
    try:
        endpoint = sm.describe_endpoint(EndpointName=endpoint_name)
        status = endpoint["EndpointStatus"]
        logger.info(f"Endpoint status: {status}")

        if status == "InService":
            # AutoRollbackConfiguration
            alarm_name = f"HighErrorRate-{project_name}"

            sm.update_endpoint(
                EndpointName=endpoint_name,
                EndpointConfigName=config_name,
                DeploymentConfig={
                    "BlueGreenUpdatePolicy": {
                        "TrafficRoutingConfiguration": {
                            "Type": "ALL_AT_ONCE",
                            "WaitIntervalInSeconds": 300  # 5 mins
                        },
                        "TerminationWaitInSeconds": 60,
                        "MaximumExecutionTimeoutInSeconds": 1800
                    },
                    "AutoRollbackConfiguration": {
                        "Alarms": [{"AlarmName": alarm_name}]
                    }
                }
            )
            return {"status": "updating", "model": model_package_arn}

        elif status in ["Failed", "OutOfService"]:
            logger.warning("Endpoint is broken. Recreating...")
            sm.delete_endpoint(EndpointName=endpoint_name)
            time.sleep(20)
            sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)
            return {"status": "recreating"}

    except sm.exceptions.ClientError:
        logger.info("Endpoint not found. Creating new...")
        sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)
        return {"status": "creating"}

    return {"status": "unknown"}