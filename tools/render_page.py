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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.impact import assess, load_business, vendor_labels

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
OUT = os.path.join(ROOT, "docs", "index.html")

CSS = """
:root{
  --bg:#faf9f7; --ink:#16150f; --muted:#6b675c; --rule:#e0ddd4;
  --ok:#2f6f4e; --warn:#8a3324; --card:#fffefb;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#14140f; --ink:#f2f0e8; --muted:#9a968a; --rule:#2e2d26;
    --ok:#7cc79c; --warn:#e59a86; --card:#1c1b16;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:44rem;margin:0 auto;padding:clamp(2rem,8vw,6rem) 1.5rem 4rem}
.state{font-size:clamp(2.2rem,7vw,3.6rem);line-height:1.1;letter-spacing:-.02em;
  font-weight:600;margin:0 0 .6rem}
.state.ok{color:var(--ok)} .state.warn{color:var(--warn)}
.sub{color:var(--muted);margin:0 0 3rem;font-size:1.05rem}
.note{background:var(--card);border:1px solid var(--rule);border-radius:10px;
  padding:1.5rem;margin:0 0 3rem;white-space:pre-wrap;
  font:15px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
  font-weight:600;margin:0 0 1rem}
table{width:100%;border-collapse:collapse;margin:0 0 3rem;font-size:.95rem}
th,td{text-align:left;padding:.6rem 1.25rem .6rem 0;border-bottom:1px solid var(--rule);
  vertical-align:top}
th:last-child,td:last-child{padding-right:0}
th{color:var(--muted);font-weight:500;font-size:.8rem;text-transform:uppercase;
  letter-spacing:.06em}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--muted)}
td.when{white-space:nowrap;color:var(--muted);font-variant-numeric:tabular-nums;width:1%}
details{border-top:1px solid var(--rule);padding-top:1.5rem;margin-top:1rem}
summary{cursor:pointer;color:var(--muted);font-size:.95rem;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"+ ";font-variant-numeric:tabular-nums}
details[open] summary::before{content:"- "}
details>*:not(summary){margin-top:1.5rem}
footer{color:var(--muted);font-size:.85rem;line-height:1.7;border-top:1px solid var(--rule);
  padding-top:1.5rem;margin-top:3rem}
a{color:inherit}
code{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
  background:var(--card);border:1px solid var(--rule);border-radius:4px;padding:.05em .35em}
.scroll{overflow-x:auto}
"""


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

    # ---- the state, which is the whole point
    if outstanding:
        state_class, state = "warn", "Something broke."
        sub = "One of the things your shop runs on changed, and it matters to you."
    else:
        state_class, state = "ok", "Still working."
        sub = "Nothing that matters to you changed."

    parts = [f"<style>{CSS}</style>", '<div class="wrap">',
             f'<p class="state {state_class}">{html.escape(state)}</p>',
             f'<p class="sub">{html.escape(sub)}</p>']

    # ---- the note itself, if there is one. Saying "something broke" and not saying what
    #      is worse than saying nothing.
    if outstanding:
        newest = outstanding[-1]
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
                         "part: a company changed something one of your routines relies on."
                         "</div>")

    # ---- what it watches, in her words
    parts.append("<h2>What I watch for you</h2>")
    parts.append('<div class="scroll"><table><tr><th>Thing</th><th>Last changed</th></tr>')
    for v in vendors:
        latest_path = os.path.join(CONTRACTS, "latest", f"{v['id']}.json")
        vrows = [r for r in rows if r["vendor"] == v["id"]]
        last = max((r["date"] for r in vrows), default=None)
        gap = (today - dt.date.fromisoformat(last)).days if last else None
        label = labels.get(v["id"], {}).get("address_as", v["name"])
        seen = "watched" if os.path.exists(latest_path) else "not yet checked"
        parts.append(f"<tr><td>{html.escape(label.capitalize())}</td>"
                     f'<td class="n">{html.escape(human_gap(gap) if last else seen)}</td></tr>')
    parts.append("</table></div>")

    # ---- the evidence, folded away
    total_changes = sum(r["total_count"] for r in rows)
    total_breaking = sum(r["breaking_count"] for r in rows)
    if rows:
        dates = sorted(r["date"] for r in rows)
        span = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days
    else:
        span = 0

    parts.append("<details><summary>What this has caught, and what it stayed quiet about</summary>")
    parts.append(
        f"<p>Over <strong>{span} days</strong> the four companies above made "
        f"<strong>{total_changes} changes</strong> to what their software accepts. "
        f"<strong>{total_breaking}</strong> of those could break somebody. "
        f"<strong>{len(reaching)}</strong> would have reached Maya.</p>")
    if reaching:
        parts.append('<div class="scroll"><table><tr><th>When</th><th>What she would have been told</th></tr>')
        for r in reaching:
            a = assess(business, r)
            names = ", ".join(x["what_maya_calls_it"] for x in a["routines_touched"]
                              if x["has_breaking_change"])
            parts.append(f"<tr><td class=\"when\">{html.escape(human_date(r['date']))}</td>"
                         f"<td>{html.escape(names)}</td></tr>")
        parts.append("</table></div>")
    parts.append(
        "<p>Everything else was additive: new things her shop does not use, which an "
        "integration that already works can ignore. That ratio is the product. A tool that "
        "forwarded all "
        f"{total_changes} would have been switched off in a fortnight.</p>")
    parts.append("</details>")

    parts.append(
        "<footer>"
        f"<p>Checked {html.escape(dt.datetime.now(dt.timezone.utc).strftime('%d %B %Y at %H:%M UTC'))}. "
        "Regenerated by a scheduled job, not by hand.</p>"
        "<p>This reads what each company <strong>publishes</strong>, not what they have "
        "deployed, so a company whose documentation lags its rollout will not be caught. "
        "The link between Maya's routines and the calls they rely on was worked out at "
        "setup and can be wrong, so anything uncertain is held back for a person rather "
        "than sent to her.</p>"
        "<p><a href=\"https://github.com/iamrobertmoore/still-working\">"
        "github.com/iamrobertmoore/still-working</a></p>"
        "</footer></div>")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           "<title>Still Working</title>"
           "<meta name=\"description\" content=\"An agent that tells a shop owner when one of "
           "her suppliers has broken something. Most mornings it says two words.\">"
           "</head><body>" + "".join(parts) + "</body></html>")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)

    print(f"wrote {os.path.relpath(OUT, ROOT)}  ({len(doc):,} bytes)")
    print(f"state: {state}   outstanding: {len(outstanding)}   caught in {span} days: {len(reaching)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
