"""A deterministic Strands model provider, for running the agent without credentials.

The Strands Model base class has four abstract methods. Implementing them against a fixed
script makes the whole agent loop runnable with no AWS account, no network and no
flakiness, which is how the tests below run in well under a second.

This is a test double. It has no judgement. Swapping it for BedrockModel is a one line
change and the agent code does not move.
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator, AsyncIterable, Optional

from strands.models.model import Model


class ScriptedModel(Model):
    def __init__(self, script: list[dict[str, Any]]):
        self._script = list(script)
        self._turn = 0
        self._config: dict[str, Any] = {"model_id": "scripted"}
        self.seen_tool_specs: list[str] = []

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self._config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs) -> AsyncGenerator:
        yield {"output": output_model()}

    async def stream(self, messages, tool_specs=None, system_prompt: Optional[str] = None,
                     **kwargs: Any) -> AsyncIterable[dict]:
        if tool_specs:
            self.seen_tool_specs = [s["name"] for s in tool_specs]

        turn = self._script[self._turn] if self._turn < len(self._script) else {"text": "Done."}
        self._turn += 1

        yield {"messageStart": {"role": "assistant"}}
        if "tool" in turn:
            yield {"contentBlockStart": {"start": {"toolUse": {
                "toolUseId": turn.get("id", f"t{self._turn}"), "name": turn["tool"]}},
                "contentBlockIndex": 0}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn.get("input", {}))}},
                                         "contentBlockIndex": 0}}
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}, "contentBlockIndex": 0}}
            yield {"contentBlockDelta": {"delta": {"text": turn["text"]}, "contentBlockIndex": 0}}
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                            "metrics": {"latencyMs": 0}}}
