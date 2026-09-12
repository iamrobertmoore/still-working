#!/usr/bin/env python3
"""Capture a controlled low-confidence review scenario against the actual runtime.

The supplier change is historical; lowered confidence and reviewer decisions are
explicit demonstration inputs. They are not a real developer's validation.
"""
from copy import deepcopy
import datetime as dt
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agent.review import case_id
from tools.cloud import runtime_client


def main():
    cases=json.loads((ROOT/'docs/replay/recordings.json').read_text())['cases']
    original=next(c for c in cases if c['record']['vendor']=='square' and c['record']['date']=='2026-07-14')
    impact=deepcopy(original['impact']);impact['delivery_history']=[]
    for routine in impact['routines_touched']:
        routine['mapping_confidence']='low'
    routine=next(r for r in impact['routines_touched'] if r['has_breaking_change'])
    key=case_id(impact,routine)
    approve={'case_id':key,'decision':'approve','reviewer':'Example reviewer',
             'reason':'Demonstration input: assume a developer has confirmed that this routine uses the affected call. No real integration was checked.'}
    dismiss=dict(approve,decision='dismiss',reason='Demonstration input: assume a developer checked and this routine does not use the affected call.')
    invoke=runtime_client();steps={}
    for name,request in [('held',impact),('approved',dict(impact,human_reviews={key:approve})),
                         ('dismissed',dict(impact,human_reviews={key:dismiss}))]:
        response=invoke(request);steps[name]={'input':request,'result':response}
        print(name,response['state'],response['agent_runs'],flush=True)
    repeat=dict(impact,human_reviews={key:approve},delivery_history=steps['approved']['result']['delivery_history'])
    steps['repeat']={'input':repeat,'result':invoke(repeat)}
    assert steps['held']['result']['state']=='held_for_a_person'
    assert steps['approved']['result']['note'] and steps['approved']['result']['agent_runs']==1
    assert steps['dismissed']['result']['agent_runs']==0 and not steps['dismissed']['result']['pending_routines']
    assert steps['repeat']['result']['agent_runs']==0 and not steps['repeat']['result']['notes']
    payload={'mode':'example','captured_at':dt.datetime.now(dt.timezone.utc).isoformat(),
             'method':'Real AgentCore responses to a controlled review scenario. Historical Square change; mapping confidence deliberately lowered from high to low. Reviewer decisions are simulated, not customer validation.',
             'case':{'case_id':key,'date':impact['date'],'vendor':impact['vendor'],'routine':routine},'steps':steps}
    dest=ROOT/'docs/review/proof.json';dest.parent.mkdir(parents=True,exist_ok=True)
    temporary=dest.with_suffix('.tmp');temporary.write_text(json.dumps(payload,indent=2)+'\n');temporary.replace(dest)
    print('Saved four actual review-branch responses.')


if __name__=='__main__':main()
