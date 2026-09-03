"""Still Working, the judgement layer, deployed on Bedrock AgentCore Runtime.

Only this layer is here, and that is the design rather than a shortcut.

  tools/snapshot.py   what changed, in the suppliers' language   deterministic, runs in CI
  tools/impact.py     which of Maya's routines that touches      deterministic, runs in CI
  THIS                whether it actually breaks her, and how    needs a model, runs here

The two deterministic layers are cheap, reproducible and need no credentials, so paying
for a model to run them would be silly and would make them harder to test. They run in the
scheduled job and hand this service the result.

So the runtime bundle carries no contracts, no snapshots, no business profile and no
imports from the repository root. Everything it needs arrives in the payload.

One behaviour differs from the local run, deliberately. There is no human at a console
here, so a Confirm cannot be answered. A break that only implicates a low confidence
mapping is therefore held rather than auto approved, and the caller is told it is waiting
for a person. Silently approving what we said needed checking would make the confidence
level decorative.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from strands.hooks import BeforeToolCallEvent
from strands.interventions import Confirm, Deny, InterventionHandler, Proceed

from model.load import load_model

app = BedrockAgentCoreApp()
log = app.logger

MODEL_ID = os.environ.get("STILL_WORKING_MODEL", "(from model/load.py)")

SYSTEM = """You look after one person's shop. Her name is Maya.

You are given a supplier change and the routine of hers it touches. Decide whether it
actually stops that routine working. If it does, tell her what stopped, what it costs her,
and who to forward it to.

Writing to Maya:

* Never use the words endpoint, parameter, API or version. She does not have those words
  and does not need them. All of that goes in the part addressed to whoever fixes things.
* Call each supplier what she calls it. Use `vendor_address_as` when the supplier is the
  subject or object of a sentence, because it is phrased to fit one. `vendor_in_her_words`
  is her own first-person wording and only works when quoting how she talks about it.
  Never use the company's product name.
* Address the forwarded section to the person named in `business.who_fixes_things`, by
  name. Never write "your developer" when you have been given a name.
* Read `business.who_fixes_things` before telling her when something will be fixed. If that
  person is part time or not on retainer, do not promise same day.
* `business.how_maya_finds_out_today` is how she would otherwise have learned about this.
  It is usually worth one line, because it is the whole value of telling her now.
* No em dashes and no en dashes. Use a comma or start a new sentence.

Timing. You are given the change date and how many days ago it was. Use them as given.
**Never do arithmetic with dates.** Do not subtract days_ago from the date, or add it, or
work out any other date from them. Say "on 14 July" or "about seven weeks ago" using only
what you were handed. A date you calculated is not a fact even when it is written next to
the word FACT.

Certainty, and this is the one that decides whether she keeps reading these.

* That the supplier changed something is a FACT, from their own published record.
* That her routine is affected is an INFERENCE, from a mapping worked out at setup that
  carries a confidence.
* Say each at its real strength. At high confidence "this will have stopped working" is
  fair. At medium, write it as conditional. Never write "your X is broken" as a flat fact
  when what you have is a contract change plus a mapping.
* Give the fact and the inference separately in the forwarded section, so the person who
  can check does not have to trust it.

Call send_to_maya exactly once when something has broken. Do not call it otherwise."""

_DASHES = re.compile(r"\s*[—–]\s*")

_MONTHS = ("january february march april may june july august september october november "
           "december").split()
_MON3 = [m[:3] for m in _MONTHS]
_MONTH_RE = "|".join(_MONTHS + _MON3)
_DATE_IN_TEXT = re.compile(
    r"\b(\d{4}-\d{2}-\d{2})\b"
    r"|\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTH_RE + r")\b"
    r"|\b(" + _MONTH_RE + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.I)


def dates_mentioned(text: str) -> set[tuple[int, int]]:
    """Every (month, day) a piece of text actually asserts.

    A bare month name is not a date. "In December it is worse" is a season, not a claim
    about when something happened, so it must not trip the check.
    """
    found: set[tuple[int, int]] = set()
    for iso, day_first, month_after, month_first, day_after in _DATE_IN_TEXT.findall(text):
        if iso:
            _, m, d = iso.split("-")
            found.add((int(m), int(d)))
        elif day_first:
            found.add((_MONTHS.index(month_after.lower()[:3] and
                                     next(mm for mm in _MONTHS
                                          if mm.startswith(month_after.lower()[:3]))) + 1,
                       int(day_first)))
        elif month_first:
            found.add((_MONTHS.index(next(mm for mm in _MONTHS
                                          if mm.startswith(month_first.lower()[:3]))) + 1,
                       int(day_after)))
    return found


def house_style(text: str) -> str:
    """Maya's note has a house style, enforced where the format is made, not requested."""
    return _DASHES.sub(", ", text or "")


