#!/usr/bin/env python3
"""One morning, four suppliers, one message.

The rest of this project judges a single supplier's changes at a time. That is the right
unit for the judgement, and the wrong unit for Maya. On 24 April, Xero deleted the employee
section. If Square had also broken something that day, she would have received two separate
notes about two separate parts of her own business, from the same tool, in the same minute.
Two notes is how a person learns to archive the sender.

So the per-supplier agents report to a round-up, which writes the one message she gets.
Strands exposes any agent as a tool with `Agent.as_tool()`, so each supplier's judgement
agent becomes a tool the round-up can call, with its interventions still attached. The
supplier agents keep every control they had. Nothing about the decision to speak moved.

The important constraint, and the reason this does not undo the whole thesis:

    The round-up merges. It never selects.

It is only ever handed notes that have already passed `OnlyWhenItCostsHer`. If no supplier
produced a note, the round-up is never constructed and no model runs at all, which the
self test asserts by counting model calls rather than by trusting the code to be careful.
A round-up that could decide to stay quiet about something that got through would be a
second, softer, prompt-shaped version of the control this project exists to avoid.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strands import Agent

from agent.model_double import ScriptedModel
from agent.notes import house_style
from agent.still_working import build, live_model, prompt_for
from tools.impact import assess, load_business

ROUNDUP_SYSTEM = """You are writing the single message a shop owner gets this morning.

You have one tool per supplier that had something to say. Call every one of them. Each
returns a note that has already been checked and cleared for sending, so your job is not to
decide what is worth telling her.

Your job is to put them together into one message.

* Open with how many things need her attention, in her words, not the suppliers'.
* Keep each note's own headline. Do not summarise a consequence away.
* If two notes are about the same part of her business, say so once and say it is two
  suppliers, rather than repeating her.
* Keep the forwarding section at the bottom, addressed to whoever fixes things, with
  every supplier's technical detail under its own heading. That part is forwarded whole.
* Never drop a note. If you were given three, all three appear.
* No em dashes and no en dashes."""


def suppliers_with_something_to_say(business: dict, records: list[dict],
                                    today: str | None = None) -> list[dict]:
    """The deterministic gate, before any model is constructed.

    `assess` is set membership. On most mornings this returns an empty list and the whole
    expensive layer is never built.
    """
    out = []
    for record in records:
        impact = assess(business, record, today=today)
        if impact["reaches_maya"]:
            out.append({"record": record, "impact": impact})
    return out


def judge(vendor_impact: dict, script: list[dict] | None = None, live: bool = False,
          model=None):
    """One supplier's judgement agent, with its interventions intact."""
    impact = vendor_impact["impact"]
    agent, stamp, decide = build(impact, script, live=live, model=model)
    agent.name = f"supplier_{impact['vendor']}"
    agent.description = (
        f"Judges this morning's changes at {impact['vendor_address_as']} and returns the "
        "note Maya should get, or says nothing needs sending.")
    return agent, stamp, decide


def round_up(business: dict, records: list[dict], scripts: dict[str, list[dict]] | None = None,
             roundup_script: list[dict] | None = None, live: bool = False,
             today: str | None = None):
    """Run the morning. Returns (message, per_supplier, model_calls).

    `model_calls` is counted from the round-up model itself rather than asserted, because
    the claim being made is that a quiet morning costs nothing, and a number I write down
    is not evidence of that. With a scripted model it is `stream_calls`; with a live one
    the round-up either ran or it did not.

    `message` is None when nothing reached her, and on those mornings no round-up agent
    exists. That is the quiet case and it is the common one.
    """
    scripts = scripts or {}
    speaking = suppliers_with_something_to_say(business, records, today)
    if not speaking:
        return None, [], 0

    per_supplier = []
    tools = []
    used_names: set[str] = set()
    for entry in speaking:
        vendor = entry["impact"]["vendor"]
        agent, stamp, decide = judge(entry, scripts.get(vendor), live=live)
        agent(prompt_for(entry["record"], entry["impact"]))
        row = {"vendor": vendor, "sent": decide.sent, "denied": decide.denied,
               "asked": decide.asked, "agent": agent, "decide": decide, "tool_name": None}
        per_supplier.append(row)
        if decide.sent:
            # Two records for the same supplier on one morning is ordinary, and Strands
            # refuses a duplicate tool name, so the name carries a count. Without this the
            # second Xero record of the day crashed the whole morning.
            name = f"supplier_{vendor}"
            while name in used_names:
                name = f"supplier_{vendor}_{len(used_names) + 1}"
            used_names.add(name)
            row["tool_name"] = name
            tools.append(agent.as_tool(
                name=name,
                description=f"The cleared note about {entry['impact']['vendor_address_as']}."))

    cleared = [p for p in per_supplier if p["sent"]]
    if not cleared:
        return None, per_supplier, 0
    if len(cleared) == 1:
        # One supplier, one note. A round-up of one is a model call that can only make the
        # note worse, so it is not made.
        return last_note(cleared[0]["decide"]), per_supplier, 0

    model = live_model() if live else ScriptedModel(roundup_script or [])
    roundup = Agent(model=model, tools=tools, system_prompt=ROUNDUP_SYSTEM,
                    callback_handler=None)

    asked = (f"This morning {len(cleared)} of her suppliers broke something. "
             "Call every tool you have, then write her one message.")
    result = roundup(asked)

    # The round-up's output is the model's own prose rather than something MayaNote
    # rendered, so the house style has to be applied here as well. It was not, and an em
    # dash from a live round-up would have gone straight to her.
    message = house_style(str(result))
    # Counted from the model, not asserted. `stream_calls` is every turn the round-up
    # model took, so it is 0 on a morning where no round-up was ever built.
    return message, per_supplier, getattr(model, "stream_calls", 1)


