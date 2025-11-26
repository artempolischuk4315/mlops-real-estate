import boto3
import time
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sm = boto3.client("sagemaker")


def lambda_handler(event, context):
    logger.info(f"Received event: {event}")

    model_package_arn = event.get("model_package_arn")
    endpoint_name = event.get("endpoint_name")
    role_arn = event.get("role_arn")

    if not model_package_arn or not endpoint_name:
        raise ValueError("Missing parameters")

    timestamp = int(time.time())
    model_name = f"pipeline-model-{timestamp}"
    config_name = f"pipeline-config-{timestamp}"

    # 1. Create Model object
    logger.info(f"Creating Model: {model_name}")
    sm.create_model(
        ModelName=model_name,
        PrimaryContainer={"ModelPackageName": model_package_arn,
                          "Environment": {
                              "SAGEMAKER_PROGRAM": "inference.py"
                          }
                        },
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

    # 3. Check Endpoint Status
    try:
        response = sm.describe_endpoint(EndpointName=endpoint_name)
        status = response["EndpointStatus"]
        logger.info(f"Endpoint '{endpoint_name}' exists. Status: {status}")

        if status == "InService":
            logger.info("Updating endpoint...")
            sm.update_endpoint(
                EndpointName=endpoint_name,
                EndpointConfigName=config_name
            )
            return {"status": "updating", "endpoint": endpoint_name}

        elif status in ["Failed", "OutOfService"]:
            logger.warning(f"Endpoint is in {status} state. Deleting and recreating...")
            sm.delete_endpoint(EndpointName=endpoint_name)
            time.sleep(20)
            sm.create_endpoint(
                EndpointName=endpoint_name,
                EndpointConfigName=config_name
            )
            return {"status": "recreating", "endpoint": endpoint_name}

        elif status in ["Creating", "Updating", "SystemUpdating"]:
            logger.warning("Endpoint is busy. Cannot update now.")
            raise Exception(f"Endpoint is busy ({status}). Please try again later.")

    except sm.exceptions.ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ValidationException' and "Could not find endpoint" in e.response['Error']['Message']:
            logger.info(f"Endpoint not found. Creating new: {endpoint_name}")
            sm.create_endpoint(
                EndpointName=endpoint_name,
                EndpointConfigName=config_name
            )
            return {"status": "creating", "endpoint": endpoint_name}
        else:
            logger.error(f"Unexpected error: {e}")
            raise e

    return {"status": "done"}