@dataclass
class MayaNote:
    routine: str
    headline: str
    what_happened: str
    what_it_costs: str
    how_late_normally: str
    what_to_do: str
    forward_to: str
    uncertain: bool = False
    uncertainty: str = ""
    for_the_developer: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [self.headline, "", self.what_happened, "",
                 f"What it costs you: {self.what_it_costs}",
                 f"How late you would normally find out: {self.how_late_normally}"]
        if self.uncertain:
            lines += ["", f"I am not certain about this. {self.uncertainty}"]
        lines += ["", f"What to do: {self.what_to_do}", "",
                  f"--- forward this part to {self.forward_to} ---"]
        lines += [f"  {d}" for d in self.for_the_developer]
        out = house_style("\n".join(lines))
        assert "—" not in out and "–" not in out
        return out


class OnlyWhenItCostsHer(InterventionHandler):
    """The interruption rule as a control, not an instruction in a prompt."""

    name = "only-when-it-costs-her"

    def __init__(self, impact: dict) -> None:
        self.impact = impact
        self.outcome = "still_working"
        self.reason = "nothing she depends on is broken"
        self.routine: str | None = None
        self.uncertain = False

    def before_tool_call(self, event: BeforeToolCallEvent, **kwargs):
        if event.tool_use["name"] != "send_to_maya":
            return Proceed(reason="reading only, nothing reaches her")

        breaking = [r for r in self.impact.get("routines_touched", [])
                    if r.get("has_breaking_change")]
        if not breaking:
            total = self.impact.get("vendor_total_changes", 0)
            self.outcome, self.reason = "still_working", (
                f"of {total} changes that day, none broke a routine she depends on")
            return Deny(reason="Do not send this. Nothing she depends on is broken.")

        confident = [r for r in breaking if r.get("mapping_confidence") != "low"]
        if confident:
            top = confident[0]
            self.outcome = "something_broke"
            self.routine = top["what_maya_calls_it"]
            self.reason = "a routine she depends on is broken"
            if top.get("mapping_confidence") == "medium":
                self.uncertain = True
                return Proceed(reason=(
                    "Send it, but the mapping is medium confidence, so the note must say "
                    "what we are unsure about."))
            return Proceed(reason="broken, and the mapping is sound")

        low = breaking[0]
        self.outcome = "held_for_a_person"
        self.routine = low["what_maya_calls_it"]
        self.reason = ("the only thing broken was mapped at low confidence during setup, "
                       "and there is nobody here to confirm it")
        # response=False: nothing reaches her. There is no console to answer a Confirm on,
        # and auto approving what we said needed checking makes the confidence decorative.
        return Confirm(prompt=f"Tell Maya that '{low['what_maya_calls_it']}' is broken?",
                       response=False)


# Set per invocation. A tool cannot see the payload, and the date is the one fact in the
# note that is checkable and therefore the one worth checking.
_ALLOWED_DATE: tuple[int, int] | None = None
_ALLOWED_TEXT: str = ""


@tool
def send_to_maya(routine: str, headline: str, what_happened: str, what_it_costs: str,
                 how_late_normally: str, what_to_do: str, forward_to: str,
                 for_the_developer: str, uncertainty: str = "") -> str:
    """Send Maya a note. This is the only thing that ever reaches her.

    Args:
        routine: what Maya calls the routine that broke.
        headline: one sentence, a consequence in her words.
        what_happened: two sentences, plain English, no supplier vocabulary.
        what_it_costs: what it costs her.
        how_late_normally: how late she would normally have found out.
        what_to_do: the single next action.
        forward_to: who fixes it, by name.
        for_the_developer: the technical detail, one item per line, fact and inference apart.
        uncertainty: if the agent is not sure, what it is not sure about.
    """
    body = "\n".join([headline, what_happened, what_it_costs, how_late_normally,
                      what_to_do, for_the_developer, uncertainty])
    if _ALLOWED_DATE is not None:
        wrong = dates_mentioned(body) - {_ALLOWED_DATE}
        if wrong:
            # Do not render it. Hand the mistake back so the model can correct itself.
            # The first live run stated a date it had calculated by subtracting days_ago
            # from the change date, and put it under the word FACT.
            bad = ", ".join(f"{d:02d}/{m:02d}" for m, d in sorted(wrong))
            return (f"REJECTED: the note mentions {bad}, which is not when this happened. "
                    f"The supplier changed it on {_ALLOWED_TEXT}. Do not calculate dates. "
                    "Use the date given, or say how long ago in words, and call the tool "
                    "again.")

    return MayaNote(
        routine=routine, headline=headline, what_happened=what_happened,
        what_it_costs=what_it_costs, how_late_normally=how_late_normally,
        what_to_do=what_to_do, forward_to=forward_to,
        uncertain=bool(uncertainty), uncertainty=uncertainty,
        for_the_developer=[l for l in for_the_developer.splitlines() if l.strip()],
    ).render()


