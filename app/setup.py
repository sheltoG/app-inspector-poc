"""
Deploy SNS -> Lambda -> SQS pipeline with a deliberate bug:
SNS subscription filter expects type=order but publisher sends type=purchase.
Messages are silently dropped by the filter — Lambda is never invoked.
"""
import io
import json
import os
import zipfile

import boto3

LOCALSTACK_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION = "us-east-1"
ACCOUNT_ID = "000000000000"
OUTPUT_FILE = "/tmp/poc_config.json"


def client(service):
    return boto3.client(
        service,
        endpoint_url=LOCALSTACK_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def build_lambda_zip():
    buf = io.BytesIO()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(script_dir, "lambda_function.py"), "lambda_function.py")
    return buf.getvalue()


def setup():
    sqs_client = client("sqs")
    sns_client = client("sns")
    lambda_client = client("lambda")

    # --- SQS ---
    queue = sqs_client.create_queue(QueueName="orders-queue")
    queue_url = queue["QueueUrl"]
    queue_arn = sqs_client.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]
    print(f"[setup] SQS queue: {queue_url}")

    # --- SNS ---
    topic = sns_client.create_topic(Name="events-topic")
    topic_arn = topic["TopicArn"]
    print(f"[setup] SNS topic: {topic_arn}")

    # --- Lambda ---
    zip_bytes = build_lambda_zip()
    role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/lambda-exec-role"
    try:
        func = lambda_client.create_function(
            FunctionName="order-processor",
            Runtime="python3.11",
            Role=role_arn,
            Handler="lambda_function.handler",
            Code={"ZipFile": zip_bytes},
            Environment={
                "Variables": {
                    "SQS_QUEUE_URL": queue_url,
                    "LOCALSTACK_ENDPOINT": LOCALSTACK_URL,
                }
            },
            Timeout=30,
        )
        lambda_arn = func["FunctionArn"]
    except lambda_client.exceptions.ResourceConflictException:
        lambda_client.update_function_code(
            FunctionName="order-processor", ZipFile=zip_bytes
        )
        func = lambda_client.get_function(FunctionName="order-processor")
        lambda_arn = func["Configuration"]["FunctionArn"]
    print(f"[setup] Lambda: {lambda_arn}")

    # Allow SNS to invoke the Lambda
    try:
        lambda_client.add_permission(
            FunctionName="order-processor",
            StatementId="sns-invoke",
            Action="lambda:InvokeFunction",
            Principal="sns.amazonaws.com",
            SourceArn=topic_arn,
        )
    except lambda_client.exceptions.ResourceConflictException:
        pass

    # --- SNS Subscription with BUGGY filter ---
    # Filter expects type=order but publisher will send type=purchase
    sns_client.subscribe(
        TopicArn=topic_arn,
        Protocol="lambda",
        Endpoint=lambda_arn,
        Attributes={"FilterPolicy": json.dumps({"type": ["order"]})},
    )
    print("[setup] SNS subscription created")
    print("[setup] BUG: filter policy expects type=order")

    config = {"topic_arn": topic_arn, "queue_url": queue_url, "lambda_arn": lambda_arn}
    with open(OUTPUT_FILE, "w") as f:
        json.dump(config, f)
    print(f"[setup] Config written to {OUTPUT_FILE}")
    print("[setup] Done.")


if __name__ == "__main__":
    setup()
