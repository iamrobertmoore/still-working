"""The controls. This is the file that matters most.

Everything this project claims rests on the interruption rule being a control rather than
an instruction. A prompt that says "only tell her when it matters" is a probability whose
failure mode is silent: it pings her about nothing for a fortnight and she stops reading.
`Deny` on before_tool_call is a control, and a control is something you can test.
"""
from __future__ import annotations

import tempfile

import pytest

from conftest import note_script
from agent import memory
from agent.still_working import (BRIEF_CHANGE, LOW_ONLY_DAY, MIXED_DAY, QUIET_DAY, SEND,
                                 XERO_24_APR, XERO_29_APR, PAYROLL_SEND, build,
                                 cost_of_the_morning, routine_to_report, run)


def tool_inputs(agent, name="send_to_maya"):
    return [b["toolUse"]["input"] for m in agent.messages for b in m.get("content", [])
            if isinstance(b, dict) and b.get("toolUse", {}).get("name") == name]


def tool_results(agent):
    return [b["toolResult"]["content"][0]["text"] for m in agent.messages
            for b in m.get("content", []) if isinstance(b, dict) and "toolResult" in b]


def notes(agent):
    """Only the notes that were actually rendered for Maya.

    A blocked send still leaves a tool result in the transcript, carrying the reason the
    control gave the model. That is not a note. Telling the two apart is the difference
    between "she was told" and "the model was told no", and a test that confused them
    would pass while the product interrupted her.
    """
    return [t for t in tool_results(agent) if "forward this part to" in t]


# ---------------------------------------------------------------- deny

def test_nothing_of_hers_broken_means_nothing_is_sent():
    _, handler, agent = run(QUIET_DAY, note_script())
    assert handler.sent == []
    assert handler.denied
    assert notes(agent) == []
    assert any("Do not send" in t for t in tool_results(agent)), "the model was told why"


def test_the_denial_reason_names_what_was_ignored():
    """The reason the model is shown, not the label the handler keeps for itself.

    This assertion used to read `X in Y or handler.denied`, where X was never in Y. The
    `or` made it pass on a non-empty list, so the thing it was named for was untested.
    """
    _, handler, agent = run(QUIET_DAY, note_script())
    shown = " ".join(tool_results(agent))
    assert "none broke a routine" in shown, shown
    assert str(handler.impact["vendor_total_changes"]) in shown
    assert handler.denied == ["nothing she depends on is broken"], handler.denied


def test_a_model_that_insists_still_cannot_reach_her():
    """Three attempts in a row, all blocked. The control does not tire."""
    attempt = note_script()[0]
    script = [dict(attempt, id="a1"), dict(attempt, id="a2"), dict(attempt, id="a3"),
              {"text": "gave up"}]
    _, handler, agent = run(QUIET_DAY, script)
    assert handler.sent == []
    assert len(tool_inputs(agent)) == 3, "the model tried three times"
    assert notes(agent) == []


# ---------------------------------------------------------------- proceed

def test_a_confident_break_is_sent_without_asking_anybody():
    _, handler, _ = run(BRIEF_CHANGE, [SEND, {"text": "told her"}])
    assert handler.sent == ["orders-into-accounts"]
    assert handler.asked == []


def test_a_confident_break_beats_a_shaky_one_arriving_at_the_same_time():
    """One change touching a high and a low confidence routine must not wait for a person.

    This ordering was wrong first time: the low confidence check ran first, so one shaky
    mapping could hold a certain problem behind a human.
    """
    _, handler, _ = run(MIXED_DAY, [SEND, {"text": "told her"}])
    assert handler.sent == ["orders-into-accounts"]
    assert handler.asked == []


def test_a_low_confidence_only_break_is_held_for_a_person():
    """Held means a person is asked first, not that the note is thrown away."""
    _, handler, _ = run(LOW_ONLY_DAY, [SEND, {"text": "asked"}])
    assert handler.asked == ["monday-figure"]
    assert handler.sent == ["monday-figure"], "the person in this run said yes"


def test_a_person_who_says_no_stops_the_note():
    _, handler, agent = run(LOW_ONLY_DAY, [SEND, {"text": "asked"}],
                            approve_low_confidence=False)
    assert handler.sent == []
    assert notes(agent) == []
    assert any("CONFIRMATION_FAILED" in t for t in tool_results(agent))


