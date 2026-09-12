#!/usr/bin/env python3
"""Take today's matched changes through AgentCore and save notes for Maya's page.

Only relevant changes invoke the cloud. The authenticated job owns the delivery ledger;
the model cannot edit it. Notes and the ledger are committed with the regenerated page.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.cloud import runtime_client
from tools.impact import assess, load_business


def process(records, business, state, invoke, reviews=None):
    state = json.loads(json.dumps(state))
    state.setdefault("history", [])
    state.setdefault("processed", [])
    state.setdefault("pending", {})
    notes, outcomes = {}, []
    candidates = {hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest(): r for r in records}
    candidates.update({k: v["record"] for k, v in state["pending"].items()})
    for key, record in sorted(candidates.items(), key=lambda kv: (kv[1]["date"], kv[1]["vendor"])):
        if key in state["processed"]:
            continue
        impact = assess(business, record)
        if not impact["reaches_maya"]:
            state["processed"].append(key)
            continue
        impact["delivery_history"] = state["history"]
        impact["human_reviews"] = reviews or {}
        result = invoke(impact)
        state["history"] = result["delivery_history"]
        outcomes.append({"date": record["date"], "vendor": record["vendor"], "result": result})
        if result.get("note"):
            vendor = record["vendor"]
            dt.date.fromisoformat(record["date"])
            if not re.fullmatch(r"[a-z0-9_-]+", vendor):
                raise ValueError("unsafe vendor id")
            notes[f"{record['date']}-{vendor}.md"] = result["note"]
        if result.get("pending_routines") or result["state"] == "held_for_a_person":
            state["pending"][key] = {"record": record, "reason": result["reason"], "routine_ids": result.get("pending_routines")}
        else:
            state["pending"].pop(key, None)
            state["processed"].append(key)
    return state, notes, outcomes


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    ap.add_argument("--runtime-arn")
    args = ap.parse_args()
    dt.date.fromisoformat(args.date)
    contracts = ROOT / "contracts"
    path = contracts / "delivery-state.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    records = [json.loads(line) for line in (contracts / "changes.jsonl").read_text().splitlines() if line.strip()]
    records = [r for r in records if r["date"] == args.date]
    # Constructing a client does not invoke a model. Missing configuration fails loudly.
    reviews_path = contracts / "reviews.json"
    reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
    state, notes, outcomes = process(records, load_business(), state, runtime_client(args.runtime_arn), reviews)
    for name, text in notes.items():
        dest = contracts / "notes" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix(".tmp")
        temporary.write_text(text + "\n")
        temporary.replace(dest)
    atomic_json(path, state)
    atomic_json(contracts / "last-delivery.json", {"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                                  "date": args.date, "outcomes": outcomes,
                                                  "pending_count": len(state["pending"])})
    print(f"{args.date}: {len(records)} supplier-change records, {len(outcomes)} runtime assessments, "
          f"{len(notes)} notes, {len(state['pending'])} pending human review.")


if __name__ == "__main__":
    main()
