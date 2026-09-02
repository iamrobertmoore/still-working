#!/usr/bin/env python3
"""Reconstruct the contract history from what each vendor already published.

Daily polling only knows what happened while it was running. Mine was not running for
eight days and missed a real Stripe change, which is exactly the failure the product is
about, on the product itself.

But every one of these four vendors publishes their contract in a public git repository,
so the history is already there, timestamped by them. This reads it. It goes back as far
as you ask, it is exact rather than sampled, and anyone can re-run it and get the same
answer, which is the whole point of a measurement.

Not a substitute for the daily job. The daily job is the product working. This is how you
find out what the product would have told Maya before it existed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.snapshot import CONTRACTS, LATEST, SNAPDIR, classify, load_json, normalise, parse_spec, write_json

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".spec-cache")


def run(args: list[str], cwd: str | None = None) -> str:
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout


def ensure_clone(vendor: dict) -> str:
    """Blobless clone. We only ever need a handful of blobs out of a large history."""
    path = os.path.join(CACHE, vendor["id"])
    if os.path.isdir(os.path.join(path, ".git")):
        run(["git", "fetch", "-q", "origin"], cwd=path)
        return path
    os.makedirs(CACHE, exist_ok=True)
    run(["git", "clone", "--filter=blob:none", "--no-checkout", "-q", vendor["spec_repo"], path])
    return path


def revisions(repo: str, spec_path: str, since: str) -> list[tuple[str, str]]:
    """(sha, YYYY-MM-DD) oldest first, at most ONE per calendar day.

    Vendors push more than once a day and sometimes revert within the day. Stripe did
    exactly that on 2026-07-01: forward to one version and back again. Counting both
    transitions would report two changes that nobody outside Stripe ever saw, and would
    make the contract look twice as unstable as it is.

    A daily poller sees the last state of each day and nothing else, so that is what this
    reconstructs. Intra-day churn is invisible to Maya and is invisible here too.
    """
    raw = run(["git", "log", "--format=%H %ad", "--date=short", f"--since={since}",
               "--", spec_path], cwd=repo)
    by_day: dict[str, str] = {}
    for line in raw.splitlines():          # git log is newest first
        sha, _, date = line.partition(" ")
        date = date.strip()
        if sha and date not in by_day:     # first seen is the latest that day
            by_day[date] = sha
    return [(by_day[d], d) for d in sorted(by_day)]


def snapshot_at(vendor: dict, repo: str, sha: str, date: str) -> dict:
    blob = subprocess.run(["git", "show", f"{sha}:{vendor['spec_path']}"],
                          cwd=repo, capture_output=True, check=True).stdout
    spec = parse_spec(blob, vendor.get("spec_format", "json"))
    info = spec.get("info") or {}
    endpoints = normalise(spec)
    return {
        "vendor": vendor["id"],
        "name": vendor["name"],
        "what_maya_calls_it": vendor.get("what_maya_calls_it"),
        "spec_url": vendor["spec_url"],
        "fetched_at": f"{date}T00:00:00+00:00",
        "source": f"reconstructed from {vendor['spec_repo']} at {sha[:12]}",
        "raw_bytes": len(blob),
        "raw_sha256": hashlib.sha256(blob).hexdigest(),
        "spec_version": info.get("version"),
        "spec_title": info.get("title"),
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-04-01")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    vendors = load_json(os.path.join(CONTRACTS, "vendors.json"))["vendors"]
    changelog = os.path.join(CONTRACTS, "changes.jsonl")
    records: list[dict] = []

    for vendor in vendors:
        repo = ensure_clone(vendor)
        revs = revisions(repo, vendor["spec_path"], args.since)
        print(f"{vendor['id']:11s} {len(revs)} revisions since {args.since}")

        skipped_intraday = 0
        previous = None
        for sha, date in revs:
            current = snapshot_at(vendor, repo, sha, date)
            if not args.dry_run:
                write_json(os.path.join(SNAPDIR, vendor["id"], f"{date}.json"), current)
            if previous is not None:
                changes = classify(previous, current)
                if changes:
                    breaking = [c for c in changes if c["breaking"]]
                    records.append({
                        "date": date, "vendor": vendor["id"],
                        "from_fetched_at": previous["fetched_at"], "to_fetched_at": current["fetched_at"],
                        "from_version": previous.get("spec_version"), "to_version": current.get("spec_version"),
                        "breaking_count": len(breaking), "total_count": len(changes),
                        "reconstructed": True, "changes": changes,
                    })
                    print(f"            {date}  {len(changes):5d} changes, {len(breaking):3d} breaking"
                          f"   {previous.get('spec_version')!r} -> {current.get('spec_version')!r}")
            previous = current

        if previous is not None and not args.dry_run:
            write_json(os.path.join(LATEST, f"{vendor['id']}.json"), previous)
        del skipped_intraday

    records.sort(key=lambda r: (r["date"], r["vendor"]))
    if not args.dry_run:
        with open(changelog, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, sort_keys=True) + "\n")

    print()
    print(f"{len(records)} contract revisions with changes, written to contracts/changes.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
