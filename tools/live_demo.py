#!/usr/bin/env python3
"""Run the historical stock change against AWS now, then prove the repeat is held.

Uses the current matcher and profile, fresh cloud responses and an isolated ledger.
Does not change the daily delivery state or overwrite the published replay.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.cloud import runtime_client
from tools.impact import assess, load_business


def demonstrate(record, business, invoke):
    impact = assess(business, record, today=record['date'])
    impact['delivery_history'] = []
    steps = []

    def call(name, request):
        print(f'{name}: calling AgentCore...', flush=True)
        started = time.monotonic()
        result = invoke(deepcopy(request))
        if result.get('controls_version') != 'shared-v1':
            raise RuntimeError('Unexpected deployed controls. No successful demonstration claimed.')
        steps.append({'step': name, 'input': deepcopy(request), 'result': result,
                      'elapsed_seconds': round(time.monotonic() - started, 3)})
        return result

    first = call('1. Stock warning', impact)
    ledger = first.get('delivery_history')
    expected = {r['routine_id'] for r in impact['routines_touched'] if r['has_breaking_change']}
    if (first.get('state') != 'something_broke' or first.get('agent_runs') != 1
            or not isinstance(first.get('note'), str) or not first['note'].strip()
            or not isinstance(ledger, list) or len(ledger) != 1
            or ledger[0].get('routine_id') not in expected
            or ledger[0].get('change_date') != record['date']):
        raise RuntimeError('The stock case did not produce one note and its matching ledger entry.')
    print(f"   One note rendered; one agent run. {steps[-1]['elapsed_seconds']:.1f}s", flush=True)
    print(f"   {first['note'].strip().splitlines()[0]}", flush=True)

    repeat = dict(impact, delivery_history=deepcopy(ledger))
    second = call('2. Same change, returned ledger', repeat)
    if (second.get('state') != 'still_working' or second.get('agent_runs') != 0
            or second.get('note') or second.get('notes') or second.get('pending_routines')
            or second.get('delivery_history') != ledger):
        raise RuntimeError('Repeat suppression failed: expected no model, no note and unchanged ledger.')
    print(f"   Repeat held; zero agent runs; no second note. {steps[-1]['elapsed_seconds']:.1f}s", flush=True)
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-arn')
    parser.add_argument('--output', type=Path, help='Save these fresh inputs and responses as JSON.')
    args = parser.parse_args()
    changelog = ROOT / 'contracts/changes.jsonl'
    profile = ROOT / 'business/maya.yaml'
    records = [json.loads(line) for line in changelog.read_text().splitlines() if line.strip()]
    record = next(r for r in records if r['vendor'] == 'square' and r['date'] == '2026-07-14')
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    print('STILL WORKING | fresh cloud execution', flush=True)
    print(f'UTC: {started_at}', flush=True)
    print('Input: Square publication, 14 July 2026. Illustrative shop; isolated demo ledger.', flush=True)
    steps = demonstrate(record, load_business(str(profile)), runtime_client(args.runtime_arn))
    payload = {'mode': 'fresh_historical_demo', 'started_at': started_at,
               'completed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'method': 'Historical supplier input, current matcher, illustrative shop, fresh AWS responses. Returned ledger carried to a second invocation.',
               'changes_sha256': hashlib.sha256(changelog.read_bytes()).hexdigest(),
               'profile_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
               'record': record, 'steps': steps}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + '\n')
        print(f'Fresh inputs and responses saved to {args.output}', flush=True)
    print('Verified: a useful warning, then no repeated interruption.', flush=True)


if __name__ == '__main__':
    main()
