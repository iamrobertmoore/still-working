"""The detector: what changed, in the suppliers' own language.

This layer has a right answer and no judgement in it at all, which is exactly why it is
worth testing hard. Everything downstream trusts it.
"""
from __future__ import annotations

import json

import pytest

from tools.snapshot import BREAKING_KINDS, classify, normalise, parse_spec


def kinds(changes):
    return [c["kind"] for c in changes]


def only(changes, kind):
    return [c for c in changes if c["kind"] == kind]


# ------------------------------------------------------- every kind it can emit

def test_endpoint_removed_is_detected(spec, endpoint):
    got = classify(spec({"GET /a": endpoint()}), spec({}))
    assert kinds(got) == ["endpoint_removed"]
    assert got[0]["endpoint"] == "GET /a"


def test_endpoint_added_is_detected(spec, endpoint):
    got = classify(spec({}), spec({"GET /a": endpoint()}))
    assert kinds(got) == ["endpoint_added"]


def test_param_removed_is_detected(spec, endpoint):
    got = classify(spec({"GET /a": endpoint(params=["x"])}), spec({"GET /a": endpoint()}))
    assert kinds(got) == ["param_removed"]
    assert got[0]["param"] == "x"


def test_param_added_is_detected(spec, endpoint):
    got = classify(spec({"GET /a": endpoint()}), spec({"GET /a": endpoint(params=["x"])}))
    assert kinds(got) == ["param_added"]


def test_param_became_required_is_detected(spec, endpoint):
    before = spec({"GET /a": endpoint(params=["x"])})
    after = spec({"GET /a": endpoint(params=["x"], required=["x"])})
    assert kinds(classify(before, after)) == ["param_became_required"]


def test_param_became_optional_is_detected(spec, endpoint):
    before = spec({"GET /a": endpoint(params=["x"], required=["x"])})
    after = spec({"GET /a": endpoint(params=["x"])})
    assert kinds(classify(before, after)) == ["param_became_optional"]


def test_response_added_and_removed_are_detected(spec, endpoint):
    before = spec({"GET /a": endpoint(responses=["200"])})
    after = spec({"GET /a": endpoint(responses=["200", "429"])})
    assert kinds(classify(before, after)) == ["response_added"]
    assert kinds(classify(after, before)) == ["response_removed"]


def test_version_string_change_is_its_own_kind(spec, endpoint):
    before = {"spec_version": "1.0", "endpoints": {}}
    after = {"spec_version": "1.1", "endpoints": {}}
    got = classify(before, after)
    assert kinds(got) == ["version_string_changed"]
    assert got[0]["from"] == "1.0" and got[0]["to"] == "1.1"


# ---------------------------------------------------------------- breaking or not

@pytest.mark.parametrize("before,after", [
    # endpoint_removed
    ({"GET /a": None}, {}),
    # param_removed
    ({"GET /a": ["x"]}, {"GET /a": []}),
])
def test_a_removal_is_marked_breaking_by_classify(spec, endpoint, before, after):
    mk = lambda d: spec({k: endpoint(params=v or []) for k, v in d.items()})
    got = classify(mk(before), mk(after))
    assert got and all(c["breaking"] for c in got), got


def test_a_tightened_parameter_is_marked_breaking_by_classify(spec, endpoint):
    got = classify(spec({"GET /a": endpoint(params=["x"])}),
                   spec({"GET /a": endpoint(params=["x"], required=["x"])}))
    assert [c["breaking"] for c in got] == [True]


@pytest.mark.parametrize("before,after", [
    ({}, {"GET /a": {"params": [], "required": [], "responses": ["200"]}}),
    ({"GET /a": {"params": [], "required": [], "responses": ["200"]}},
     {"GET /a": {"params": ["x"], "required": [], "responses": ["200"]}}),
    ({"GET /a": {"params": ["x"], "required": ["x"], "responses": ["200"]}},
     {"GET /a": {"params": ["x"], "required": [], "responses": ["200"]}}),
    ({"GET /a": {"params": [], "required": [], "responses": ["200"]}},
     {"GET /a": {"params": [], "required": [], "responses": ["200", "429"]}}),
    ({"GET /a": {"params": [], "required": [], "responses": ["200", "429"]}},
     {"GET /a": {"params": [], "required": [], "responses": ["200"]}}),
])
def test_additive_and_cosmetic_changes_are_not_marked_breaking_by_classify(spec, before, after):
    got = classify(spec(before), spec(after))
    assert got, "the fixture changed nothing"
    assert not any(c["breaking"] for c in got), got