def test_reading_a_routine_is_never_blocked():
    script = [{"tool": "read_routine", "id": "r1", "input": {"routine_id": "orders-into-accounts"}},
              {"text": "read it"}]
    _, handler, agent = run(QUIET_DAY, script)
    assert tool_inputs(agent, "read_routine"), "the read was blocked, it should not be"
    assert handler.sent == []


# ---------------------------------------------------------------- transform

def test_a_date_the_model_invented_is_overwritten_with_the_real_one():
    """The exact bug: a model given 14 July and 51 days ago wrote 2026-05-24 under FACT."""
    bad = {"tool": "send_to_maya", "id": "b1",
           "input": dict(SEND["input"], change_date="2026-05-24", routine_id="made-up")}
    _, handler, agent = run(BRIEF_CHANGE, [bad, {"text": "told her"}])
    sent = tool_inputs(agent)[0]
    assert sent["change_date"] == "2026-09-02"
    assert sent["routine_id"] == "orders-into-accounts"
    assert set(handler.stamp.overwritten) == {"change_date", "routine_id"}


def test_days_ago_is_stamped_rather_than_calculated():
    _, handler, agent = run(BRIEF_CHANGE, [SEND, {"text": "ok"}], today="2026-09-03")
    assert tool_inputs(agent)[0]["days_ago"] == 1


def test_a_model_that_leaves_the_facts_blank_still_gets_them():
    _, handler, agent = run(BRIEF_CHANGE, [SEND, {"text": "ok"}])
    sent = tool_inputs(agent)[0]
    assert sent["change_date"] and sent["routine_id"]
    assert handler.stamp.overwritten == [], "nothing to overwrite, the model left them blank"


def test_the_note_that_renders_carries_the_stamped_date_not_the_models():
    """The end of the chain, which is the only place that proves the stamp does anything.

    The three tests above assert on the tool payload. All three passed while the rendered
    note still carried the invented date, because nothing in the note was built from the
    stamped fields. That is the bug this test exists to catch.
    """
    _, handler, _ = run(BRIEF_CHANGE, [SEND, {"text": "ok"}], today="2026-09-03")
    assert handler.delivered, "nothing rendered"
    note = handler.delivered[-1]
    assert "2 September 2026" in note, note
    assert "yesterday" in note, note


def test_a_note_asserting_a_date_the_supplier_did_not_make_is_refused():
    """The model can still write a wrong date in its own prose. That note is not sent."""
    bad = {"tool": "send_to_maya", "id": "b1", "input": dict(
        SEND["input"], for_the_developer="FACT: removed on 2026-05-24 (51 days ago)")}
    _, handler, agent = run(BRIEF_CHANGE, [bad, {"text": "gave up"}])
    assert handler.refused == ["orders-into-accounts"], handler.refused
    assert handler.delivered == [], handler.delivered
    assert handler.sent == [], "a refused note must not count as sent"
    assert any(t.startswith("REJECTED") for t in tool_results(agent))


def test_the_model_can_correct_itself_and_the_second_note_is_delivered():
    bad = {"tool": "send_to_maya", "id": "b1", "input": dict(
        SEND["input"], for_the_developer="FACT: removed on 2026-05-24")}
    good = {"tool": "send_to_maya", "id": "g1", "input": dict(SEND["input"])}
    _, handler, _ = run(BRIEF_CHANGE, [bad, good, {"text": "ok"}])
    assert handler.refused == ["orders-into-accounts"]
    assert handler.sent == ["orders-into-accounts"]
    assert len(handler.delivered) == 1
    assert "2 September 2026" in handler.delivered[0]


def test_a_refused_note_is_not_recorded_as_told():
    """Otherwise the corrected retry is denied as a repeat of a note she never saw."""
    import tempfile
    bad = {"tool": "send_to_maya", "id": "b1", "input": dict(
        SEND["input"], headline="It broke on 24 May.")}
    with tempfile.TemporaryDirectory() as store:
        _, handler, agent = run(BRIEF_CHANGE, [bad, {"text": "gave up"}],
                                remember=True, session_id="t", storage_dir=store)
        assert memory.ledger(agent) == [], memory.ledger(agent)


