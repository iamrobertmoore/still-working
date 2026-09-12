"""The deployed judgement layer, tested from outside the bundle.

`runtime/` is self-contained on purpose: it is the only part of this repository that ships
to AgentCore, and it must not reach back into the rest of the project. tools/
check_runtime_isolation.py asserts that. This file does the other half, which is checking
that the thing inside the bundle behaves, and it imports it by path rather than as a
package so that the isolation is not quietly broken by the test suite itself.

The date guard is the reason this file exists. On the first live run the model was given a
change dated 14 July and a `days_ago` of 51, subtracted one from the other, got 24 May,
and filed it under the word FACT. Every case below is that bug and its neighbours.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "runtime", "app", "StillWorking", "main.py")

bedrock = pytest.importorskip(
    "bedrock_agentcore", reason="the deployed bundle's own runtime is not installed here")

# The bundle is deployed with its own directory on the path, so `from model.load import
# load_model` resolves inside it. Putting that directory on sys.path here reproduces the
# deployed import graph exactly, rather than editing the bundle to suit the test suite.
BUNDLE = os.path.dirname(MAIN)
if BUNDLE not in sys.path:
    sys.path.insert(0, BUNDLE)

spec = importlib.util.spec_from_file_location("deployed_main", MAIN)
deployed = importlib.util.module_from_spec(spec)
sys.modules["deployed_main"] = deployed
spec.loader.exec_module(deployed)


IMPACT = {
    "date": "2026-07-14", "vendor": "square", "days_ago": 51,
    "vendor_in_her_words": "my till and my bookings",
    "vendor_address_as": "your till and bookings",
    "business": {"owner": "Maya", "who_fixes_things": "Priya, a freelance developer"},
    "routines_touched": [{"routine_id": "stock-between-counter-and-website",
                          "what_maya_calls_it": "Stock moving between the counter and the website",
                          "mapping_confidence": "high", "has_breaking_change": True,
                          "changes": []}],
    "reaches_maya": True, "vendor_total_changes": 3, "ignored_count": 2,
}


def note(**kw):
    base = dict(routine="Stock", headline="Stock stopped.", what_happened="It stopped.",
                what_it_costs="Money.", how_late_normally="weeks",
                what_to_do="Forward this.", forward_to="Priya",
                for_the_developer="square: a call was removed")
    base.update(kw)
    return base


# ---------------------------------------------------------------- dates in text

@pytest.mark.parametrize("text,expected", [
    ("on 2026-07-14 it broke", {(7, 14)}),
    ("on 14 July it broke", {(7, 14)}),
    ("on July 14 it broke", {(7, 14)}),
    ("on 14th July it broke", {(7, 14)}),
    ("on Jul 14 it broke", {(7, 14)}),
    ("on 2026-05-24", {(5, 24)}),
    ("nothing here", set()),
])
def test_a_date_in_prose_is_found_however_it_is_written(text, expected):
    assert deployed.dates_mentioned(text) == expected


@pytest.mark.parametrize("text", [
    "In December it is worse",
    "Her busiest month is December",
    "every January she does stocktake",
    "trading in December is a day an hour",
])
def test_a_bare_month_is_a_season_not_a_date(text):
    assert deployed.dates_mentioned(text) == set()


def test_two_different_dates_are_both_found():
    assert deployed.dates_mentioned("on 14 July and again on 2026-04-24") == {(7, 14), (4, 24)}


# ---------------------------------------------------------------- the guard

def test_the_guard_is_armed_from_the_change_record():
    words = deployed._date_guard(IMPACT)
    assert words == "14 July 2026"
    assert deployed._ALLOWED_DATE == (7, 14)


def test_a_record_with_no_date_arms_nothing_rather_than_guessing():
    assert deployed._date_guard({"date": None}) == "an unknown date"
    assert deployed._ALLOWED_DATE is None


def test_a_record_with_an_unparseable_date_does_not_crash():
    assert deployed._date_guard({"date": "sometime"}) == "sometime"


def test_the_real_note_is_rendered_when_the_date_is_right():
    deployed._date_guard(IMPACT)
    out = deployed.send_to_maya(**note(what_happened="It broke on 14 July."))
    assert "REJECTED" not in out
    assert "forward this part to Priya" in out


def test_the_exact_bug_is_rejected():
    """FACT: ... on 2026-05-24 (51 days ago). The model did arithmetic and got it wrong."""
    deployed._date_guard(IMPACT)
    out = deployed.send_to_maya(**note(
        for_the_developer="FACT: square removed this on 2026-05-24 (51 days ago)"))
    assert out.startswith("REJECTED")
    assert "14 July 2026" in out
    assert "Do not calculate dates" in out


def test_the_rejection_names_the_wrong_date_it_saw():
    deployed._date_guard(IMPACT)
    out = deployed.send_to_maya(**note(headline="It broke on 24 May."))
    assert "24/05" in out


@pytest.mark.parametrize("field", ["headline", "what_happened", "what_it_costs",
                                   "how_late_normally", "what_to_do", "for_the_developer"])
def test_a_wrong_date_in_any_field_is_rejected(field):
    deployed._date_guard(IMPACT)
    out = deployed.send_to_maya(**note(**{field: "this happened on 2026-05-24"}))
    assert out.startswith("REJECTED"), field


def test_a_season_in_the_note_is_not_rejected():
    deployed._date_guard(IMPACT)
    out = deployed.send_to_maya(**note(
        what_it_costs="Every hour of downtime is a day of trading in December."))
    assert "REJECTED" not in out


def test_saying_how_long_ago_in_words_is_allowed():
    deployed._date_guard(IMPACT)
    out = deployed.send_to_maya(**note(headline="Stock stopped about seven weeks ago."))
    assert "REJECTED" not in out


def test_with_no_date_armed_nothing_is_rejected():
    deployed._date_guard({"date": None})
    out = deployed.send_to_maya(**note(headline="It broke on 2026-05-24."))
    assert "REJECTED" not in out


# ---------------------------------------------------------------- payload shapes

def test_a_bare_impact_payload_is_accepted():
    assert deployed._impact_from(IMPACT)["date"] == "2026-07-14"


def test_an_impact_under_its_own_key_is_accepted():
    assert deployed._impact_from({"impact": IMPACT})["date"] == "2026-07-14"


def test_a_json_string_in_prompt_is_accepted_because_the_cli_only_offers_prompt():
    import json
    assert deployed._impact_from({"prompt": json.dumps(IMPACT)})["date"] == "2026-07-14"


def test_a_json_string_in_prompt_under_an_impact_key_is_accepted():
    import json
    got = deployed._impact_from({"prompt": json.dumps({"impact": IMPACT})})
    assert got["date"] == "2026-07-14"


def test_a_chat_prompt_is_refused_with_an_explanation_rather_than_a_stack():
    with pytest.raises(ValueError) as exc:
        deployed._impact_from({"prompt": "hello, what is broken today?"})
    assert "does not take a chat prompt" in str(exc.value)


def test_a_payload_of_the_wrong_shape_names_what_it_got():
    with pytest.raises(ValueError) as exc:
        deployed._impact_from({"vendor": "square", "whatever": 1})
    assert "assess()" in str(exc.value)


def test_a_payload_that_is_not_an_object_is_refused():
    with pytest.raises(ValueError):
        deployed._impact_from(["not", "an", "object"])


# ---------------------------------------------------------------- house style

@pytest.mark.parametrize("written", ["a — b", "a–b", "a  —  b"])
def test_the_deployed_bundle_enforces_the_same_house_style(written):
    assert "—" not in deployed.house_style(written)
    assert "–" not in deployed.house_style(written)


def test_the_deployed_note_has_no_long_dashes():
    deployed._date_guard(IMPACT)
    out = deployed.send_to_maya(**note(headline="Stock stopped — on Tuesday."))
    assert "—" not in out


def test_the_two_house_styles_agree():
    """The bundle carries its own copy. A copy that has drifted is worse than no copy."""
    from agent.notes import house_style as local
    for text in ["a — b", "a–b", "a - b", "plain", ""]:
        assert deployed.house_style(text) == local(text), text


# ---------------------------------------------------------------- what comes back

def result_block(text):
    return {"role": "user", "content": [{"toolResult": {"content": [{"text": text}]}}]}


def test_the_note_returned_is_the_last_note_not_the_last_tool_result():
    """A refusal followed by the model giving up used to come back as Maya's note."""
    deployed._date_guard(IMPACT)
    real = deployed.send_to_maya(**note(what_happened="It broke on 14 July."))
    messages = [result_block(real), result_block("REJECTED: the note mentions 24/05, ...")]
    assert deployed.last_note(messages) == real


def test_a_lookup_after_the_note_does_not_become_the_note():
    deployed._date_guard(IMPACT)
    real = deployed.send_to_maya(**note())
    messages = [result_block(real), result_block('{"id": "stock", "derived": {}}')]
    assert deployed.last_note(messages) == real


def test_a_morning_with_no_note_returns_none_rather_than_a_refusal():
    messages = [result_block("REJECTED: the note mentions 24/05, ...")]
    assert deployed.last_note(messages) is None


def test_a_later_note_replaces_an_earlier_one():
    deployed._date_guard(IMPACT)
    first = deployed.send_to_maya(**note(headline="First."))
    second = deployed.send_to_maya(**note(headline="Second."))
    assert deployed.last_note([result_block(first), result_block(second)]) == second


def test_no_messages_at_all_is_none_not_a_crash():
    assert deployed.last_note([]) is None
    assert deployed.last_note(None) is None


def test_the_bundle_and_the_repo_agree_on_what_counts_as_a_note():
    from agent.still_working import is_a_note as local
    for text in ["--- forward this part to Priya ---", "REJECTED: ...", "", "Still working."]:
        assert deployed.is_a_note(text) == local(text), text
