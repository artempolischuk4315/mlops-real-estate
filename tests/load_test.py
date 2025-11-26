import boto3
import json
import time
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()


def invoke_lambda(client, func_name, payload):
    try:
        start = time.time()
        response = client.invoke(
            FunctionName=func_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        latency = (time.time() - start) * 1000
        status = response['StatusCode']

        payload_resp = json.loads(response['Payload'].read())
        if "errorMessage" in payload_resp:
            status = 500

        return status, latency
    except Exception as e:
        logger.error(f"Error: {e}")
        return 500, 0


def run_load_test(func_name, total_requests=100, concurrency=10):
    logger.info(f"Starting load test on {func_name}. Requests: {total_requests}, Concurrency: {concurrency}")

    client = boto3.client("lambda", region_name="eu-north-1")

    payload = {"data": [[2013.5, 42.0, 55.0, 10, 24.98, 121.54]]}

    success_count = 0
    error_count = 0
    latencies = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(invoke_lambda, client, func_name, payload) for _ in range(total_requests)]

        for future in futures:
            status, latency = future.result()
            latencies.append(latency)
            if status == 200:
                success_count += 1
            else:
                error_count += 1

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0

    logger.info(f"Test finished.")
    logger.info(f"Success: {success_count}, Errors: {error_count}")
    logger.info(f"Avg Latency: {avg_latency:.2f}ms, Max Latency: {max_latency:.2f}ms")

    if error_count > 0:
        logger.error("Load test failed due to errors.")
        exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--function-name", required=True)
    args = parser.parse_args()

    run_load_test(args.function_name)