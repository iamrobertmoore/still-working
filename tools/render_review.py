#!/usr/bin/env python3
"""Render a review workbench whose exported decisions the real pipeline can import."""
import html
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.render_page import CSS,mark,human_date
from tools.review import pending_cases
from tools.impact import load_business

REVIEW_CSS='''
.review-nav{display:flex;gap:25px;padding:20px 0;font-size:14px}.review-head{padding:30px 0;max-width:760px}.review-head h1{font:normal clamp(38px,5vw,60px)/1.1 Georgia,serif;letter-spacing:-1.8px;margin:10px 0 20px}.review-head p{font-size:16px;color:var(--muted)}.review-grid{display:grid;grid-template-columns:1fr 1fr;gap:25px;align-items:start}.review-card{padding:28px;border:1px solid var(--line);border-radius:14px;background:var(--surface);font-size:16px}.review-card h2{font-size:22px;margin-bottom:20px}.review-card h3{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:25px 0 8px}.review-card p{margin:12px 0}.review-card pre{font:12px/1.7 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--soft);padding:16px;border-radius:8px}.review-tag{font-size:12px;color:var(--warn);letter-spacing:.08em;text-transform:uppercase}.review-card fieldset{border:0;padding:0;margin:0}.review-card legend{font-size:16px;font-weight:600;margin-bottom:14px}.review-choice{display:flex;align-items:flex-start;gap:10px;border:1px solid var(--line);border-radius:8px;padding:14px;margin:10px 0;cursor:pointer;font-size:14px}.review-choice:has(input:checked){border-color:var(--green);background:var(--mint)}.review-choice input{margin-top:5px;accent-color:var(--green)}.review-choice small{display:block;color:var(--muted);font-size:13px;margin-top:4px}.review-field{display:block;margin-top:20px;font-size:14px}.review-field input,.review-field textarea{display:block;margin-top:7px;width:100%;border:1px solid var(--line);border-radius:8px;padding:12px;background:var(--bg);color:var(--ink);font:inherit}.review-field textarea{min-height:100px;resize:vertical}.review-card button,.download-review{display:inline-block;margin-top:22px;padding:13px 20px;background:var(--green);color:var(--bg);border:0;border-radius:8px;font:inherit;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none}.review-card button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid var(--green);outline-offset:3px}.review-result{margin-top:22px;border-top:1px solid var(--line);padding-top:20px}.review-result h3{margin-top:0;text-transform:none;font-size:20px;color:var(--green);letter-spacing:0}.review-result .receipt-note{font-size:14px;white-space:pre-line}.review-result details{margin-top:18px}.review-result summary{padding:12px 0;font-size:14px}.review-footer{margin:35px 0;border-top:1px solid var(--line);padding-top:25px;color:var(--muted);font-size:13px}.review-footer a{margin-right:18px}.case-queue{margin:30px 0}.case-queue a{display:block;padding:18px;border:1px solid var(--line);border-radius:8px;margin:12px 0}#error{color:var(--warn);font-size:14px}[hidden]{display:none!important}@media(max-width:760px){.review-grid{grid-template-columns:1fr}.review-card{padding:23px}.review-head{padding-top:20px}.review-nav{gap:20px}.identity{display:none}}
'''


