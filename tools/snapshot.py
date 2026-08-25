#!/usr/bin/env python3
"""Take a daily snapshot of the vendors Maya's shop runs on, and classify what moved.

This is the boring half of Still Working. It answers "did anything change", in the
vendors' language. The judgement layer answers "does that matter to Maya", in hers.

Design notes, all of them learned by getting something wrong before:

* Store the NORMALISED endpoint map, never the raw spec. The three raw documents are
  about 20 MB a day between them. The normalised map is a few hundred KB and git
  delta-compresses it to almost nothing because most days nothing changes.
* Classify changes by whether they can break an EXISTING caller, which is only three
  shapes: an endpoint disappears, a parameter disappears, or an optional parameter
  becomes required. Everything else is additive and a caller can ignore it.
* The alarm is raised on the specific classification, never on "the job failed". A
  broken job is a broken job, not a vendor changing their API.
* This needs no credentials at all. Every spec is public. There is nothing to gate on,
  so the job cannot silently skip its own work for want of a secret.
* Specs come as JSON or YAML depending on the vendor. Xero publishes YAML. Normalising
  both to the same endpoint map is the point: Maya does not care what format her
  accounting software's documentation is written in.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
SNAPDIR = os.path.join(CONTRACTS, "snapshots")
LATEST = os.path.join(CONTRACTS, "latest")
CHANGELOG = os.path.join(CONTRACTS, "changes.jsonl")

BREAKING_KINDS = {"endpoint_removed", "param_removed", "param_became_required"}


# ---------------------------------------------------------------- normalisation

def normalise(spec: dict) -> dict[str, dict]:
    """Reduce an OpenAPI document to what a caller can actually depend on."""
    out: dict[str, dict] = {}
    for path, item in sorted((spec.get("paths") or {}).items()):
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") or []
        for method, op in sorted(item.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(op, dict):
                continue
            params = list(shared) + list(op.get("parameters") or [])
            names, required = [], []
            for p in params:
                if not isinstance(p, dict):
                    continue
                n = p.get("name")
                if not n:
                    continue
                names.append(n)
                if p.get("required"):
                    required.append(n)
            out[f"{method.upper()} {path}"] = {
                "params": sorted(set(names)),
                "required": sorted(set(required)),
                "responses": sorted(str(k) for k in (op.get("responses") or {})),
            }
    return out


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "contract-watch/0.1 (+hackathon)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_spec(raw: bytes, fmt: str) -> dict:
    """Vendors publish JSON or YAML. Both reduce to the same endpoint map."""
    if fmt == "yaml":
        return yaml.safe_load(raw)
    return json.loads(raw)


def snapshot_one(vendor: dict, timeout: int = 60) -> dict:
    raw = fetch(vendor["spec_url"], timeout=timeout)
    spec = parse_spec(raw, vendor.get("spec_format", "json"))
    info = spec.get("info") or {}
    endpoints = normalise(spec)
    return {
        "vendor": vendor["id"],
        "name": vendor["name"],
        "what_maya_calls_it": vendor.get("what_maya_calls_it"),
        "spec_url": vendor["spec_url"],
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "raw_bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "spec_version": info.get("version"),
        "spec_title": info.get("title"),
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
    }


# ---------------------------------------------------------------- classification

def classify(previous: dict, current: dict) -> list[dict]:
    """Return one record per change. `breaking` is a property of the change, not the run."""
    old, new = previous.get("endpoints", {}), current.get("endpoints", {})
    changes: list[dict] = []

    for key in sorted(set(old) - set(new)):
        changes.append({"kind": "endpoint_removed", "endpoint": key})
    for key in sorted(set(new) - set(old)):
        changes.append({"kind": "endpoint_added", "endpoint": key})

    for key in sorted(set(old) & set(new)):
        o, n = old[key], new[key]
        for p in sorted(set(o["params"]) - set(n["params"])):
            changes.append({"kind": "param_removed", "endpoint": key, "param": p})
        for p in sorted(set(n["params"]) - set(o["params"])):
            changes.append({"kind": "param_added", "endpoint": key, "param": p})
        for p in sorted(set(n["required"]) - set(o["required"])):
            if p in o["params"]:
                changes.append({"kind": "param_became_required", "endpoint": key, "param": p})
        for p in sorted(set(o["required"]) - set(n["required"])):
            changes.append({"kind": "param_became_optional", "endpoint": key, "param": p})
        for r in sorted(set(n["responses"]) - set(o["responses"])):
            changes.append({"kind": "response_added", "endpoint": key, "status": r})
        for r in sorted(set(o["responses"]) - set(n["responses"])):
            changes.append({"kind": "response_removed", "endpoint": key, "status": r})

    if previous.get("spec_version") != current.get("spec_version"):
        changes.append({
            "kind": "version_string_changed",
            "from": previous.get("spec_version"),
            "to": current.get("spec_version"),
        })

    for c in changes:
        c["breaking"] = c["kind"] in BREAKING_KINDS
    return changes


# ---------------------------------------------------------------- io

def write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
        fh.write("\n")


def load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def set_output(name: str, value: str) -> None:
    print(f"::{name}={value}")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


# ---------------------------------------------------------------- self test

def self_test() -> int:
    """Prove the detector can fire. A check nobody has seen fail asserts nothing."""
    before = {"spec_version": "1", "endpoints": {
        "GET /a": {"params": ["x", "y"], "required": ["x"], "responses": ["200"]},
        "POST /gone": {"params": [], "required": [], "responses": ["201"]},
    }}
    after = {"spec_version": "2", "endpoints": {
        "GET /a": {"params": ["x", "z"], "required": ["x", "z"], "responses": ["200", "429"]},
        "POST /new": {"params": [], "required": [], "responses": ["201"]},
    }}
    got = {(c["kind"], c.get("endpoint"), c.get("param")) for c in classify(before, after)}
    expected = {
        ("endpoint_removed", "POST /gone", None),
        ("endpoint_added", "POST /new", None),
        ("param_removed", "GET /a", "y"),
        ("param_added", "GET /a", "z"),
        ("response_added", "GET /a", None),
        ("version_string_changed", None, None),
    }
    missing = expected - got
    if missing:
        print("SELF TEST FAILED, detector did not report:", sorted(missing), file=sys.stderr)
        return 1

    breaking = {c["kind"] for c in classify(before, after) if c["breaking"]}
    if breaking != {"endpoint_removed", "param_removed"}:
        print("SELF TEST FAILED, wrong breaking set:", sorted(breaking), file=sys.stderr)
        return 1

    # A parameter that is new AND required is additive for an existing caller only if the
    # caller never sent it. It is the transition of an EXISTING optional param to required
    # that breaks them. Assert we make that distinction.
    b2 = {"spec_version": "1", "endpoints": {"GET /a": {"params": ["x"], "required": [], "responses": []}}}
    a2 = {"spec_version": "1", "endpoints": {"GET /a": {"params": ["x"], "required": ["x"], "responses": []}}}
    kinds = {c["kind"] for c in classify(b2, a2)}
    if "param_became_required" not in kinds:
        print("SELF TEST FAILED, missed an optional to required transition", file=sys.stderr)
        return 1

    quiet = classify(before, before)
    if quiet:
        print("SELF TEST FAILED, reported changes against an identical snapshot:", quiet, file=sys.stderr)
        return 1

    print("self test OK: detector fires on all six kinds, marks exactly two as breaking,")
    print("distinguishes optional-to-required, and stays silent on an unchanged contract.")
    return 0


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--date", default=None, help="override the snapshot date, for backfill")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    day = args.date or dt.date.today().isoformat()
    vendors = load_json(os.path.join(CONTRACTS, "vendors.json"))["vendors"]

    any_changed = False
    any_breaking = False
    failures: list[str] = []
    summary: list[str] = []

    for vendor in vendors:
        vid = vendor["id"]
        try:
            current = snapshot_one(vendor, timeout=args.timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError,
                TimeoutError, yaml.YAMLError) as exc:
            # A vendor being unreachable is MY problem, not a contract change. Record it,
            # keep going, and never let it look like drift.
            failures.append(f"{vid}: {type(exc).__name__}: {exc}")
            summary.append(f"  {vid:12s} UNREACHABLE ({type(exc).__name__})")
            continue

        write_json(os.path.join(SNAPDIR, vid, f"{day}.json"), current)

        previous = load_json(os.path.join(LATEST, f"{vid}.json"))
        if previous is None:
            summary.append(f"  {vid:12s} baseline, {current['endpoint_count']} endpoints, version {current['spec_version']!r}")
        else:
            changes = classify(previous, current)
            if changes:
                any_changed = True
                breaking = [c for c in changes if c["breaking"]]
                if breaking:
                    any_breaking = True
                record = {
                    "date": day,
                    "vendor": vid,
                    "from_fetched_at": previous.get("fetched_at"),
                    "to_fetched_at": current.get("fetched_at"),
                    "from_version": previous.get("spec_version"),
                    "to_version": current.get("spec_version"),
                    "breaking_count": len(breaking),
                    "total_count": len(changes),
                    "changes": changes,
                }
                os.makedirs(CONTRACTS, exist_ok=True)
                with open(CHANGELOG, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, sort_keys=True) + "\n")
                summary.append(
                    f"  {vid:12s} {len(changes)} changes, {len(breaking)} breaking"
                    f" (version {previous.get('spec_version')!r} -> {current.get('spec_version')!r})"
                )
            else:
                summary.append(f"  {vid:12s} unchanged, {current['endpoint_count']} endpoints")

        write_json(os.path.join(LATEST, f"{vid}.json"), current)

    print(f"contract snapshot {day}")
    print("\n".join(summary))

    set_output("changed", "true" if any_changed else "false")
    set_output("breaking", "true" if any_breaking else "false")
    set_output("unreachable", "true" if failures else "false")

    if failures:
        print("\nunreachable vendors (this is a job problem, not a contract change):", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        # Non-zero so the run is visibly red, but the drift alarm is gated on
        # `breaking`, not on this exit code, so a broken fetch never announces
        # itself as a vendor API change.
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
