#!/usr/bin/env python3
"""Publish a browser-readable view of captured AgentCore responses. Never invent output."""
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.render_page import CSS, human_date, mark, icon

OUT = ROOT / 'docs' / 'replay'
EXTRA = '''
.replay-head{padding:55px 0 32px;max-width:790px}.replay-head h1{font:normal clamp(40px,5vw,65px)/1.08 Georgia,serif;letter-spacing:-.04em;margin:12px 0 24px}.replay-head p{color:var(--muted)}
.replay-label{color:var(--green);font-size:11px;text-transform:uppercase;letter-spacing:.13em}.replay-nav{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 32px}.replay-nav a,.replay-link{padding:11px 17px;background:var(--surface);border:1px solid var(--line);border-radius:8px;text-decoration:none;font-size:12px}.replay-nav a:hover,.replay-nav a[aria-current=page]{background:var(--green);color:var(--bg)}
.case-grid{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(0,1fr);gap:28px;align-items:start}.case-note{background:var(--surface);border:1px solid var(--line);border-radius:15px;padding:30px}.case-note h2{font:normal 27px/1.25 Georgia,serif;margin:10px 0 22px}.case-note p{font-size:14px;white-space:pre-line}.case-note details{margin-top:25px;border-top:1px solid var(--line)}.case-note summary{padding:18px 0;font-size:13px;justify-content:space-between}.case-note pre,.receipt pre{white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.7 ui-monospace,monospace;color:var(--muted)}
.receipt{padding:24px;border:1px solid var(--line);border-radius:15px;background:var(--soft)}.receipt h2{margin-bottom:18px}.receipt dl{margin:0}.receipt dt{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:18px}.receipt dd{margin:4px 0;font-size:13px}.receipt p{font-size:12px;color:var(--muted)}.record-list{margin:36px 0}.record-list summary{justify-content:space-between;border:1px solid var(--line);border-radius:10px}.record-list table{font-size:12px}.replay-footer{margin:40px 0 30px;padding-top:24px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}.replay-footer p{max-width:850px}.receipt .delivery{margin-bottom:12px}.empty-note{min-height:320px;display:flex;flex-direction:column;justify-content:center}.empty-note h2{font-size:40px;color:var(--green)}
@media(max-width:750px){.case-grid{grid-template-columns:1fr}.replay-head{padding-top:35px}.case-note{padding:24px}.masthead .identity{display:none}.replay-nav a{flex:1 1 calc(50% - 10px);text-align:center}.receipt{padding:22px}}
'''

def esc(value):
    return html.escape(str(value))