def render(case, mode, proof=None):
    routine=case['routine'];example=mode=='example'
    bundle={'mode':mode,'case_id':case['case_id'],'proof':proof}
    encoded=json.dumps(bundle).replace('<','\\u003c')
    changes='\n'.join(c.get('kind','')+': '+c.get('endpoint','')+(' / '+c['param'] if c.get('param') else '') for c in routine['changes'] if c.get('breaking'))
    explanation=('This is a recorded test of the review gate. The supplier change is real; its mapping confidence was deliberately lowered. Try either developer decision and inspect the captured cloud result.' if example else 'A detected supplier change is waiting for someone who knows the integration. Record the check, download your decision, and give it to the project operator to apply.')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review a match | Still Working</title><link rel="icon" href="../brand/mark.svg"><style>{CSS}\n{REVIEW_CSS}</style></head><body><div class="wrap"><header class="masthead"><a class="brand" href="../">{mark()}<span>still working.</span></a><span class="identity">A decision for the person who knows the integration.</span></header><nav class="review-nav"><a href="../">Daily check-in</a><a href="../replay/">Recorded warnings</a><a href="live.html">Pending queue</a></nav>
    <main><section class="review-head"><span class="review-tag">{'Recorded review example' if example else 'Pending developer review'}</span><h1>A question before<br>another interruption.</h1><p>{explanation}</p></section>
    <div class="review-grid"><section class="review-card"><span class="review-tag">Waiting for a person · No note sent</span><h2>{html.escape(routine['what_maya_calls_it'])}</h2><h3>What is known</h3><p>{html.escape(case['vendor'].title())} published a potentially breaking change on {human_date(case['date'])}.</p><pre>{html.escape(changes)}</pre><h3>What is uncertain</h3><p>Does this routine actually use the affected call? The mapping has <strong>{html.escape(routine['mapping_confidence'])} confidence</strong>.</p><h3>Why it could matter</h3><p>{html.escape(routine['what_it_costs'])}</p><p class="section-meta">The business consequence is an illustrative assumption, not an observed outage.</p></section>
    <section class="review-card"><h2>Check the dependency.</h2><form id="review-form"><fieldset><legend>What did the integration check show?</legend><label class="review-choice"><input type="radio" name="decision" value="approve" required><span>This routine uses the affected call.<small>Permit the agent to assess and write a note. Its delivery controls still apply.</small></span></label><label class="review-choice"><input type="radio" name="decision" value="dismiss"><span>This change does not affect this routine.<small>Close this case without invoking a model or sending a note.</small></span></label><label class="review-choice"><input type="radio" name="decision" value="unsure"><span>I still cannot establish the dependency.<small>Keep it pending. An unanswered question is not an approval.</small></span></label></fieldset><label class="review-field">Reviewer<input id="reviewer" minlength="2" maxlength="120" required value="{'Example reviewer' if example else ''}" autocomplete="off"></label><label class="review-field">What did you check?<textarea id="reason" minlength="2" maxlength="1200" required>{'Demonstration decision. No real integration or customer was checked.' if example else ''}</textarea></label><button type="submit">{'Try this review decision' if example else 'Prepare review file'}</button><p id="error" role="alert"></p></form>
    <div id="review-result" class="review-result" aria-live="polite" hidden><h3 id="result-title"></h3><p id="result-copy"></p><p id="result-metrics"></p><details id="note-details" hidden><summary>Read the captured note</summary><div id="result-note" class="receipt-note"></div></details><a id="download" class="download-review" hidden>Download {'example ' if example else ''}review file</a></div></section></div></main>
    <footer class="review-footer"><p>{'Example decisions are for demonstration only and cannot be imported into the live queue. The selected branch shows a saved AWS response, not a fresh browser invocation.' if example else 'Nothing is submitted from this page. A repository operator must import the downloaded file; the daily caller then applies the decision. A reviewer name is supplied, not identity-verified.'}</p><p>Each review is bound to the exact date, supplier and assessed routine. Changing the case invalidates the decision.</p><a href="{'proof.json' if example else 'pending.json'}">Inspect the source record</a><a href="https://github.com/iamrobertmoore/still-working/blob/main/docs/REVIEW.md">How the review reaches the agent</a></footer></div><script id="review-data" type="application/json">{encoded}</script><script src="review.js"></script></body></html>'''


def main():
    out=ROOT/'docs/review';out.mkdir(parents=True,exist_ok=True)
    proof_path=out/'proof.json'
    if proof_path.exists():
        proof=json.loads(proof_path.read_text());(out/'index.html').write_text(render(proof['case'],'example',proof['steps']))
    state_path=ROOT/'contracts/delivery-state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    cases=pending_cases(load_business(),state)
    (out/'pending.json').write_text(json.dumps({'mode':'live','cases':list(cases.values())},indent=2)+'\n')
    links=[]
    for key,case in cases.items():
        (out/f'{key}.html').write_text(render(case,'live'))
        links.append(f'<a href="{key}.html">{html.escape(case["routine"]["what_maya_calls_it"])} · {human_date(case["date"])}</a>')
    body=''.join(links) or '<p>There are no pending cases in the latest published queue.</p><p><a href="./">Try the recorded review example</a></p>'
    (out/'live.html').write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pending reviews | Still Working</title><style>{CSS}{REVIEW_CSS}</style></head><body><div class="wrap"><header class="masthead"><a class="brand" href="../">{mark()}<span>still working.</span></a></header><main class="review-head"><p class="eyebrow">Published review queue</p><h1>Waiting for a person.</h1><div class="case-queue">{body}</div></main></div></body></html>')
    print(f'Rendered review flow and {len(cases)} live pending cases.')


if __name__=='__main__':main()