def test_a_season_in_the_note_is_not_mistaken_for_a_date():
    """Maya's own profile says trading in December. That sentence reaches her notes."""
    ok = {"tool": "send_to_maya", "id": "s1", "input": dict(
        SEND["input"], what_it_costs="Every hour of downtime is a day of trading in December.")}
    _, handler, _ = run(BRIEF_CHANGE, [ok, {"text": "ok"}])
    assert handler.refused == []
    assert handler.delivered


def test_the_stamper_runs_before_the_tool_builds_the_note():  # noqa: D401
    """What the ordering actually has to guarantee.

    An earlier version of this asserted the order of a tuple the test itself wrote, which
    is not a test. The real requirement is that by the time `send_to_maya` runs, the
    factual fields hold the system's values, which is observable in the note.
    """
    bad = {"tool": "send_to_maya", "id": "b1", "input": dict(
        SEND["input"], change_date="1999-01-01", days_ago=9999)}
    _, handler, agent = run(BRIEF_CHANGE, [bad, {"text": "ok"}], today="2026-09-03")
    assert tool_inputs(agent)[0]["change_date"] == "2026-09-02"
    assert handler.delivered and "2 September 2026" in handler.delivered[0]
    assert "1999" not in handler.delivered[0]


def test_the_stamp_and_the_decision_choose_the_same_routine():
    """They chose differently, so a two routine day stamped the id of the other one."""

    _, handler, agent = run(MIXED_DAY, [SEND, {"text": "ok"}])
    subject = routine_to_report(handler.impact)
    assert subject["routine_id"] == handler.sent[0]
    assert tool_inputs(agent)[0]["routine_id"] == handler.sent[0]


def test_a_confident_routine_is_preferred_over_a_shaky_one_as_the_subject():
    _, handler, _ = run(MIXED_DAY, [SEND, {"text": "ok"}])
    touched = [r["routine_id"] for r in handler.impact["routines_touched"]]
    assert len(touched) > 1, "this fixture is meant to touch two routines"
    assert routine_to_report(handler.impact)["mapping_confidence"] != "low"


def test_a_model_that_calls_the_tool_three_times_does_not_send_three_notes():
    """One morning, one routine. The repeat rule has to bound this invocation too."""
    import tempfile
    attempt = {"tool": "send_to_maya", "id": "a", "input": dict(SEND["input"])}
    script = [dict(attempt, id=f"a{i}") for i in range(3)] + [{"text": "done"}]
    with tempfile.TemporaryDirectory() as store:
        _, handler, _ = run(BRIEF_CHANGE, script, remember=True, session_id="t",
                            storage_dir=store)
    assert handler.sent == ["orders-into-accounts"], handler.sent
    assert len(handler.delivered) == 1, handler.delivered
    assert handler.suppressed_repeat == ["orders-into-accounts"] * 2, handler.suppressed_repeat


def test_the_within_morning_rule_works_without_a_session_too():
    attempt = {"tool": "send_to_maya", "id": "a", "input": dict(SEND["input"])}
    _, handler, _ = run(BRIEF_CHANGE, [dict(attempt, id="a1"), dict(attempt, id="a2"),
                                       {"text": "done"}])
    assert len(handler.delivered) == 1, handler.delivered


def test_a_note_a_person_approved_counts_as_sent():
    """It was in the ledger and not in `sent`, so the morning produced no message."""
    _, handler, _ = run(LOW_ONLY_DAY, [SEND, {"text": "ok"}], approve_low_confidence=True)
    assert handler.asked == ["monday-figure"]
    assert handler.sent == ["monday-figure"]
    assert handler.delivered


# ---------------------------------------------------------------- memory

def test_the_same_routine_is_not_reported_twice_in_five_days():
    with tempfile.TemporaryDirectory() as store:
        _, first, _ = run(XERO_24_APR, [PAYROLL_SEND, {"text": "ok"}],
                          remember=True, session_id="t", storage_dir=store)
        _, second, _ = run(XERO_29_APR, [PAYROLL_SEND, {"text": "ok"}],
                           remember=True, session_id="t", storage_dir=store)
    assert first.sent == ["paying-the-team"]
    assert second.sent == []
    assert second.suppressed_repeat == ["paying-the-team"]


