# Generated from agent/review.py by tools/sync_runtime.py.
"""A human decision is scoped to an exact assessed case, never to model output.

The authenticated caller loads these decisions from an operator-imported review file.
Names are supplied by the reviewer, not identity-verified by this module.
"""
import hashlib
import json


def case_id(impact, routine):
    facts = {'date': impact.get('date'), 'vendor': impact.get('vendor'), 'routine': routine}
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_decision(value, expected_id):
    if not isinstance(value, dict) or value.get('case_id') != expected_id:
        raise ValueError('Review does not match the exact assessed case')
    if value.get('decision') not in ('approve', 'dismiss'):
        raise ValueError('Review decision must be approve or dismiss')
    for key, limit in [('reviewer', 120), ('reason', 1200)]:
        if not isinstance(value.get(key), str) or not 2 <= len(value[key].strip()) <= limit:
            raise ValueError(f'Review requires a {key} between 2 and {limit} characters')
    return {key: value[key].strip() for key in ('case_id', 'decision', 'reviewer', 'reason')}


def decision_for(impact, routine):
    key = case_id(impact, routine)
    value = impact.get('human_reviews', {}).get(key)
    return validate_decision(value, key) if value is not None else None
