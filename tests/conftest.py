"""Shared fixtures.

Every test in here runs with no credentials, no network and no AWS account, in well under
a second, because the only thing that needs a model is behind `agent/model_double.py`.
That is not a convenience. A suite that needs Bedrock is a suite that stops being run.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.impact import load_business          # noqa: E402


@pytest.fixture(scope="session")
def business():
    return load_business()


@pytest.fixture
def spec():
    """A minimal contract, in the shape tools/snapshot.py normalises to."""
    def make(endpoints):
        return {"spec_version": "1.0", "endpoints": endpoints}
    return make


@pytest.fixture
def endpoint():
    def make(params=(), required=(), responses=("200",)):
        return {"params": list(params), "required": list(required), "responses": list(responses)}
    return make


def note_script(routine="Orders going into the accounts", **overrides):
    """One scripted send_to_maya turn, then a closing line."""
    payload = {
        "routine": routine,
        "headline": f"{routine} stopped.",
        "what_happened": "A supplier removed something this relies on.",
        "what_it_costs": "Time and trust.",
        "how_late_normally": "weeks",
        "what_to_do": "Forward the part below to Priya.",
        "forward_to": "Priya",
        "for_the_developer": "vendor: call removed",
    }
    payload.update(overrides)
    return [{"tool": "send_to_maya", "id": "t1", "input": payload}, {"text": "done"}]