def test_the_same_routine_is_reported_again_after_the_quiet_period():
    later = dict(XERO_29_APR, date="2026-06-01")
    with tempfile.TemporaryDirectory() as store:
        run(XERO_24_APR, [PAYROLL_SEND, {"text": "ok"}],
            remember=True, session_id="t", storage_dir=store)
        _, second, _ = run(later, [PAYROLL_SEND, {"text": "ok"}],
                           remember=True, session_id="t", storage_dir=store)
    assert second.sent == ["paying-the-team"]
    assert second.suppressed_repeat == []


def test_a_different_routine_is_never_suppressed_by_an_earlier_one():
    with tempfile.TemporaryDirectory() as store:
        run(XERO_24_APR, [PAYROLL_SEND, {"text": "ok"}],
            remember=True, session_id="t", storage_dir=store)
        other = dict(BRIEF_CHANGE, date="2026-04-26")
        _, second, _ = run(other, [SEND, {"text": "ok"}],
                           remember=True, session_id="t", storage_dir=store)
    assert second.sent == ["orders-into-accounts"]


def test_an_agent_with_no_memory_has_never_told_her_anything():
    _, handler, _ = run(XERO_29_APR, [PAYROLL_SEND, {"text": "ok"}])
    assert handler.history == []
    assert handler.sent == ["paying-the-team"]


def test_the_ledger_records_what_went_out_not_what_was_asked_for():
    """The transcript holds what the model wanted. The ledger holds what cleared."""
    with tempfile.TemporaryDirectory() as store:
        _, handler, agent = run(QUIET_DAY, note_script(),
                                remember=True, session_id="t", storage_dir=store)
        assert memory.ledger(agent) == []
        assert memory.notes_in_transcript(agent.messages), "the model did ask"


@pytest.mark.parametrize("gap,suppressed", [(0, True), (1, True), (5, True), (6, False), (40, False)])
def test_the_quiet_window_is_five_days(gap, suppressed):
    rows = [{"routine_id": "r", "change_date": "2026-04-24"}]
    import datetime as dt
    today = (dt.date(2026, 4, 24) + dt.timedelta(days=gap)).isoformat()
    assert bool(memory.told_recently(rows, "r", today)) is suppressed


def test_a_change_older_than_the_note_is_not_a_repeat():
    rows = [{"routine_id": "r", "change_date": "2026-04-24"}]
    assert memory.told_recently(rows, "r", "2026-04-20") is None


def test_a_ledger_row_with_a_broken_date_is_ignored_rather_than_crashing():
    rows = [{"routine_id": "r", "change_date": "not a date"}]
    assert memory.told_recently(rows, "r", "2026-04-25") is None


def test_a_repeat_is_only_suppressed_when_it_is_the_only_thing_broken():
    """If something new broke as well, she hears about the morning."""
    rows = [{"routine_id": "paying-the-team", "change_date": "2026-04-24"}]
    both = {"date": "2026-04-26", "vendor": "xero", "changes": [
        {"kind": "endpoint_removed", "endpoint": "GET /Employees", "breaking": True},
        {"kind": "endpoint_removed", "endpoint": "GET /BankTransactions", "breaking": True}]}
    from tools.impact import assess, load_business
    impact = assess(load_business(), both)
    agent, stamp, decide = build(impact, [PAYROLL_SEND, {"text": "ok"}])
    decide.history = rows
    agent("go")
    assert decide.sent, "a new break must not be held back by an old repeat"


# ---------------------------------------------------------------- accounting

def test_the_result_reports_what_the_morning_cost():
    _, handler, _ = run(BRIEF_CHANGE, [SEND, {"text": "ok"}])
    summary = cost_of_the_morning(handler.result)
    assert "cycles" in summary and "tokens" in summary


def test_a_denied_morning_still_reports_its_cost():
    _, handler, _ = run(QUIET_DAY, note_script())
    assert "cycles" in cost_of_the_morning(handler.result)


