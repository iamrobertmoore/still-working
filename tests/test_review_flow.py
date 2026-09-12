"""A review must bind to the exact case and only affect that case's delivery."""
import asyncio
from copy import deepcopy
import pytest
from agent.review import case_id, decision_for
from agent.model_double import ScriptedModel
from test_runtime_contract import deployed, IMPACT, note
from tools.review import import_decisions


def low_impact():
    impact = deepcopy(IMPACT)
    impact['routines_touched'][0]['mapping_confidence'] = 'low'
    return impact


def review(impact, decision='approve'):
    key = case_id(impact, impact['routines_touched'][0])
    return {'case_id':key, 'decision':decision, 'reviewer':'Example reviewer',
            'reason':'Checked the integration and this routine uses the affected call.'}


def test_approved_low_confidence_case_reaches_the_actual_delivery_tool(monkeypatch):
    impact=low_impact();choice=review(impact);impact['human_reviews']={choice['case_id']:choice}
    monkeypatch.setattr(deployed,'load_model',lambda:ScriptedModel([
        {'tool':'send_to_maya','id':'approved','input':note()}, {'text':'done'}]))
    result=asyncio.run(deployed.invoke(impact))
    assert result['note'] and len(result['delivery_history']) == 1
    assert result['decisions'][0]['review'] == choice
    assert result['agent_runs'] == 1


def test_dismissal_requires_no_model_and_does_not_fake_a_delivery(monkeypatch):
    impact=low_impact();choice=review(impact,'dismiss');impact['human_reviews']={choice['case_id']:choice}
    monkeypatch.setattr(deployed,'load_model',lambda:pytest.fail('dismissed case built a model'))
    result=asyncio.run(deployed.invoke(impact))
    assert result['note'] is None and result['delivery_history'] == []
    assert result['decisions'][0]['outcome'] == 'dismissed_by_reviewer'
    assert not result['pending_routines']


def test_changing_the_day_or_mapping_invalidates_the_approval(monkeypatch):
    impact=low_impact();choice=review(impact);impact['human_reviews']={choice['case_id']:choice}
    monkeypatch.setattr(deployed,'load_model',lambda:pytest.fail('stale approval built a model'))
    for changed in [dict(impact,date='2026-07-15'),deepcopy(impact)]:
        if changed['date'] == impact['date']:
            changed['routines_touched'][0]['changes'].append({'kind':'param_removed','param':'different','breaking':True})
        assert asyncio.run(deployed.invoke(changed))['state'] == 'held_for_a_person'


def test_review_import_rejects_examples_stale_cases_and_partial_batches():
    impact=low_impact();choice=review(impact);key=choice['case_id'];available={key:{}}
    previous={}
    with pytest.raises(ValueError):import_decisions({'mode':'example','decisions':[choice]},available,previous)
    with pytest.raises(ValueError):import_decisions({'mode':'live','decisions':[choice,dict(choice,case_id='stale')]},available,previous)
    assert previous == {}
    accepted=import_decisions({'mode':'live','decisions':[choice]},available,previous)
    assert accepted == {key:choice}
    assert import_decisions({'mode':'live','decisions':[choice]},available,accepted)==accepted
    with pytest.raises(ValueError):import_decisions({'mode':'live','decisions':[dict(choice,decision='dismiss')]},available,accepted)


def test_approval_survives_relative_age_changing_but_not_a_business_consequence():
    impact=low_impact();choice=review(impact);impact['human_reviews']={choice['case_id']:choice}
    assert decision_for(dict(impact,days_ago=100),impact['routines_touched'][0]) == choice
    changed=deepcopy(impact);changed['routines_touched'][0]['what_it_costs']='Different consequence'
    assert decision_for(changed,changed['routines_touched'][0]) is None


def test_downloaded_review_closes_the_real_pending_delivery_loop(monkeypatch):
    import json
    from pathlib import Path
    from tools.deliver import process
    from tools.impact import load_business
    from tools.review import pending_cases
    root=Path(__file__).resolve().parents[1]
    records=[json.loads(line) for line in (root/'contracts/changes.jsonl').read_text().splitlines()]
    record=next(r for r in records if r['vendor']=='square' and r['date']=='2026-07-14')
    business=deepcopy(load_business())
    for routine in business['routines']:
        if routine['id']=='stock-between-counter-and-website':routine['derived']['confidence']='low'
    def cloud(impact):return asyncio.run(deployed.invoke(impact))
    monkeypatch.setattr(deployed,'load_model',lambda:pytest.fail('unreviewed case built a model'))
    state,notes,_=process([record],business,{},cloud)
    assert state['pending'] and not notes and not state['history']
    available=pending_cases(business,state)
    key=next(iter(available))
    choice={'case_id':key,'decision':'approve','reviewer':'Example reviewer','reason':'Checked the exact affected call.'}
    accepted=import_decisions({'mode':'live','decisions':[choice]},available,{})
    monkeypatch.setattr(deployed,'load_model',lambda:ScriptedModel([
        {'tool':'send_to_maya','id':'approved','input':note()}, {'text':'done'}]))
    state,notes,outcomes=process([],business,state,cloud,accepted)
    assert not state['pending'] and len(state['history'])==1 and len(notes)==1
    assert outcomes[0]['result']['decisions'][0]['review']==choice
    state2,notes2,outcomes2=process([record],business,state,lambda _:pytest.fail('processed case invoked twice'),accepted)
    assert state2==state and not notes2 and not outcomes2
