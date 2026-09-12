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

import datetime as dt
import json
import os
import re
import sys
from typing import Any

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
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


def vendor_labels() -> dict[str, dict]:
    """How to name each supplier to Maya.

    Two forms, because they are not the same job. `what_maya_calls_it` is her own
    first-person phrasing and belongs in her profile. `how_to_address_it` is a second
    person noun phrase, because the first form collapses the moment it is used as the
    subject of a sentence: "how customers pay me removed a feature" is not English.
    """
    path = os.path.join(ROOT, "contracts", "vendors.json")
    with open(path, "r", encoding="utf-8") as fh:
        return {v["id"]: {"hers": v.get("what_maya_calls_it") or v["name"],
                          "address_as": v.get("how_to_address_it") or v["name"]}
                for v in json.load(fh)["vendors"]}


def days_ago(date: str | None, today: str | None = None) -> int | None:
    """How long ago the supplier changed it.

    Without this the model has a date and no sense of distance from now, and fills the gap
    itself. The first live run said "this morning" about a change from 14 July.
    """
    if not date:
        return None
    try:
        then = dt.date.fromisoformat(date)
        now = dt.date.fromisoformat(today) if today else dt.date.today()
    except (TypeError, ValueError):
        return None
    return (now - then).days


def assess(business: dict, change_record: dict, today: str | None = None) -> dict[str, Any]:
    """Split one day of vendor changes into what reaches Maya and what does not."""
    index = watched_calls(business)
    vendor = change_record["vendor"]
    labels = vendor_labels().get(vendor, {"hers": vendor, "address_as": vendor})

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
        "vendor_in_her_words": labels["hers"],
        "vendor_address_as": labels["address_as"],
        "days_ago": days_ago(change_record.get("date"), today),
        "business": {
            "owner": business.get("owner"),
            "who_fixes_things": business.get("who_fixes_things"),
            "how_maya_finds_out_today": business.get("how_maya_finds_out_today"),
        },
        "vendor_total_changes": len(change_record.get("changes", [])),
        "ignored_count": len(ignored),
        "routines_touched": sorted(touched.values(), key=lambda e: e["routine_id"]),
        "reaches_maya": any(e["has_breaking_change"] for e in touched.values()),
    }


# ---------------------------------------------------------------- the README block

README_START = "<!-- measurement:start -->"
README_END = "<!-- measurement:end -->"
VENDORS_START = "<!-- vendors:start -->"
VENDORS_END = "<!-- vendors:end -->"

# The quiet window has one home, in the agent, because it is a product decision rather
# than a reporting one. It was defined here as well, and in measure(), and again in the
# tests, which meant changing it in the agent silently desynchronised everything that
# reports on the agent. agent/memory.py imports Strands lazily, so this costs nothing.
from agent.memory import QUIET_DAYS  # noqa: E402


def figures(business: dict | None = None) -> dict:
    """The headline numbers, computed from the record rather than remembered.

    Every figure in the README, on Maya's screen and in the video comes from here. A claim
    nobody re-derives is a claim that drifts, and this project is mostly an argument about
    a ratio.
    """
    business = business or load_business()
    path = os.path.join(ROOT, "contracts", "changes.jsonl")
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    # Sorted, because the file is append only and a backfill run after a daily run puts
    # older records at the end. Unsorted, the repeat rule saw the second Xero deletion
    # first and reported three interruptions instead of two.
    rows.sort(key=lambda r: (r["date"], r["vendor"]))
    dates = [r["date"] for r in rows]
    span = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days

    reaching, touched = [], 0
    for r in rows:
        a = assess(business, r)
        if a["routines_touched"]:
            touched += 1
        if a["reaches_maya"]:
            reaching.append((r, a))

    told: list[tuple[dt.date, str]] = []
    sent: list[tuple[dict, dict]] = []
    held: list[tuple[dict, dict]] = []
    gaps: dict[int, int] = {}
    for r, a in reaching:
        when = dt.date.fromisoformat(r["date"])
        names = {x["routine_id"] for x in a["routines_touched"] if x["has_breaking_change"]}
        earlier = [d for d, n in told if n in names and 0 <= (when - d).days <= QUIET_DAYS]
        if earlier:
            held.append((r, a))
            # Days since she was TOLD about this routine, which is not the same as days
            # since the last day that reached her. A held day in between would otherwise
            # make this say two when the answer is five.
            gaps[id(r)] = (when - max(earlier)).days
            continue
        sent.append((r, a))
        told += [(when, n) for n in names]

    total = sum(r["total_count"] for r in rows)
    sent_ids = {id(x) for x, _ in sent}
    return {
        "first": dates[0], "last": dates[-1], "span": span,
        "revisions": len(rows), "changes": total,
        "breaking": sum(r["breaking_count"] for r in rows),
        "breaking_days": sum(1 for r in rows if r["breaking_count"]),
        "touched": touched, "reaching": len(reaching),
        "interruptions": len(sent), "held": len(held),
        "ratio": (len(sent) / total * 100) if total else 0.0,
        "rows": [(r["date"], a["vendor_address_as"],
                  ", ".join(x["what_maya_calls_it"] for x in a["routines_touched"]
                            if x["has_breaking_change"]),
                  "sent" if id(r) in sent_ids else "held",
                  gaps.get(id(r)))
                 for r, a in reaching],
    }


