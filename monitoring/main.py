import os
import io
import json
import logging
from datetime import date, timedelta

import boto3
import pandas as pd
from evidently.report import Report
from evidently.metric_preset import DataDriftPreset
from evidently.pipeline.column_mapping import ColumnMapping

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

BUCKET = os.environ["MONITORING_BUCKET"]
REF_KEY = os.environ.get("REFERENCE_KEY", "monitoring/reference/reference_data.csv")
PREDICTIONS_PREFIX = os.environ.get("MONITORING_PREFIX", "monitoring/predictions/")
REPORT_PREFIX = os.environ.get("REPORT_PREFIX", "monitoring/reports/")

ENDPOINT_NAME = os.environ.get("ENDPOINT_NAME", "real-estate-endpoint")

FEATURE_COLUMNS = [
    "X1 transaction date",
    "X2 house age",
    "X3 distance to the nearest MRT station",
    "X4 number of convenience stores",
    "X5 latitude",
    "X6 longitude"
]
TARGET_COLUMN = "Y house price of unit area"
PREDICTION_COLUMN = "prediction"


def read_reference_df() -> pd.DataFrame:
    logger.info(f"Reading reference data from: {REF_KEY}")
    obj = s3.get_object(Bucket=BUCKET, Key=REF_KEY)
    return pd.read_csv(obj["Body"])


def read_current_df(target_date: date) -> pd.DataFrame:
    prefix = f"{PREDICTIONS_PREFIX}{target_date}/"
    logger.info(f"Scanning S3 prefix: {prefix}")

    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=BUCKET, Prefix=prefix)

    records = []
    for page in pages:
        if "Contents" not in page:
            continue
        for obj_meta in page["Contents"]:
            key = obj_meta["Key"]
            if key.endswith("/"): continue
            try:
                response = s3.get_object(Bucket=BUCKET, Key=key)
                body = response["Body"].read().decode("utf-8")
                record = json.loads(body)
                records.append(record)
            except Exception as e:
                logger.error(f"Error reading file {key}: {e}")
                continue

    logger.info(f"Parsed {len(records)} records")
    if not records:
        return pd.DataFrame()

    rows = []
    for rec in records:

        feats_raw = rec.get("features", [])

        if isinstance(feats_raw, dict) and "data" in feats_raw:
            feats_raw = feats_raw["data"]

        final_features = []
        if isinstance(feats_raw, list):
            if len(feats_raw) > 0 and isinstance(feats_raw[0], list):
                final_features = feats_raw[0]  # Розпаковуємо вкладений список
            else:
                final_features = feats_raw
        else:
            logger.warning(f"Unexpected features format: {feats_raw}")
            continue

        row = {f"temp_{i}": v for i, v in enumerate(final_features)}

        pred = rec.get("prediction")
        if isinstance(pred, list):
            if len(pred) > 0:
                val = pred[0]
                if isinstance(val, list) and len(val) > 0:
                    pred = val[0]
                else:
                    pred = val

        row[PREDICTION_COLUMN] = pred
        rows.append(row)

    df = pd.DataFrame(rows)

    temp_cols = sorted([c for c in df.columns if c.startswith("temp_")])

    rename_map = {}
    for i, col_name in enumerate(temp_cols):
        if i < len(FEATURE_COLUMNS):
            rename_map[col_name] = FEATURE_COLUMNS[i]

    df.rename(columns=rename_map, inplace=True)

    return df


def lambda_handler(event, context):
    logger.info("--- STARTING MONITORING (WITH CLOUDWATCH METRICS) ---")

    target_date = date.today() - timedelta(days=1)
    if event.get("force_today"):
        target_date = date.today()

    reference = read_reference_df()
    current = read_current_df(target_date)

    if current.empty:
        return {"statusCode": 200, "body": json.dumps({"message": "No data found"})}

    if PREDICTION_COLUMN not in reference.columns:
        logger.info("Adding artificial prediction column to reference")
        reference[PREDICTION_COLUMN] = reference[TARGET_COLUMN]

    common_cols = list(set(reference.columns) & set(current.columns))
    reference = reference[common_cols]
    current = current[common_cols]

    actual_features = [c for c in FEATURE_COLUMNS if c in current.columns]

    mapping = ColumnMapping()
    mapping.numerical_features = actual_features
    mapping.prediction = PREDICTION_COLUMN if PREDICTION_COLUMN in current.columns else None
    mapping.target = None

    logger.info(f"Reference columns: {reference.columns.tolist()}")
    logger.info(f"Current columns: {current.columns.tolist()}")

    report = Report(metrics=[DataDriftPreset()])

    report.run(
        reference_data=reference,
        current_data=current,
        column_mapping=mapping
    )

    # Save HTML to S3
    html_buffer = io.StringIO()
    report.save_html(html_buffer)
    html_key = f"{REPORT_PREFIX}data_drift_report_{target_date.isoformat()}.html"

    s3.put_object(
        Bucket=BUCKET,
        Key=html_key,
        Body=html_buffer.getvalue().encode("utf-8"),
        ContentType="text/html"
    )

    # Extract Metrics & Save JSON
    json_result = report.as_dict()

    dataset_drift = False
    drift_score = 0.0

    try:
        metrics = json_result["metrics"][0]["result"]
        dataset_drift = metrics["dataset_drift"]
        drift_score = metrics["share_of_drifted_features"]
    except Exception as e:
        logger.error(f"Error parsing drift metrics: {e}")
        # Не перериваємо роботу, але ставимо 0
        dataset_drift = False
        drift_score = 0.0

    result_key = f"{REPORT_PREFIX}data_drift_result_{target_date.isoformat()}.json"
    s3.put_object(
        Bucket=BUCKET,
        Key=result_key,
        Body=json.dumps({
            "target_date": target_date.isoformat(),
            "dataset_drift": dataset_drift,
            "drift_score": drift_score,
            "raw": json_result
        }).encode("utf-8"),
        ContentType="application/json"
    )

    try:
        logger.info(f"Pushing metrics to CloudWatch: DriftDetected={dataset_drift}, DriftScore={drift_score}")

        cloudwatch = boto3.client('cloudwatch')

        cloudwatch.put_metric_data(
            Namespace='MLOps/RealEstate',
            MetricData=[
                {
                    'MetricName': 'DriftScore',
                    'Dimensions': [
                        {
                            'Name': 'EndpointName',
                            'Value': ENDPOINT_NAME
                        },
                    ],
                    'Value': drift_score,
                    'Unit': 'None'
                },
                {
                    'MetricName': 'DatasetDriftDetected',
                    'Dimensions': [
                        {
                            'Name': 'EndpointName',
                            'Value': ENDPOINT_NAME
                        },
                    ],
                    'Value': 1 if dataset_drift else 0,
                    'Unit': 'Count'
                }
            ]
        )
        logger.info("Successfully pushed metrics to CloudWatch")

    except Exception as e:
        logger.error(f"Failed to push metrics to CloudWatch: {e}")
        raise e

    return {
        "statusCode": 200,
        "body": json.dumps({
            "drift": dataset_drift,
            "drift_score": drift_score,
            "report": html_key
        })
    }