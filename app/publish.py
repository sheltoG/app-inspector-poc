"""
Publish a test event to SNS with type=purchase.
The subscription filter expects type=order — message is silently dropped.
"""
import json
import os

import boto3

LOCALSTACK_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION = "us-east-1"
CONFIG_FILE = "/tmp/poc_config.json"


def publish():
    with open(CONFIG_FILE) as f:
        config = json.load(f)

    sns = boto3.client(
        "sns",
        endpoint_url=LOCALSTACK_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    response = sns.publish(
        TopicArn=config["topic_arn"],
        Message=json.dumps({"orderId": "ORD-001", "amount": 99.99, "currency": "USD"}),
        Subject="New purchase event",
        MessageAttributes={
            # BUG: sending type=purchase but filter expects type=order
            "type": {"DataType": "String", "StringValue": "purchase"}
        },
    )
    print(f"[publish] Message ID: {response['MessageId']}")
    print("[publish] Sent with MessageAttribute type=purchase")
    print("[publish] Expected: Lambda invoked, message in SQS")
    print("[publish] Actual: message silently dropped by SNS filter")


if __name__ == "__main__":
    publish()
