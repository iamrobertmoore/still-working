#!/usr/bin/env python3
"""Still Working: the agent that decides whether a vendor change reaches Maya.

Three layers, and keeping them apart is the whole design.

  1. tools/snapshot.py  What changed, in the vendors' language. Deterministic.
  2. tools/impact.py    Which of Maya's routines that touches. Deterministic, set membership.
  3. this file          Whether it actually breaks her, and how to say it. Judgement.

Only the third layer needs a model, and it is the only layer where being wrong is a
matter of degree rather than a bug.

The interruption rule lives in a Strands intervention rather than in a prompt. A prompt
that says "only tell her when it matters" is a probability. `Deny` on before_tool_call is
a control. The difference matters because the failure mode of the prompt version is
silent: it pings her about nothing for a fortnight and she stops reading.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent
from strands.interventions import Confirm, Deny, InterventionHandler, Proceed

from agent.model_double import ScriptedModel
from agent.notes import MayaNote
from tools.impact import assess, load_business

# Set by tools/check_bedrock.py, which finds out which ids this account can actually
# invoke rather than guessing from list-foundation-models.
BEDROCK_MODEL = os.environ.get("STILL_WORKING_MODEL", "eu.anthropic.claude-sonnet-4-6")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")


def live_model():
    """The real model. One line, and no agent code moves to get here."""
    from strands.models.bedrock import BedrockModel
    return BedrockModel(model_id=BEDROCK_MODEL, region_name=AWS_REGION, max_tokens=1200)

SYSTEM = """You look after one person's shop. Her name is Maya.

You are given a supplier change and the routine of hers it touches. Decide whether it
actually stops that routine working. If it does, tell her what stopped, what it costs her,
and who to forward it to.

Writing to Maya:

* Never use the words endpoint, parameter, API or version. She does not have those words
  and does not need them. All of that goes in the part addressed to whoever fixes things.
* Call each supplier what she calls it. Use `vendor_address_as` when the supplier is the
  subject or object of a sentence, because it is phrased to fit one. `vendor_in_her_words`
  is her own first-person wording and only works when you are quoting how she talks about
  it. Never use the company's product name.
* Address the forwarded section to the person named in `business.who_fixes_things`, by
  name. Never write "your developer" when you have been given a name.
* Read `business.who_fixes_things` before telling her when something will be fixed. If that
  person is part time or not on retainer, do not promise same day.
* `business.how_maya_finds_out_today` is how she would otherwise have learned about this.
  It is usually worth one line, because it is the whole value of telling her now.
* No em dashes and no en dashes. Use a comma or start a new sentence.

Timing. Use `days_ago`, which is how long ago the supplier made the change. Say it plainly
in her terms, "seven weeks ago", "on Tuesday". Never invent recency. If you do not know
when something happened, do not imply that you do.

Certainty, and this is the one that decides whether she keeps reading these.

* That the supplier changed something is a FACT. It is in their own published record.
* That her routine is affected is an INFERENCE, from a mapping that was worked out during
  setup and carries a confidence.
* Say each at its real strength. At high confidence "this will have stopped working" is
  fair. At medium, write it as conditional: what the routine relies on, and what will have
  happened if it does. Never write "your X is broken" as a flat statement of fact when what
  you have is a contract change plus a mapping.
* The forwarded section is read by someone who can check. Give them the fact and the
  inference separately so they can verify the second one rather than trusting it.

