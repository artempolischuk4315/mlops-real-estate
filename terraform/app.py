import os
import json
import logging
import joblib
import pandas as pd
from flask import Flask, request, Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

model = None


def load_model():
    global model
    if model is None:
        model_dir = os.environ.get("SM_MODEL_DIR", "/opt/ml/model")
        model_path = os.path.join(model_dir, "model.pkl")

        if not os.path.exists(model_path):
            local_path = "model.pkl"
            if os.path.exists(local_path):
                model_path = local_path
            else:
                logger.error(f"Model not found at {model_path}")
                return None

        logger.info(f"Loading model from {model_path}")
        try:
            model = joblib.load(model_path)
            logger.info("Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
    return model


@app.route("/ping", methods=["GET"])
def ping():
    m = load_model()
    if m:
        return Response(response="\n", status=200)
    else:
        return Response(response="Model not loaded", status=500)


@app.route("/invocations", methods=["POST"])
def predict():
    m = load_model()
    if not m:
        return Response(response="Model not loaded", status=500)

    if request.content_type == "application/json":
        data = request.get_json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        try:
            df = pd.DataFrame(data)

            prediction = m.predict(df)
            return json.dumps({"predictions": prediction.tolist()})

        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return Response(response=str(e), status=400)

    elif request.content_type == "text/csv":
        try:
            df = pd.read_csv(request.files['body'] if 'body' in request.files else request.stream, header=None)
            prediction = m.predict(df)
            return json.dumps({"predictions": prediction.tolist()})
        except Exception as e:
            return Response(response=str(e), status=400)

    else:
        return Response(response="Unsupported content type", status=415)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)