def readme_block(business: dict | None = None) -> str:
    """The measurement, as markdown, regenerated by the scheduled job.

    This is between markers in README.md and rewritten on every run, for the same reason
    docs/index.html is: a number typed into a document by hand is a number that is true on
    the day it was typed.
    """
    f = figures(business)
    lines = [
        README_START,
        f"**{f['span']} days. {f['revisions']} days on which a contract changed shape. "
        f"{f['changes']} individual changes. {f['breaking']} of those could break somebody. "
        f"{f['touched']} landed on a call one of Maya's routines actually uses.**",
        "",
        f"**{f['reaching']} landed on a routine of hers that was actually broken. "
        f"She is interrupted {_words(f['interruptions'])}.**",
        "",
        "| When | Who | What she would have been told | |",
        "|---|---|---|---|",
    ]
    for date, hers, names, state, gap in f["rows"]:
        because = ("sent" if state == "sent"
                   else f"held, she was told {gap} days earlier")
        lines.append(f"| {human(date)} | {hers.capitalize()} | {names} | {because} |")
    lines += [
        "",
        f"{_count(f['interruptions']).capitalize()} interruptions in {f['span'] // 30} "
        f"months, from {f['changes']} supplier changes. That is **{f['ratio']:.1f}%**. Not "
        "zero, which would mean she does not need this. Not weekly, which is why she would "
        "turn it off. That ratio is the product.",
        "",
        f"_Window {f['first']} to {f['last']}. Regenerated by the scheduled job on every "
        "run, never typed by hand. Re-run it with `python tools/impact.py --measure`._",
        README_END,
    ]
    return "\n".join(lines)


def _words(n: int) -> str:
    """How many times she was interrupted, as an adverb."""
    return {0: "never", 1: "once", 2: "twice", 3: "three times"}.get(n, f"{n} times")


def _count(n: int) -> str:
    """The same number as a cardinal, for use before a noun."""
    return {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}.get(n, str(n))


