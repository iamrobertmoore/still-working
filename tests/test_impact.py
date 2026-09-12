"""The matcher: which of Maya's routines a change touches.

Set membership, no model. The interesting behaviour is the silence, because most supplier
changes touch nothing she depends on and a tool that forwarded them all would be switched
off in a fortnight.
"""
from __future__ import annotations

import pytest

from tools.impact import assess, canon, days_ago, vendor_labels, watched_calls


def change(vendor="square", date="2026-09-02", **kw):
    return {"date": date, "vendor": vendor, "changes": [dict(kw)]}


def breaking(endpoint, vendor="square", date="2026-09-02"):
    return {"date": date, "vendor": vendor,
            "changes": [{"kind": "endpoint_removed", "endpoint": endpoint, "breaking": True}]}


# ---------------------------------------------------------------- canonical form

@pytest.mark.parametrize("written,expected", [
    ("GET /v2/orders/{order_id}", "GET /v2/orders/{}"),
    ("GET /v2/orders/{id}", "GET /v2/orders/{}"),
    ("get /v2/orders", "GET /v2/orders"),
    ("GET /v2/orders/", "GET /v2/orders"),
    ("  GET   /v2/orders  ", "GET /v2/orders"),
    ("POST /Invoices", "POST /Invoices"),
    ("GET /v1/labels/{label_id}/track", "GET /v1/labels/{}/track"),
])
def test_canon_normalises_the_ways_a_call_gets_written(written, expected):
    assert canon(written) == expected


def test_a_renamed_path_parameter_is_the_same_call():
    assert canon("GET /v1/payment_intents/{intent}") == canon("GET /v1/payment_intents/{pi_id}")


def test_a_different_path_is_not_the_same_call():
    assert canon("GET /v2/orders/{id}") != canon("GET /v2/payments/{id}")


def test_a_different_method_is_not_the_same_call():
    assert canon("GET /v2/orders") != canon("POST /v2/orders")


# ---------------------------------------------------------------- reaching Maya

def test_a_change_on_a_watched_call_reaches_her(business):
    got = assess(business, breaking("GET /v2/orders/{order_id}"))
    assert got["reaches_maya"] is True
    assert [r["routine_id"] for r in got["routines_touched"]] == ["orders-into-accounts"]


def test_a_busy_day_that_touches_nothing_of_hers_stays_silent(business):
    noisy = {"date": "2026-09-03", "vendor": "stripe", "changes": [
        {"kind": "endpoint_removed", "endpoint": "GET /v1/issuing/cards", "breaking": True},
        {"kind": "param_removed", "endpoint": "POST /v1/terminal/readers", "param": "label",
         "breaking": True},
        {"kind": "endpoint_added", "endpoint": "POST /v1/tax/registrations", "breaking": False}]}
    got = assess(business, noisy)
    assert got["reaches_maya"] is False
    assert got["routines_touched"] == []
    assert got["ignored_count"] == 3


def test_an_additive_change_on_a_watched_call_does_not_raise_the_alarm(business):
    got = assess(business, change(kind="param_added", endpoint="GET /v2/locations",
                                  param="cursor", breaking=False))
    assert got["routines_touched"], "the routine should still be told it was touched"
    assert got["reaches_maya"] is False


def test_a_change_with_no_endpoint_is_counted_and_dropped(business):
    got = assess(business, change(kind="version_string_changed", **{"from": "2.0", "to": "2.1"}))
    assert got["ignored_count"] == 1
    assert got["routines_touched"] == []


def test_a_vendor_maya_does_not_use_touches_nothing(business):
    got = assess(business, breaking("GET /anything", vendor="some-other-company"))
    assert got["reaches_maya"] is False


# ---------------------------------------------------------------- her words

def test_the_supplier_reaches_the_agent_in_two_forms(business):
    got = assess(business, breaking("GET /v2/orders/{order_id}"))
    assert got["vendor_in_her_words"] == "my till and my bookings"
    assert got["vendor_address_as"] == "your till and bookings"