If the mapping between her routine and the changed call is uncertain, say so plainly rather
than sounding sure."""


class OnlyWhenItCostsHer(InterventionHandler):
    """The interruption rule, as a control rather than an instruction.

    Deny  : nothing she depends on is broken. She is never told.
    Confirm: the ONLY routines broken were mapped at low confidence during setup, so a
             person checks before Maya is told her Monday number is wrong.
    Proceed: at least one routine we are confident about is broken.

    The ordering matters and I got it wrong first. Checking for low confidence before
    checking for a confident break meant one shaky mapping could hold up a certain
    problem behind a human. A thing we know is broken goes out now; the uncertainty
    rides along inside the note instead of gating it.
    """

    name = "only-when-it-costs-her"

    def __init__(self, impact: dict, approve_low_confidence: bool = True) -> None:
        self.impact = impact
        self.approve_low_confidence = approve_low_confidence
        self.denied: list[str] = []
        self.asked: list[str] = []
        self.sent: list[str] = []
        self.flagged_uncertain: list[str] = []

    def before_tool_call(self, event: BeforeToolCallEvent, **kwargs):
        if event.tool_use["name"] != "send_to_maya":
            return Proceed(reason="reading only, nothing reaches her")

        touched = self.impact["routines_touched"]
        breaking = [r for r in touched if r["has_breaking_change"]]

        if not breaking:
            self.denied.append("nothing she depends on is broken")
            return Deny(reason=(
                "Do not send this. Of the "
                f"{self.impact['vendor_total_changes']} changes today, none broke a routine "
                "she depends on. Say nothing."))

        confident = [r for r in breaking if r["mapping_confidence"] != "low"]
        if confident:
            top = confident[0]
            self.sent.append(top["routine_id"])
            if top["mapping_confidence"] == "medium":
                self.flagged_uncertain.append(top["routine_id"])
                return Proceed(reason=(
                    f"'{top['what_maya_calls_it']}' is broken. Send it, but the mapping is "
                    "medium confidence, so the note must say what we are unsure about. "
                    "Telling her something is wrong and sounding certain when we are not is "
                    "how she stops believing the next one."))
            return Proceed(reason=(
                f"'{top['what_maya_calls_it']}' is broken and we are confident the routine "
                "really leans on that call. Send it now."))

        low = breaking[0]
        self.asked.append(low["routine_id"])
        return Confirm(
            prompt=(f"We think this breaks '{low['what_maya_calls_it']}', but that is the only "
                    "thing broken and it was mapped at low confidence during setup. Tell Maya?"),
            response=self.approve_low_confidence,
        )


@tool
def read_routine(routine_id: str) -> str:
    """Read one of Maya's routines in her own words.

    Args:
        routine_id: the routine's id, for example orders-into-accounts.
    """
    business = load_business()
    for r in business["routines"]:
        if r["id"] == routine_id:
            return json.dumps({k: v for k, v in r.items() if k != "derived"}, default=str)
    return f"no routine called {routine_id}"


@tool
def send_to_maya(routine: str, headline: str, what_happened: str, what_it_costs: str,
                 how_late_normally: str, what_to_do: str, forward_to: str,
                 for_the_developer: str, uncertainty: str = "") -> str:
    """Send Maya a note. This is the only thing that ever reaches her.

    Args:
        routine: what Maya calls the routine that broke.
        headline: one sentence, a consequence in her words.
        what_happened: two sentences, plain English, no vendor vocabulary.
        what_it_costs: what it costs her.
        how_late_normally: how late she would normally have found out.
        what_to_do: the single next action.
        forward_to: who fixes it.
        for_the_developer: the technical detail, one item per line.
        uncertainty: if the agent is not sure, what it is not sure about.
    """
    note = MayaNote(
        still_working=False, routine=routine, headline=headline,
        what_happened=what_happened, what_it_costs=what_it_costs,
        how_late_normally=how_late_normally, what_to_do=what_to_do,
        forward_to=forward_to, uncertain=bool(uncertainty), uncertainty=uncertainty,
        for_the_developer=[l for l in for_the_developer.splitlines() if l.strip()],
    )
    return note.render()


def run(change_record: dict, script: list[dict] | None = None, approve_low_confidence: bool = True,
        live: bool = False):
    """Run one day's changes through the agent.

    `live=True` swaps the scripted double for Bedrock. Nothing else changes, which is the
    point of having built against the Model interface rather than against Bedrock.
    """
    business = load_business()
    impact = assess(business, change_record)
    handler = OnlyWhenItCostsHer(impact, approve_low_confidence)

    agent = Agent(
        model=live_model() if live else ScriptedModel(script or []),
        tools=[read_routine, send_to_maya],
        system_prompt=SYSTEM,
        interventions=[handler],
        callback_handler=None,
    )
    agent(f"Today's changes from {change_record['vendor']}:\n{json.dumps(impact, indent=1)}")
    return impact, handler, agent


# ---------------------------------------------------------------- demo

SEND = {
    "tool": "send_to_maya", "id": "c1",
    "input": {
        "routine": "Orders going into the accounts",
        "headline": "Your orders stopped going into the accounts on Tuesday.",
        "what_happened": ("The till software changed how it hands over the day's orders, and "
                          "the nightly hand-off to your accounts no longer picks up your shop. "
                          "The shop is fine. Money is still arriving. It is only the copy into "
                          "the accounts that stopped."),
        "what_it_costs": ("Ines reconciles from this, so she is doing it by hand from Tuesday "
                          "onward, and the VAT return is built on it."),
        "how_late_normally": "three weeks, which is what happened last time",
        "what_to_do": "Forward the part below to Priya. It is about an hour of her time.",
        "forward_to": "Priya",
        "for_the_developer": ("square 2026-09-02: parameter location_id removed from GET /v2/orders\n"
                              "the nightly sync uses it to select this location's orders"),
    },
}

BRIEF_CHANGE = {
    "date": "2026-09-02", "vendor": "square",
    "changes": [
        {"kind": "param_removed", "endpoint": "GET /v2/orders", "param": "location_id", "breaking": True},
        {"kind": "endpoint_added", "endpoint": "POST /v2/loyalty/promotions", "breaking": False},
        {"kind": "param_added", "endpoint": "GET /v2/team-members", "param": "cursor", "breaking": False},
        {"kind": "version_string_changed", "from": "2.0", "to": "2.0", "breaking": False},
    ],
}

QUIET_DAY = {
    "date": "2026-09-03", "vendor": "stripe",
    "changes": [
        {"kind": "endpoint_removed", "endpoint": "GET /v1/issuing/cards", "breaking": True},
        {"kind": "param_removed", "endpoint": "POST /v1/terminal/readers", "param": "label", "breaking": True},
        {"kind": "endpoint_added", "endpoint": "POST /v1/tax/registrations", "breaking": False},
    ],
}

# GET /v2/locations is leaned on by both orders-into-accounts (high) and monday-figure
# (low), so a confident break and a shaky one arrive together. She should be told.
MIXED_DAY = {
    "date": "2026-09-08", "vendor": "square",
    "changes": [
        {"kind": "endpoint_removed", "endpoint": "GET /v2/locations", "breaking": True},
    ],
}

# GET /v2/payments is the only call monday-figure leans on that nothing else does, which
# is what makes a low-confidence-only day possible at all. See the note in maya.yaml.
LOW_ONLY_DAY = {
    "date": "2026-09-09", "vendor": "square",
    "changes": [
        {"kind": "param_became_required", "endpoint": "GET /v2/payments",
         "param": "begin_time", "breaking": True},
    ],
}


def demo() -> int:
    print("=" * 70)
    print("DAY ONE. Four changes at the till software. One of them matters.")
    print("=" * 70)
    impact, handler, agent = run(BRIEF_CHANGE, [SEND, {"text": "Told her."}])
    print(f"changes the vendor made          : {impact['vendor_total_changes']}")
    print(f"changes Maya does not depend on  : {impact['ignored_count']}")
    print(f"routines touched                 : {[r['routine_id'] for r in impact['routines_touched']]}")
    print(f"reached Maya                     : {bool(handler.sent)}")
    print()
    note = [b["toolResult"] for m in agent.messages for b in m.get("content", [])
            if isinstance(b, dict) and "toolResult" in b]
    print("WHAT MAYA SEES")
    print("-" * 70)
    print(note[0]["content"][0]["text"])
    print("-" * 70)

    print()
    print("=" * 70)
    print("DAY TWO. Three breaking changes at the payment processor. None of them hers.")
    print("=" * 70)
    impact2, handler2, agent2 = run(QUIET_DAY, [SEND, {"text": "Said nothing."}])
    print(f"changes the vendor made          : {impact2['vendor_total_changes']}")
    print(f"of which were breaking           : 2")
    print(f"routines touched                 : {[r['routine_id'] for r in impact2['routines_touched']]}")
    print(f"reached Maya                     : {bool(handler2.sent)}")
    print(f"blocked by the intervention      : {handler2.denied}")
    print()
    print("WHAT MAYA SEES")
    print("-" * 70)
    print(MayaNote(still_working=True, routine="", headline="", what_happened="",
                   what_it_costs="", how_late_normally="", what_to_do="",
                   forward_to="").render())
    print("-" * 70)

    print()
    print("=" * 70)
    print("DAY THREE. One change breaks something certain and something shaky at once.")
    print("=" * 70)
    impact3, handler3, _ = run(MIXED_DAY, [SEND, {"text": "Told her."}])
    print(f"routines touched                 : {[r['routine_id'] for r in impact3['routines_touched']]}")
    print(f"mapping confidence               : {[r['mapping_confidence'] for r in impact3['routines_touched']]}")
    print(f"sent without waiting for a person: {handler3.sent}")
    print(f"held for a person                : {handler3.asked}")

    print()
    print("=" * 70)
    print("DAY FOUR. The only thing broken is the one we were never sure about.")
    print("=" * 70)
    impact4, handler4, _ = run(LOW_ONLY_DAY, [SEND, {"text": "Asked first."}])
    print(f"routines touched                 : {[r['routine_id'] for r in impact4['routines_touched']]}")
    print(f"mapping confidence               : {[r['mapping_confidence'] for r in impact4['routines_touched']]}")
    print(f"asked a person before telling her: {handler4.asked}")

    assert handler.sent == ["orders-into-accounts"], handler.sent
    assert handler2.sent == [] and handler2.denied, (handler2.sent, handler2.denied)
    assert handler3.sent == ["orders-into-accounts"], handler3.sent
    assert handler3.asked == [], handler3.asked
    assert handler4.asked == ["monday-figure"], handler4.asked
    assert handler4.sent == [], handler4.sent
    print()
    print("OK. Over four days she was told twice, held once for a person, and never")
    print("bothered with the two breaking changes that were not hers.")
    return 0


def explain_aws_failure(exc: Exception) -> int:
    """Say the one thing that matters, not eighty lines of stack.

    A credentials problem surfaces from deep inside botocore, and the default is a
    traceback whose last line is the only useful part. Reusing the hints from
    tools/check_bedrock.py so there is one place that knows what these errors mean.
    """
    from tools.check_bedrock import HINTS

    name = type(exc).__name__
    text = str(exc)
    print(f"\n{name}: {text}\n", file=sys.stderr)
    hint = next((h for k, h in HINTS.items() if k in name or k in text), None)
    if hint:
        print(hint, file=sys.stderr)
    else:
        print("Run `python tools/check_bedrock.py` to diagnose this properly.", file=sys.stderr)
    return 2


def live_once(date: str | None = None) -> int:
    """Run one real recorded change through the real model, and print what Maya gets."""
    business = load_business()
    rows = [json.loads(l) for l in open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "contracts", "changes.jsonl"), encoding="utf-8")]
    reaching = [r for r in rows if assess(business, r)["reaches_maya"]]
    if not reaching:
        print("no recorded change reaches Maya, run tools/backfill.py first")
        return 1
    row = next((r for r in reaching if r["date"] == date), reaching[-1])

    print(f"model  {BEDROCK_MODEL} in {AWS_REGION}")
    print(f"event  {row['date']} {row['vendor']}, {row['total_count']} changes that day\n")

    try:
        impact, handler, agent = run(row, live=True)
    except Exception as exc:                       # noqa: BLE001, we re-raise the meaning
        return explain_aws_failure(exc)

    notes = [b["toolResult"] for m in agent.messages for b in m.get("content", [])
             if isinstance(b, dict) and "toolResult" in b]

    print("WHAT MAYA SEES")
    print("-" * 70)
    if handler.sent and notes:
        print(notes[-1]["content"][0]["text"])
    else:
        print(MayaNote(still_working=True, routine="", headline="", what_happened="",
                       what_it_costs="", how_late_normally="", what_to_do="",
                       forward_to="").render())
    print("-" * 70)
    print()
    print(f"sent                : {handler.sent}")
    print(f"carrying doubt      : {handler.flagged_uncertain}")
    print(f"held for a person   : {handler.asked}")
    print(f"blocked             : {handler.denied}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="four scripted days, no credentials")
    ap.add_argument("--live", action="store_true", help="one real recorded change, via Bedrock")
    ap.add_argument("--date", default=None, help="which recorded change to use with --live")
    args = ap.parse_args()
    if args.live:
        raise SystemExit(live_once(args.date))
    raise SystemExit(demo())