def human(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')}"


def vendors_block() -> str:
    """The four suppliers, their size and their version, read from this morning's snapshot.

    Typed by hand until 11 September, by which point it claimed Stripe published 589 calls
    at version 2026-07-29.dahlia and Xero was on 17.0.0. Stripe had moved to 594 and
    2026-08-26.dahlia, and Xero to 18.0.0. Three wrong cells in a table sitting directly
    above a sentence about not trusting version strings.
    """
    with open(os.path.join(ROOT, "contracts", "vendors.json"), "r", encoding="utf-8") as fh:
        vendors = json.load(fh)["vendors"]
    lines = [VENDORS_START,
             "| What Maya calls it | Company | Calls published | Contract version |",
             "|---|---|---|---|"]
    for v in vendors:
        path = os.path.join(ROOT, "contracts", "latest", f"{v['id']}.json")
        if not os.path.exists(path):
            lines.append(f"| {v['what_maya_calls_it']} | {v['name']} | not yet checked | |")
            continue
        with open(path, "r", encoding="utf-8") as fh:
            snap = json.load(fh)
        lines.append(f"| {v['what_maya_calls_it']} | {v['name']} | "
                     f"{snap.get('endpoint_count', '?')} | "
                     f"`{snap.get('spec_version') or 'none published'}` |")
    lines.append(VENDORS_END)
    return "\n".join(lines)


def _replace_between(text: str, start: str, end: str, block: str) -> str:
    head, _, rest = text.partition(start)
    _, _, tail = rest.partition(end)
    return head + block + tail


def update_readme(path: str | None = None) -> int:
    path = path or os.path.join(ROOT, "README.md")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    missing = [m for m in (README_START, README_END, VENDORS_START, VENDORS_END)
               if m not in text]
    if missing:
        print(f"no {missing[0]} marker in {path}, nothing rewritten")
        return 1
    new = _replace_between(text, README_START, README_END, readme_block())
    new = _replace_between(new, VENDORS_START, VENDORS_END, vendors_block())
    if new == text:
        print("README generated blocks unchanged")
        return 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    print("README generated blocks rewritten")
    return 0


# ---------------------------------------------------------------- self test

def self_test() -> int:
    business = load_business()

    # 1. Square removes the call the nightly sync uses to read each order.
    #    This was written against "GET /v2/orders" until 11 September, when
    #    tools/setup.py --verify pointed out that Square has never published that call.
    #    A fixture built on a call that does not exist tests the matcher against fiction.
    real = {
        "date": "2026-09-02", "vendor": "square",
        "changes": [
            {"kind": "endpoint_removed", "endpoint": "GET /v2/orders/{order_id}", "breaking": True},
            {"kind": "endpoint_added", "endpoint": "POST /v2/loyalty/promotions", "breaking": False},
            {"kind": "param_added", "endpoint": "GET /v2/team-members", "param": "cursor", "breaking": False},
            {"kind": "version_string_changed", "from": "2.0", "to": "2.0", "breaking": False},
        ],
    }
    got = assess(business, real)
    assert got["reaches_maya"] is True, got
    assert got["vendor_in_her_words"] == "my till and my bookings", got["vendor_in_her_words"]
    assert got["vendor_address_as"] == "your till and bookings", got["vendor_address_as"]
    assert assess(business, real, today="2026-09-03")["days_ago"] == 1, "fixture is dated 2026-09-02"
    assert assess(business, {"date": "2026-07-14", "vendor": "square", "changes": []},
                  today="2026-09-03")["days_ago"] == 51
    assert "Priya" in (got["business"]["who_fixes_things"] or ""), got["business"]
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
    print("  the supplier's name in her words and who fixes things both reach the agent")
    print("  the supplier has a second-person form that works as a sentence subject")
    print("  the agent is told how many days ago the change happened, not just the date")
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
    days = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days

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

    f = figures(business)

    print(f"Window            {dates[0]} to {dates[-1]}, {days} days")
    print(f"Vendors           {len({r['vendor'] for r in rows})}")
    print(f"Revisions         {len(rows)} days on which a contract changed shape")
    print(f"Changes           {total_changes}")
    print(f"Breaking          {total_breaking}, across {revisions_with_breaking} of those days")
    print(f"Touched Maya      {touched} days landed on a call one of her routines uses")
    print(f"Broke a routine   {f['reaching']} days broke a routine she depends on")
    print(f"INTERRUPTED HER   {f['interruptions']} days she is actually told about")
    print()

    # The suppression is worked out before anything is printed. It was printed after, so
    # the list of "what she would have been told" included a day the next paragraph said
    # she was not told about.
    sent_rows = [r for r in f["rows"] if r[3] == "sent"]
    held_rows = [r for r in f["rows"] if r[3] == "held"]

    if sent_rows:
        print("What she was told, in five months:")
        for date, who, names, _, _ in sent_rows:
            print(f"  {date}  {who:26s} {names}")
        print()
    if held_rows:
        print("Broke the same routine again, and held back because she had just been told:")
        for date, who, names, _, gap in held_rows:
            gap_text = f"{gap} days earlier" if gap is not None else "earlier"
            print(f"  {date}  {who:26s} {names}  (told {gap_text})")
        print()

    print(f"Signal ratio      {f['interruptions']} interruptions from {total_changes} "
          f"supplier changes ({f['ratio']:.1f}%)")
    print(f"                  Set membership alone would have interrupted her "
          f"{f['reaching']} times. The repeat rule in agent/memory.py removes "
          f"{f['held']}.")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--measure" in sys.argv:
        return measure()
    if "--readme" in sys.argv:
        return update_readme()
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