def _impact_from(payload: dict) -> dict:
    """The payload IS the impact assessment. Accept the three shapes it arrives in.

    Bare, under an "impact" key, or as a JSON string inside "prompt". That last one is not
    tidiness: `agentcore invoke` only offers --prompt, so without it the deployed agent
    cannot be exercised from the CLI at all, and a thing you cannot demonstrate from a
    terminal is a thing you cannot put in a video.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    impact = payload.get("impact", payload)

    if "routines_touched" not in impact and isinstance(payload.get("prompt"), str):
        text = payload["prompt"].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(
                "This agent does not take a chat prompt. It takes the output of "
                "tools/impact.py assess(), as JSON. Pass it as the whole body, under an "
                "'impact' key, or as a JSON string in 'prompt'.") from None
        if isinstance(parsed, dict):
            impact = parsed.get("impact", parsed)

    if "routines_touched" not in impact:
        raise ValueError(
            "payload must be the output of tools/impact.py assess(), bare, under an "
            "'impact' key, or as JSON in 'prompt'. Got keys: "
            + ", ".join(sorted(impact)[:8]))
    return impact


def _date_guard(impact: dict) -> str:
    """Arm the date check for this invocation, and return the date in words.

    The model is given the date and how long ago it was. It does not need to do arithmetic
    with either, and when it tried it produced a wrong date under the word FACT.
    """
    global _ALLOWED_DATE, _ALLOWED_TEXT
    iso = impact.get("date")
    _ALLOWED_DATE, _ALLOWED_TEXT = None, ""
    if not iso:
        return "an unknown date"
    try:
        y, m, d = (int(x) for x in iso.split("-"))
    except ValueError:
        return iso
    _ALLOWED_DATE = (m, d)
    _ALLOWED_TEXT = f"{d} {_MONTHS[m - 1].capitalize()} {y}"
    return _ALLOWED_TEXT


@app.entrypoint
async def invoke(payload: dict, context: Any = None) -> dict:
    impact = _impact_from(payload)
    in_words = _date_guard(impact)
    handler = OnlyWhenItCostsHer(impact)

    agent = Agent(
        model=load_model(),
        system_prompt=SYSTEM,
        tools=[send_to_maya],
        interventions=[handler],
        conversation_manager=NullConversationManager(),
        callback_handler=None,
    )

    log.info("assessing %s %s, %s routines touched", impact.get("vendor"),
             impact.get("date"), len(impact.get("routines_touched", [])))

    result = await agent.invoke_async(
        "Here is today's assessment. Decide whether it reaches Maya, and if it does, "
        f"write her note.\n\nThe supplier made this change on {in_words}, which was "
        f"{impact.get('days_ago')} days ago. Both of those are given to you. Do not "
        "calculate a date from them.\n\n" + repr(impact))

    note = None
    for message in agent.messages:
        for block in message.get("content", []):
            if isinstance(block, dict) and "toolResult" in block:
                content = block["toolResult"].get("content") or []
                if content and isinstance(content[0], dict) and "text" in content[0]:
                    note = content[0]["text"]

    log.info("outcome=%s routine=%s", handler.outcome, handler.routine)

    return {
        "state": handler.outcome,
        "reason": handler.reason,
        "routine": handler.routine,
        "note": note if handler.outcome == "something_broke" else None,
        "carrying_doubt": handler.uncertain,
        "date": impact.get("date"),
        "vendor": impact.get("vendor"),
        "vendor_in_her_words": impact.get("vendor_in_her_words"),
        "changes_that_day": impact.get("vendor_total_changes"),
        "stop_reason": getattr(result, "stop_reason", None),
    }


if __name__ == "__main__":
    app.run()
