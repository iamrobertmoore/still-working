# Architecture

![Three layers, and only the third needs a model](docs/architecture.svg)

Still Working has three layers. Two of them are deterministic, cost nothing, need no
credentials and run in CI. The third needs a model, and it is the only one deployed.

Keeping them apart is the whole design, so this document is mostly about the boundaries.

---

## Why three layers and not one agent

The obvious build is one agent with tools: fetch the contracts, work out what changed,
decide whether it matters, write to Maya. It would demo well and it would be wrong, for
three reasons.

**Most of the work has a right answer.** "Did `GET /Employees` disappear between Tuesday
and Wednesday" is set membership. There is nothing to judge. Putting it behind a model
makes it slower, more expensive, non-reproducible, and harder to test, in exchange for
nothing.

**The expensive layer should run rarely.** Over 150 days the four suppliers made 56
changes. Nine could break a caller. Three broke a routine of Maya's, and after the repeat
rule she is interrupted twice. If the model sees all 56, it is being paid to say "not this
one" 54 times.

**The controls have to sit somewhere a prompt cannot reach.** The product is the silence.
A system prompt that says "only tell her when it matters" is a probability, and its failure
mode is quiet: it pings her about nothing for a fortnight and she stops opening them. That
decision has to be code.

---

## Layer 1: collect. What changed, in the suppliers' language

`tools/snapshot.py`. Runs in GitHub Actions at 05:40 UTC, every day, on a public runner
with no secrets of any kind.

It fetches the OpenAPI description each supplier publishes, normalises it to a flat map of
`METHOD /path` to `{params, required, responses}`, and diffs it against yesterday's. Every
difference becomes one record with a `kind`.

Nine kinds are detected. Exactly three of them can break a caller who already works:

| kind | breaking | why |
| --- | --- | --- |
| `endpoint_removed` | yes | the call she relies on is gone |
| `param_removed` | yes | the filter or field she passes is gone |
| `param_became_required` | yes | a call that worked now returns an error |
| `endpoint_added` | no | something new she does not use |
| `param_added` | no | an optional extra |
| `param_became_optional` | no | a constraint relaxed |
| `response_added` / `response_removed` | no | worth recording, not worth waking her |
| `version_string_changed` | no | suppliers bump these for nothing |

`breaking` is a property of the change, not of the run. That distinction is the reason the
scheduled job's alarm is gated on `steps.snapshot.outputs.breaking` and never on
`failure()`: a broken job must not be able to announce itself as a supplier changing their
API.

Output: `contracts/snapshots/<vendor>/<date>.json` and one line appended to
`contracts/changes.jsonl`.

The 150 days of history before the job existed were reconstructed by `tools/backfill.py`,
which reads each supplier's own public git repository and replays it one calendar day at a
time. One revision per day, the last, because Stripe pushed and reverted inside 1 July and
taking every commit would have invented two changes that never reached anybody.

## Layer 2: match. Whose problem it is

`tools/impact.py`. Also deterministic, also runs in CI, also no model.

`business/maya.yaml` holds Maya's eight routines. Each is written twice. Above the line is
what she said: what she calls it, what happens if it stops, how late she would normally
notice, what it costs her. Below the line is a `derived` block naming the exact supplier
calls that routine leans on, with a confidence and a reason. She has never read the second
half, and did not write a single call name in it.

Matching is set membership on a canonical form, so `GET /v1/payment_intents/{intent}` and
`GET /v1/payment_intents/{payment_intent_id}` are the same call. Suppliers rename their own
path parameters without it meaning anything, and Maya's profile was written from her
developer's memory. Neither side should have to match the other character for character.

The output of this layer is the only thing the judgement layer ever sees. It carries the
change, the routines it touched, the mapping confidence, how the supplier should be named
to Maya, who fixes things, and how many days ago it happened.

**Nothing else reaches the model.** No contracts, no snapshots, no repository.

## Layer 3: judge. Whether it actually costs her

