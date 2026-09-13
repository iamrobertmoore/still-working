"""Fresh supplier data must not hide a failed agent, or lose yesterday's work."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from tools.delivery_status import queue_changes
from tools.deliver import process
from tools.impact import load_business
from tools import render_page

ROOT = Path(__file__).resolve().parents[1]
RECORD = next(json.loads(line) for line in (ROOT / 'contracts/changes.jsonl').read_text().splitlines()
              if json.loads(line)['vendor'] == 'square' and json.loads(line)['date'] == '2026-07-14')


def test_collection_keeps_a_change_when_cloud_fails_then_next_day_delivers_it_once():
    original = {'history': [], 'processed': [], 'pending': {}}
    business = load_business()
    queued = queue_changes([RECORD], business, original, RECORD['date'])
    assert original['pending'] == {} and len(queued['pending']) == 1
    before = deepcopy(queued)
    def unavailable(_):
        raise RuntimeError('AWS unavailable')
    with pytest.raises(RuntimeError, match='AWS unavailable'):
        process([], business, queued, unavailable)
    assert queued == before
    tomorrow = queue_changes([], business, queued, '2026-07-15')
    calls = []
    def deliver(impact):
        calls.append(impact)
        return {'state': 'something_broke', 'note': 'Check stock.', 'pending_routines': [],
                'delivery_history': [{'routine_id': 'stock-between-counter-and-website', 'change_date': impact['date']}]}
    done, notes, _ = process([], business, tomorrow, deliver)
    assert len(calls) == len(notes) == len(done['history']) == 1 and not done['pending']
    again = queue_changes([RECORD], business, done, RECORD['date'])
    _, notes, _ = process([], business, again, lambda _: pytest.fail('delivered twice'))
    assert not notes and not again['pending']


def test_collection_does_not_replay_the_historical_demo_or_replace_a_human_hold():
    business = load_business()
    assert not queue_changes([RECORD], business, {}, '2026-09-13')['pending']
    queued = queue_changes([RECORD], business, {}, RECORD['date'])
    key = next(iter(queued['pending']))
    queued['pending'][key]['reason'] = 'Needs the developer to check the mapping.'
    assert queue_changes([RECORD], business, queued, RECORD['date']) == queued


@pytest.mark.parametrize('phase', ['pending', 'failed', 'complete'])
def test_page_distinguishes_fresh_collection_from_agent_completion(tmp_path, monkeypatch, phase):
    import shutil
    shutil.copytree(ROOT / 'contracts', tmp_path / 'contracts')
    data = tmp_path / 'contracts'
    (data / 'agent-status.json').write_text(json.dumps({
        'state': phase, 'last_completed_at': '2026-09-13T20:00:00+00:00'}))
    (data / 'changes.jsonl').write_text('')
    (data / 'delivery-state.json').write_text('{"pending": {}}')
    output = tmp_path / 'index.html'
    monkeypatch.setattr(render_page, 'CONTRACTS', str(data))
    monkeypatch.setattr(render_page, 'OUT', str(output))
    render_page.main()
    page = output.read_text()
    assert 'Checked ' in page
    if phase == 'complete':
        assert 'class="state ok">Still working.' in page and 'Agent review complete' in page
    else:
        assert 'class="state warn">Check in progress.' in page
        assert 'Get on with your day' not in page
        assert ('Agent review pending' if phase == 'pending' else 'Agent review could not finish') in page


def test_collection_publishes_before_cloud_and_failed_cloud_publishes_its_status():
    import yaml
    workflow = yaml.safe_load((ROOT / '.github/workflows/contract-watch.yml').read_text())
    collector = workflow['jobs']['collect']
    delivery = workflow['jobs']['deliver']
    assert 'id-token' not in workflow['permissions']
    assert all('configure-aws-credentials' not in step.get('uses', '') for step in collector['steps'])
    assert delivery['needs'] == 'collect'
    assert delivery['permissions']['id-token'] == 'write'
    steps = collector['steps']
    queue = next(i for i, step in enumerate(steps) if 'delivery_status.py collected' in step.get('run', ''))
    publish = next(i for i, step in enumerate(steps) if step.get('id') == 'publish')
    assert queue < publish
    result = delivery['steps'][-1]
    assert 'always()' in result['if'] and 'failed' in result['env']['DELIVERY_PHASE']
    assert 'continue-on-error' not in next(step for step in delivery['steps'] if step.get('id') == 'deliver')
