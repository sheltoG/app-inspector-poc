# App Inspector POC — Claude Code Context

## What this repo is
A POC that runs an event-driven AWS pipeline (SNS → Lambda → SQS) in LocalStack CI,
deliberately introduces a bug, and uses a Claude agent to diagnose it via the
App Inspector API.

## The bug
The SNS subscription filter policy expects `type=order` but the publisher sends
`type=purchase`. Messages are silently dropped — Lambda is never invoked.

## The pipeline
- `app/setup.py` — deploys SNS topic, Lambda function, SQS queue
- `app/publish.py` — publishes a test event with the wrong message attribute
- `agent/agent.py` — Claude agent that calls App Inspector endpoints to diagnose
- `.circleci/config.yml` — CI pipeline that runs all of the above

## App Inspector API (runs on LocalStack at port 4566)
All endpoints are under `http://localhost:4566/_localstack/appinspector`

| Method | Path | What it returns |
|--------|------|-----------------|
| GET | `/status` | Whether App Inspector is enabled |
| PUT | `/status` | Enable/disable (`{"status": "enabled"}`) |
| GET | `/v1/traces` | All captured traces |
| GET | `/v1/traces/{trace_id}/spans` | Spans for a trace (service call chain) |
| GET | `/v1/traces/{trace_id}/spans/{span_id}/events` | Raw event data for a span |

## The debug report
After a CI run, download `debug_report.json` from the CircleCI Artifacts tab.
It contains:
- `timestamp` — when the run happened
- `api_calls` — every App Inspector API response collected during the run
  - `endpoint` — the path called
  - `response` — the full raw JSON response
- `diagnosis` — Claude's written diagnosis from the CI run

## How to use this with Claude Code
Load the report and ask follow-up questions:

```
claude "Here is the debug report from our last CI run: @debug_report.json — why did the SNS span not trigger Lambda?"
```

Claude Code can read the raw trace/span/event data in the report and answer
questions like:
- "What was the exact filter policy on the subscription?"
- "Which spans were present and which were missing?"
- "What message attributes did the publisher send?"
- "Show me the raw event payload for the SNS span"
- "What's the exact line of code I need to change to fix this?"