`agent/still_working.py` locally, `runtime/app/StillWorking/main.py` deployed. Strands
Agents, on Amazon Bedrock AgentCore Runtime, us-east-1, Claude Sonnet 4.5 through
the global inference profile.

This layer has two jobs and neither of them is deciding whether Maya is interrupted.

1. Decide whether a contract change that touches a routine actually stops it working. A
   removed call she leans on does. A parameter removed from a call she uses for something
   else may not.
2. Write it in her language: a consequence, what it costs her, how late she would normally
   have found out, and a section to forward to Priya.

---

## The controls

Everything that decides whether Maya hears anything lives in Strands interventions on
`before_tool_call`, not in the system prompt. There is exactly one tool that reaches her,
`send_to_maya`, so there is exactly one place to stand.

Two handlers run in order, because they are two different jobs.

### 1. `StampTheFacts`, a `Transform`

Overwrites the note's factual fields with the values from the deterministic layer, whatever
the model put there: the routine id, the date the supplier made the change, and how many
days ago that was.

This exists because of a specific failure. Given a change dated 14 July and a `days_ago` of
51, the model subtracted one from the other, got 24 May, and wrote it under the word
**FACT**. It had done arithmetic, got it wrong, and presented the result with more
confidence than anything else in the note.

The fix is not a firmer instruction. The fix is that the model is never the source of a
fact the system already holds. `Transform` mutates the call in place and lets the pipeline
continue, so the handler below sees the corrected version.

### 2. `OnlyWhenItCostsHer`, the interruption rule

| outcome | when |
| --- | --- |
| `Deny` | nothing she depends on is broken. She is never told. |
| `Deny` | she was told about this same routine within the last five days. |
| `Proceed` | a routine mapped at high or medium confidence is broken. Send it now. |
| `Confirm` | the only thing broken was mapped at low confidence. A person checks first. |

The ordering matters and I had it wrong first. Checking for low confidence before checking
for a confident break meant one shaky mapping could hold a certain problem behind a human.
Something I know is broken goes out now, and the uncertainty rides along inside the note
instead of gating it.

The repeat rule came from the data. Xero deleted the employee section on 24 April, put it
back, and deleted it again on the 29th. Both days are real and both break the routine Maya
calls "Paying the twelve of us". Two notes in five days about her payroll is how a person
learns to archive the sender. The quiet window lives in one named constant in
`agent/memory.py`, not spread across a prompt.

### Where the record lives

The ledger of what actually reached Maya is held in the agent's own state, persisted by a
Strands `FileSessionManager`. The transcript records what the model asked to send; the
ledger records what cleared the controls. Those are not the same thing, and the difference
between them is the measurement this project rests on.

---

## What runs where

```
GitHub Actions, 05:40 UTC daily, no secrets
  tools/snapshot.py        --self-test    the detector still detects
  tools/impact.py          --self-test    the right things still reach Maya
  tools/setup.py           --self-test    setup cannot invent a call into her profile
  agent/morning.py         --self-test    a quiet morning builds no agent at all
  agent/still_working.py   --demo         six days, scripted model, no AWS
  agent/still_working.py   --stream       the note still streams
  tools/check_runtime_isolation.py        the bundle does not reach into the repo
  pytest tests/                           325 cases, about three seconds
  tools/setup.py           --verify       no call in her profile is one that never existed
  tools/snapshot.py                       fetch and diff four public contracts
  tools/render_page.py                    regenerate docs/index.html
  tools/impact.py          --readme       regenerate the numbers in the README
  commit, push

Bedrock AgentCore Runtime, us-east-1, consumption billed
  runtime/app/StillWorking/main.py        the judgement layer, and nothing else

GitHub Pages, from docs/ on main
  Maya's screen. One file, no JavaScript, no external requests.
```

### Why the deployed bundle carries nothing

