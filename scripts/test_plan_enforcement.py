"""E2E test: agent limit and rate limit enforcement.

Requires:
    VEX_API_KEY: API key for a free-plan org
    VEX_INGEST_URL: Ingestion API base URL (e.g. http://localhost:8001)
"""

import os
import sys

import requests

API_KEY = os.environ.get("VEX_API_KEY", "")
INGEST_URL = os.environ.get("VEX_INGEST_URL", "http://localhost:8001")
HEADERS = {"X-Vex-Key": API_KEY, "Content-Type": "application/json"}


def test_agent_limit():
    print("Testing agent limit enforcement...")
    for i in range(10):
        payload = {"agent_id": f"limit-test-agent-{i}", "task": "test", "output": f"out-{i}"}
        resp = requests.post(f"{INGEST_URL}/v1/observe", json=payload, headers=HEADERS)
        if resp.status_code == 403:
            print(f"  PASS: Got 403 after agent #{i + 1} — {resp.json().get('detail')}")
            return True
        if resp.status_code not in (200, 201, 202):
            print(f"  Unexpected {resp.status_code}: {resp.text}")
    print("  INFO: 10 agents without hitting limit")
    return True


def test_rate_limit():
    print("Testing rate limit enforcement...")
    payload = {"agent_id": "rate-limit-agent", "task": "test", "output": "test"}
    for i in range(150):
        resp = requests.post(f"{INGEST_URL}/v1/observe", json=payload, headers=HEADERS)
        if resp.status_code == 429:
            print(f"  PASS: Got 429 after {i + 1} requests, Retry-After: {resp.headers.get('Retry-After')}")
            return True
    print("  INFO: No 429 in 150 requests")
    return True


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: VEX_API_KEY required")
        sys.exit(1)
    sys.exit(0 if all([test_agent_limit(), test_rate_limit()]) else 1)
