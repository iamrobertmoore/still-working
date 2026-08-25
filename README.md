# Still Working

**Maya runs a twelve-person online shop. Her orders stopped going into her accounting
software three weeks ago and she found out from her bookkeeper.**

Still Working is an agent that watches the handful of companies Maya's shop depends on, and
tells her when one of them has broken something. Not a diff. A sentence about her business.

Most mornings it says two words.

---

## The problem

A small shop runs on four or five companies it does not control. The card processor. The
till. The accounts. The shipping label service. Every one of them changes things whenever
they like, and none of them writes to Maya about it.

When one of those changes lands, nothing looks wrong. The shop keeps taking orders. The
money still arrives. What stops is something quiet: the nightly copy of orders into the
accounts, the tracking number in the dispatch email, the weekly figure she makes decisions
on. She finds out weeks later, from a bookkeeper, a customer, or a VAT return that will not
reconcile.

The information that would have warned her exists. Every one of those companies publishes,
in public, a machine-readable description of what their software accepts. Nobody reads it,
because reading it is a full-time job in a language Maya does not speak.

## Who it's for

**Maya.** Twelve people. Homeware, mostly. Sells online and at one counter.

She is not a developer and does not want to become one. She has Priya, a freelance
developer, two days a month and not on retainer. Priya is who fixes things. Maya is who
has to know there is something to fix, and right now she has no way of knowing.

Her whole business is written down, in her own words, in
[`business/maya.yaml`](business/maya.yaml). Five routines. What she calls each one, what
happens if it stops, how late she would normally notice, and what it costs her. She did
not write a single vendor call name in that file and could not have. She answered five
questions about her week and the agent worked the rest out during setup, which is recorded
separately, with a confidence level, so it can be checked and corrected when it is wrong.

This is the part that makes it hers rather than Priya's. The engine underneath compares
published contracts. What reaches Maya is a consequence.

## Why it matters

Because the failure is silent, and silent failures get expensive by sitting there.

Maya's nightly sync broke and cost her three weeks of manual reconciliation and a VAT
return built on numbers nobody trusted. The change that caused it was published, in public,
the day it happened. There was nothing secret about it. It just had nobody reading it who
knew what her shop needed.

And the reason nobody builds this for her is that the obvious version is useless. A tool
that forwards every vendor change gets switched off in week two. Over four simulated days
in the demo below, the companies Maya uses made eight changes, three of which would break
somebody. She is told about two of them. That ratio is the product.

---

## What it does

Three layers, and keeping them apart is the design.

| | What it answers | How |
|---|---|---|
| `tools/snapshot.py` | What changed, in the vendors' language | Deterministic. Fetch, normalise, classify. |
| `tools/impact.py` | Which of Maya's routines that touches | Deterministic. Set membership. |
| `agent/still_working.py` | Whether it actually breaks her, and how to say it | Judgement. Strands. |

Only the last layer needs a model, and it is the only one where being wrong is a matter of
degree rather than a bug.

**The interruption rule is a control, not an instruction.** "Only tell her when it matters"
in a prompt is a probability, and its failure mode is silent: it pings her about nothing
for a fortnight and she stops reading. Instead it is a Strands `InterventionHandler` on
`before_tool_call` around the one tool that can reach her:

- **Deny** when nothing she depends on is broken. She is never told.
- **Confirm** when the only thing broken is a routine the setup mapped at *low* confidence.
  A person checks before Maya is told her Monday figure is wrong.
- **Proceed** when a routine we are confident about is broken.

## What she actually sees

A day where something broke:

```
Your orders stopped going into the accounts on Tuesday.

The till software changed how it hands over the day's orders, and the nightly
hand-off to your accounts no longer picks up your shop. The shop is fine. Money
is still arriving. It is only the copy into the accounts that stopped.

What it costs you: Ines reconciles from this, so she is doing it by hand from
Tuesday onward, and the VAT return is built on it.
How late you would normally find out: three weeks, which is what happened last time

What to do: Forward the part below to Priya. It is about an hour of her time.

--- forward this part to Priya ---
  square 2026-09-02: parameter location_id removed from GET /v2/orders
  the nightly sync uses it to select this location's orders
```

