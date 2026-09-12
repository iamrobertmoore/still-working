# Generated from agent/memory.py by tools/sync_runtime.py.
"""What Maya has already been told, and why that has to be a control rather than a habit.

Xero deleted the employee section of their contract on 24 April, put it back, and deleted
it again on 29 April. Both days are real, both are breaking, and both land on the routine
Maya calls "Paying the twelve of us". A tool with no memory tells her twice in five days
that her payroll is broken. The second message is the one that teaches her the first was
noise, and after that she stops opening them.

So the agent remembers its own mornings. Strands persists two things through a session
manager: the conversation, and the agent's state. The ledger of what reached Maya lives in
the state rather than in the transcript, because the transcript records what the model
asked for and the ledger has to record what actually went out. Those are not the same
thing: one of them has been through the interventions.

The answer gates the send in `OnlyWhenItCostsHer`, not in the prompt. "Do not repeat
yourself" is an instruction a model follows most of the time. A `Deny` is a control.

Repeating is not always wrong. If the same routine breaks again after the quiet period, or
a different routine breaks, she should hear about it. The window is deliberately short and
lives here, in one named constant, rather than being spread across a system prompt.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any, Iterable

# How long a routine stays quiet after Maya has been told about it. Five days covers the
# Xero delete, restore, delete sequence of April 2026, which is where this number came from.
QUIET_DAYS = 5

# The key the ledger lives under in the agent's persisted state.
LEDGER = "told_maya"

SESSIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "contracts", "sessions")


def session_manager(session_id: str = "maya", storage_dir: str | None = None):
    """The agent's memory of its own mornings.

    Imported lazily so nothing here forces a Strands import on the deterministic tools,
    which have no business depending on the agent framework.
    """
    from strands.session import FileSessionManager
    return FileSessionManager(session_id=session_id, storage_dir=storage_dir or SESSIONS)


def ledger(agent) -> list[dict[str, Any]]:
    """Every note that actually reached Maya, oldest first.

    Empty for an agent with no session, which is the right answer: an agent with no memory
    has never told her anything.
    """
    if agent is None:
        return []
    try:
        rows = agent.state.get(LEDGER)
    except Exception:                                   # noqa: BLE001, state is optional
        return []
    return list(rows or [])


def record(agent, routine_id: str, change_date: str | None, vendor: str | None = None,
           what_maya_calls_it: str | None = None) -> list[dict[str, Any]]:
    """Write one delivered note into the ledger. Called by the control, not by the model."""
    rows = ledger(agent)
    rows.append({"routine_id": routine_id, "change_date": change_date,
                 "vendor": vendor, "what_maya_calls_it": what_maya_calls_it})
    if agent is not None:
        agent.state.set(LEDGER, rows)
    return rows


def told_recently(rows: Iterable[dict[str, Any]], routine_id: str, today: str | None,
                  quiet_days: int = QUIET_DAYS) -> dict[str, Any] | None:
    """The most recent note about this routine inside the quiet window, or None.

    `today` is the date of the change being considered, not the wall clock, so replaying
    five months of recorded history gives the same answer every time it is replayed. A
    change dated before the note it is being compared against is not a repeat; it is
    history arriving out of order, and the caller should see it.
    """
    if not today:
        return None
    try:
        now = dt.date.fromisoformat(today)
    except (TypeError, ValueError):
        return None

    best: dict[str, Any] | None = None
    for note in rows or []:
        if note.get("routine_id") != routine_id:
            continue
        try:
            then = dt.date.fromisoformat(note.get("change_date"))
        except (TypeError, ValueError):
            continue
        gap = (now - then).days
        if 0 <= gap <= quiet_days:
            if best is None or then > dt.date.fromisoformat(best["change_date"]):
                best = dict(note, days_since=gap)
    return best


def notes_in_transcript(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every send_to_maya the model asked for, read from the agent's own message history.

    This is what the model wanted to send, before the interventions had their say, so it
    is always a superset of the ledger. Kept because the difference between the two is the
    measurement this whole project rests on: how often the judgement layer was stopped.
    """
    out: list[dict[str, Any]] = []
    for message in messages or []:
        for block in message.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            use = block.get("toolUse")
            if isinstance(use, dict) and use.get("name") == "send_to_maya":
                payload = use.get("input") or {}
                if isinstance(payload, dict):
                    out.append(payload)
    return out
