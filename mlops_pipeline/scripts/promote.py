import subprocess
import sys


def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])


try:
    import mlflow
except ImportError:
    print("Installing mlflow...")
    install("mlflow==2.13.2")
    import mlflow

import os
import argparse

if __name__ == "__main__":
    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI")
    model_name = "RealEstateModel"
    alias = "Production"

    print(f"Connecting to MLflow at {mlflow_uri}...")
    mlflow.set_tracking_uri(mlflow_uri)
    client = mlflow.MlflowClient()

    print(f"Promoting latest version of '{model_name}' to '{alias}'...")

    versions = client.search_model_versions(f"name='{model_name}'")

    if not versions:
        print("❌ No model versions found in MLflow Registry!")
        exit(0)

    latest_version = sorted(versions, key=lambda x: int(x.version), reverse=True)[0]

    client.set_registered_model_alias(model_name, alias, latest_version.version)

    print(f"✅ Successfully promoted version {latest_version.version} to {alias}")