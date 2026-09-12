# Still Working

**The Devpost submission text, kept in the repository so it can be checked against the
code rather than remembered.**

Live: <https://iamrobertmoore.github.io/still-working/>
Source: <https://github.com/iamrobertmoore/still-working>
Architecture: [`docs/architecture.svg`](docs/architecture.svg) and
[`ARCHITECTURE.md`](ARCHITECTURE.md)

---

## Who it is for

**Maya.** Twelve people, an online shop and one counter, homeware mostly. She is not a
developer and does not want to become one. Priya is her freelance developer, two days a
month and not on retainer. Ines is her bookkeeper.

Maya is not a persona invented to frame a developer tool. Her whole business is written
down, in her own words, in [`business/maya.yaml`](business/maya.yaml): eight routines, what
she calls each one, what happens if it stops, how late she would normally notice, and what
it costs her. She did not write a single supplier call name in that file and could not
have. The agent worked those out at setup, and recorded them separately with a confidence,
so they can be checked and corrected when they are wrong.

## The problem

Her shop runs on four companies she does not control: the card processor, the till, the
accounts, the shipping labels. Every one of them changes what their software accepts
whenever they like, and none of them writes to Maya about it.

When one of those changes lands, nothing looks wrong. The shop keeps taking orders. The
money still arrives. What stops is something quiet: the nightly copy of orders into the
accounts, the payroll run that reads the staff list, the stock count moving between the
counter and the website. She finds out weeks later, from a bookkeeper, a customer, or a VAT
return that will not reconcile.

Her orders stopped going into her accounting software and she found out three weeks later,
from Ines.

## Why it matters

**The warning already existed.** Every one of those companies publishes, in public, a
machine-readable description of exactly what their software accepts, and updates it the day
they change it. Nobody reads it, because reading it is a full-time job in a language Maya
does not speak.

**And the obvious version of this product is useless.** A tool that forwards every supplier
change gets switched off in week two. So I measured it, against real history rather than a
demo.

> **150 days. Four suppliers. 56 changes to what their software accepts.**
> **Nine of those could break somebody. Seven landed on a call one of Maya's routines uses.**
> **Two would have interrupted her.**

Two, from 56. That ratio is the product, and it is the reason a model is in here at all.

Reproduce it yourself: `python tools/impact.py --measure`.

## How it works

Three layers. Only the third needs a model, and it is the only one deployed.

**1. Collect, deterministic.** A scheduled job fetches the four public contracts every
morning at 05:40 UTC and diffs them against yesterday. Nine kinds of change are detected.
Exactly three of them can break a caller who already works: a call removed, a parameter
removed, or an optional parameter becoming required. Everything else is additive and is
counted and dropped. No model, no credentials.

**2. Match, deterministic.** Set membership against Maya's profile: is the call that
changed one of the calls this routine leans on? Reproducible, the same answer every time.
No model, no credentials. Most mornings this ends the job.

**3. Judge, Strands Agents on Bedrock AgentCore Runtime.** Only what survived layer 2 gets
here. The model decides whether the change actually stops the routine working, and writes
it in Maya's language: a consequence, what it costs her, how late she would otherwise have
found out, and a section addressed to Priya by name.

### The interruption rule is a control, not a prompt line

This is the part I would defend hardest. A system prompt that says "only tell her when it
matters" is a probability, and its failure mode is silent: it pings her about nothing for a
fortnight and she stops opening them.

So the rule is a Strands `InterventionHandler` on `before_tool_call`, and `send_to_maya` is
the only tool that reaches her.

| outcome | when |
| --- | --- |
| `Deny` | nothing she depends on is broken |
| `Deny` | she was told about this same routine within the last five days |
| `Proceed` | a routine mapped at high or medium confidence is broken |
| `Confirm` | the only thing broken was mapped at low confidence, so a person checks first |

A second handler runs before it and uses `Transform` to overwrite the note's factual
fields with the values the system already holds. That one exists because of a specific
failure: given a change dated 14 July and a `days_ago` of 51, the model subtracted one from
the other, got 24 May, and filed it under the word **FACT**. The fix was not a firmer
instruction. The fix is that the model is never the source of a fact the system knows.

### What she actually sees

Most mornings, two words.

```
Still working.
Nothing that matters to you changed.
```

And on the mornings that are not most mornings, a note in her own vocabulary with the
technical half clearly addressed to somebody else, because Maya forwards that part, she
does not read it.

## What it is built with

| | |
| --- | --- |
| Agent framework | Strands Agents SDK, `strands-agents>=1.55.1` |
| Deployed on | Amazon Bedrock AgentCore Runtime, us-east-1 |
| Model | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` on Amazon Bedrock |
| Scheduler | GitHub Actions, daily, no secrets of any kind |
| Maya's screen | GitHub Pages, one file, no JavaScript, no external requests |
| Language | Python 3.11 in CI, 3.14 in the deployed runtime |

Strands surfaces used, and what each is for, are listed in
[ARCHITECTURE.md](ARCHITECTURE.md#the-strands-surface-this-uses-and-what-each-one-is-for):
`Agent`, `@tool`, `strands.hooks`, `strands.interventions` (`Transform`, `Deny`, `Confirm`,
`Proceed`), a custom `Model` provider, `structured_output_model=`, `FileSessionManager`,
`AgentState`, `Agent.as_tool()`, `stream_async`, `StrandsTelemetry` and `result.metrics`.

## How to run it

No AWS account needed for any of this:

```bash
pip install -r requirements.txt

python agent/still_working.py --demo     # six days, scripted model, no credentials
python agent/still_working.py --stream   # the same note, arriving as it is written
python agent/morning.py --demo           # four suppliers, one morning, one message
python tools/impact.py --measure         # the five month measurement
python tools/setup.py --verify           # every call in her profile, against today's contracts
python -m pytest tests/ -q               # 325 tests, about three seconds
```

With an AWS account and Bedrock model access:

```bash
python tools/check_bedrock.py            # which model ids this account can actually invoke
python agent/still_working.py --live     # one real recorded change, through Bedrock
```

## What I got wrong, and kept

The repository keeps its mistakes in it on purpose, because the interesting parts of this
build were all failures.

- **The measurement returned zero the first time.** Not because the premise was wrong,
  because Maya's profile was too thin: five routines, and only the calls I guessed had
  broken. Widening it to eight routines with their full call sets, and recording the zero,
  is in the footer of `business/maya.yaml`.
- **Eight days of collection were lost.** Recovered by reconstructing history from the
  suppliers' own public git repositories, which turned twelve days of data into five months.
- **The scheduled job had never been run when it was written**, so a missing `pip install`
  killed it in twelve seconds and the self tests it existed to run never executed.
  The note is still in the workflow file.
- **The model invented a date under the word FACT.** See `Transform`, above.
- **Three calls in Maya's profile did not exist.** `tools/setup.py --verify` found them on
  11 September, after a fortnight in the repository, having passed every other test. A
  watch on a call a supplier has never published can never fire, and nothing would ever
  have said so.

## What I would do next, for Maya

- **Let her correct a mapping without a developer.** "This has nothing to do with my Monday
  figure" should downgrade a confidence, and it is the only feedback signal that matters.
- **Watch the fifth supplier.** She has one more than the four I modelled, and the setup
  conversation is the part that does not scale yet.
- **Tell Priya before Maya, when Priya is working.** The note already carries a section
  addressed to her. Sending it directly on the two days a month she is on is a scheduling
  problem, not an agent problem.
- **Say what it cost.** A monthly line saying "your suppliers changed 41 things, you heard
  about one" is the number that makes the silence legible.
