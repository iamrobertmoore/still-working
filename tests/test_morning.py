"""Four suppliers, one morning, one message.

The round-up merges and never selects. If it could decide to stay quiet about a note that
had already cleared the controls, it would be a second, softer, prompt-shaped version of
the thing this project exists to avoid.

The trap in testing this is that the merged message is written by a scripted model, which
means the test wrote it. Asserting that it contains what the test put in it proves
nothing, and an earlier version of this file did exactly that: a mutant that dropped every
note after the first passed all thirteen cases. So the assertions here are about what the
round-up is *given*, which the test does not control, and about counts read off the model.
"""
from __future__ import annotations

import pytest

from agent.model_double import ScriptedModel
from agent.morning import (QUIET, ROUNDUP_SYSTEM, TWO_AT_ONCE, _send, last_note, round_up,
                           suppliers_with_something_to_say)

SCRIPTS = {
    "xero": [_send("Paying the twelve of us", "payroll", "xero: GET /Employees removed"),
             {"text": "done"}],
    "square": [_send("Orders going into the accounts", "orders",
                     "square: GET /v2/orders/{order_id} removed"), {"text": "done"}],
}

MERGED = ("Two things need you this morning.\n\n"
          "Paying the twelve of us may have stopped.\n"
          "Orders going into the accounts may have stopped.\n\n"
          "--- forward this part to Priya ---\n"
          "  xero: GET /Employees removed\n"
          "  square: GET /v2/orders/{order_id} removed\n")


def roundup_script(text=MERGED):
    return [{"tool": "supplier_xero", "id": "r1", "input": {"prompt": "go"}},
            {"tool": "supplier_square", "id": "r2", "input": {"prompt": "go"}},
            {"text": text}]


STRIPE_NOT_HERS = {"date": "2026-09-10", "vendor": "stripe",
                   "changes": [{"kind": "endpoint_removed", "endpoint": "GET /v1/issuing/cards",
                                "breaking": True}]}


# ---------------------------------------------------------------- the quiet morning

def test_a_quiet_morning_constructs_no_agent_at_all(business):
    message, per, calls = round_up(business, QUIET)
    assert message is None
    assert per == []
    assert calls == 0


def test_a_quiet_morning_is_decided_before_any_model_exists(business):
    assert suppliers_with_something_to_say(business, QUIET) == []


def test_a_supplier_that_broke_nothing_of_hers_never_becomes_an_agent(business):
    _, per, _ = round_up(business, [STRIPE_NOT_HERS], SCRIPTS)
    assert per == []


# ---------------------------------------------------------------- one supplier

def test_one_supplier_makes_no_second_model_call(business):
    message, per, calls = round_up(business, [TWO_AT_ONCE[0]], SCRIPTS)
    assert calls == 0, "a round-up of one can only make the note worse"
    assert message is not None


def test_one_supplier_gets_the_note_its_own_agent_rendered(business):
    message, per, _ = round_up(business, [TWO_AT_ONCE[0]], SCRIPTS)
    assert message == per[0]["decide"].delivered[-1]


def test_last_note_reads_what_was_delivered_not_the_last_tool_result(business):
    """A read_routine after the note would otherwise hand Maya a JSON blob."""
    script = [_send("Paying the twelve of us", "payroll", "xero: GET /Employees removed"),
              {"tool": "read_routine", "id": "r9", "input": {"routine_id": "paying-the-team"}},
              {"text": "done"}]
    _, per, _ = round_up(business, [TWO_AT_ONCE[0]], {"xero": script})
    note = last_note(per[0]["decide"])
    assert "forward this part to" in note
    assert "depends_on" not in note


# ---------------------------------------------------------------- two suppliers

def test_two_suppliers_both_clear_their_own_controls(business):
    _, per, _ = round_up(business, TWO_AT_ONCE, SCRIPTS, roundup_script())
    assert sorted(r for p in per for r in p["sent"]) == ["orders-into-accounts",
                                                         "paying-the-team"]


def test_the_round_up_runs_when_two_suppliers_clear(business):
    _, _, calls = round_up(business, TWO_AT_ONCE, SCRIPTS, roundup_script())
    assert calls > 0


def test_the_round_up_is_offered_one_tool_per_cleared_supplier(business):
    """The check that catches a merge silently dropping a note.

    The merged text is written by this test, so asserting on it proves nothing. What the
    round-up is handed is not written by this test.
    """
    _, per, _ = round_up(business, TWO_AT_ONCE, SCRIPTS, roundup_script())
    offered = sorted(p["tool_name"] for p in per if p["tool_name"])
    assert offered == ["supplier_square", "supplier_xero"]
    assert all(p["tool_name"] for p in per), "a cleared supplier with no tool is a dropped note"


def test_the_model_sees_exactly_those_tools(business):
    """Read off the model's own record of the tool specs it was given."""
    model = ScriptedModel(roundup_script())
    import agent.morning as m
    real = m.ScriptedModel
    m.ScriptedModel = lambda script=None: model
    try:
        round_up(business, TWO_AT_ONCE, SCRIPTS, roundup_script())
    finally:
        m.ScriptedModel = real
    assert sorted(model.seen_tool_specs) == ["supplier_square", "supplier_xero"], \
        model.seen_tool_specs


def test_a_supplier_whose_note_was_denied_contributes_no_tool(business):
    mixed = [TWO_AT_ONCE[0], STRIPE_NOT_HERS]
    _, per, calls = round_up(business, mixed, SCRIPTS)
    assert [p["vendor"] for p in per] == ["xero"]
    assert calls == 0


def test_two_records_from_one_supplier_get_distinct_tool_names(business):
    """Strands refuses a duplicate tool name, and this used to crash the morning."""
    twice = [TWO_AT_ONCE[0], dict(TWO_AT_ONCE[0], date="2026-09-10")]
    _, per, _ = round_up(business, twice, SCRIPTS, roundup_script())
    names = [p["tool_name"] for p in per if p["tool_name"]]
    assert len(names) == len(set(names)), names


# ---------------------------------------------------------------- house style

def test_the_merged_message_goes_through_the_house_style(business):
    """MayaNote never sees the merged text, so the formatter has to be applied here too."""
    message, _, _ = round_up(business, TWO_AT_ONCE, SCRIPTS,
                             roundup_script("Two things — both need you."))
    assert "—" not in message and "–" not in message


@pytest.mark.parametrize("written", ["a — b", "a–b", "a  —  b"])
def test_any_long_dash_in_the_merge_is_removed(business, written):
    message, _, _ = round_up(business, TWO_AT_ONCE, SCRIPTS, roundup_script(written))
    assert "—" not in message and "–" not in message


# ---------------------------------------------------------------- the prompt

def test_the_round_up_is_told_it_does_not_decide():
    flat = " ".join(ROUNDUP_SYSTEM.lower().split())
    assert "your job is not to decide what is worth telling her" in flat
    assert "never drop a note" in flat


def test_the_round_up_is_told_to_keep_each_headline():
    assert "keep each note's own headline" in " ".join(ROUNDUP_SYSTEM.lower().split())


def test_the_round_up_forbids_the_house_style_dashes():
    assert "no em dashes and no en dashes" in " ".join(ROUNDUP_SYSTEM.lower().split())
