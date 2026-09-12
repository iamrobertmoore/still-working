"""The setup conversation, which is the one place a model writes something we keep.

It is also the only place where a mistake is silent for months: a watch on a call the
supplier does not publish can never fire, and nothing would ever say so.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.model_double import ScriptedModel
from tools.setup import (RoutineMapping, SETUP_SYSTEM, derive, only_real_calls,
                         published_calls, removals_on_record, verify)

PUBLISHED = ["GET /v2/orders", "POST /v2/orders/search", "GET /v2/locations",
             "GET /v2/payments", "POST /v2/refunds"]

ROUTINE = {"id": "orders-into-accounts", "what_maya_calls_it": "Orders going into the accounts",
           "in_her_words": "Every night the day's orders turn up in my accounting software.",
           "how_often": "every night", "if_it_stops": "Ines reconciles from this."}


def ask(calls, confidence="high", why="because"):
    model = ScriptedModel(structured=[{"calls": calls, "confidence": confidence, "why": why}])
    return derive(ROUTINE, "square", model=model, published=PUBLISHED), model


# ---------------------------------------------------------------- the control

def test_a_valid_choice_is_stored_exactly_as_chosen():
    got, _ = ask(["GET /v2/orders", "GET /v2/locations"])
    assert got["calls"] == ["GET /v2/orders", "GET /v2/locations"]
    assert got["invented"] == []


def test_a_call_the_supplier_does_not_publish_never_reaches_her_profile():
    got, _ = ask(["GET /v2/orders", "GET /v2/accounting/sync"])
    assert got["calls"] == ["GET /v2/orders"]
    assert got["invented"] == ["GET /v2/accounting/sync"]


def test_a_wholly_invented_answer_produces_an_empty_mapping_not_a_wrong_one():
    got, _ = ask(["GET /v2/made/up", "POST /v2/also/made/up"])
    assert got["calls"] == []
    assert len(got["invented"]) == 2


def test_a_renamed_path_parameter_still_matches_the_published_call():
    kept, dropped = only_real_calls(["GET /v2/orders/{x}"], ["GET /v2/orders/{order_id}"])
    assert kept == ["GET /v2/orders/{order_id}"]
    assert dropped == []


def test_a_trailing_slash_still_matches():
    got, _ = ask(["GET /v2/orders/"])
    assert got["calls"] == ["GET /v2/orders"]


def test_a_lowercase_method_still_matches():
    kept, _ = only_real_calls(["get /v2/orders"], PUBLISHED)
    assert kept == ["GET /v2/orders"]


def test_the_same_call_chosen_twice_is_stored_once():
    got, _ = ask(["GET /v2/orders", "GET /v2/orders"])
    assert got["calls"] == ["GET /v2/orders"]


def test_the_stored_call_is_the_suppliers_spelling_not_the_models():
    kept, _ = only_real_calls(["get /v2/orders/"], ["GET /v2/orders"])
    assert kept == ["GET /v2/orders"]


# ---------------------------------------------------------------- the schema

@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_the_three_allowed_confidences_are_accepted(confidence):
    assert RoutineMapping(calls=[], confidence=confidence, why="x").confidence == confidence


@pytest.mark.parametrize("confidence", ["fairly high", "HIGH", "very low", "", "maybe", "1"])
def test_any_other_confidence_is_rejected_by_the_schema(confidence):
    with pytest.raises(ValidationError):
        RoutineMapping(calls=[], confidence=confidence, why="x")


def test_the_schema_requires_a_reason():
    with pytest.raises(ValidationError):
        RoutineMapping(calls=[], confidence="high")


def test_the_confidence_survives_the_round_trip():
    got, _ = ask(["GET /v2/orders"], confidence="medium")
    assert got["confidence"] == "medium"


def test_the_reason_survives_the_round_trip():
    got, _ = ask(["GET /v2/orders"], why="  She named the accounting software.  ")
    assert got["why"] == "She named the accounting software."


# ---------------------------------------------------------------- the prompt

def test_the_model_is_asked_to_choose_rather_than_to_write():
    flat = " ".join(SETUP_SYSTEM.lower().split())
    assert "choose only from the list you are given" in flat
    assert "never write a call that is not in the list" in flat
    assert "copy each one exactly as it appears" in flat


def test_the_model_is_shown_the_suppliers_calls():
    _, model = ask(["GET /v2/orders"])
    assert model.structured_calls == 1


def test_structured_output_is_used_rather_than_free_text_that_needs_parsing():
    """Strands fulfils structured output by forcing a tool named after the model class.

    This assertion used to read `A and B or A`, which is just `A`, and the B half was
    false anyway. What is actually true, and worth asserting, is that exactly one
    structured request was made and the tool the model was shown was the schema.
    """
    _, model = ask(["GET /v2/orders"])
    assert model.structured_calls == 1
    assert model.seen_tool_specs == ["RoutineMapping"], model.seen_tool_specs


# ---------------------------------------------------------------- the verifier

def test_the_verifier_passes_on_the_profile_as_it_stands():
    assert verify(quiet=True) == 0


def test_the_verifier_knows_which_calls_the_suppliers_removed():
    removed = removals_on_record()
    assert any("xero|GET /Employees" == k for k in removed), removed
    assert removed["xero|GET /Employees"] == "2026-04-29"


def test_the_verifier_reads_every_supplier_snapshot_on_disk():
    for vendor in ("square", "xero", "stripe", "shipengine"):
        assert published_calls(vendor), vendor


def test_a_snapshot_that_does_not_exist_is_an_empty_list_not_a_crash():
    assert published_calls("a-company-maya-does-not-use") == []


def test_square_really_does_not_publish_the_call_that_was_wrong_for_a_fortnight():
    """The bug tools/setup.py --verify found on 11 September."""
    assert "GET /v2/orders" not in published_calls("square")
    assert "GET /v2/orders/{order_id}" in published_calls("square")


def test_xero_really_did_remove_the_employee_section():
    assert not [c for c in published_calls("xero") if "Employee" in c]
