import boto3
import logging
import os
import json
from datetime import date, datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def json_serial(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))


REGION = os.environ.get("AWS_REGION", "eu-north-1")
sm = boto3.client("sagemaker", region_name=REGION)


def lambda_handler(event, context):
    logger.info(f"🌍 Connecting to SageMaker in region: {REGION}")

    endpoint_name = os.environ.get("ENDPOINT_NAME")
    if not endpoint_name:
        endpoint_name = event.get("endpoint_name")

    if not endpoint_name:
        raise ValueError("ENDPOINT_NAME must be provided")

    logger.info(f"🔄 Attempting manual rollback for endpoint: {endpoint_name}")

    try:
        logger.info("Step 1: Describing endpoint...")
        response = sm.describe_endpoint(EndpointName=endpoint_name)
        current_config_name = response["EndpointConfigName"]
        logger.info(f"📍 Current active config: {current_config_name}")

        logger.info("Step 2: Listing endpoint configurations...")

        history = sm.list_endpoint_configs(
            SortBy="CreationTime",
            SortOrder="Descending",
            MaxResults=50
        )

        logger.info(f"AWS Raw Response keys: {history.keys()}")
        configs = history.get("EndpointConfigs", [])
        logger.info(f"📊 Found {len(configs)} configurations in account.")

        if not configs:
            logger.error(f"FULL AWS RESPONSE: {json.dumps(history, default=json_serial)}")
            raise Exception(f"No endpoint configurations found in region {REGION}! Please check region settings.")

        previous_config_name = None

        for config in configs:
            name = config["EndpointConfigName"]
            if len(configs) > 0 and config == configs[0]:
                logger.info(f"Latest candidate: {name}")

            if name != current_config_name:
                previous_config_name = name
                logger.info(f"✅ Found previous candidate: {name}")
                break

        if not previous_config_name:
            all_names = [c["EndpointConfigName"] for c in configs]
            logger.error(f"Available configs: {all_names}")
            raise Exception(f"Could not find any previous configuration distinct from {current_config_name}")

        logger.info(f"🔙 Rolling back to: {previous_config_name}")

        sm.update_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=previous_config_name
        )

        return {
            "statusCode": 200,
            "body": f"Rollback started. Switched from {current_config_name} to {previous_config_name}"
        }

    except Exception as e:
        logger.error(f"❌ Rollback failed: {e}")
        raise e