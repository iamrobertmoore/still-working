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
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent
from strands.interventions import Confirm, Deny, InterventionHandler, Proceed, Transform

from agent import memory
from agent.model_double import ScriptedModel
from agent.notes import MayaNote, in_words, wrong_dates_in
from tools.impact import assess, load_business

# The same id the deployed bundle uses, so local and deployed are not quietly different
# models. Set by tools/check_bedrock.py, which finds out which ids this account can
# actually invoke rather than guessing from list-foundation-models.
#
# The default was eu.anthropic.claude-sonnet-4-6 in eu-west-2 until 11 September. That
# region reported "use case details not submitted" for a model that was in fact end of
# life, and us-east-1 said so plainly. Two regions, one model, two errors, one of them
# true. See working notes and tools/check_bedrock.py.
BEDROCK_MODEL = os.environ.get("STILL_WORKING_MODEL",
                               "global.anthropic.claude-sonnet-4-5-20250929-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


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


def is_a_note(text: str) -> bool:
    """Whether this tool result is a note Maya was actually shown.

    Positive recognition rather than a list of known failures. MayaNote always ends with
    the forwarding line, and nothing else the tool can return does.
    """
    return "forward this part to" in (text or "")


def _result_text(result) -> str:
    """The text of a tool result, whatever shape the framework hands it over in."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for block in result.get("content", []) or []:
            if isinstance(block, dict) and "text" in block:
                return block["text"]
    return str(result or "")


def routine_to_report(impact: dict) -> dict | None:
    """Which of the broken routines this note is about.

    One function, used by both handlers, because they were choosing differently. The
    stamper took the first alphabetically and the decision took the first confident one,
    so on a day that broke two routines the note was stamped with the id of a routine it
    was not about. Nothing caught it except reading the demo output.
    """
    breaking = [r for r in impact.get("routines_touched", []) if r["has_breaking_change"]]
    if not breaking:
        return None
    confident = [r for r in breaking if r["mapping_confidence"] != "low"]
    return (confident or breaking)[0]


class StampTheFacts(InterventionHandler):
    """The model writes the words. The code writes the facts.

    Every factual error this project has shipped came from the same place: the model was
    holding a fact and a gap, and filled the gap. It was given a change dated 14 July and
    a `days_ago` of 51, and wrote "on 2026-05-24 (51 days ago)" under the word FACT. It
    had done arithmetic, got it wrong, and presented the result with more confidence than
    anything else in the note.

    The fix is not a firmer instruction. The fix is that the model is never the source of
    a fact that the system already knows. This handler runs before the decision handler
    and overwrites the factual fields of the outgoing note with the values from the
    deterministic layer, whatever the model put there.

    `Transform` mutates the event in place and lets the pipeline continue, so the handler
    that decides whether Maya hears anything at all sees the corrected call.
    """

    name = "stamp-the-facts"

    def __init__(self, impact: dict) -> None:
        self.impact = impact
        self.overwritten: list[str] = []

    def _stamp(self, event: BeforeToolCallEvent) -> None:
        payload = event.tool_use.get("input")
        if not isinstance(payload, dict):
            return
        subject = routine_to_report(self.impact)
        facts = {
            "routine_id": subject["routine_id"] if subject else "",
            "change_date": self.impact.get("date") or "",
            "days_ago": self.impact.get("days_ago"),
        }
        for key, value in facts.items():
            if payload.get(key) not in (None, "", value):
                self.overwritten.append(key)
            payload[key] = value

    def before_tool_call(self, event: BeforeToolCallEvent, **kwargs):
        if event.tool_use["name"] != "send_to_maya":
            return Proceed(reason="not a note")
        return Transform(apply=self._stamp, reason=(
            "The date and the routine are not the model's to supply. They come from the "
            "vendor's own published record and from the deterministic matcher."))


class OnlyWhenItCostsHer(InterventionHandler):
    """The interruption rule, as a control rather than an instruction.

    Deny  : nothing she depends on is broken. She is never told.
    Deny  : she was told about this same routine within the last few days. Xero deleted
            the employee section on 24 April, restored it, and deleted it again on the
            29th. Two notes in five days about her payroll is how she learns to ignore
            the third. See agent/memory.py.
    Confirm: the ONLY routines broken were mapped at low confidence during setup, so a
             person checks before Maya is told her Monday number is wrong.
    Proceed: at least one routine we are confident about is broken.

    The ordering matters and I got it wrong first. Checking for low confidence before
    checking for a confident break meant one shaky mapping could hold up a certain
    problem behind a human. A thing we know is broken goes out now; the uncertainty
    rides along inside the note instead of gating it.
    """

    name = "only-when-it-costs-her"

    def __init__(self, impact: dict, approve_low_confidence: bool = True,
                 quiet_days: int = memory.QUIET_DAYS) -> None:
        self.impact = impact
        self.approve_low_confidence = approve_low_confidence
        self.quiet_days = quiet_days
        self.denied: list[str] = []
        self.asked: list[str] = []
        self.sent: list[str] = []
        self.flagged_uncertain: list[str] = []
        self.suppressed_repeat: list[str] = []
        self.history: list[dict] = []
        self.told_today: list[dict] = []
        self.delivered: list[str] = []
        self.refused: list[str] = []
        self.failed: list[str] = []
        self._pending: dict[str, dict] = {}
        self.agent = None

    def bind(self, agent) -> "OnlyWhenItCostsHer":
        """Take the agent as the record of what Maya has already been told.

        The agent is constructed with a session manager, so its state already carries the
        previous mornings by the time this is called. The ledger is read from there rather
        than from a side file, so there is one record and not two that can disagree.
        """
        self.agent = agent
        self.history = memory.ledger(agent)
        return self

    def _remember(self, routine: dict, use_id: str) -> None:
        """Record this note optimistically, and be ready to take it back.

        Two things have to be true at once and they pull in opposite directions.

        The within-morning repeat bound has to see this note *immediately*, because a model
        can ask to send three at once and a framework is free to run every `before` hook
        before any `after` hook. Waiting for the result meant all three were decided
        against an empty record and all three went out.

        The ledger must record only what actually rendered, because the tool can still
        refuse a note, and a refused note filed as told gets the model's corrected retry
        denied as a repeat of something Maya never saw.

        So: written at decision time, keyed on the tool use id, and retracted in
        `after_tool_call` if that call did not produce a note.
        """
        row = {"routine_id": routine["routine_id"],
               "change_date": self.impact.get("date"),
               "vendor": self.impact.get("vendor"),
               "what_maya_calls_it": routine.get("what_maya_calls_it")}
        self._pending[use_id] = row
        self.told_today.append(row)

    def _retract(self, row: dict, routine_id: str) -> None:
        if row in self.told_today:
            self.told_today.remove(row)
        for i in range(len(self.sent) - 1, -1, -1):
            if self.sent[i] == routine_id:
                del self.sent[i]
                break

    def after_tool_call(self, event: AfterToolCallEvent, **kwargs):
        if event.tool_use["name"] != "send_to_maya":
            return Proceed(reason="not a note")
        row = self._pending.pop(event.tool_use.get("toolUseId"), None)
        if row is None:
            return Proceed(reason="this call was never allowed through")

        rendered = _result_text(event.result)
        # A delivery is recognised by what a delivered note contains, not by the absence
        # of a known failure string. An exception inside the tool comes back as an error
        # message, and matching only on "REJECTED" filed that as a note Maya had been
        # sent, which then blocked the retry and, in the round-up, became her morning.
        if event.exception is not None or not is_a_note(rendered):
            (self.refused if rendered.startswith("REJECTED") else self.failed).append(
                row["routine_id"])
            self._retract(row, row["routine_id"])
            return Proceed(reason="nothing rendered, so nothing reached her")

        self.delivered.append(rendered)
        memory.record(self.agent, row["routine_id"], row["change_date"],
                      row["vendor"], row["what_maya_calls_it"])
        return Proceed(reason="she was told, and the ledger now says so")

    def before_tool_call(self, event: BeforeToolCallEvent, **kwargs):
        if event.tool_use["name"] != "send_to_maya":
            return Proceed(reason="reading only, nothing reaches her")
        use_id = event.tool_use.get("toolUseId") or ""

        touched = self.impact["routines_touched"]
        breaking = [r for r in touched if r["has_breaking_change"]]

        if not breaking:
            self.denied.append("nothing she depends on is broken")
            return Deny(reason=(
                "Do not send this. Of the "
                f"{self.impact['vendor_total_changes']} changes today, none broke a routine "
                "she depends on. Say nothing."))

        # `self.history` is what she was told on earlier mornings. `self.told_today` is
        # what has already gone out during this invocation. Both count, and only the
        # first did until a model that called the tool three times in a row put three
        # identical notes in front of her and nothing stopped it.
        seen_in = self.history + self.told_today
        repeat = next((r for r in breaking
                       if memory.told_recently(seen_in, r["routine_id"],
                                               self.impact.get("date"), self.quiet_days)),
                      None)
        already_today = any(r["routine_id"] == (repeat or {}).get("routine_id")
                            for r in self.told_today)
        if repeat and (len(breaking) == 1 or already_today):
            seen = memory.told_recently(seen_in, repeat["routine_id"],
                                        self.impact.get("date"), self.quiet_days)
            self.suppressed_repeat.append(repeat["routine_id"])
            self.denied.append(
                f"already told her about {repeat['routine_id']} "
                f"{seen['days_since']} days ago")
            return Deny(reason=(
                f"Do not send this. Maya was told about '{repeat['what_maya_calls_it']}' "
                f"{seen['days_since']} days ago and it is still the same routine and the "
                "same supplier. Sending it again teaches her the first one was noise. "
                "Say nothing."))

        confident = [r for r in breaking if r["mapping_confidence"] != "low"]
        if confident:
            top = routine_to_report(self.impact)
            self.sent.append(top["routine_id"])
            self._remember(top, use_id)
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
        if self.approve_low_confidence:
            # A person said yes, so this note goes out and everything downstream that asks
            # "was anything sent" has to see it. It was in the ledger and not in `sent`,
            # which meant agent/morning.py silently produced no message on a morning where
            # a human had explicitly approved one.
            self.sent.append(low["routine_id"])
            self._remember(low, use_id)
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
                 for_the_developer: str, uncertainty: str = "",
                 routine_id: str = "", change_date: str = "", days_ago: int | None = None) -> str:
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
        routine_id: leave blank. Stamped by the system from the deterministic matcher.
        change_date: leave blank. Stamped by the system from the supplier's own record.
        days_ago: leave blank. Stamped by the system. Never calculate a date.
    """
    body = "\n".join([headline, what_happened, what_it_costs, how_late_normally,
                      what_to_do, for_the_developer, uncertainty])
    wrong = wrong_dates_in(body, change_date)
    if wrong:
        # Do not render it. Hand the mistake back so the model can correct itself, which
        # is what the deployed bundle does too. Stamping the right date into the note is
        # not enough on its own: the model can still assert a different one in its own
        # prose, and the first live run did exactly that, under the word FACT.
        bad = ", ".join(f"{d:02d}/{m:02d}" for m, d in sorted(wrong))
        return (f"REJECTED: this note mentions {bad}, which is not when this happened. "
                f"The supplier changed it on {in_words(change_date)}. Do not "
                "calculate dates. Say how long ago it was in words, or say nothing about "
                "when, and call the tool again.")

    # `routine` is not carried into the note. The headline already says what broke in her
    # words, and a second label above it read like a form. The argument stays because it
    # makes the model commit to one routine before it starts writing, and because the
    # stamped `routine_id` next to it is what the system actually uses.
    note = MayaNote(
        still_working=False, headline=headline,
        what_happened=what_happened, what_it_costs=what_it_costs,
        how_late_normally=how_late_normally, what_to_do=what_to_do,
        forward_to=forward_to, uncertain=bool(uncertainty), uncertainty=uncertainty,
        for_the_developer=[l for l in for_the_developer.splitlines() if l.strip()],
        change_date=change_date, days_ago=days_ago,
    )
    return note.render()


def build(impact: dict, script: list[dict] | None = None, approve_low_confidence: bool = True,
          live: bool = False, remember: bool = False, session_id: str = "maya",
          storage_dir: str | None = None, model=None):
    """Assemble the agent for one morning.

    Two interventions, because they are two different jobs:

      1. `StampTheFacts`   overwrites the note's factual fields with the system's own
                           values, so the model is never the source of a date.
      2. `OnlyWhenItCostsHer` decides whether Maya hears anything at all.

    The stamper is registered first and uses `Transform`, which mutates the call in place
    and lets the pipeline continue. What matters is that it runs before the tool, because
    the tool builds the note from those fields and refuses one that asserts a different
    date. The decision handler reads the impact record rather than the payload, so it is
    not sensitive to the order; saying otherwise in an earlier version of this docstring
    described a dependency that did not exist.

    `remember=True` attaches a session, which is what makes "do not tell her the same
    thing twice" possible. It is off by default so the scripted tests stay hermetic.
    """
    stamp = StampTheFacts(impact)
    decide = OnlyWhenItCostsHer(impact, approve_low_confidence)

    kwargs = {}
    if remember:
        kwargs["session_manager"] = memory.session_manager(session_id, storage_dir)

    agent = Agent(
        model=model or (live_model() if live else ScriptedModel(script or [])),
        tools=[read_routine, send_to_maya],
        system_prompt=SYSTEM,
        interventions=[stamp, decide],
        callback_handler=None,
        **kwargs,
    )
    decide.bind(agent)
    return agent, stamp, decide


def prompt_for(change_record: dict, impact: dict) -> str:
    return f"Today's changes from {change_record['vendor']}:\n{json.dumps(impact, indent=1)}"


def run(change_record: dict, script: list[dict] | None = None, approve_low_confidence: bool = True,
        live: bool = False, remember: bool = False, session_id: str = "maya",
        storage_dir: str | None = None, today: str | None = None):
    """Run one day's changes through the agent.

    `live=True` swaps the scripted double for Bedrock. Nothing else changes, which is the
    point of having built against the Model interface rather than against Bedrock.
    """
    business = load_business()
    impact = assess(business, change_record, today=today)
    agent, stamp, handler = build(impact, script, approve_low_confidence, live,
                                  remember, session_id, storage_dir)
    result = agent(prompt_for(change_record, impact))
    handler.result = result
    handler.stamp = stamp
    return impact, handler, agent


async def run_streaming(change_record: dict, script: list[dict] | None = None,
                        live: bool = False, out=None):
    """The same morning, delivered a piece at a time.

    Maya's note is short and a shop owner reading it at 06:00 does not need it to
    typewrite at her. This exists for the operator watching the agent work, and because a
    framework's streaming path is not exercised by calling it synchronously and hoping.
    """
    out = out or sys.stdout
    business = load_business()
    impact = assess(business, change_record)
    agent, stamp, handler = build(impact, script, live=live)

    pieces = 0
    result = None
    async for event in agent.stream_async(prompt_for(change_record, impact)):
        if isinstance(event, dict):
            chunk = event.get("data")
            if chunk:
                pieces += 1
                out.write(chunk)
                out.flush()
            if "result" in event:
                result = event["result"]
    out.write("\n")
    # The same attributes `run` attaches, so a streamed morning can be inspected the same
    # way. Without this, cost_of_the_morning(handler.result) raised AttributeError on the
    # one code path nothing called it from.
    handler.result = result
    handler.stamp = stamp
    return impact, handler, pieces


def cost_of_the_morning(result) -> str:
    """What the judgement layer cost, from the framework's own accounting.

    Worth printing because the claim this project makes is that the expensive layer runs
    rarely. A number from `result.metrics` is that claim audited by the framework rather
    than asserted by me.
    """
    m = getattr(result, "metrics", None)
    if m is None:
        return "no metrics on this result"
    summary = m.get_summary()
    usage = summary.get("accumulated_usage", {})
    return (f"cycles {summary.get('total_cycles', 0)}   "
            f"tokens in {usage.get('inputTokens', 0)} out {usage.get('outputTokens', 0)}   "
            f"model time {summary.get('accumulated_metrics', {}).get('latencyMs', 0)} ms")


# ---------------------------------------------------------------- demo

SEND = {
    "tool": "send_to_maya", "id": "c1",
    "input": {
        "routine": "Orders going into the accounts",
        "headline": "Your orders stopped going into the accounts on Tuesday.",
        "what_happened": ("The till software removed the way it hands over a single order, and "
                          "the nightly hand-off to your accounts no longer picks up your shop. "
                          "The shop is fine. Money is still arriving. It is only the copy into "
                          "the accounts that stopped."),
        "what_it_costs": ("Ines reconciles from this, so she is doing it by hand from Tuesday "
                          "onward, and the VAT return is built on it."),
        "how_late_normally": "three weeks, which is what happened last time",
        "what_to_do": "Forward the part below to Priya. It is about an hour of her time.",
        "forward_to": "Priya",
        "for_the_developer": ("square: GET /v2/orders/{order_id} removed\n"
                              "the nightly sync reads each order through it before writing to Xero"),
    },
}

BRIEF_CHANGE = {
    "date": "2026-09-02", "vendor": "square",
    "changes": [
        {"kind": "endpoint_removed", "endpoint": "GET /v2/orders/{order_id}", "breaking": True},
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


# The real thing, from contracts/changes.jsonl. Xero deleted the employee section on
# 24 April, put it back, and deleted it again on the 29th. Both days are breaking and both
# land on "Paying the twelve of us". The second note is the one that would have taught
# Maya the first was noise.
XERO_24_APR = {
    "date": "2026-04-24", "vendor": "xero",
    "changes": [
        {"kind": "endpoint_removed", "endpoint": "GET /Employees", "breaking": True},
        {"kind": "endpoint_removed", "endpoint": "GET /Employees/{EmployeeID}", "breaking": True},
    ],
}

XERO_29_APR = {
    "date": "2026-04-29", "vendor": "xero",
    "changes": [
        {"kind": "endpoint_removed", "endpoint": "GET /Employees", "breaking": True},
        {"kind": "endpoint_removed", "endpoint": "GET /Employees/{EmployeeID}", "breaking": True},
    ],
}

PAYROLL_SEND = {
    "tool": "send_to_maya", "id": "c9",
    "input": {
        "routine": "Paying the twelve of us",
        "headline": "Paying the twelve of you may have stopped working last Friday.",
        "what_happened": ("Your accounts software removed the part that lists your staff. "
                          "Payroll reads that list every month."),
        "what_it_costs": "Twelve people not paid on time, and you would find out from them.",
        "how_late_normally": "the day somebody is not paid",
        "what_to_do": "Forward the part below to Priya before the next run.",
        "forward_to": "Priya",
        "for_the_developer": "xero: GET /Employees removed",
    },
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
    breaking_today = sum(1 for c in QUIET_DAY["changes"] if c["breaking"])
    print(f"of which were breaking           : {breaking_today}")
    print(f"routines touched                 : {[r['routine_id'] for r in impact2['routines_touched']]}")
    print(f"reached Maya                     : {bool(handler2.sent)}")
    print(f"blocked by the intervention      : {handler2.denied}")
    print()
    print("WHAT MAYA SEES")
    print("-" * 70)
    print(MayaNote(still_working=True, headline="", what_happened="",
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
    print(f"the person said yes, so it went    : {handler4.sent}")

    print()
    print("=" * 70)
    print("APRIL, FOR REAL. Xero deleted the employee section, restored it, deleted it again.")
    print("=" * 70)
    import tempfile
    with tempfile.TemporaryDirectory() as store:
        i5, h5, _ = run(XERO_24_APR, [PAYROLL_SEND, {"text": "Told her."}],
                        remember=True, session_id="demo", storage_dir=store)
        print(f"24 April, told her               : {h5.sent}")
        i6, h6, _ = run(XERO_29_APR, [PAYROLL_SEND, {"text": "Told her again."}],
                        remember=True, session_id="demo", storage_dir=store)
        print(f"29 April, same routine, same shop: {h6.sent or 'nothing sent'}")
        print(f"held back as a repeat            : {h6.suppressed_repeat}")
        for d in h6.denied:
            print(f"why                              : {d}")

    print()
    print("WHAT THE JUDGEMENT LAYER COST")
    print("-" * 70)
    print(f"day one (she was told)  : {cost_of_the_morning(handler.result)}")
    print(f"day two (she was not)   : {cost_of_the_morning(handler2.result)}")
    print("The expensive layer runs on every change that reaches a routine. What it")
    print("decides is whether anything leaves the building.")

    assert handler.sent == ["orders-into-accounts"], handler.sent
    assert handler2.sent == [] and handler2.denied, (handler2.sent, handler2.denied)
    assert handler3.sent == ["orders-into-accounts"], handler3.sent
    assert handler3.asked == [], handler3.asked
    assert handler4.asked == ["monday-figure"], handler4.asked
    assert handler4.sent == ["monday-figure"], handler4.sent
    assert h5.sent == ["paying-the-team"], h5.sent
    assert h6.sent == [], h6.sent
    assert h6.suppressed_repeat == ["paying-the-team"], h6.suppressed_repeat
    assert handler.stamp.overwritten == [], handler.stamp.overwritten
    print()
    print("OK. Over six days she was told three times, asked a person once before a")
    print("fourth, was never bothered with the two breaking changes that were not hers,")
    print("and was never told the same thing twice.")
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


NOTES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "contracts", "notes")


def save_note(row: dict, text: str) -> str:
    """Keep the note the model actually wrote.

    The page Maya looks at has to show what she was told, not a placeholder. Storing the
    real generated note means the published page is the product's own output rather than
    a mock of it, and the file is diffable so a bad note is visible in review.
    """
    os.makedirs(NOTES, exist_ok=True)
    path = os.path.join(NOTES, f"{row['date']}-{row['vendor']}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")
    return path


def live_once(date: str | None = None, save: bool = False) -> int:
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
        text = notes[-1]["content"][0]["text"]
        print(text)
        if save:
            print(f"\n(saved to {os.path.relpath(save_note(row, text), os.path.dirname(NOTES))})")
    else:
        print(MayaNote(still_working=True, headline="", what_happened="",
                       what_it_costs="", how_late_normally="", what_to_do="",
                       forward_to="").render())
    print("-" * 70)
    print()
    print(f"sent                : {handler.sent}")
    print(f"carrying doubt      : {handler.flagged_uncertain}")
    print(f"held for a person   : {handler.asked}")
    print(f"blocked             : {handler.denied}")
    return 0


def start_tracing() -> None:
    """Print every step of the agent loop to the console.

    Strands emits OpenTelemetry spans for the model calls, the tool calls and the
    interventions. Turning the console exporter on is one line and it is the fastest way
    to answer "why did it do that", which on this project is usually "an intervention
    stopped it" rather than anything the model decided.
    """
    from strands.telemetry import StrandsTelemetry
    StrandsTelemetry().setup_console_exporter()


def stream_demo() -> int:
    """The same first day, delivered a piece at a time."""
    import asyncio
    print("Streaming one morning. The note arrives as it is written.\n")
    impact, handler, pieces = asyncio.run(
        run_streaming(BRIEF_CHANGE, [SEND, {"text": "Told her, and here is why it mattered."}]))
    print(f"\narrived in {pieces} pieces   sent: {handler.sent}")
    assert pieces > 1, "streamed in one lump, which is not streaming"
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="six scripted days, no credentials")
    ap.add_argument("--stream", action="store_true", help="one day, streamed as it is written")
    ap.add_argument("--live", action="store_true", help="one real recorded change, via Bedrock")
    ap.add_argument("--date", default=None, help="which recorded change to use with --live")
    ap.add_argument("--save", action="store_true", help="store the note under contracts/notes/")
    ap.add_argument("--trace", action="store_true", help="print every model, tool and intervention span")
    args = ap.parse_args()
    if args.trace:
        start_tracing()
    if args.stream:
        raise SystemExit(stream_demo())
    if args.live:
        raise SystemExit(live_once(args.date, save=args.save))
    raise SystemExit(demo())
