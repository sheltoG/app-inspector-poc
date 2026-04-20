"""
App Inspector Debug Agent

Uses Claude + App Inspector API to diagnose why an SNS -> Lambda -> SQS
pipeline is silently dropping messages. Runs in CI after the workload executes.

All raw API data and Claude's diagnosis are saved to debug_report.json
so you can load it into Claude Code for interactive follow-up questions.
"""
import json
import os
import sys
from datetime import datetime, timezone

import anthropic
import requests

LOCALSTACK_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
APPINSPECTOR_BASE = f"{LOCALSTACK_URL}/_localstack/appinspector"
REPORT_PATH = os.environ.get("REPORT_PATH", "debug_report.json")

client = anthropic.Anthropic()

# Raw data collected during the run — saved to the report
_collected: dict = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "localstack_url": LOCALSTACK_URL,
    "api_calls": [],  # every App Inspector response, keyed by endpoint
    "diagnosis": None,
}

TOOLS = [
    {
        "name": "get_app_inspector_status",
        "description": "Check whether App Inspector is enabled on the LocalStack instance.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_traces",
        "description": (
            "List all traces captured by App Inspector. Each trace represents "
            "a top-level operation (e.g. an SNS Publish call). Returns trace IDs, "
            "span counts, error counts, and timestamps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of traces to return (1-100)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_spans",
        "description": (
            "Get all spans for a trace. Spans represent individual service operations "
            "within the trace (e.g. SNS.Publish, Lambda.Invoke). Shows the call chain, "
            "status codes, service names, resource names, and operation names. "
            "Use this to see what services were involved and whether any were skipped."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "32-character hex trace ID",
                }
            },
            "required": ["trace_id"],
        },
    },
    {
        "name": "get_events",
        "description": (
            "Get events for a specific span. Events contain detailed payload data "
            "exchanged during the operation — request parameters, response data, "
            "filter policies, message attributes. Use this to inspect the exact "
            "data to find mismatches (e.g. filter policy vs message attributes)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "32-character hex trace ID",
                },
                "span_id": {
                    "type": "string",
                    "description": "16-character hex span ID",
                },
            },
            "required": ["trace_id", "span_id"],
        },
    },
]

SYSTEM_PROMPT = """\
You are a cloud infrastructure debugging agent with access to LocalStack's App Inspector API.
App Inspector captures distributed traces of AWS service interactions in real time.

The pipeline under investigation:
  SNS topic (events-topic)
  → Lambda subscription (order-processor, filter policy: type=order)
  → SQS queue (orders-queue)

Symptom: a message was published to SNS but Lambda was never invoked and SQS remains empty.

Your task:
1. Verify App Inspector is enabled.
2. Retrieve traces — identify the SNS Publish trace.
3. Get spans for that trace — check which services appear and which are absent.
4. Get events for the SNS span — inspect the filter policy and message attributes.
5. State the root cause precisely.
6. Output the exact code change that fixes it.

Be concise and methodical. Print a clear "ROOT CAUSE" and "FIX" section at the end.\
"""


def call_api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{APPINSPECTOR_BASE}{path}"
    try:
        if method == "GET":
            resp = requests.get(url, timeout=10)
        elif method == "PUT":
            resp = requests.put(url, json=body, timeout=10)
        else:
            return {"error": f"Unsupported method: {method}"}
        resp.raise_for_status()
        result = resp.json() if resp.content else {}
    except requests.RequestException as e:
        result = {"error": str(e)}

    # Save every API response to the report
    _collected["api_calls"].append({"endpoint": path, "method": method, "response": result})
    return result


def execute_tool(name: str, inputs: dict) -> dict:
    if name == "get_app_inspector_status":
        return call_api("GET", "/status")

    if name == "get_traces":
        limit = inputs.get("limit", 20)
        return call_api("GET", f"/v1/traces?limit={limit}")

    if name == "get_spans":
        trace_id = inputs["trace_id"]
        return call_api("GET", f"/v1/traces/{trace_id}/spans")

    if name == "get_events":
        trace_id = inputs["trace_id"]
        span_id = inputs["span_id"]
        return call_api("GET", f"/v1/traces/{trace_id}/spans/{span_id}/events")

    return {"error": f"Unknown tool: {name}"}


def save_report(diagnosis: str):
    _collected["diagnosis"] = diagnosis
    with open(REPORT_PATH, "w") as f:
        json.dump(_collected, f, indent=2)
    print(f"\n[agent] Report saved to {REPORT_PATH}")


def run_agent():
    print("=" * 60)
    print("App Inspector Debug Agent")
    print("=" * 60)

    messages = [
        {
            "role": "user",
            "content": (
                "A message was published to SNS with MessageAttribute type=purchase, "
                "but Lambda was never invoked and SQS is empty. "
                "Use App Inspector to find out why and provide the fix."
            ),
        }
    ]

    diagnosis_parts = []

    while True:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        for block in response.content:
            if block.type == "text":
                print(block.text)
                diagnosis_parts.append(block.text)

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            print(f"[agent] Unexpected stop_reason: {response.stop_reason}", file=sys.stderr)
            break

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for call in tool_calls:
            print(f"\n[tool] {call.name}({json.dumps(call.input)})")
            result = execute_tool(call.name, call.input)
            display = json.dumps(result)
            print(f"[tool] → {display[:400]}{'...' if len(display) > 400 else ''}")
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    save_report("\n\n".join(diagnosis_parts))

    print()
    print("=" * 60)
    print("Debug session complete.")
    print("=" * 60)


if __name__ == "__main__":
    run_agent()
