"""End-to-end delivery invariants at the actual deployed entrypoint."""
import asyncio
from copy import deepcopy

import pytest

from agent.model_double import ScriptedModel
from test_runtime_contract import deployed, IMPACT, note


def run(monkeypatch, impact=None, script=None):
    monkeypatch.setattr(deployed, "load_model", lambda: ScriptedModel(script or []))
    return asyncio.run(deployed.invoke(deepcopy(impact or IMPACT)))


def send(**kwargs):
    return {"tool": "send_to_maya", "id": "send-1", "input": note(**kwargs)}


def test_rejected_note_is_not_an_all_clear_and_does_not_enter_the_ledger(monkeypatch):
    result = run(monkeypatch, script=[send(headline="It stopped on 24 May."), {"text": "Done."}])
    assert result["state"] == "held_for_a_person"
    assert result["note"] is None
    assert result["delivery_history"] == []
    assert result["decisions"][0]["outcome"] == "note_needs_review"


def test_a_corrected_retry_gets_through_and_only_it_is_remembered(monkeypatch):
    result = run(monkeypatch, script=[send(headline="It stopped on 24 May."),
                                      dict(send(headline="The stock sync needs checking."), id="send-2"),
                                      {"text": "Done."}])
    assert result["state"] == "something_broke"
    assert "24 May" not in result["note"]
    assert "14 July 2026" in result["note"]
    assert len(result["delivery_history"]) == 1
    assert result["decisions"][0]["refused_attempts"] == 1


def test_two_attempts_cannot_make_two_deliveries(monkeypatch):
    result = run(monkeypatch, script=[send(), dict(send(), id="send-2"), {"text": "Done."}])
    assert len(result["notes"]) == 1
    assert len(result["delivery_history"]) == 1


def test_a_fresh_invocation_carries_the_returned_repeat_ledger(monkeypatch):
    first = run(monkeypatch, script=[send(), {"text": "Done."}])
    next_day = dict(IMPACT, date="2026-07-19", delivery_history=first["delivery_history"])
    monkeypatch.setattr(deployed, "load_model", lambda: pytest.fail("a repeat constructed a model"))
    second = asyncio.run(deployed.invoke(next_day))
    assert second["note"] is None
    assert second["decisions"] == [{"routine_id": IMPACT["routines_touched"][0]["routine_id"],
                                    "outcome": "repeat_held", "days_since": 5}]
    assert second["agent_runs"] == 0
    assert len(second["delivery_history"]) == 1


@pytest.mark.parametrize("confidence", ["low", "unknown", None])
def test_an_unconfirmed_mapping_never_constructs_a_model_or_sends(monkeypatch, confidence):
    impact = deepcopy(IMPACT)
    impact["routines_touched"][0]["mapping_confidence"] = confidence
    monkeypatch.setattr(deployed, "load_model", lambda: pytest.fail("uncertain mapping reached the model"))
    result = asyncio.run(deployed.invoke(impact))
    assert result["state"] == "held_for_a_person"
    assert result["note"] is None
    assert result["agent_runs"] == 0


def test_a_quiet_day_constructs_no_model(monkeypatch):
    monkeypatch.setattr(deployed, "load_model", lambda: pytest.fail("quiet day constructed a model"))
    result = asyncio.run(deployed.invoke(dict(IMPACT, routines_touched=[])))
    assert result["state"] == "still_working" and result["agent_runs"] == 0


def test_medium_confidence_is_visible_even_when_the_model_omits_it(monkeypatch):
    impact = deepcopy(IMPACT)
    impact["routines_touched"][0]["mapping_confidence"] = "medium"
    result = run(monkeypatch, impact, [send(), {"text": "Done."}])
    assert result["carrying_doubt"]
    assert "I am not certain about this" in result["note"]


def test_a_model_changing_the_year_is_also_refused(monkeypatch):
    result = run(monkeypatch, script=[send(headline="It stopped on 2025-07-14."), {"text": "Done."}])
    assert result["note"] is None
    assert result["delivery_history"] == []


def test_concurrent_invocations_do_not_share_date_guards(monkeypatch):
    scripts = iter([[send(headline="It stopped on 14 July."), {"text": "Done."}],
                    [send(headline="It stopped on 24 April."), {"text": "Done."}]])
    monkeypatch.setattr(deployed, "load_model", lambda: ScriptedModel(next(scripts)))
    async def both():
        return await asyncio.gather(deployed.invoke(deepcopy(IMPACT)),
                                    deployed.invoke(dict(deepcopy(IMPACT), date="2026-04-24")))
    first, second = asyncio.run(both())
    assert "14 July 2026" in first["note"]
    assert "24 April 2026" in second["note"]
    assert "24 April" not in first["note"]
    assert "14 July" not in second["note"]


def test_a_repeat_cannot_hide_a_different_routine(monkeypatch):
    impact = deepcopy(IMPACT)
    rid = impact["routines_touched"][0]["routine_id"]
    impact["delivery_history"] = [{"routine_id": rid, "change_date": impact["date"]}]
    impact["routines_touched"].append(dict(impact["routines_touched"][0], routine_id="payroll",
                                         what_maya_calls_it="Paying the team"))
    result = run(monkeypatch, impact, [send(headline="Payroll needs checking."), {"text": "Done."}])
    assert result["routine"] == "Paying the team"
    assert len(result["notes"]) == 1
    assert len(result["delivery_history"]) == 2


def test_the_runtime_packages_the_canonical_controls_without_drift():
    from tools.sync_runtime import main
    assert main(check=True) == 0


def test_a_changed_bundle_is_detected(tmp_path, monkeypatch):
    from tools import sync_runtime
    monkeypatch.setattr(sync_runtime, "BUNDLE", tmp_path)
    assert sync_runtime.main() == 0
    (tmp_path / "controls.py").write_text("# stale runtime\n")
    assert sync_runtime.main(check=True) == 1
