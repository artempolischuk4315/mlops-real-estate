import boto3
import json
import random
import time

REGION = "eu-north-1"
PROJECT_NAME = "mlops-real-estate"

lambda_client = boto3.client("lambda", region_name=REGION)
functions = lambda_client.list_functions()
inference_fn_name = next(
    (f["FunctionName"] for f in functions["Functions"]
     if f["FunctionName"].startswith("InferenceLambda") and PROJECT_NAME in f["FunctionName"]),
    None
)

if not inference_fn_name:
    print("❌ Не знайдено Inference Lambda. Перевірте ім'я в консолі.")
    exit(1)

print(f"🚀 Sending traffic to: {inference_fn_name}...")

for i in range(15):
    payload = {
        "data": [[
            2013.5 + random.uniform(0, 1),  # Transaction date
            random.uniform(5, 50),          # House age
            random.uniform(100, 2000),      # Distance to MRT
            random.randint(1, 10),          # Convenience stores
            24.9 + random.uniform(0, 0.1),  # Latitude
            121.5 + random.uniform(0, 0.1)  # Longitude
        ]]
    }

    response = lambda_client.invoke(
        FunctionName=inference_fn_name,
        InvocationType='Event',
        Payload=json.dumps(payload)
    )
    print(f"Request {i+1}: Sent. Status: {response['StatusCode']}")
    time.sleep(0.5)

print("✅ Traffic generation complete. Logs should be in S3.")