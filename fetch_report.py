"""
Downloads the latest debug_report.json artifact from the most recent
CircleCI pipeline run for this project.

Usage:
    export CIRCLECI_TOKEN=your_token_here
    python3 fetch_report.py
"""
import os
import sys

import requests

TOKEN = os.environ.get("CIRCLECI_TOKEN")
if not TOKEN:
    print("Error: CIRCLECI_TOKEN environment variable not set.")
    print("Get one at: circleci.com → User Settings → Personal API Tokens")
    sys.exit(1)

PROJECT_SLUG = "gh/sheltoG/app-inspector-poc"
ARTIFACT_NAME = "debug_report.json"
OUTPUT_PATH = "debug_report.json"

HEADERS = {"Circle-Token": TOKEN}
BASE = "https://circleci.com/api/v2"


def get(path, **kwargs):
    resp = requests.get(f"{BASE}{path}", headers=HEADERS, **kwargs)
    resp.raise_for_status()
    return resp.json()


def fetch_report():
    # 1. Latest pipeline on main
    print("Fetching latest pipeline...")
    pipelines = get(f"/project/{PROJECT_SLUG}/pipeline", params={"branch": "main"})
    if not pipelines["items"]:
        print("No pipelines found.")
        sys.exit(1)
    pipeline_id = pipelines["items"][0]["id"]
    pipeline_number = pipelines["items"][0]["number"]
    print(f"  Pipeline #{pipeline_number} ({pipeline_id})")

    # 2. Workflows in that pipeline
    workflows = get(f"/pipeline/{pipeline_id}/workflow")
    if not workflows["items"]:
        print("No workflows found.")
        sys.exit(1)
    workflow_id = workflows["items"][0]["id"]
    workflow_status = workflows["items"][0]["status"]
    print(f"  Workflow status: {workflow_status}")

    if workflow_status not in ("success", "failed"):
        print(f"  Workflow is still {workflow_status} — wait for it to finish.")
        sys.exit(1)

    # 3. Jobs in that workflow
    jobs = get(f"/workflow/{workflow_id}/job")
    if not jobs["items"]:
        print("No jobs found.")
        sys.exit(1)
    job_number = jobs["items"][0]["job_number"]
    print(f"  Job #{job_number}")

    # 4. Artifacts for that job
    artifacts = get(f"/project/{PROJECT_SLUG}/job/{job_number}/artifacts")
    report = next(
        (a for a in artifacts["items"] if a["path"] == ARTIFACT_NAME), None
    )
    if not report:
        print(f"  Artifact '{ARTIFACT_NAME}' not found. Did the job complete successfully?")
        sys.exit(1)

    # 5. Download
    print(f"  Downloading {ARTIFACT_NAME}...")
    download = requests.get(report["url"], headers=HEADERS)
    download.raise_for_status()
    with open(OUTPUT_PATH, "wb") as f:
        f.write(download.content)

    print(f"\nSaved to {OUTPUT_PATH}")
    print(f"\nNow ask Claude Code:")
    print(f'  claude "@{OUTPUT_PATH} why did the SNS message not trigger Lambda?"')


if __name__ == "__main__":
    fetch_report()
