"""Prove the deployed judgement layer's outcomes, with no AWS, no model and no repo.

Self-contained on purpose. The runtime bundle is deployed on its own, so a test that
reached back into the repository root would pass here and prove nothing about what
actually ships. The scripted model below is a deliberate duplicate of the one in the
repository's agent/ package: a few lines of duplication is cheaper than coupling a
deployable to a tree it will not be deployed with.

What this does not test is whether Claude writes a good note. Nothing offline can.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from strands.models.model import Model


class ScriptedModel(Model):
    """Replays a fixed script of assistant turns. The Model ABC is four methods."""

    def __init__(self, script: list[dict[str, Any]]):
        self._script, self._turn = list(script), 0
        self._config = {"model_id": "scripted"}

    def update_config(self, **c: Any) -> None:
        self._config.update(c)

    def get_config(self) -> dict:
        return self._config

    async def structured_output(self, output_model, prompt, system_prompt=None, **k) -> AsyncGenerator:
        yield {"output": output_model()}

    async def stream(self, messages, tool_specs=None, system_prompt: Optional[str] = None,
                     **kwargs: Any) -> AsyncIterable[dict]:
        turn = self._script[self._turn] if self._turn < len(self._script) else {"text": "Done."}
        self._turn += 1
        yield {"messageStart": {"role": "assistant"}}
        if "tool" in turn:
            yield {"contentBlockStart": {"start": {"toolUse": {
                "toolUseId": turn.get("id", "t1"), "name": turn["tool"]}}, "contentBlockIndex": 0}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {
                "input": json.dumps(turn.get("input", {}))}}, "contentBlockIndex": 0}}
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}, "contentBlockIndex": 0}}
            yield {"contentBlockDelta": {"delta": {"text": turn["text"]}, "contentBlockIndex": 0}}
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                            "metrics": {"latencyMs": 0}}}


SEND = {
    "tool": "send_to_maya", "id": "c1",
    "input": {
        "routine": "Stock moving between the counter and the website",
        "headline": "Your website may be selling stock it no longer has.",
        "what_happened": "Seven weeks ago your till and bookings removed something the stock sync relies on.",
        "what_it_costs": "A refund, an apology and likely a bad review.",
        "how_late_normally": "a few days, when a second customer complains",
        "what_to_do": "Forward the part below to Priya.",
        "forward_to": "Priya",
        "for_the_developer": ("FACT: GET /v2/inventory/transfers/{transfer_id} removed 51 days ago\n"
                              "INFERENCE (high): the sync reads it"),
    },
}
SCRIPTS = {"send": [SEND, {"text": "Told her."}], "quiet": [{"text": "Nothing to say."}]}

import model.load as ml            # noqa: E402  patched before main imports it
import main                        # noqa: E402


def run(payload: dict, script: str = "send") -> dict:
    ml.load_model = lambda: ScriptedModel(SCRIPTS[script])
    main.load_model = ml.load_model
    return asyncio.run(main.invoke(payload))


def impact(routines, total=8):
    return {"date": "2026-07-14", "vendor": "square", "vendor_total_changes": total,
            "vendor_in_her_words": "my till and my bookings",
            "vendor_address_as": "your till and bookings", "days_ago": 51,
            "business": {"owner": "Maya",
                         "who_fixes_things": "Priya, freelance, two days a month",
                         "how_maya_finds_out_today": "someone tells her"},
            "routines_touched": routines,
            "reaches_maya": any(r["has_breaking_change"] for r in routines)}


HIGH = [{"routine_id": "stock", "what_maya_calls_it": "Stock moving between the counter and the website",
         "mapping_confidence": "high", "has_breaking_change": True, "changes": []}]
MED = [dict(HIGH[0], mapping_confidence="medium")]
LOW = [{"routine_id": "monday", "what_maya_calls_it": "The Monday morning number",
        "mapping_confidence": "low", "has_breaking_change": True, "changes": []}]
NONE = [dict(HIGH[0], has_breaking_change=False)]

failures = []

r = run(impact(HIGH))
assert r["state"] == "something_broke", r
assert r["note"] and "Priya" in r["note"], r
assert "—" not in r["note"] and "–" not in r["note"], "a dash survived the house style"
assert r["carrying_doubt"] is False, r
print(f"high confidence break   -> {r['state']}, note {len(r['note'])} chars")

r = run(impact(MED))
assert r["state"] == "something_broke" and r["carrying_doubt"] is True, r
print(f"medium confidence       -> {r['state']}, carrying doubt")

r = run(impact(LOW))
assert r["state"] == "held_for_a_person", r
assert r["note"] is None, "a held note must never reach her"
print(f"low confidence only     -> {r['state']}, nothing sent")

r = run(impact(NONE), script="quiet")
assert r["state"] == "still_working" and r["note"] is None, r
print(f"nothing she depends on  -> {r['state']}")

try:
    run({"nonsense": True})
    failures.append("a malformed payload was accepted")
except ValueError as exc:
    print(f"malformed payload       -> rejected: {str(exc)[:56]}")

r = run({"impact": impact(HIGH)})
assert r["state"] == "something_broke", r
print("wrapped under 'impact'  -> accepted")

# agentcore invoke only offers --prompt, so the JSON has to survive that route too.
r = run({"prompt": json.dumps(impact(HIGH))})
assert r["state"] == "something_broke", r
print("JSON inside 'prompt'    -> accepted (this is what `agentcore invoke` sends)")

# The first live run stated a date it had calculated, under the word FACT. This is the
# control that stops that reaching Maya, tested against the exact text it produced.
BAD_DATE = {"tool": "send_to_maya", "id": "c1", "input": dict(
    SEND["input"],
    what_happened="Your till and bookings removed part of their system 51 days ago, on May 24th.",
    for_the_developer="FACT: Square removed the endpoint on 2026-05-24 (51 days ago).")}
SCRIPTS["baddate"] = [BAD_DATE, {"text": "corrected"}]
r = run(impact(HIGH), script="baddate")
assert r["note"] is None or "May" not in r["note"], f"a fabricated date reached Maya: {r['note']}"
print("fabricated date         -> rejected before rendering")

assert main.dates_mentioned("In December it is worse") == set(), "a bare month is not a date"
assert main.dates_mentioned("on 14 July, July 14th, 2026-07-14") == {(7, 14)}
print("date detector           -> finds real dates, ignores bare month names")

try:
    run({"prompt": "tell me a joke"})
    failures.append("a chat prompt was accepted")
except ValueError as exc:
    assert "does not take a chat prompt" in str(exc), exc
    print(f"chat prompt             -> rejected: {str(exc)[:52]}")

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("\nOK. Four outcomes, one rejection, one payload shape. No AWS, no repo, no model.")