def test_the_two_forms_are_different_for_every_supplier():
    for vendor, label in vendor_labels().items():
        assert label["hers"] and label["address_as"], vendor
        assert label["hers"] != label["address_as"], vendor


def test_the_second_person_form_works_as_a_sentence_subject():
    for vendor, label in vendor_labels().items():
        assert not label["address_as"].lower().startswith("my "), vendor


def test_who_fixes_things_reaches_the_agent(business):
    got = assess(business, breaking("GET /v2/orders/{order_id}"))
    assert "Priya" in got["business"]["who_fixes_things"]


def test_how_she_finds_out_today_reaches_the_agent(business):
    got = assess(business, breaking("GET /v2/orders/{order_id}"))
    assert got["business"]["how_maya_finds_out_today"]


def test_a_touched_routine_carries_her_own_description(business):
    got = assess(business, breaking("GET /v2/orders/{order_id}"))
    routine = got["routines_touched"][0]
    for field in ("in_her_words", "if_it_stops", "what_it_costs", "what_maya_calls_it"):
        assert routine[field], field


# ---------------------------------------------------------------- time

@pytest.mark.parametrize("then,now,expected", [
    ("2026-09-02", "2026-09-03", 1),
    ("2026-07-14", "2026-09-03", 51),
    ("2026-09-03", "2026-09-03", 0),
    ("2026-04-24", "2026-04-29", 5),
])
def test_days_ago_counts_days(then, now, expected):
    assert days_ago(then, now) == expected


def test_days_ago_on_a_bad_date_is_none_rather_than_a_guess():
    assert days_ago("not a date", "2026-09-03") is None
    assert days_ago(None, "2026-09-03") is None


def test_the_agent_is_told_how_long_ago_not_only_the_date(business):
    got = assess(business, breaking("GET /v2/orders/{order_id}", date="2026-07-14"),
                 today="2026-09-03")
    assert got["days_ago"] == 51
    assert got["date"] == "2026-07-14"


# ---------------------------------------------------------------- the profile itself

def test_every_routine_watches_at_least_one_call_no_other_routine_watches(business):
    index = watched_calls(business)
    for routine in business["routines"]:
        exclusive = [call for call, owners in index.items()
                     if len(owners) == 1 and owners[0]["id"] == routine["id"]]
        assert exclusive, (
            f"{routine['id']} shares every call it watches, so it can never be the only "
            "routine a change touches, and its own path through the agent is untestable")


def test_every_routine_has_a_confidence_from_the_allowed_three(business):
    for routine in business["routines"]:
        assert (routine.get("derived") or {}).get("confidence") in ("high", "medium", "low"), \
            routine["id"]


def test_every_routine_says_what_it_costs_her(business):
    for routine in business["routines"]:
        assert (routine.get("what_it_costs") or "").strip(), routine["id"]


def test_every_routine_says_how_late_she_would_notice(business):
    for routine in business["routines"]:
        assert routine.get("how_late_would_she_notice"), routine["id"]


def test_no_routine_description_contains_vendor_vocabulary(business):
    forbidden = ("endpoint", "parameter", "api ", "json", "webhook", "oauth")
    for routine in business["routines"]:
        hers = " ".join(str(routine.get(k, "")) for k in
                        ("what_maya_calls_it", "in_her_words", "if_it_stops", "what_it_costs"))
        for word in forbidden:
            assert word not in hers.lower(), (routine["id"], word)


def test_maya_never_wrote_a_call_name(business):
    """Every call name lives under `derived`, which she has not read."""
    for routine in business["routines"]:
        hers = {k: v for k, v in routine.items() if k != "derived"}
        flat = str(hers)
        assert "GET /" not in flat and "POST /" not in flat, routine["id"]


def test_the_profile_covers_more_than_one_supplier(business):
    vendors = {dep["vendor"] for r in business["routines"]
               for dep in (r.get("derived") or {}).get("depends_on", [])}
    assert len(vendors) >= 3, vendors


def test_every_derived_block_explains_itself(business):
    for routine in business["routines"]:
        why = (routine.get("derived") or {}).get("why", "")
        assert len(why.split()) >= 8, (routine["id"], why)