def test_metrics_come_from_the_framework_not_from_a_counter_of_mine():
    _, handler, _ = run(BRIEF_CHANGE, [SEND, {"text": "ok"}])
    assert handler.result.metrics.get_summary()["total_cycles"] >= 1


# ---------------------------------------------------------------- several at once

def three_sends(**overrides):
    payload = dict(SEND["input"], **overrides)
    return [{"tool": "send_to_maya", "id": f"p{i}", "input": dict(payload)} for i in range(3)]


def test_three_notes_asked_for_in_one_message_still_produce_one():
    """A model can ask for several tools at once, and every before-hook runs first.

    The bookkeeping was written one call at a time, so all three were decided against an
    empty record of what had already gone out this morning, and all three rendered.
    """
    _, handler, _ = run(BRIEF_CHANGE, [{"tools": three_sends()}, {"text": "done"}])
    assert len(handler.delivered) == 1, handler.delivered
    assert handler.sent == ["orders-into-accounts"], handler.sent
    assert len(handler.suppressed_repeat) == 2, handler.suppressed_repeat


def test_three_at_once_on_a_day_that_breaks_two_routines_still_produce_one():
    _, handler, _ = run(MIXED_DAY, [{"tools": three_sends()}, {"text": "done"}])
    assert len(handler.delivered) == 1, handler.delivered
    assert handler.sent == ["orders-into-accounts"], handler.sent


def test_a_bad_and_a_good_note_in_one_message_never_send_the_bad_one():
    """Asserted as an invariant, because the interleaving is the framework's business.

    Strands is free to run the hooks for a batch of tool calls either way round, and it
    does. On Python 3.11 every decision is taken before any tool runs, so the good note is
    held as a repeat of the bad one and the morning ends silent. On 3.14 they run in pairs,
    the bad one is refused and retracted, and the good one goes out.

    Both are acceptable. An earlier version of this test pinned one of them, which meant it
    was testing the version of Python it happened to be run on, and it passed here and
    failed on the machine this is built on. What has to be true either way is that the
    wrong date never reaches Maya and that she never gets two notes.
    """
    calls = [{"tool": "send_to_maya", "id": "bad",
              "input": dict(SEND["input"], headline="It broke on 24 May.")},
             {"tool": "send_to_maya", "id": "good", "input": dict(SEND["input"])}]
    _, handler, _ = run(BRIEF_CHANGE, [{"tools": calls}, {"text": "done"}])

    assert handler.refused == ["orders-into-accounts"], handler.refused
    assert len(handler.delivered) <= 1, handler.delivered
    assert len(handler.sent) == len(handler.delivered), (handler.sent, handler.delivered)
    for note in handler.delivered:
        assert "24 May" not in note and "2026-05-24" not in note, note
        assert "2 September 2026" in note, note


def test_a_batch_of_identical_notes_never_produces_more_than_one():
    """The invariant that matters, across every interleaving and every batch size."""
    for size in (2, 3, 5):
        calls = [{"tool": "send_to_maya", "id": f"b{i}", "input": dict(SEND["input"])}
                 for i in range(size)]
        _, handler, _ = run(BRIEF_CHANGE, [{"tools": calls}, {"text": "done"}])
        assert len(handler.delivered) == 1, (size, handler.delivered)
        assert handler.sent == ["orders-into-accounts"], (size, handler.sent)
        assert len(handler.suppressed_repeat) == size - 1, (size, handler.suppressed_repeat)


def test_and_the_next_attempt_after_that_batch_does_get_through():
    """Whichever way the batch went, one more attempt leaves exactly one note delivered."""
    calls = [{"tool": "send_to_maya", "id": "bad",
              "input": dict(SEND["input"], headline="It broke on 24 May.")},
             {"tool": "send_to_maya", "id": "good", "input": dict(SEND["input"])}]
    retry = {"tool": "send_to_maya", "id": "retry", "input": dict(SEND["input"])}
    _, handler, _ = run(BRIEF_CHANGE, [{"tools": calls}, retry, {"text": "done"}])
    assert len(handler.delivered) == 1, handler.delivered
    assert handler.sent == ["orders-into-accounts"], handler.sent
    assert "2 September 2026" in handler.delivered[0]


