import sys
import os
import json
import argparse
import tarfile
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))

import pandas as pd
import joblib
import mlflow
from mlflow.tracking import MlflowClient
from sklearn.metrics import mean_squared_error

FEATURE_COLUMNS = ["X1 transaction date", "X2 house age", "X3 distance to the nearest MRT station",
                   "X4 number of convenience stores", "X5 latitude", "X6 longitude"]
TARGET = "Y house price of unit area"

if __name__ == "__main__":
    logger.info("--- Starting Evaluation Script ---")

    parser = argparse.ArgumentParser()
    parser.add_argument("--test-data", type=str, default="/opt/ml/processing/test")
    parser.add_argument("--model-path", type=str, default="/opt/ml/processing/model")
    args = parser.parse_args()

    # 1. Setup MLflow
    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI")
    logger.info(f"Connecting to MLflow URI: {mlflow_uri}")

    if not mlflow_uri:
        logger.error("MLFLOW_TRACKING_URI is not set!")
        sys.exit(1)

    mlflow.set_tracking_uri(mlflow_uri)
    client = MlflowClient()

    # 2. Load Model
    logger.info(f"Extracting model from {args.model_path}")
    model_tar = os.path.join(args.model_path, "model.tar.gz")

    try:
        with tarfile.open(model_tar) as tar:
            tar.extractall(path=".")
        logger.info("Model extracted successfully.")

        model = joblib.load("model.pkl")
        logger.info("Model loaded into memory.")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        sys.exit(1)

    # 3. Get Parent Run ID
    parent_run_id = None
    if os.path.exists("run_id.txt"):
        with open("run_id.txt", "r") as f:
            parent_run_id = f.read().strip()
        logger.info(f"Found Parent Run ID from training: {parent_run_id}")
    else:
        logger.warning("run_id.txt not found! Metrics will not be attached to the training run.")

    # 4. Load Data
    test_file = os.path.join(args.test_data, "test.csv")
    logger.info(f"Reading test data from {test_file}")

    try:
        df = pd.read_csv(test_file, header=None)
        logger.info(f"Data loaded. Shape: {df.shape}")

        if df.shape[1] == len(FEATURE_COLUMNS) + 1:
            df.columns = FEATURE_COLUMNS + [TARGET]
        else:
            logger.warning(f"Unexpected column count: {df.shape[1]}. Expected {len(FEATURE_COLUMNS) + 1}")
            df.columns = FEATURE_COLUMNS + [TARGET]

        X_test = df[FEATURE_COLUMNS]
        y_test = df[TARGET]
    except Exception as e:
        logger.error(f"Failed to load/parse test data: {e}")
        sys.exit(1)

    # 5. Calculate Metrics
    logger.info("Predicting on test set...")
    preds = model.predict(X_test)
    test_rmse = mean_squared_error(y_test, preds, squared=False)
    logger.info(f"🆕 Challenger RMSE (Test): {test_rmse}")

    # 6. Log to MLflow
    if parent_run_id:
        try:
            logger.info(f"Logging 'test_rmse' to run {parent_run_id}...")
            client.log_metric(parent_run_id, "test_rmse", test_rmse)
            client.log_metric(parent_run_id, "rmse", test_rmse)
            client.set_tag(parent_run_id, "evaluation_stage", "completed")
            logger.info("Metrics logged successfully.")
        except Exception as e:
            logger.error(f"Error logging to MLflow: {e}")

    # 7. Compare with Production
    prod_rmse = float("inf")
    try:
        logger.info("Fetching Production model metrics...")
        prod_model = client.get_model_version_by_alias("RealEstateModel", "Production")
        prod_run = client.get_run(prod_model.run_id)

        prod_rmse = prod_run.data.metrics.get("test_rmse", prod_run.data.metrics.get("rmse", float("inf")))
        logger.info(f"🏆 Champion (Prod) RMSE: {prod_rmse}")
    except Exception as e:
        logger.warning(f"No production model found or error fetching metrics: {e}")
        logger.info("Assuming Challenger is better (First run).")

    # Logic
    is_better = 1.0 if test_rmse < prod_rmse else 0.0

    if is_better:
        logger.info("✅ DECISION: New model is BETTER! (Passing to ConditionStep)")
    else:
        logger.info("❌ DECISION: New model is WORSE. (Will skip deployment)")

    # 8. Report for SageMaker ConditionStep
    report = {"metrics": {"rmse": {"value": test_rmse}, "is_better": {"value": is_better}}}

    output_dir = "/opt/ml/processing/evaluation"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "evaluation.json")

    with open(output_path, "w") as f:
        json.dump(report, f)

    logger.info(f"Evaluation report saved to {output_path}")