def page(data, selected):
    case = data['cases'][selected]
    r, result = case['record'], case['result']
    delivered = bool(result['notes'])
    repeat = any(d['outcome'] == 'repeat_held' for d in result['decisions'])
    title = 'A note worth opening.' if delivered else 'Already on your list.' if repeat else 'Nothing to interrupt you for.'
    nav = []
    for date, vendor, label in [('2026-07-14','square','The stock warning'),('2026-04-24','xero','The payroll warning'),('2026-04-29','xero','The repeat held'),('2026-08-26','stripe','A quiet day')]:
        current = ' aria-current="page"' if (r['date'],r['vendor']) == (date,vendor) else ''
        nav.append(f'<a href="{date}-{vendor}.html"{current}>{label}</a>')
    note = result['note']
    if note:
        owner, sep, technician = note.partition('--- forward this part to Priya ---')
        paragraphs = owner.strip().split('\n\n')
        body = f'<h2>{esc(paragraphs[0])}</h2>' + ''.join(f'<p>{esc(p)}</p>' for p in paragraphs[1:])
        if sep:
            body += f'<details><summary>Forward this part to Priya <span class="toggle" aria-hidden="true">{icon("plus")}</span></summary><pre>{esc(technician.strip())}</pre></details>'
    else:
        body = '<div class="empty-note"><h2>' + ('You have already been told.' if repeat else 'Still working.') + '</h2><p>' + ('The payroll routine was flagged five days earlier. The delivery ledger holds this repeat before a model is built. This is a decision about another notification, not proof the issue is resolved.' if repeat else 'These published changes do not match a potentially breaking change to a routine in the shop profile. No note. No model invocation.') + '</p></div>'
    endpoints = '\n'.join(c['kind'] + (': ' + c['endpoint'] if c.get('endpoint') else '') + (' / ' + c['param'] if c.get('param') else '') for c in r['changes'])
    outcomes = ', '.join(d['outcome'].replace('_',' ') for d in result['decisions']) or 'No relevant breaking change'
    confidence = ', '.join(sorted({x.get('mapping_confidence','unknown') for x in case['impact']['routines_touched'] if x['has_breaking_change']})) or 'No affected routine'
    receipt = f'''<aside class="receipt"><span class="delivery">Captured from AWS AgentCore</span><h2>The decision receipt</h2><dl>
    <dt>Published change</dt><dd>{human_date(r['date'])} · {esc(r['vendor'].title())}</dd>
    <dt>Matched routine</dt><dd>{esc(result.get('routine') or ('Paying the twelve of us' if repeat else 'None requiring a note'))}</dd>
    <dt>Decision</dt><dd>{esc(outcomes)}</dd><dt>Mapping confidence</dt><dd>{esc(confidence)}</dd>
    <dt>Model invocations</dt><dd>{result['model_invocations']}</dd><dt>Notes rendered</dt><dd>{len(result['notes'])}</dd></dl>
    <p>Publication is observed. Dependence on these calls and the business consequence are inferred from the illustrative profile.</p>
    <details><summary>Inspect the supplier changes</summary><pre>{esc(endpoints)}</pre></details>
    <p><a href="recordings.json">Full input, response and delivery ledger</a></p></aside>'''
    rows = []
    for c in data['cases']:
        rr, out = c['record'], c['result']
        status = 'Note rendered' if out['notes'] else 'Repeat held' if any(d['outcome']=='repeat_held' for d in out['decisions']) else 'No note'
        rows.append(f'<tr><td><a href="{rr["date"]}-{rr["vendor"]}.html">{esc(human_date(rr["date"]))}</a></td><td>{esc(rr["vendor"].title())}</td><td>{rr["total_count"]}</td><td>{status}</td><td>{out["model_invocations"]}</td></tr>')
    m = data['measurement']
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} | Still Working replay</title><meta name="description" content="Inspect real AgentCore responses to five months of supplier history, using an illustrative shop profile."><link rel="icon" href="../brand/mark.svg"><style>{CSS}\n{EXTRA}</style></head><body><a class="skip" href="#main">Skip to the recorded decision</a><div class="wrap">
    <header class="masthead"><a class="brand" href="../">{mark()}<span>still working.</span></a><span class="brand-caption">Less noise. More peace of mind.</span><a href="../" class="identity">Today’s check-in ↗</a></header>
    <main id="main"><div class="replay-head"><span class="replay-label">Historical replay · Real cloud responses</span><h1>{title}</h1><p>Maya’s shop is illustrative. The supplier history is real. These are saved responses from the deployed agent, replaying each change as if it had just arrived.</p></div>
    <nav class="replay-nav" aria-label="Choose a recorded moment">{''.join(nav)}</nav><div class="case-grid"><article class="case-note"><span class="replay-label">{esc(human_date(r['date']))} · Maya’s screen</span>{body}</article>{receipt}</div>
    <section class="record-list"><details><summary><span>Every decision in the replay</span><span>{len(data['cases'])} records · {data['delivered_notes']} notes</span></summary><div class="scroll"><table><thead><tr><th>Date</th><th>Supplier</th><th>Changes</th><th>Outcome</th><th>Model calls</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details></section>
    </main><footer class="replay-footer"><p><strong>{m['changes']} supplier changes. {data['delivered_notes']} notes. That ratio is the product.</strong><br>Notification volume in this replay, not measured accuracy, prevented outages or customer savings.</p><p>Captured {esc(data['captured_at'][:10])}. {len(data['cases'])} supplier-day records across {len({c['record']['date'] for c in data['cases']})} calendar dates, spanning {m['span']} days. Relative dates in the notes are anchored to each historical event. The original model wording is preserved, including its limitations. “Delivered” means the tool rendered a note; no email or message was sent to a real person.</p><p><a href="recordings.json">Download the evidence</a> · <a href="https://github.com/iamrobertmoore/still-working/blob/main/tools/replay.py">Reproduce it</a> · <a href="../">Back to the daily page</a></p></footer></div></body></html>'''


def main():
    data = json.loads((OUT / 'recordings.json').read_text())
    for i, case in enumerate(data['cases']):
        r = case['record']
        content = page(data, i)
        (OUT / f'{r["date"]}-{r["vendor"]}.html').write_text(content)
        if (r['date'], r['vendor']) == ('2026-07-14','square'):
            (OUT / 'index.html').write_text(content)
    print(f'Rendered {len(data["cases"])} recorded decisions.')

if __name__ == '__main__':
    main()