def last_note(decide) -> str | None:
    """The last note this supplier's agent actually delivered.

    Read from the handler's record of what rendered, not from the last tool result in the
    transcript. A refusal, a denial, and a reply to `read_routine` are all tool results,
    and taking the last one would have handed Maya a JSON blob the first time a live model
    looked up a routine after writing her note.
    """
    return decide.delivered[-1] if decide.delivered else None


# ---------------------------------------------------------------- self test

def _send(routine: str, routine_id: str, detail: str) -> dict:
    return {"tool": "send_to_maya", "id": f"c-{routine_id}", "input": {
        "routine": routine, "headline": f"{routine} may have stopped.",
        "what_happened": "A supplier removed something this relies on.",
        "what_it_costs": "Time and trust.", "how_late_normally": "weeks",
        "what_to_do": "Forward the part below to Priya.", "forward_to": "Priya",
        "for_the_developer": detail}}


QUIET = [
    {"date": "2026-09-10", "vendor": "stripe",
     "changes": [{"kind": "endpoint_added", "endpoint": "POST /v1/tax/registrations",
                  "breaking": False}]},
    {"date": "2026-09-10", "vendor": "shipengine",
     "changes": [{"kind": "param_added", "endpoint": "POST /v1/labels", "param": "note",
                  "breaking": False}]},
]

TWO_AT_ONCE = [
    {"date": "2026-09-10", "vendor": "xero",
     "changes": [{"kind": "endpoint_removed", "endpoint": "GET /Employees", "breaking": True}]},
    {"date": "2026-09-10", "vendor": "square",
     "changes": [{"kind": "endpoint_removed", "endpoint": "GET /v2/orders/{order_id}",
                  "breaking": True}]},
]


