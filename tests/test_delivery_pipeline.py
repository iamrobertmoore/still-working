"""The scheduled caller must persist only real outcomes and retry incomplete work."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from tools.deliver import process
from tools.impact import load_business

ROOT = Path(__file__).resolve().parents[1]
ROWS = [json.loads(l) for l in (ROOT / 'contracts/changes.jsonl').read_text().splitlines()]
BREAK = next(r for r in ROWS if r['breaking_count'])


def delivered(impact):
    row = next(r for r in impact['routines_touched'] if r['has_breaking_change'])
    return {'state': 'something_broke', 'reason': 'rendered', 'note': 'A note for Priya.',
            'delivery_history': impact['delivery_history'] + [
                {'routine_id': row['routine_id'], 'change_date': impact['date']}],
            'pending_routines': []}


def test_unrelated_changes_never_invoke_the_runtime():
    rows = [r for r in ROWS if not r['breaking_count']]
    def never(_):
        pytest.fail('irrelevant change reached the cloud')
    state, notes, outcomes = process(rows, load_business(), {}, never)
    assert not notes and not outcomes and state['history'] == []


def test_only_a_rendered_note_moves_the_delivery_ledger_and_reruns_do_nothing():
    state, notes, outcomes = process([BREAK], load_business(), {}, delivered)
    assert len(notes) == 1 and len(state['history']) == 1
    state2, notes2, outcomes2 = process([BREAK], load_business(), state,
                                       lambda _: pytest.fail('rerun invoked the runtime'))
    assert state2 == state and not notes2 and not outcomes2


def test_a_runtime_failure_cannot_mutate_the_callers_ledger():
    state = {'history': [], 'processed': [], 'pending': {}}
    before = deepcopy(state)
    def failure(_):
        raise RuntimeError('provider unavailable')
    with pytest.raises(RuntimeError):
        process([BREAK], load_business(), state, failure)
    assert state == before


def test_a_pending_note_is_retried_even_when_no_new_supplier_change_arrives():
    def pending(impact):
        return {'state': 'held_for_a_person', 'reason': 'note needs checking', 'note': None,
                'delivery_history': impact['delivery_history'], 'pending_routines': ['paying-the-team']}
    state, notes, _ = process([BREAK], load_business(), {}, pending)
    assert not notes and state['pending'] and not state['history']
    state, notes, _ = process([], load_business(), state, delivered)
    assert len(notes) == 1 and len(state['history']) == 1 and not state['pending']
