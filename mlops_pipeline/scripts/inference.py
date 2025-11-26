import os
import json
import logging
from io import StringIO
import joblib
import pandas as pd

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FEATURE_COLUMNS = ["X1 transaction date", "X2 house age", "X3 distance to the nearest MRT station",
                   "X4 number of convenience stores", "X5 latitude", "X6 longitude"]


def model_fn(model_dir: str):
    logger.info(f"Loading model from {model_dir}")
    model_path = os.path.join(model_dir, "model.pkl")

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found at {model_path}")

    model = joblib.load(model_path)
    logger.info("Model loaded successfully")
    return model


def input_fn(request_body, request_content_type):
    logger.info(f"Received content type: {request_content_type}")

    if request_content_type == "text/csv":
        df = pd.read_csv(StringIO(request_body), header=None)
        df.columns = FEATURE_COLUMNS
        return df

    elif request_content_type == "application/json":
        data = json.loads(request_body)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        df = pd.DataFrame(data, columns=FEATURE_COLUMNS)
        return df

    else:
        raise ValueError(f"Unsupported content type: {request_content_type}")


def predict_fn(input_data, model):
    logger.info(f"Making prediction for shape: {input_data.shape}")
    return model.predict(input_data)


def output_fn(prediction, response_content_type):
    logger.info(f"Formatting prediction: {prediction}")
    return json.dumps({"predictions": prediction.tolist()})