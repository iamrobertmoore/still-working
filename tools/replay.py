#!/usr/bin/env python3
"""Replay every recorded supplier-change day through the real AgentCore runtime.

Maya is an illustrative profile. Supplier changes are historical observations. The
notes are newly generated responses, not messages sent to a real shop in April.
The output records inputs, outputs and hashes; a failed call never becomes a fixture.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.cloud import runtime_client
from tools.impact import assess, figures, load_business


def agent_runs(result):
    # Format v1 used an inaccurate name for this counter. It counted agent runs,
    # never individual Bedrock requests. Preserve the old responses verbatim.
    return result.get("agent_runs", result.get("model_invocations", 0))


def replay(records, business, invoke):
    ledger, captured = [], []
    for record in sorted(records, key=lambda r: (r["date"], r["vendor"])):
        impact = assess(business, record, today=record["date"])
        impact["delivery_history"] = list(ledger)
        started = time.monotonic()
        result = invoke(impact)
        if "delivery_history" not in result:
            raise RuntimeError("runtime response has no delivery ledger")
        ledger = result["delivery_history"]
        captured.append({"record": record, "impact": impact, "result": result,
                         "elapsed_seconds": round(time.monotonic() - started, 3)})
        print(f"{record['date']}  {record['vendor']:10}  {result['state']:20}  "
              f"agent runs: {agent_runs(result)}", flush=True)
    return captured


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime-arn")
    ap.add_argument("--output", type=Path, default=ROOT / "docs" / "replay" / "recordings.json")
    args = ap.parse_args()
    changelog = ROOT / "contracts" / "changes.jsonl"
    profile = ROOT / "business" / "maya.yaml"
    records = [json.loads(line) for line in changelog.read_text().splitlines() if line.strip()]
    captured = replay(records, load_business(), runtime_client(args.runtime_arn))
    payload = {
        "format_version": 2, "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "recorded_agentcore_replay", "persona": "illustrative, not a real customer",
        "method": "Each supplier change is assessed as of its recorded date. The returned ledger is carried forward.",
        "changes_sha256": hashlib.sha256(changelog.read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "measurement": figures(), "cases": captured,
        "delivered_notes": sum(len(c["result"]["notes"]) for c in captured),
        "agent_runs": sum(agent_runs(c["result"]) for c in captured),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(args.output)
    print(f"Saved {len(captured)} real runtime responses to {args.output}")
    print(f"Notes rendered: {payload['delivered_notes']}; agent runs: {payload['agent_runs']}")


if __name__ == "__main__":
    main()