Every other day:

```
Still working.
Nothing that matters to you changed.
```

The technical detail is in the note, complete, and clearly addressed to somebody else.
Maya forwards it. She never reads it. Leaving it out would make the note useless to the
person who can act on it; putting it above the line would make it useless to her.

## What is being watched

Four real companies, four real contracts, none of which I control.

| What Maya calls it | Company | Endpoints | Contract version |
|---|---|---|---|
| how customers pay me | Stripe | 589 | `2026-07-29.dahlia` |
| my till and my bookings | Square | 334 | `2.0` |
| my accounts, where my bookkeeper works | Xero | 235 | `17.0.0` |
| how I print labels | ShipEngine | 97 | `1.1.202604070904` |

Two of those stamp a version that moves. Square's has said `2.0` for years. **The company
that does not version its contract is the one you cannot watch by reading a version
string**, which is most of the reason this reads the whole document every day instead.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python tools/snapshot.py --self-test    # prove the change detector fires
python tools/impact.py   --self-test    # prove the right things reach Maya
python agent/still_working.py --demo    # four days, end to end
python tools/snapshot.py                # take today's snapshot
```

Nothing above needs an AWS account, a key, or a network call to a model. The agent runs
against a scripted model provider so the harness is testable on its own. Swapping in
`BedrockModel` is a one line change and no agent code moves.

## What the checks actually assert

A green tick is not evidence, so being exact about this:

- It reads what each company **publishes**, not their live system. A company whose
  documentation lags its deployment will not be caught.
- The mapping from Maya's routines to vendor calls was **inferred at setup and can be
  wrong**. Every routine carries its confidence, and a low-confidence routine cannot reach
  her without a person agreeing first.
- `tools/snapshot.py --self-test` proves the detector fires on all six change kinds, marks
  exactly the right two as breaking, tells an optional parameter becoming required apart
  from a brand new required one, and stays silent on an identical snapshot.
- `tools/impact.py --self-test` proves a busy day of breaking changes she does not depend
  on stays silent, that a company renaming its own path parameter still matches her
  profile, and that **every routine has at least one call no other routine watches**. That
  last test exists because one did not, which made its own behaviour untestable and which
  nothing else would have caught.
- The scheduled job runs the self tests **first** and fails loudly if they stop passing. A
  check that has quietly stopped checking still goes green.
- A company being unreachable is reported as a job failure, never as a change. The alarm is
  gated on the classification, never on the job's exit code.
- Nothing is gated on a credential. Every contract is public. There is no secret that can
  go missing and let the job skip its work while still passing.

## Layout

```
business/maya.yaml          Maya's shop in her words, and what setup inferred from it
contracts/vendors.json      the four companies being watched
contracts/snapshots/        one normalised snapshot per company per day
contracts/latest/           the running head
contracts/changes.jsonl     append only, one record per detected change
tools/snapshot.py           fetch, normalise, classify. Deterministic
tools/impact.py             which routines a change touches. Deterministic
agent/still_working.py      the Strands agent, its tools, and the interruption rule
agent/notes.py              the only format Maya ever sees
agent/model_double.py       a scripted Strands model provider, for credential-free tests
.github/workflows/          the daily job
```

Snapshots store the **normalised** map, never the raw document. The four raw files are
about 23 MB a day between them. The normalised map is under 250 KB and git compresses it to
almost nothing, because on most days nothing changes.

## Disclosure

I built a CI job earlier this year that compared a generated artifact against a live vendor
API. **No code from it is in this repository.** What carried over is the idea that the
interesting comparison is against a third party you do not control, and two things I got
wrong the first time: raise the alarm on the specific failing check rather than on the job
failing, and never gate a suite on a credential you do not have. Both are written into the
workflow and the self tests here.

## Licence

MIT. See [LICENSE](LICENSE).
