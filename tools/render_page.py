#!/usr/bin/env python3
"""Render Maya's screen.

This is the whole product surface. Most mornings it says two words.

It is also the live demo link, which means it has two readers: Maya, who wants one
sentence, and a judge, who wants the evidence. The page resolves that by being Maya's
screen, with the evidence folded away behind one control. If the evidence were on the
front it would not be her screen any more.

Static output, no build step, no JavaScript framework, no external requests. The daily
job regenerates it and commits it, so what you are looking at is the real state of the
four contracts as of the last run rather than a mock.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import subprocess
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.impact import assess, figures, load_business, vendor_labels

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
OUT = os.path.join(ROOT, "docs", "index.html")

with open(os.path.join(ROOT, "tools", "page.css"), encoding="utf-8") as fh:
    CSS = fh.read()

# One continuous, open circle and a forward-moving check: quiet continuity.
MARK = '<path d="M52 31a21 21 0 1 1-14-20"/><path d="m22 29 9 9 22-23"/>'
ICONS = {
    "plus": '<path d="M6 12h12M12 6v12"/>',
    "stripe": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 10h18M7 15h4"/>',
    "square": '<rect x="4" y="3" width="16" height="13" rx="2"/><path d="M8 21h8M12 16v5M8 7h8"/>',
    "xero": '<path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1v15"/>',
    "shipengine": '<path d="m12 3 9 5v9l-9 5-9-5V8l9-5ZM3 8l9 5 9-5M12 13v9M7.5 5.5l9 5v5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "quiet": '<path d="M9 18h6M10 21h4M5 15c2-2 2-3 2-6a5 5 0 0 1 10 0c0 3 0 4 2 6H5Z"/>',
    "source": '<path d="m8 5-7 7 7 7M16 5l7 7-7 7M14 3l-4 18"/>',
    "warning": '<path d="M32 17v20M32 45v1"/><circle cx="32" cy="32" r="23"/>',
}


def icon(name: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{ICONS.get(name, ICONS["quiet"])}</svg>')


def mark(warning: bool = False) -> str:
    return ('<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" '
            'stroke-width="4" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{ICONS["warning"] if warning else MARK}</svg>')


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def human_date(iso: str) -> str:
    """Maya does not read ISO dates."""
    try:
        d = dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%B')} {d.year}"


def _times(n: int) -> str:
    return {0: "never", 1: "once", 2: "twice", 3: "three times"}.get(n, f"{n} times")


def human_gap(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    return f"{days // 30} months ago"


def main() -> int:
    business = load_business()
    labels = vendor_labels()
    vendors = load(os.path.join(CONTRACTS, "vendors.json"))["vendors"]
    today = dt.date.today()

    changelog = os.path.join(CONTRACTS, "changes.jsonl")
    rows = []
    if os.path.exists(changelog):
        rows = [json.loads(l) for l in open(changelog, encoding="utf-8")]

    reaching = [r for r in rows if assess(business, r)["reaches_maya"]]
    reaching.sort(key=lambda r: r["date"])
    outstanding = [r for r in reaching if (today - dt.date.fromisoformat(r["date"])).days <= 14]

    delivery_path = os.path.join(CONTRACTS, "delivery-state.json")
    pending = load(delivery_path).get("pending", {}) if os.path.exists(delivery_path) else {}

    # ---- the state, which is the whole point
    if outstanding or pending:
        state_class, state = "warn", "Worth a look."
        sub = "A supplier changed something your shop may rely on."
    else:
        state_class, state = "ok", "Still working."
        sub = "No new supplier risk found for your routines."

    fetched = [load(os.path.join(CONTRACTS, "latest", f"{v['id']}.json")).get("fetched_at")
               for v in vendors if os.path.exists(os.path.join(CONTRACTS, "latest", f"{v['id']}.json"))]
    checked = (dt.datetime.fromisoformat(min(fetched)).strftime('%d %B %Y at %H:%M UTC')
               if len(fetched) == len(vendors) and all(fetched) else "not all suppliers checked")
    parts = ['<a class="skip" href="#main">Skip to your daily check-in</a>',
             '<div class="wrap"><header class="masthead">',
             f'<a class="brand" href="./" aria-label="Still Working home">{mark()}'
             '<span>still working<span class="brand-dot">.</span></span></a>',
             '<span class="brand-caption">A quiet eye on the things you count on.</span>',
             '<div class="identity"><span class="avatar" aria-hidden="true">M</span>'
             '<span>Maya’s shop · Illustrative</span></div></header>',
             '<nav class="product-nav" aria-label="Explore Still Working"><span>Today’s check-in</span><a href="replay/">Recorded warnings</a><a href="review/">Review a match</a></nav>',
             '<main id="main"><section class="hero" aria-labelledby="daily-state">',
             '<div class="hero-copy"><p class="eyebrow">Your daily check-in</p>',
             f'<h1 id="daily-state" class="state {state_class}">{html.escape(state)}</h1>',
             f'<p class="sub">{html.escape(sub)}</p>',
             '<p class="reassurance">' + ('The details below will help you take the next step.'
                if outstanding or pending else 'One less thing to think about. Get on with your day.') + '</p>'
             '<div class="hero-actions"><a class="primary-link" href="replay/">See what it catches <span aria-hidden="true">↗</span></a>'
             '<span>Real supplier history. Saved cloud responses.</span></div></div>',
             f'<div class="hero-art {"warning" if outstanding or pending else ""}" aria-hidden="true">'
             '<div class="art-grid"></div>'
             f'<div class="seal">{mark(bool(outstanding or pending))}</div>'
             '<span class="satellite"></span><span class="art-caption">'
             + ('Let’s take a look' if outstanding or pending else 'Quietly looking out for you') + '</span></div></section>',
             '<div class="check-strip"><span class="checked">' + icon("clock") +
             f'<span>Checked {html.escape(checked)}</span></span>'
             '<a href="#watching">What’s being watched <span class="arrow" aria-hidden="true">↓</span></a></div>']

    replay_data = load(os.path.join(ROOT, "docs", "replay", "recordings.json"))
    replay_measure = replay_data["measurement"]
    parts.append('<section class="demo-feature" aria-labelledby="demo-title"><div><p class="eyebrow">When a change deserves your attention</p>'
                 '<h2 id="demo-title">The website might keep selling after the counter sells the last one.</h2>'
                 '<p>A real Square publication becomes a possible consequence, a next step, and a note for the developer who can check it.</p>'
                 '<a href="replay/2026-07-14-square.html">Open the recorded warning <span aria-hidden="true">↗</span></a></div>'
                 f'<aside><span class="feature-number">{replay_measure["changes"]} → {replay_data["delivered_notes"]}</span><p>Supplier changes to rendered notes.</p><strong>That ratio is the product.</strong>'
                 f'<p class="feature-caveat">An illustrative shop across {replay_measure["span"]} days of real history. Notification volume, not measured accuracy or savings.</p></aside></section>')

    # ---- the note itself, if there is one. Saying "something broke" and not saying what
    #      is worse than saying nothing.
    for newest in outstanding:
        note_path = os.path.join(CONTRACTS, "notes", f"{newest['date']}-{newest['vendor']}.md")
        if os.path.exists(note_path):
            with open(note_path, "r", encoding="utf-8") as fh:
                parts.append(f'<div class="note">{html.escape(fh.read().strip())}</div>')
        else:
            a = assess(business, newest)
            hit = ", ".join(x["what_maya_calls_it"] for x in a["routines_touched"]
                            if x["has_breaking_change"])
            parts.append(f'<div class="note">{html.escape(hit)}.\n\n'
                         "The full note has not been written yet. This is the deterministic "
                         "part: a company changed something one of your routines may rely on."
                         "</div>")

    if pending:
        parts.append('<div class="note">A supplier change is waiting for someone to check the match to your routines. Ask Priya to <a href="review/live.html">review the pending case</a> before treating it as resolved.</div>')

    # ---- what it watches, in her words
    parts.append('<section class="watch-section" id="watching" aria-labelledby="watch-title">'
                 '<div class="section-heading"><h2 id="watch-title">What I watch for you</h2>'
                 f'<span class="section-meta">{len(vendors)} suppliers · Every day</span></div>'
                 '<ul class="vendor-grid">')
    for v in vendors:
        latest_path = os.path.join(CONTRACTS, "latest", f"{v['id']}.json")
        vrows = [r for r in rows if r["vendor"] == v["id"]]
        last = max((r["date"] for r in vrows), default=None)
        gap = (today - dt.date.fromisoformat(last)).days if last else None
        label = labels.get(v["id"], {}).get("address_as", v["name"])
        seen = "watched" if os.path.exists(latest_path) else "not yet checked"
        vendor_name = "Xero" if v["id"] == "xero" else v["name"]
        parts.append(f'<li class="vendor-card"><div class="vendor-top">'
                     f'<span class="vendor-icon">{icon(v["id"])}</span>'
                     f'<span class="vendor-name">{html.escape(vendor_name)}</span></div>'
                     f'<h3>{html.escape(label.capitalize())}</h3>'
                     '<div class="vendor-bottom"><span>Last changed</span>'
                     f'<strong>{html.escape(human_gap(gap) if last else seen)}</strong></div>')
        if any(r["vendor"] == v["id"] for r in outstanding):
            parts.append('<p class="attention">Needs your attention</p>')
        parts.append('</li>')
    parts.append('</ul></section>')

    # ---- the evidence, folded away
    total_changes = sum(r["total_count"] for r in rows)
    total_breaking = sum(r["breaking_count"] for r in rows)
    if rows:
        dates = sorted(r["date"] for r in rows)
        span = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days
    else:
        span = 0

    parts.append('<section class="evidence-wrap" aria-label="The story behind your check-in">'
                 '<details><summary><span class="evidence-icon">' + icon("quiet") + '</span>'
                 '<span class="summary-copy"><span class="summary-title">Only the changes that matter.</span>'
                 '<span class="summary-sub">What this has caught, and what it stayed quiet about</span></span>'
                 '<span class="toggle" aria-hidden="true">' + icon("plus") +
                 '</span></summary><div class="evidence-content">')
    # The same suppression the agent applies, so this page and the README agree. Without
    # it the page said three days reached her while everything else said two.
    told = figures(business)
    parts.append('<div class="metrics">'
                 f'<div class="metric"><span class="metric-value">{span}</span><span class="metric-label">days of history</span></div>'
                 f'<div class="metric"><span class="metric-value">{total_changes}</span><span class="metric-label">supplier changes</span></div>'
                 f'<div class="metric"><span class="metric-value">{told["interruptions"]}</span><span class="metric-label">notes in this replay</span></div></div>')
    parts.append(
        f"<p>Over <strong>{span} days</strong> the four companies above made "
        f"<strong>{total_changes} changes</strong> to what their software accepts. "
        f"<strong>{total_breaking}</strong> of those could break somebody. "
        f"<strong>{told['reaching']}</strong> records matched a possible risk to your routines. In this replay you would "
        f"have been interrupted <strong>{_times(told['interruptions'])}</strong>.</p>")
    if told["rows"]:
        parts.append('<div class="scroll"><table><tr><th>When</th>'
                     "<th>What you would have been told</th><th>Notification</th></tr>")
        for date, _who, names, delivery_state, gap in told["rows"]:
            aside = ("" if delivery_state == "sent"
                     else f"you had just been told, {gap} days before" if gap is not None
                     else "you had just been told")
            parts.append(f"<tr><td class=\"when\">{html.escape(human_date(date))}</td>"
                         f"<td>{html.escape(names)}</td>"
                         f'<td class="n"><span class="delivery {"held" if delivery_state != "sent" else ""}">'
                         f'{"Sent" if delivery_state == "sent" else "Held back"}</span>'
                         f'{"<br>" + html.escape(aside) if aside else ""}</td></tr>')
        parts.append("</table></div>")
    parts.append(
        "<p><strong>That ratio is the product.</strong> The rest did not need another interruption: changes that were additive, did not "
        "affect your routines, or had already been brought to your attention. A tool that forwarded all "
        f"{total_changes} would demand attention without knowing your shop.</p>")
    parts.append('<p>Maya is an illustrative shop owner. The supplier history is real; the business consequences are inferred. These counts measure notification volume, not accuracy or proven savings.</p>'
                 '<p><a class="replay-link" href="replay/">Replay the recorded changes <span aria-hidden="true">↗</span></a></p>')
    parts.append("</div></details></section></main>")

    parts.append(
        '<footer><div class="footer-top"><p>Regenerated by a scheduled job, not by hand.</p>'
        '<a class="source-link" href="https://github.com/iamrobertmoore/still-working">' + icon("source") +
        'View the project <span aria-hidden="true">↗</span></a></div>'
        '<div class="fine-print"><p><span class="footer-motto">Less noise. More peace of mind.</span>'
        'Still Working · A quiet eye on your business.</p>'
        '<p>This reads what each company <strong>publishes</strong>, not what they have '
        'deployed, so a company whose documentation lags its rollout will not be caught. '
        'The link between your routines and the calls they rely on was worked out at '
        'setup and can be wrong, so low-confidence matches wait for a person to review '
        'the dependency before a note can reach you.</p></div></footer></div>')

    try:
        revision = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    if revision:
        parts.append('<p class="build-stamp">Source revision <a href="https://github.com/iamrobertmoore/still-working/commit/' + revision + '">' + revision + '</a> · <a href="https://github.com/iamrobertmoore/still-working/commits/main/">See the latest changes</a></p>')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    favicon = quote('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                    '<rect width="64" height="64" rx="15" fill="#255a43"/>'
                    '<g transform="translate(5 5) scale(.84)" fill="none" stroke="#f7f8f2" '
                    'stroke-width="4" stroke-linecap="round" stroke-linejoin="round">'
                    + MARK + '</g></svg>', safe='')
    doc = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           "<title>Still Working</title>"
           f'<link rel="icon" href="data:image/svg+xml,{favicon}">'
           '<meta name="theme-color" content="#f7f8f2" media="(prefers-color-scheme: light)">'
           '<meta name="theme-color" content="#15251f" media="(prefers-color-scheme: dark)">'
           "<meta name=\"description\" content=\"An agent that tells a shop owner when a change by one of "
           "her suppliers may affect a business routine. Most mornings it says two words.\">"
           f"<style>{CSS}</style></head><body>" + "".join(parts) + "</body></html>")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)

    print(f"wrote {os.path.relpath(OUT, ROOT)}  ({len(doc):,} bytes)")
    print(f"state: {state}   outstanding: {len(outstanding)}   "
          f"in {span} days: {told['reaching']} broke a routine, "
          f"{told['interruptions']} would have interrupted her")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
