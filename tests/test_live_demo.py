from copy import deepcopy
import json

import pytest

from tools.live_demo import ROOT, demonstrate
from tools.impact import load_business

RECORD = next(json.loads(line) for line in (ROOT / 'contracts/changes.jsonl').read_text().splitlines()
              if json.loads(line)['vendor'] == 'square' and json.loads(line)['date'] == '2026-07-14')


def response(impact):
    prior = impact['delivery_history']
    routine = next(r for r in impact['routines_touched'] if r['has_breaking_change'])
    return {'controls_version': 'shared-v1', 'state': 'still_working' if prior else 'something_broke',
            'agent_runs': 0 if prior else 1, 'note': None if prior else 'Check the stock routine.',
            'notes': [] if prior else ['Check the stock routine.'], 'pending_routines': [],
            'delivery_history': prior or [{'routine_id': routine['routine_id'], 'change_date': impact['date']}]}


def test_repeat_uses_the_fresh_cloud_ledger_and_preserves_original_input():
    calls = []
    def invoke(impact):
        calls.append(deepcopy(impact))
        return response(impact)
    steps = demonstrate(RECORD, load_business(), invoke)
    assert len(calls) == 2
    assert calls[0]['delivery_history'] == []
    assert calls[1]['delivery_history'] == steps[0]['result']['delivery_history']
    assert steps[0]['input']['delivery_history'] == []


@pytest.mark.parametrize('defect', ['refused', 'wrong_ledger', 'repeat_runs', 'repeat_ledger', 'old_contract'])
def test_a_bad_cloud_result_never_prints_a_verified_result(defect, capsys):
    def invoke(impact):
        result = response(impact)
        if defect == 'refused':
            result.update(state='held_for_a_person', note=None)
        elif defect == 'wrong_ledger':
            result['delivery_history'][0]['change_date'] = '2026-01-01'
        elif defect == 'old_contract':
            result['controls_version'] = 'old'
        elif impact['delivery_history'] and defect == 'repeat_runs':
            result['agent_runs'] = 1
        elif impact['delivery_history'] and defect == 'repeat_ledger':
            result['delivery_history'] = []
        return result
    with pytest.raises(RuntimeError):
        demonstrate(RECORD, load_business(), invoke)
    assert 'Repeat held' not in capsys.readouterr().out


def test_provider_failure_is_not_replaced_with_a_saved_response():
    def unavailable(_):
        raise RuntimeError('provider unavailable')
    with pytest.raises(RuntimeError, match='provider unavailable'):
        demonstrate(RECORD, load_business(), unavailable)