def self_test() -> int:
    business = load_business()

    # 1. A quiet morning builds nothing. No agent, no model call, no cost. Counted from
    #    the model rather than from a literal, because the claim is about cost.
    message, per, calls = round_up(business, QUIET)
    assert message is None, message
    assert per == [], per
    assert calls == 0, calls
    print("  a morning where nothing reaches her constructs no agent at all")

    # 2. One supplier, one note, and no round-up model call at all.
    one = [TWO_AT_ONCE[0]]
    scripts = {"xero": [_send("Paying the twelve of us", "payroll", "xero: GET /Employees removed"),
                        {"text": "done"}]}
    message, per, calls = round_up(business, one, scripts)
    assert message and "Paying the twelve of us" in message, message
    assert calls == 0, "a round-up of one is a model call that can only make it worse"
    assert message == per[0]["decide"].delivered[-1], "she got the note the agent rendered"
    print("  one supplier means one note and no second model call")

    # 3. Two suppliers, two cleared notes, and the round-up is handed both of them.
    scripts = {
        "xero": [_send("Paying the twelve of us", "payroll", "xero: GET /Employees removed"),
                 {"text": "done"}],
        "square": [_send("Orders going into the accounts", "orders",
                         "square: GET /v2/orders/{order_id} removed"), {"text": "done"}],
    }
    merged = ("Two things need you this morning.\n\n"
              "Paying the twelve of us may have stopped.\n"
              "Orders going into the accounts may have stopped.\n\n"
              "--- forward this part to Priya ---\n"
              "  xero: GET /Employees removed\n"
              "  square: GET /v2/orders/{order_id} removed\n")
    roundup_model = ScriptedModel([
        {"tool": "supplier_xero", "id": "r1", "input": {"prompt": "go"}},
        {"tool": "supplier_square", "id": "r2", "input": {"prompt": "go"}},
        {"text": merged}])
    message, per, calls = round_up(business, TWO_AT_ONCE, scripts,
                                   roundup_script=roundup_model._script)
    assert calls > 0, calls
    sent_routines = sorted(r for p in per for r in p["sent"])
    assert sent_routines == ["orders-into-accounts", "paying-the-team"], sent_routines
    print("  two suppliers both clear their own controls")

    # 4. The round-up is offered exactly the suppliers that cleared, and no others. This
    #    is the check that catches a merge quietly dropping one, which asserting on the
    #    scripted output cannot: that output is written by the test.
    offered = sorted(p["tool_name"] for p in per if p["tool_name"])
    assert offered == ["supplier_square", "supplier_xero"], offered
    assert all(p["tool_name"] for p in per), "a cleared supplier with no tool is a dropped note"
    print("  the round-up is handed one tool per cleared supplier, and no others")

    # 5. A supplier whose note was denied contributes nothing to the round-up.
    mixed = [TWO_AT_ONCE[0],
             {"date": "2026-09-10", "vendor": "stripe",
              "changes": [{"kind": "endpoint_removed", "endpoint": "GET /v1/issuing/cards",
                           "breaking": True}]}]
    _, per_mixed, calls_mixed = round_up(business, mixed, scripts)
    assert [p["vendor"] for p in per_mixed] == ["xero"], [p["vendor"] for p in per_mixed]
    assert calls_mixed == 0, calls_mixed
    print("  a supplier that broke nothing of hers never becomes a tool")

    # 6. Two records from the same supplier on one morning do not collide.
    twice = [TWO_AT_ONCE[0], dict(TWO_AT_ONCE[0], date="2026-09-10")]
    _, per_twice, _ = round_up(business, twice, scripts)
    names = [p["tool_name"] for p in per_twice if p["tool_name"]]
    assert len(names) == len(set(names)), names
    print("  two records from one supplier get two distinct tool names")

    # 7. The house style reaches the merged message too, which MayaNote never sees.
    dashed = ScriptedModel([
        {"tool": "supplier_xero", "id": "r1", "input": {"prompt": "go"}},
        {"tool": "supplier_square", "id": "r2", "input": {"prompt": "go"}},
        {"text": "Two things \u2014 both need you."}])
    message, _, _ = round_up(business, TWO_AT_ONCE, scripts, roundup_script=dashed._script)
    assert "\u2014" not in message and "\u2013" not in message, message
    print("  the merged message goes through the same house style as a single note")

    # 8. The round-up is told it does not decide, and the tests above are the control.
    flat = " ".join(ROUNDUP_SYSTEM.lower().split())
    assert "your job is not to decide what is worth telling her" in flat
    assert "never drop a note" in flat
    assert "keep each note's own headline" in flat
    assert "no em dashes and no en dashes" in flat
    print("  the round-up is told it does not decide, and tested on it")

    print("\nself test OK: four suppliers, one message, and a quiet morning that")
    print("costs nothing because no agent is ever built.")
    return 0


def demo() -> int:
    business = load_business()
    print("=" * 70)
    print("A QUIET MORNING. Two suppliers changed things. Neither was hers.")
    print("=" * 70)
    message, per, calls = round_up(business, QUIET)
    print(f"agents built  : {len(per)}")
    print(f"model calls   : {calls}")
    print(f"message       : {message or 'Still working.'}")

    print()
    print("=" * 70)
    print("A MORNING WHERE TWO SUPPLIERS BROKE SOMETHING AT ONCE")
    print("=" * 70)
    scripts = {
        "xero": [_send("Paying the twelve of us", "payroll", "xero: GET /Employees removed"),
                 {"text": "done"}],
        "square": [_send("Orders going into the accounts", "orders",
                         "square: GET /v2/orders/{order_id} removed"), {"text": "done"}],
    }
    merged = ("Two things need you this morning.\n\n"
              "Paying the twelve of us may have stopped.\n"
              "Orders going into the accounts may have stopped.\n\n"
              "--- forward this part to Priya ---\n"
              "  xero: GET /Employees removed\n"
              "  square: GET /v2/orders/{order_id} removed\n")
    roundup_script = [{"tool": "supplier_xero", "id": "r1", "input": {"prompt": "go"}},
                      {"tool": "supplier_square", "id": "r2", "input": {"prompt": "go"}},
                      {"text": merged}]
    message, per, calls = round_up(business, TWO_AT_ONCE, scripts, roundup_script)
    print(f"supplier agents        : {[p['vendor'] for p in per]}")
    print(f"notes cleared to send  : {[r for p in per for r in p['sent']]}")
    print(f"messages Maya receives : {1 if message else 0}")
    print()
    print("-" * 70)
    print(message)
    print("-" * 70)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    raise SystemExit(demo() if args.demo else self_test())
