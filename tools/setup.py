#!/usr/bin/env python3
"""The setup conversation: turn what Maya says about her week into calls to watch.

`business/maya.yaml` has two halves. Above the line is Maya describing her own business.
Below the line is a `derived` block naming the exact vendor calls each routine leans on,
with a confidence and a reason. Maya did not write that half and could not. This file is
what writes it.

It is the only place in the project where a model produces something that is then stored
and trusted later, so it is the place where being careless would be most expensive. Three
things keep it honest:

  1. It uses Strands structured output, so the result is a validated object with a fixed
     shape and a confidence drawn from three allowed values. Free text that has to be
     parsed afterwards is how a "medium" becomes a "high".

  2. The model is shown the vendor's published call list and asked to choose from it. It
     is never asked to write a call name.

  3. Anything it returns that is not in that published list is dropped before the result
     is written anywhere, and the drop is reported. This is the control. Point 2 is an
     instruction and instructions are followed most of the time; point 3 is the thing that
     makes it impossible for an invented call to end up in Maya's profile.

The output of this is checkable by Priya, which is the point of recording the reasoning
next to the answer. A mapping that is wrong is a bug with a name and a confidence, not a
mystery.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Literal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel, Field

from tools.impact import ROOT, canon, load_business

CONFIDENCE = ("high", "medium", "low")


class RoutineMapping(BaseModel):
    """What the setup conversation is allowed to conclude about one routine.

    `confidence` is a closed set rather than a string, because the difference between
    high and medium decides whether Maya is told something or a person is asked first.
    A model that can return "fairly high" can return anything.
    """

    calls: list[str] = Field(
        description="Calls from the supplied list that this routine relies on. Copy them exactly.")
    confidence: Literal["high", "medium", "low"] = Field(
        description=("high: the routine cannot work without these calls. "
                     "medium: these are the likely calls but another design is possible. "
                     "low: a guess from one sentence, needs checking with her developer."))
    why: str = Field(
        description="One or two sentences, addressed to the developer who will check this.")


SETUP_SYSTEM = """You are setting up a watch on one small business owner's suppliers.

You are given one routine, described by the owner in her own words, and the full list of
calls her supplier publishes. Decide which of those calls the routine relies on.

Rules.

* Choose only from the list you are given. Copy each one exactly as it appears. Never
  write a call that is not in the list, and never adjust one to fit.
* Prefer the smallest set that could actually carry out what she describes. Every extra
  call is a morning she gets interrupted about something that is not hers.
* Her words are about outcomes, not software. "The orders turn up in my accounts" means
  something reads orders on one side and writes them on the other. Work out both ends.
* Set confidence honestly. She gave you two sentences. If two different designs would
  both match what she said, that is medium at best.
