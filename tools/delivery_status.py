#!/usr/bin/env python3
"""Persist the collection-to-delivery queue and report both stages independently."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.deliver import atomic_json
from tools.impact import assess, load_business


def queue_changes(records, business, state, day):
    state = json.loads(json.dumps(state))
    state.setdefault('history', [])
    state.setdefault('processed', [])
    state.setdefault('pending', {})
    for record in records:
        if record['date'] != day:
            continue
        key = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        if key in state['processed'] or key in state['pending']:
            continue
        impact = assess(business, record)
        if impact['reaches_maya']:
            state['pending'][key] = {
                'record': record, 'reason': 'Waiting for the agent to review this change.',
                'routine_ids': [r['routine_id'] for r in impact['routines_touched'] if r['has_breaking_change']]}
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['collected', 'complete', 'failed'])
    args = parser.parse_args()
    contracts = ROOT / 'contracts'
    now = dt.datetime.now(dt.timezone.utc)
    status_path = contracts / 'agent-status.json'
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    if args.phase == 'collected':
        state_path = contracts / 'delivery-state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        records = [json.loads(line) for line in (contracts / 'changes.jsonl').read_text().splitlines() if line.strip()]
        atomic_json(state_path, queue_changes(records, load_business(), state, now.date().isoformat()))
    if args.phase == 'complete':
        status['last_completed_at'] = now.isoformat()
    status.update(state='pending' if args.phase == 'collected' else args.phase, updated_at=now.isoformat())
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if run_id.isdigit():
        status['workflow_url'] = f'https://github.com/iamrobertmoore/still-working/actions/runs/{run_id}'
    atomic_json(status_path, status)
    print(f"Agent review: {status['state']}. Collection and delivery timestamps remain separate.")


if __name__ == '__main__':
    main()
