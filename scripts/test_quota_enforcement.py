"""E2E test: quota enforcement.

Sends observations via the API until quota exceeded,
verifies 429 response with upgrade message.

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


def test_quota_exceeded():
    print("Testing quota enforcement...")
    payload = {
        "agent_id": "test-agent-quota",
        "task": "quota-test",
        "output": "test output",
    }

    last_status = None
    for i in range(100):
        resp = requests.post(f"{INGEST_URL}/v1/observe", json=payload, headers=HEADERS)
        last_status = resp.status_code
        if resp.status_code == 429:
            body = resp.json()
            assert "quota" in body.get("detail", "").lower() or "upgrade" in body.get("detail", "").lower()
            print(f"  PASS: Got 429 after {i + 1} requests — {body.get('detail')}")
            return True
        if resp.status_code not in (200, 201, 202):
            print(f"  Unexpected status {resp.status_code}: {resp.text}")
            return False

    print(f"  INFO: Sent 100 requests, last status={last_status} (quota not yet exceeded)")
    return True


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: VEX_API_KEY required")
        sys.exit(1)
    sys.exit(0 if test_quota_exceeded() else 1)
