import sys
import os
import glob
import argparse
import joblib
import shutil

import pandas as pd
import mlflow
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

FEATURE_COLUMNS = ["X1 transaction date", "X2 house age", "X3 distance to the nearest MRT station",
                   "X4 number of convenience stores", "X5 latitude", "X6 longitude"]
TARGET = "Y house price of unit area"

if __name__ == "__main__":
    print(f"Training script started. Python: {sys.version}")

    parser = argparse.ArgumentParser()
    parser.add_argument("--train-data", type=str, default=os.environ.get("SM_CHANNEL_TRAIN"))
    parser.add_argument("--model-dir", type=str, default=os.environ.get("SM_MODEL_DIR"))
    args = parser.parse_args()

    # Setup MLflow
    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI")
    experiment_name = os.environ.get("MLFLOW_EXPERIMENT_NAME", "Default_Exp")

    if mlflow_uri:
        print(f"Connecting to MLflow: {mlflow_uri}")
        mlflow.set_tracking_uri(mlflow_uri)
        mlflow.set_experiment(experiment_name)

    # Load Data
    input_files = glob.glob(os.path.join(args.train_data, "*.csv"))
    if not input_files: raise ValueError("No CSV files")

    df = pd.read_csv(input_files[0], header=None)

    # Fix Columns
    expected_cols = len(FEATURE_COLUMNS) + 1
    if df.shape[1] == expected_cols:
        df.columns = FEATURE_COLUMNS + [TARGET]
    elif df.shape[1] == expected_cols + 1:
        df = df.iloc[:, 1:]
        df.columns = FEATURE_COLUMNS + [TARGET]
    else:
        raise ValueError(f"Bad columns: {df.shape[1]}")

    X_train = df[FEATURE_COLUMNS]
    y_train = df[TARGET]

    # Train
    with mlflow.start_run() as run:
        print(f"MLflow Run ID: {run.info.run_id}")

        # Save Run ID
        with open(os.path.join(args.model_dir, "run_id.txt"), "w") as f:
            f.write(run.info.run_id)

        model = LinearRegression()
        model.fit(X_train, y_train)

        preds = model.predict(X_train)
        rmse = mean_squared_error(y_train, preds, squared=False)
        mae = mean_absolute_error(y_train, preds)
        r2 = r2_score(y_train, preds)

        mlflow.log_metric("train_rmse", rmse)
        mlflow.log_metric("train_mae", mae)
        mlflow.log_metric("train_r2", r2)

        # Save Model
        joblib.dump(model, os.path.join(args.model_dir, "model.pkl"))

        code_dir = os.path.join(args.model_dir, "code")
        os.makedirs(code_dir, exist_ok=True)

        shutil.copy("inference.py", os.path.join(code_dir, "inference.py"))
        print("Copied inference.py to model artifact")
        print(f"Model and code saved to {args.model_dir}")

        # Log Model to MLflow
        mlflow.sklearn.log_model(model, "model", registered_model_name="RealEstateModel")

        print("Training finished.")