* `why` is read by a freelance developer who has two days a month and will check this. Give
  her the reasoning, not the conclusion."""


def published_calls(vendor_id: str) -> list[str]:
    """Every call this supplier currently publishes, from the snapshot on disk."""
    path = os.path.join(ROOT, "contracts", "latest", f"{vendor_id}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return sorted(json.load(fh).get("endpoints", {}))


def only_real_calls(chosen: list[str], published: list[str]) -> tuple[list[str], list[str]]:
    """Split what the model chose into calls the supplier actually publishes, and the rest.

    Matching is on the canonical form, so a path parameter the model renamed still counts
    as the same call. An invented call does not.
    """
    index = {canon(c): c for c in published}
    kept, dropped = [], []
    for call in chosen:
        real = index.get(canon(call))
        if real and real not in kept:
            kept.append(real)
        elif not real:
            dropped.append(call)
    return kept, dropped


def derive(routine: dict, vendor_id: str, model=None, published: list[str] | None = None) -> dict:
    """Ask for one routine's mapping, then keep only the part that is real.

    Returns the mapping plus what was dropped, because a mapping that needed three calls
    thrown away is a mapping somebody should look at.
    """
    from strands import Agent

    calls = published if published is not None else published_calls(vendor_id)
    if not calls:
        # ValueError, not SystemExit. This is a library function and a caller is entitled
        # to handle the problem rather than have the interpreter shut down underneath it.
        raise ValueError(f"no snapshot for {vendor_id}. Run tools/snapshot.py first.")

    agent = Agent(model=model, system_prompt=SETUP_SYSTEM, callback_handler=None)
    asked = (
        f"The owner calls this routine: {routine.get('what_maya_calls_it')}\n"
        f"She says: {(routine.get('in_her_words') or '').strip()}\n"
        f"How often: {routine.get('how_often')}\n"
        f"If it stops: {(routine.get('if_it_stops') or '').strip()}\n\n"
        f"Supplier: {vendor_id}\n"
        f"Calls this supplier publishes ({len(calls)}):\n" + "\n".join(calls))

    # `structured_output_model` on the invocation rather than the deprecated
    # `Agent.structured_output` method, which Strands 1.55 warns about at call time.
    result = agent(asked, structured_output_model=RoutineMapping)
    answer: RoutineMapping = result.structured_output
    if answer is None:
        raise ValueError(
            f"the setup conversation returned nothing usable for {routine.get('id')}")
    kept, dropped = only_real_calls(answer.calls, calls)
    return {
        "routine_id": routine.get("id"),
        "vendor": vendor_id,
        "calls": kept,
        "invented": dropped,
        "confidence": answer.confidence,
        "why": answer.why.strip(),
    }


# ---------------------------------------------------------------- verify

def removals_on_record() -> dict[str, str]:
    """Every call a supplier has been recorded removing, and the day they did it.

    Read from contracts/changes.jsonl, which is the day by day record the scheduled job
    has been building since April.
    """
    path = os.path.join(ROOT, "contracts", "changes.jsonl")
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            for change in row.get("changes", []):
                if change.get("kind") == "endpoint_removed" and change.get("endpoint"):
                    key = f"{row['vendor']}|{canon(change['endpoint'])}"
                    if key not in out or row["date"] > out[key]:
                        out[key] = row["date"]
    return out


def verify(business: dict | None = None, quiet: bool = False) -> int:
    """Check every call in Maya's profile against what the supplier publishes now.

    No model. This is the maintenance job, and it splits its findings in two, because the
    two mean opposite things.

      removed   The supplier published this call and then took it away. The profile was
                right. This is the product working, and each one of these is a morning
                Maya was told something.

      phantom   The supplier has never published this call and there is no record of them
                removing it. The profile was wrong when it was written. A watch on a call
                that does not exist can never fire, and nothing would ever say so.

    Only phantoms fail the run. Three were found the first time this was run, in a profile
    that had been in the repository for a fortnight and had passed every other test.
    """
    business = business or load_business()
    removed_on = removals_on_record()
    published: dict[str, list[str]] = {}
    removed: list[tuple] = []
    phantom: list[tuple] = []
    total = 0

    for routine in business.get("routines", []):
        for dep in (routine.get("derived") or {}).get("depends_on", []):
            vendor = dep["vendor"]
            if vendor not in published:
                published[vendor] = published_calls(vendor)
            if not published[vendor]:
                if not quiet:
                    print(f"  {routine['id']:<34} {vendor:<11} no snapshot, cannot check")
                continue
            known = {canon(c) for c in published[vendor]}
            for call in dep.get("calls", []):
                total += 1
                if canon(call) in known:
                    continue
                when = removed_on.get(f"{vendor}|{canon(call)}")
                (removed if when else phantom).append((routine["id"], vendor, call, when))

    if not quiet:
        if removed:
            print("Removed by the supplier. The profile was right, and she was told.\n")
            for rid, vendor, call, when in removed:
                print(f"  {when}  {rid:<34} {vendor:<11} {call}")
            print()
        if phantom:
            print("Never published, and no record of a removal. The profile is wrong.\n")
            for rid, vendor, call, _ in phantom:
                print(f"  {'':<10}  {rid:<34} {vendor:<11} {call}")
            print()
        print(f"{total - len(removed) - len(phantom)} of {total} recorded calls are in the "
              "suppliers' contracts today.")
        print(f"{len(removed)} were taken away by the supplier. {len(phantom)} were never there.")
    return 1 if phantom else 0


# ---------------------------------------------------------------- self test

def self_test() -> int:
    from agent.model_double import ScriptedModel

    # A made up published list, deliberately. These tests are about the filter, not about
    # Square, and using a real snapshot here would make them fail whenever Square moves.
    published = ["GET /v2/orders", "POST /v2/orders/search", "GET /v2/locations",
                 "GET /v2/payments", "POST /v2/refunds"]
    routine = {"id": "orders-into-accounts", "what_maya_calls_it": "Orders going into the accounts",
               "in_her_words": "Every night the day's orders turn up in my accounting software.",
               "how_often": "every night", "if_it_stops": "Ines reconciles from this."}

    # 1. The ordinary case. A valid choice survives intact.
    model = ScriptedModel(structured=[{"calls": ["GET /v2/orders", "GET /v2/locations"],
                                       "confidence": "high", "why": "Reads orders for one shop."}])
    got = derive(routine, "square", model=model, published=published)
    assert got["calls"] == ["GET /v2/orders", "GET /v2/locations"], got
    assert got["confidence"] == "high", got
    assert got["invented"] == [], got
    assert model.structured_calls == 1, model.structured_calls
    print("  a valid mapping is stored exactly as chosen")

    # 2. The control. A call the supplier does not publish never reaches her profile.
    model = ScriptedModel(structured=[{"calls": ["GET /v2/orders", "GET /v2/accounting/sync"],
                                       "confidence": "high", "why": "Invented one."}])
    got = derive(routine, "square", model=model, published=published)
    assert got["calls"] == ["GET /v2/orders"], got
    assert got["invented"] == ["GET /v2/accounting/sync"], got
    print("  an invented call is dropped before it is written anywhere, and reported")

    # 3. A renamed path parameter is the same call, not a new one.
    model = ScriptedModel(structured=[{"calls": ["GET /v2/orders/"], "confidence": "medium",
                                       "why": "Trailing slash."}])
    got = derive(routine, "square", model=model, published=published)
    assert got["calls"] == ["GET /v2/orders"], got
    assert got["invented"] == [], got
    print("  a call written with a trailing slash still matches the published one")

    # 4. The same call twice is stored once.
    model = ScriptedModel(structured=[{"calls": ["GET /v2/orders", "GET /v2/orders"],
                                       "confidence": "low", "why": "Duplicated."}])
    got = derive(routine, "square", model=model, published=published)
    assert got["calls"] == ["GET /v2/orders"], got
    print("  a duplicate choice is stored once")

    # 5. The schema is the control on confidence, not the prompt.
    from pydantic import ValidationError
    try:
        RoutineMapping(calls=[], confidence="fairly high", why="x")
        raise AssertionError("a confidence outside the three allowed values was accepted")
    except ValidationError:
        pass
    print("  a confidence outside high, medium and low is rejected by the schema")

    # 6. The model is shown the supplier's calls, and asked to choose rather than write.
    flat = " ".join(SETUP_SYSTEM.lower().split())
    assert "choose only from the list you are given" in flat
    assert "never write a call that is not in the list" in flat
    assert "copy each one exactly as it appears" in flat
    print("  the prompt asks it to choose from the published list")

    # 7. Maya's profile contains no call her supplier has never published.
    #    Calls the supplier removed are expected to be in here. Those are the three
    #    mornings she was interrupted, and removing them from the profile would delete
    #    the evidence.
    assert verify(quiet=True) == 0, (
        "a call in maya.yaml was never published by that supplier. Run "
        "`python tools/setup.py --verify` to see which.")
    print("  no call in Maya's profile is one her supplier has never published")

    print("\nself test OK: the setup conversation cannot put a call into Maya's profile")
    print("that her supplier does not publish, whatever the model returns.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true", help="no credentials needed")
    ap.add_argument("--verify", action="store_true", help="check the profile against today's contracts")
    args = ap.parse_args()
    if args.verify:
        raise SystemExit(verify())
    raise SystemExit(self_test())