def test_a_version_bump_alone_is_not_breaking(spec):
    got = classify({"spec_version": "1.0", "endpoints": {}},
                   {"spec_version": "2.0", "endpoints": {}})
    assert [c["breaking"] for c in got] == [False]


def test_every_kind_classify_can_emit_is_known_to_be_breaking_or_not(spec, endpoint):
    """No kind may reach Maya's side of the system without a breaking verdict."""
    import re as _re
    source = open(__file__.replace("tests/test_snapshot.py", "tools/snapshot.py")).read()
    emitted = set(_re.findall(r'"kind": "([a-z_]+)"', source))
    assert len(emitted) >= 9, emitted
    for kind in emitted:
        assert isinstance(kind in BREAKING_KINDS, bool)
    assert BREAKING_KINDS <= emitted, BREAKING_KINDS - emitted


def test_exactly_three_kinds_can_break_a_caller():
    assert BREAKING_KINDS == {"endpoint_removed", "param_removed", "param_became_required"}


def test_optional_to_required_is_breaking_but_required_to_optional_is_not(spec, endpoint):
    before = spec({"GET /a": endpoint(params=["x"])})
    after = spec({"GET /a": endpoint(params=["x"], required=["x"])})
    tightened = classify(before, after)
    loosened = classify(after, before)
    assert tightened[0]["breaking"] is True
    assert loosened[0]["breaking"] is False


def test_a_new_endpoint_is_never_breaking_however_many_there_are(spec, endpoint):
    after = spec({f"GET /new{i}": endpoint() for i in range(40)})
    got = classify(spec({}), after)
    assert len(got) == 40
    assert not any(c["breaking"] for c in got)


# ---------------------------------------------------------------- silence

def test_identical_contracts_produce_nothing(spec, endpoint):
    same = spec({"GET /a": endpoint(params=["x"], required=["x"], responses=["200", "404"])})
    assert classify(same, json.loads(json.dumps(same))) == []


def test_an_empty_contract_compared_with_itself_produces_nothing(spec):
    assert classify(spec({}), spec({})) == []


def test_reordering_params_is_not_a_change(spec, endpoint):
    before = spec({"GET /a": endpoint(params=["x", "y"])})
    after = spec({"GET /a": endpoint(params=["y", "x"])})
    assert classify(before, after) == []


# ---------------------------------------------------------------- determinism

def test_changes_are_ordered_the_same_way_every_time(spec, endpoint):
    before = spec({f"GET /{c}": endpoint() for c in "dcba"})
    after = spec({})
    first = classify(before, after)
    second = classify(before, after)
    assert first == second
    assert [c["endpoint"] for c in first] == sorted(c["endpoint"] for c in first)


def test_every_change_carries_a_breaking_flag(spec, endpoint):
    before = spec({"GET /a": endpoint(params=["x"], required=["x"], responses=["200"])})
    after = spec({"GET /b": endpoint(params=["y"])})
    for change in classify(before, after):
        assert isinstance(change["breaking"], bool)


# ---------------------------------------------------------------- parsing

def test_json_and_yaml_specs_parse_to_the_same_thing():
    as_json = parse_spec(b'{"openapi": "3.0.0", "paths": {}}', "json")
    as_yaml = parse_spec(b"openapi: 3.0.0\npaths: {}\n", "yaml")
    assert as_json == as_yaml


def test_normalise_lowercases_nothing_it_should_not(spec):
    got = normalise({"paths": {"/Invoices": {"get": {"parameters": []}}}})
    assert "GET /Invoices" in got, got


def test_normalise_keeps_path_case_because_xero_depends_on_it():
    got = normalise({"paths": {"/BankTransactions": {"get": {}}}})
    assert list(got) == ["GET /BankTransactions"]