def test_a_tool_that_raises_is_not_recorded_as_a_note_she_received(monkeypatch):
    """It was, because the check was "does the result start with REJECTED".

    An exception comes back as an error string, which is neither a note nor a refusal. It
    was filed as a delivery, which blocked the retry and, in the round-up, became the
    message Maya got.
    """
    from agent import notes as notes_module

    def explode(self):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(notes_module.MayaNote, "render", explode)
    _, handler, _ = run(BRIEF_CHANGE, [SEND, {"text": "gave up"}])
    assert handler.delivered == [], handler.delivered
    assert handler.failed == ["orders-into-accounts"], handler.failed
    assert handler.sent == [], "a note that never rendered is not a note she was sent"


def test_a_tool_that_raises_leaves_the_ledger_empty_so_the_retry_is_allowed():
    from agent import notes as notes_module
    import tempfile
    real = notes_module.MayaNote.render
    calls = {"n": 0}

    def once(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("renderer exploded")
        return real(self)

    notes_module.MayaNote.render = once
    try:
        with tempfile.TemporaryDirectory() as store:
            _, handler, _ = run(BRIEF_CHANGE,
                                [{"tool": "send_to_maya", "id": "a", "input": dict(SEND["input"])},
                                 {"tool": "send_to_maya", "id": "b", "input": dict(SEND["input"])},
                                 {"text": "done"}],
                                remember=True, session_id="t", storage_dir=store)
    finally:
        notes_module.MayaNote.render = real
    assert handler.failed == ["orders-into-accounts"]
    assert len(handler.delivered) == 1, "the retry after a crash must get through"


# ---------------------------------------------------------------- the guard's edges

@pytest.mark.parametrize("line", [
    "stripe: contract version moved to 2026-08-26.dahlia",
    "square: GET /v1/reports/2026-08-26 removed",
    "this may 3 times a week",
    "every hour of downtime is a day of trading in December",
])
def test_the_date_guard_does_not_refuse_a_legitimate_note(line):
    """A version string, a path with a date in it, a lowercase may, and a season."""
    send = {"tool": "send_to_maya", "id": "ok", "input": dict(SEND["input"],
                                                              for_the_developer=line)}
    _, handler, _ = run(BRIEF_CHANGE, [send, {"text": "ok"}])
    assert handler.refused == [], (line, handler.refused)
    assert handler.delivered, line


@pytest.mark.parametrize("line", [
    "FACT: removed on 2026-05-24",
    "FACT: removed on 2026-05-24.",
    "removed on 2026-05-24, which was 51 days ago",
    "this happened on 24 May",
])
def test_the_date_guard_still_refuses_a_second_date(line):
    send = {"tool": "send_to_maya", "id": "bad", "input": dict(SEND["input"],
                                                               for_the_developer=line)}
    _, handler, _ = run(BRIEF_CHANGE, [send, {"text": "gave up"}])
    assert handler.refused == ["orders-into-accounts"], (line, handler.refused)
    assert handler.delivered == [], line


# ---------------------------------------------------------------- streaming

def test_a_streamed_morning_can_be_costed_like_any_other():
    """`cost_of_the_morning(handler.result)` raised on the one path nothing called it on."""
    import asyncio
    import io
    from agent.still_working import run_streaming
    buf = io.StringIO()
    _, handler, pieces = asyncio.run(run_streaming(
        BRIEF_CHANGE, [SEND, {"text": "Told her, and here is why it mattered."}], out=buf))
    assert pieces > 1, "streamed in one lump, which is not streaming"
    assert handler.sent == ["orders-into-accounts"]
    assert "cycles" in cost_of_the_morning(handler.result)
    assert handler.stamp is not None


def test_a_streamed_morning_delivers_the_same_note_as_a_synchronous_one():
    import asyncio
    import io
    from agent.still_working import run_streaming
    _, sync_handler, _ = run(BRIEF_CHANGE, [SEND, {"text": "ok"}], today="2026-09-03")
    _, streamed, _ = asyncio.run(run_streaming(BRIEF_CHANGE, [SEND, {"text": "ok"}],
                                               out=io.StringIO()))
    assert streamed.delivered and sync_handler.delivered
    assert streamed.delivered[-1].splitlines()[0] == sync_handler.delivered[-1].splitlines()[0]
