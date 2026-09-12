"""Small, explicit client for the deployed judgement layer. No credential fallback."""
from __future__ import annotations

import json
import os
import uuid


def runtime_client(runtime_arn: str | None = None):
    import boto3
    from botocore.config import Config
    arn = runtime_arn or os.environ.get("STILL_WORKING_RUNTIME_ARN")
    if not arn:
        raise ValueError("Set STILL_WORKING_RUNTIME_ARN to the deployed AgentCore runtime ARN.")
    parts = arn.split(":")
    if len(parts) < 6 or parts[2] != "bedrock-agentcore":
        raise ValueError("STILL_WORKING_RUNTIME_ARN must be an AgentCore runtime ARN.")
    client = boto3.client("bedrock-agentcore", region_name=parts[3],
                          config=Config(read_timeout=180, retries={"max_attempts": 0}))

    def invoke(impact: dict) -> dict:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=arn, runtimeSessionId=str(uuid.uuid4()),
            contentType="application/json", accept="application/json",
            payload=json.dumps({"impact": impact}).encode())
        body = response["response"].read().decode()
        result = json.loads(body)
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict) or result.get("controls_version") != "shared-v1":
            raise RuntimeError("The runtime did not return the current delivery contract. Redeploy before recording.")
        if result.get("state") not in {"still_working", "something_broke", "held_for_a_person"}:
            raise RuntimeError("The runtime returned an unknown state.")
        if result["state"] == "something_broke" and not result.get("note"):
            raise RuntimeError("The runtime reported a delivery without a note.")
        return result

    return invoke


def main():
    """A real, model-free invocation verifies the scheduled role and deployed contract."""
    import datetime as dt
    result = runtime_client()({'date': dt.datetime.now(dt.timezone.utc).date().isoformat(),
                               'vendor': 'healthcheck', 'routines_touched': [],
                               'vendor_total_changes': 0, 'delivery_history': []})
    if result['state'] != 'still_working' or result.get('agent_runs', result.get('model_invocations')) != 0 or result.get('note'):
        raise RuntimeError('The deployed quiet gate did not return a model-free quiet result.')
    print(f"AgentCore reached through the scheduled role: {result['controls_version']}, no model, no note.")


if __name__ == '__main__':
    main()
