import boto3
import os
import json
import logging
import uuid
import time
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

runtime_client = boto3.client('sagemaker-runtime')
s3_client = boto3.client('s3')
cw_client = boto3.client('cloudwatch')

ENDPOINT_NAME = os.environ.get('ENDPOINT_NAME')
MONITORING_BUCKET = os.environ.get('MONITORING_BUCKET')
MONITORING_PREFIX = os.environ.get('MONITORING_PREFIX', 'monitoring/predictions/')
METRICS_NAMESPACE = "RealEstate/Inference"


def log_payload_to_s3(features, prediction, request_id):
    if not MONITORING_BUCKET:
        logger.warning("MONITORING_BUCKET not set. Skipping S3 logging.")
        return

    try:
        timestamp = datetime.utcnow().isoformat()
        log_data = {
            "uuid": request_id,
            "timestamp": timestamp,
            "features": features,
            "prediction": prediction
        }

        date_str = datetime.utcnow().date().isoformat()
        s3_key = f"{MONITORING_PREFIX}{date_str}/{request_id}.json"

        s3_client.put_object(
            Bucket=MONITORING_BUCKET,
            Key=s3_key,
            Body=json.dumps(log_data),
            ContentType='application/json'
        )
        logger.info(f"Logged prediction to s3://{MONITORING_BUCKET}/{s3_key}")

    except Exception as e:
        logger.error(f"Failed to log to S3: {str(e)}")


def push_metrics_to_cw(latency_ms, prediction_value):
    try:
        if not ENDPOINT_NAME:
            return

        val = 0.0
        if isinstance(prediction_value, list):
            if len(prediction_value) > 0:
                v = prediction_value[0]
                val = v[0] if isinstance(v, list) else v
        else:
            val = float(prediction_value)

        cw_client.put_metric_data(
            Namespace=METRICS_NAMESPACE,
            MetricData=[
                {
                    'MetricName': 'Latency',
                    'Dimensions': [{'Name': 'EndpointName', 'Value': ENDPOINT_NAME}],
                    'Value': latency_ms,
                    'Unit': 'Milliseconds'
                },
                {
                    'MetricName': 'RequestCount',
                    'Dimensions': [{'Name': 'EndpointName', 'Value': ENDPOINT_NAME}],
                    'Value': 1,
                    'Unit': 'Count'
                },
                {
                    'MetricName': 'AveragePrediction',
                    'Dimensions': [{'Name': 'EndpointName', 'Value': ENDPOINT_NAME}],
                    'Value': float(val),
                    'Unit': 'Count'
                }
            ]
        )
    except Exception as e:
        logger.error(f"Failed to push metrics to CloudWatch: {e}")


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    request_id = str(uuid.uuid4())

    try:
        if 'body' in event:
            payload = json.loads(event['body'])
        else:
            payload = event

        if isinstance(payload, dict) and "data" not in payload:
            pass

    except Exception as e:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Invalid JSON format: {str(e)}'})
        }

    try:
        if not ENDPOINT_NAME:
            raise ValueError("ENDPOINT_NAME environment variable is not set.")

        start_time = time.time()

        response = runtime_client.invoke_endpoint(
            EndpointName=ENDPOINT_NAME,
            ContentType='application/json',
            Body=json.dumps(payload)
        )

        latency = (time.time() - start_time) * 1000

        result_body = response['Body'].read().decode('utf-8')
        result_json = json.loads(result_body)

        prediction = result_json.get('predictions', result_json)

        log_payload_to_s3(payload, prediction, request_id)

        push_metrics_to_cw(latency, prediction)

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'request_id': request_id,
                'prediction': prediction
            })
        }

    except Exception as e:
        logger.error(f"Error invoking endpoint: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }