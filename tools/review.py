#!/usr/bin/env python3
"""Export pending cases and import a human's case-specific decisions.

Imports require the local operator to run --apply. The public page cannot change shared
state or invoke AWS. Example-mode decisions are never accepted into the live ledger.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.review import case_id, validate_decision
from tools.impact import assess, load_business


def pending_cases(business, state):
    result = {}
    for pending in state.get('pending', {}).values():
        impact = assess(business, pending['record'])
        for routine in impact['routines_touched']:
            if not routine['has_breaking_change'] or (pending.get('routine_ids') and routine['routine_id'] not in pending['routine_ids']):
                continue
            key = case_id(impact, routine)
            result[key] = {'case_id': key, 'date': impact['date'], 'vendor': impact['vendor'],
                           'routine': routine, 'impact': impact}
    return result


def import_decisions(document, available, previous):
    if not isinstance(document, dict) or document.get('mode') != 'live':
        raise ValueError('Only live review files can be imported; example decisions are demonstrations')
    choices = document.get('decisions')
    if not isinstance(choices, list) or not choices:
        raise ValueError('Review file must contain at least one decision')
    updated = dict(previous)
    seen = set()
    for choice in choices:
        key = choice.get('case_id') if isinstance(choice, dict) else None
        if key not in available or key in seen:
            raise ValueError('Unknown, stale or duplicate review case; export the pending queue again')
        checked = validate_decision(choice, key)
        if key in updated and updated[key] != checked:
            raise ValueError('This case already has a different decision; do not silently replace it')
        updated[key] = checked
        seen.add(key)
    return updated


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', type=Path, help='Import a reviewed JSON file')
    args = ap.parse_args()
    state_path = ROOT / 'contracts/delivery-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    available = pending_cases(load_business(), state)
    review_path = ROOT / 'contracts/reviews.json'
    previous = json.loads(review_path.read_text()) if review_path.exists() else {}
    if args.apply:
        updated = import_decisions(json.loads(args.apply.read_text()), available, previous)
        temp = review_path.with_suffix('.tmp');temp.write_text(json.dumps(updated, indent=2)+'\n');temp.replace(review_path)
        print(f'Imported {len(updated)-len(previous)} new case-specific reviews. Commit contracts/reviews.json so the daily caller can use them.')
    else:
        dest = ROOT / 'docs/review/pending.json';dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({'mode':'live','cases':list(available.values())}, indent=2)+'\n')
        print(f'Exported {len(available)} pending review cases.')


if __name__ == '__main__':
    main()
