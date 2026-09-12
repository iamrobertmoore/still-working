"""A deterministic Strands model provider, for running the agent without credentials.

The Strands Model base class has four abstract methods. Implementing them against a fixed
script makes the whole agent loop runnable with no AWS account, no network and no
flakiness, which is how the tests run in well under a second.

This is a test double. It has no judgement. Swapping it for BedrockModel is a one line
change and the agent code does not move.

It implements `structured_output` for real, rather than yielding an empty instance, because
tools/setup.py depends on structured output and a double that cannot fail the same way the
real thing fails is not testing anything. It also counts its own calls, which is how the
tests assert that a quiet morning costs zero model invocations.
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator, AsyncIterable, Optional

from strands.models.model import Model


class ScriptedModel(Model):
    """Replays a fixed script of turns. One turn consumed per `stream` call.

    A turn is one of:

      {"tool": name, "input": {...}}     one tool call
      {"tools": [{...}, {...}]}          several tool calls in one assistant message
      {"text": "..."}                    plain text

    The middle form exists because a real model can ask for several tools at once, and a
    framework is free to run every before-hook before any after-hook. Bookkeeping that
    looked correct one call at a time was wrong in that case, and a double that could only
    emit one call at a time could never have shown it.

    Running off the end of the script yields a plain "Done." rather than raising, so a test
    that only cares about the first two turns does not have to pad the script.
    """

    def __init__(self, script: list[dict[str, Any]] | None = None,
                 structured: list[Any] | None = None):
        self._script = list(script or [])
        self._structured = list(structured or [])
        self._turn = 0
        self._config: dict[str, Any] = {"model_id": "scripted"}
        self.seen_tool_specs: list[str] = []
        self.seen_system_prompts: list[str] = []
        self.stream_calls = 0
        self.structured_calls = 0

    # ---- Model interface, all four abstract methods

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self._config

    async def structured_output(self, output_model, prompt, system_prompt=None,
                                **kwargs) -> AsyncGenerator:
        """Hand back the next queued object, validated against the caller's model.

        Validating rather than trusting matters: tools/setup.py asks for a shape it then
        writes into Maya's profile, and a double that returned any old object would let a
        schema change pass the tests and fail in front of a judge.
        """
        self.structured_calls += 1
        if system_prompt:
            self.seen_system_prompts.append(system_prompt)
        if not self._structured:
            yield {"output": output_model()}
            return
        nxt = self._structured.pop(0)
        if isinstance(nxt, output_model):
            yield {"output": nxt}
        elif isinstance(nxt, dict):
            yield {"output": output_model(**nxt)}
        else:
            yield {"output": output_model.model_validate(nxt)}

    async def stream(self, messages, tool_specs=None, system_prompt: Optional[str] = None,
                     **kwargs: Any) -> AsyncIterable[dict]:
        self.stream_calls += 1
        if tool_specs:
            self.seen_tool_specs = [s["name"] for s in tool_specs]
        if system_prompt:
            self.seen_system_prompts.append(system_prompt)

        # Strands 1.55 fulfils `structured_output_model=` by forcing a tool call named
        # after the pydantic class, rather than by calling `Model.structured_output`. A
        # double that only implemented the latter would pass its own tests and fail
        # against Bedrock, so the queued structured payload is delivered the same way the
        # real model delivers it: as a tool call the framework then validates.
        if self._structured and tool_specs:
            self.structured_calls += 1
            payload = self._structured.pop(0)
            if hasattr(payload, "model_dump"):
                payload = payload.model_dump()
            name = tool_specs[0]["name"]
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {"toolUse": {
                "toolUseId": f"so{self.structured_calls}", "name": name}},
                "contentBlockIndex": 0}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(payload)}},
                                         "contentBlockIndex": 0}}
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
            yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                                "metrics": {"latencyMs": 0}}}
            return

        turn = self._script[self._turn] if self._turn < len(self._script) else {"text": "Done."}
        self._turn += 1

        yield {"messageStart": {"role": "assistant"}}
        if "tool" in turn or "tools" in turn:
            calls = turn.get("tools") or [turn]
            for i, call in enumerate(calls):
                yield {"contentBlockStart": {"start": {"toolUse": {
                    "toolUseId": call.get("id", f"t{self._turn}_{i}"), "name": call["tool"]}},
                    "contentBlockIndex": i}}
                yield {"contentBlockDelta": {
                    "delta": {"toolUse": {"input": json.dumps(call.get("input", {}))}},
                    "contentBlockIndex": i}}
                yield {"contentBlockStop": {"contentBlockIndex": i}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            # Delivered in pieces, so a test of the streaming path sees more than one
            # chunk. A single-chunk double would pass a streaming test that streams nothing.
            text = turn["text"]
            yield {"contentBlockStart": {"start": {}, "contentBlockIndex": 0}}
            for piece in _in_pieces(text):
                yield {"contentBlockDelta": {"delta": {"text": piece}, "contentBlockIndex": 0}}
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                            "metrics": {"latencyMs": 0}}}


def _in_pieces(text: str, size: int = 12):
    for i in range(0, len(text), size) or [0]:
        yield text[i:i + size]
    if not text:
        yield ""
