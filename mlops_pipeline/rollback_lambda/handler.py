import boto3
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sm = boto3.client("sagemaker")

def lambda_handler(event, context):
    endpoint_name = os.environ.get("ENDPOINT_NAME")
    if not endpoint_name:
        endpoint_name = event.get("endpoint_name")

    if not endpoint_name:
        raise ValueError("ENDPOINT_NAME must be provided either via env var or event")

    logger.info(f"Attempting manual rollback for endpoint: {endpoint_name}")

    try:
        response = sm.describe_endpoint(EndpointName=endpoint_name)
        current_config_name = response["EndpointConfigName"]
        logger.info(f"Current config: {current_config_name}")

        history = sm.list_endpoint_configs(
            SortBy="CreationTime",
            SortOrder="Descending",
            NameContains="config",
            MaxResults=5
        )

        previous_config_name = None
        for config in history["EndpointConfigSummaryList"]:
            if config["EndpointConfigName"] != current_config_name:
                previous_config_name = config["EndpointConfigName"]
                break

        if not previous_config_name:
            raise Exception("No previous configuration found! Cannot rollback.")

        logger.info(f"Found previous config: {previous_config_name}. Rolling back...")

        sm.update_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=previous_config_name
        )

        return {
            "statusCode": 200,
            "body": f"Rollback started. Switched from {current_config_name} to {previous_config_name}"
        }

    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        raise e