import json
import os
import boto3

LOCALSTACK_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")


def handler(event, context):
    sqs = boto3.client(
        "sqs",
        endpoint_url=LOCALSTACK_URL,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    queue_url = os.environ["SQS_QUEUE_URL"]

    for record in event.get("Records", []):
        message = record["Sns"]["Message"]
        sqs.send_message(QueueUrl=queue_url, MessageBody=message)
        print(f"Forwarded message to SQS: {message}")

    return {"statusCode": 200}