`runtime/` imports nothing from `agent/`, `tools/`, `business/` or `contracts/`, and
contains no absolute paths. `tools/check_runtime_isolation.py` asserts it on every run,
using `git ls-files` rather than a directory walk, because an earlier version scanned 2,325
files of AgentCore build cache to judge four. It treats zero tracked files as a failure
rather than a pass, because a check that passes when it finds nothing is not a check.

The bundle carries its own copy of the house style formatter and its own scripted model
double. A few lines of duplication is cheaper than coupling a deployable to a tree it will
not be deployed with, and there is a test asserting the two copies still agree.

### One behaviour differs on purpose

There is no human at a console inside AgentCore Runtime, so a `Confirm` cannot be answered.
A break that only implicates a low confidence mapping is therefore held and the caller is
told it is waiting for a person, rather than being auto approved. Silently approving what
the system said needed checking would make the confidence level decorative.

---

## The Strands surface this uses, and what each one is for

| Strands | where | why it is there and not just present |
| --- | --- | --- |
| `Agent` | everywhere | the loop |
| `@tool` | `read_routine`, `send_to_maya` | one tool reaches Maya, so there is one place to put the control |
| `strands.interventions` | `Transform`, `Deny`, `Confirm`, `Proceed` | the interruption rule and the fact stamping, as code |
| `strands.hooks` | `BeforeToolCallEvent` | where the controls attach |
| `strands.models.model.Model` | `agent/model_double.py` | the whole agent runs with no AWS account, in under a second |
| `structured_output_model=` | `tools/setup.py` | the setup conversation returns a validated shape with a closed confidence set |
| `strands.session.FileSessionManager` | `agent/memory.py` | "do not tell her the same thing twice" needs a record of yesterday |
| `AgentState` | the ledger | what cleared the controls, persisted with the session |
| `Agent.as_tool()` | `agent/morning.py` | four suppliers, one morning, one message |
| `stream_async` | `--stream` | the note arriving as it is written |
| `StrandsTelemetry` | `--trace` | every model call, tool call and intervention as a span |
| `result.metrics` | `cost_of_the_morning` | the claim that the expensive layer runs rarely, audited by the framework |

`agent/morning.py` deserves a note, because on its face it undoes the thesis. It uses
`Agent.as_tool()` so that each supplier's judgement agent becomes a tool a round-up agent
can call, and the round-up writes the single message Maya gets. The constraint is that

> the round-up merges, and never selects.

It is only ever handed notes that have already passed `OnlyWhenItCostsHer`. If no supplier
produced one, the round-up is never constructed and no model runs at all, which the tests
assert by counting model calls rather than by trusting the code to be careful. A round-up
that could decide to stay quiet about something that got through would be a second, softer,
prompt-shaped version of the control this whole project exists to avoid.

---

## Failure modes, and what happens in each

| what goes wrong | what happens |
| --- | --- |
| a supplier is unreachable | the snapshot step is `continue-on-error`, the run fails at the end with a message saying it is a job problem and not a contract change. No alarm is raised. |
| the job itself breaks | no issue is created, because the alarm is gated on `outputs.breaking` and never on `failure()`. |
| a mapping is wrong | it carries a confidence. Low confidence alone waits for a person. Medium sends, with the doubt stated in the note. |
| a mapping points at a call that does not exist | `tools/setup.py --verify` catches it. It found three on 11 September, in a profile that had been in the repository for a fortnight and passed every other test. |
| the model invents a date | Two controls. `Transform` overwrites the note's date field with the supplier's own, and the tool then refuses to render any note whose prose asserts a different date, handing the mistake back for the model to correct. Both the local agent and the deployed bundle do this. |
| the model writes an em dash | the formatter removes it, and asserts none survived. |
| a supplier publishes late | nothing catches it. This reads what suppliers publish, not what they have deployed, and the page says so. |

---

## What this does not do

It does not watch traffic, or instrument Maya's shop, or need access to anything of hers.
It reads four public documents. That is also its limit: a supplier whose documentation lags
their rollout will not be caught, and the page Maya looks at says so in as many words.
