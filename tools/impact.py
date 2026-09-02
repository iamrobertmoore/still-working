#!/usr/bin/env python3
"""Decide which of Maya's routines a vendor change touches. No model involved.

This is the deterministic half of the judgement. It answers a question with a right
answer: is the call that changed one of the calls this routine leans on? Set membership,
reproducible, testable, and the same every time.

What it deliberately does NOT decide is whether the change actually breaks the routine,
or how to tell Maya. Those need judgement and they live in the agent.

The important behaviour here is the silence. Most vendor changes touch nothing Maya
depends on. Those are counted and dropped. A change only travels further if it lands on
a call one of her routines needs, which is the difference between a product that pings
her twice a year and a product she turns off in week two.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BREAKING_KINDS = {"endpoint_removed", "param_removed", "param_became_required"}

_BRACES = re.compile(r"\{[^}]*\}")


def canon(endpoint: str) -> str:
    """Normalise "GET /v1/x/{intent}" and "GET /v1/x/{payment_intent}/" to one key.

    Vendors rename their own path parameters without it meaning anything. Maya's profile
    was written from her developer's memory. Neither side should have to match the other
    character for character.
    """
    method, _, path = endpoint.strip().partition(" ")
    path = _BRACES.sub("{}", path.strip()).rstrip("/")
    return f"{method.upper()} {path or '/'}"


def load_business(path: str | None = None) -> dict:
    path = path or os.path.join(ROOT, "business", "maya.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def watched_calls(business: dict) -> dict[str, list[dict]]:
    """Map a canonical "vendor|METHOD /path" to the routines that lean on it."""
    index: dict[str, list[dict]] = {}
    for routine in business.get("routines", []):
        derived = routine.get("derived") or {}
        for dep in derived.get("depends_on", []):
            for call in dep.get("calls", []):
                key = f"{dep['vendor']}|{canon(call)}"
                index.setdefault(key, []).append(routine)
    return index


def assess(business: dict, change_record: dict) -> dict[str, Any]:
    """Split one day of vendor changes into what reaches Maya and what does not."""
    index = watched_calls(business)
    vendor = change_record["vendor"]

    touched: dict[str, dict] = {}
    ignored: list[dict] = []

    for change in change_record.get("changes", []):
        endpoint = change.get("endpoint")
        if not endpoint:
            ignored.append(change)          # version strings and the like
            continue
        routines = index.get(f"{vendor}|{canon(endpoint)}")
        if not routines:
            ignored.append(change)
            continue
        for routine in routines:
            entry = touched.setdefault(routine["id"], {
                "routine_id": routine["id"],
                "what_maya_calls_it": routine["what_maya_calls_it"],
                "in_her_words": routine.get("in_her_words", "").strip(),
                "if_it_stops": routine.get("if_it_stops", "").strip(),
                "how_late_would_she_notice": routine.get("how_late_would_she_notice"),
                "what_it_costs": routine.get("what_it_costs", "").strip(),
                "mapping_confidence": (routine.get("derived") or {}).get("confidence"),
                "changes": [],
            })
            entry["changes"].append(change)

    for entry in touched.values():
        entry["has_breaking_change"] = any(c["kind"] in BREAKING_KINDS for c in entry["changes"])

    return {
        "date": change_record.get("date"),
        "vendor": vendor,
        "vendor_total_changes": len(change_record.get("changes", [])),
        "ignored_count": len(ignored),
        "routines_touched": sorted(touched.values(), key=lambda e: e["routine_id"]),
        "reaches_maya": any(e["has_breaking_change"] for e in touched.values()),
    }


# ---------------------------------------------------------------- self test

def self_test() -> int:
    business = load_business()

    # 1. The change from the brief: Square drops the filter the nightly sync uses.
    real = {
        "date": "2026-09-02", "vendor": "square",
        "changes": [
            {"kind": "param_removed", "endpoint": "GET /v2/orders", "param": "location_id", "breaking": True},
            {"kind": "endpoint_added", "endpoint": "POST /v2/loyalty/promotions", "breaking": False},
            {"kind": "param_added", "endpoint": "GET /v2/team-members", "param": "cursor", "breaking": False},
            {"kind": "version_string_changed", "from": "2.0", "to": "2.0", "breaking": False},
        ],
    }
    got = assess(business, real)
    assert got["reaches_maya"] is True, got
    assert [e["routine_id"] for e in got["routines_touched"]] == ["orders-into-accounts"], got
    assert got["ignored_count"] == 3, got

    # 2. A busy day that touches nothing she depends on must stay silent.
    noisy = {
        "date": "2026-09-03", "vendor": "stripe",
        "changes": [
            {"kind": "endpoint_removed", "endpoint": "GET /v1/issuing/cards", "breaking": True},
            {"kind": "param_removed", "endpoint": "POST /v1/terminal/readers", "param": "label", "breaking": True},
            {"kind": "endpoint_added", "endpoint": "POST /v1/tax/registrations", "breaking": False},
        ],
    }
    quiet = assess(business, noisy)
    assert quiet["reaches_maya"] is False, quiet
    assert quiet["routines_touched"] == [], quiet
    assert quiet["ignored_count"] == 3, quiet

    # 3. A path parameter renamed by the vendor must still match her profile.
    renamed = {
        "date": "2026-09-04", "vendor": "stripe",
        "changes": [
            {"kind": "param_removed", "endpoint": "GET /v1/payment_intents/{payment_intent_id}",
             "param": "client_secret", "breaking": True},
        ],
    }
    matched = assess(business, renamed)
    assert matched["reaches_maya"] is True, matched
    assert [e["routine_id"] for e in matched["routines_touched"]] == ["taking-payment"], matched

    # 4. A touched-but-additive change reaches the routine without raising the alarm.
    additive = {
        "date": "2026-09-05", "vendor": "shipengine",
        "changes": [{"kind": "param_added", "endpoint": "POST /v1/labels", "param": "carbon_offset", "breaking": False}],
    }
    soft = assess(business, additive)
    assert soft["routines_touched"], soft
    assert soft["reaches_maya"] is False, soft

    # 5. One change hitting two routines must reach both.
    both = {
        "date": "2026-09-06", "vendor": "square",
        "changes": [{"kind": "endpoint_removed", "endpoint": "POST /v2/orders/search", "breaking": True}],
    }
    pair = assess(business, both)
    ids = sorted(e["routine_id"] for e in pair["routines_touched"])
    assert ids == ["monday-figure", "orders-into-accounts"], ids

    print("impact self test OK")
    print("  the brief's change reaches exactly one routine, and 3 of 4 changes are dropped")
    print("  a day of three breaking Stripe changes she does not depend on stays silent")
    print("  a vendor renaming its own path parameter still matches her profile")
    print("  an additive change on a watched call reaches the routine but raises nothing")
    print("  a change on a shared call reaches both routines that lean on it")

    # 6. Every routine must have at least one call nothing else watches, or its own
    #    behaviour can never be observed in isolation. This test exists because
    #    monday-figure originally failed it and the failure was invisible.
    index = watched_calls(business)
    for routine in business["routines"]:
        derived = routine.get("derived") or {}
        mine = {f"{d['vendor']}|{canon(c)}" for d in derived.get("depends_on", []) for c in d["calls"]}
        exclusive = [k for k in mine if len(index[k]) == 1]
        assert exclusive, (
            f"routine {routine['id']!r} shares every one of its calls with another routine, "
            "so it can never be the only thing broken and its own path is untestable")
    print("  every routine has at least one call no other routine watches")
    return 0


def measure() -> int:
    """The number the pitch rests on: of everything the vendors did, how much reached Maya."""
    business = load_business()
    path = os.path.join(ROOT, "contracts", "changes.jsonl")
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    if not rows:
        print("no change history yet, run tools/backfill.py")
        return 1

    dates = sorted(r["date"] for r in rows)
    days = (__import__("datetime").date.fromisoformat(dates[-1])
            - __import__("datetime").date.fromisoformat(dates[0])).days

    total_changes = sum(r["total_count"] for r in rows)
    total_breaking = sum(r["breaking_count"] for r in rows)
    revisions_with_breaking = sum(1 for r in rows if r["breaking_count"])

    touched, reached, per_routine = 0, 0, {}
    reaching_rows = []
    for r in rows:
        a = assess(business, r)
        if a["routines_touched"]:
            touched += 1
        if a["reaches_maya"]:
            reached += 1
            reaching_rows.append((r["date"], r["vendor"],
                                  [x["what_maya_calls_it"] for x in a["routines_touched"]
                                   if x["has_breaking_change"]]))
            for x in a["routines_touched"]:
                if x["has_breaking_change"]:
                    per_routine[x["what_maya_calls_it"]] = per_routine.get(x["what_maya_calls_it"], 0) + 1

    print(f"Window            {dates[0]} to {dates[-1]}, {days} days")
    print(f"Vendors           4")
    print(f"Revisions         {len(rows)} days on which a contract changed shape")
    print(f"Changes           {total_changes}")
    print(f"Breaking          {total_breaking}, across {revisions_with_breaking} of those days")
    print(f"Touched Maya      {touched} days landed on a call one of her routines uses")
    print(f"REACHED MAYA      {reached} days would have interrupted her")
    print()
    if reaching_rows:
        print("What she would have been told, in five months:")
        for d, v, rs in reaching_rows:
            print(f"  {d}  {v:11s} {', '.join(rs)}")
    print()
    print(f"Signal ratio      {reached} interruptions from {total_changes} vendor changes"
          f" ({reached/total_changes*100:.1f}%)")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--measure" in sys.argv:
        return measure()
    path = os.path.join(ROOT, "contracts", "changes.jsonl")
    if not os.path.exists(path):
        print("no changes recorded yet, nothing to assess")
        return 0
    business = load_business()
    for line in open(path, encoding="utf-8"):
        print(json.dumps(assess(business, json.loads(line)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
