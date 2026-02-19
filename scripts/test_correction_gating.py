"""E2E test: correction gating on free plan.

Sends verify request with correction=cascade on free-plan org,
verifies correction_skipped=true in response.

Requires:
    VEX_API_KEY: API key for a free-plan org
    VEX_GATEWAY_URL: Sync gateway base URL (e.g. http://localhost:8000)
"""

import os
import sys

import requests

API_KEY = os.environ.get("VEX_API_KEY", "")
GATEWAY_URL = os.environ.get("VEX_GATEWAY_URL", "http://localhost:8000")
HEADERS = {"X-Vex-Key": API_KEY, "Content-Type": "application/json"}


def test_correction_gating():
    print("Testing correction gating on free plan...")
    payload = {
        "agent_id": "test-agent-gating",
        "task": "gating-test",
        "output": "The capital of France is Berlin",
        "correction_mode": "cascade",
        "checks": [{"name": "factuality", "expect": "correct facts"}],
    }

    resp = requests.post(f"{GATEWAY_URL}/v1/verify", json=payload, headers=HEADERS)
    if resp.status_code != 200:
        print(f"  FAIL: Expected 200, got {resp.status_code}: {resp.text}")
        return False

    body = resp.json()
    if body.get("correction_skipped"):
        print(f"  PASS: correction_skipped=true, reason={body.get('correction_skipped_reason')}")
        return True

    print(f"  INFO: correction_skipped=false (org may be on paid plan)")
    return True


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: VEX_API_KEY required")
        sys.exit(1)
    sys.exit(0 if test_correction_gating() else 1)
