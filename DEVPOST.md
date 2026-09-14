# Still Working

[Watch the video demo](https://www.youtube.com/watch?v=0cayNMYe2pw)

[See what it catches](https://iamrobertmoore.github.io/still-working/replay/) · [Try a review decision](https://iamrobertmoore.github.io/still-working/review/) · [Open the daily page](https://iamrobertmoore.github.io/still-working/)

The counter sells the last item. The website keeps taking orders. Still Working turns the supplier's technical change into a warning the owner can understand and a check her developer can act on.

**Professional Agents** · **Strands Agents on Amazon Bedrock AgentCore**

## Who it is for

Small-business owners whose day depends on integrations they did not build. The example follows Maya's twelve-person homeware shop: payments, payroll, stock, accounts and shipping. Priya, her freelance developer, can fix an integration once someone identifies what needs checking.

## The problem

Suppliers publish changes in the language of API calls. The shop owner thinks in routines: paying the team, reconciling yesterday's orders, keeping the counter and website in sync. Between those two descriptions is a warning nobody has translated.

Forwarding every technical change creates another inbox to ignore. Still Working connects a published change to a business routine, explains the consequence, and prepares the technical handoff.

## Why it matters

A background failure can leave the storefront looking healthy while the accounts stop reconciling or stock counts drift. The useful outcome is an earlier, specific check: which routine could be affected, what that would cost, and what the developer needs to investigate.

The owner's attention is part of the design. A quiet morning stays quiet. A repeated warning is held. An uncertain dependency waits for someone who knows the integration.

## How it works

1. **Collect.** Compare the contracts published by Stripe, Square, Xero and ShipEngine.
2. **Match.** Connect changed calls to eight routines in the shop profile. Setup checks proposed calls against supplier publications.
3. **Explain.** Strands turns an eligible change into a business warning with a section ready to forward to Priya.
4. **Control.** A Strands `Transform` stamps known factual fields. `Deny` blocks ineligible delivery attempts. Local `Confirm` supports human approval; the deployed path holds uncertain cases before building a model and accepts a case-specific review from its authenticated caller.
5. **Remember.** Persist successfully rendered notes and the delivery ledger. Quiet and repeated cases never construct a model. A refused note remains eligible for retry.

The review workbench makes the human decision inspectable: confirm the dependency, dismiss the case, or leave it pending. Its exported decision covers the exact supplier, date and assessed routine.

## What it is built with

Python, Strands Agents, Amazon Bedrock, Bedrock AgentCore, GitHub Actions and GitHub Pages. The collector and matcher are deterministic; the deployed agent uses Bedrock in `us-east-1` for judgement and note-writing.

A credential-free collection job publishes the supplier check and queues relevant changes. A separate job authenticates with temporary, repository-scoped OIDC credentials, invokes AgentCore, and publishes notes, the ledger and review status. If AWS is unavailable, collection still publishes and queued changes survive for the next run. The local and deployed delivery controls share canonical source code, with a check that rejects drift.

[Architecture diagram](https://iamrobertmoore.github.io/still-working/architecture.svg) · [Technical design](https://github.com/iamrobertmoore/still-working/blob/main/ARCHITECTURE.md) · [Source](https://github.com/iamrobertmoore/still-working)

## What I can demonstrate

**150 days of real supplier history. 56 individual changes. 23 supplier-day records. Two rendered notes.**

Xero removed employee calls from its published contract on 24 April and again on 29 April. Square removed an inventory-transfer call on 14 July. These are observed publication changes. The shop profile maps them to payroll and stock routines; the note asks the developer to check the dependency.

I replayed every record against the deployed runtime. The first payroll change produced a note. The repeat five days later was held. The Square change produced the second note. Only those two cases invoked a model.

**That ratio is the product.** Every input, response and delivery decision is available in the browser replay, without an AWS login. A separate captured review scenario shows hold, approval, dismissal and repeat suppression. The fresh cloud command below generates a new stock warning and carries its returned ledger into a second invocation.

**Come back during judging.** The scheduled check keeps running. The daily page shows when the suppliers were checked and when the agent review completed, with a link to the actual run.

## How to run it

Open the replay links above to inspect the recorded results immediately. To run the local Strands demonstration and checks:

```bash
git clone https://github.com/iamrobertmoore/still-working.git
cd still-working
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install pytest bedrock-agentcore
python agent/still_working.py --demo
python tools/impact.py --measure
python -m pytest tests/ -q
```

The local demo uses a scripted model through the real Strands loop. For fresh AWS execution, follow the [runtime setup](https://github.com/iamrobertmoore/still-working/blob/main/runtime/README.md), set `STILL_WORKING_RUNTIME_ARN` and run `python tools/live_demo.py`. It uses historical input and an isolated ledger, and can incur AWS charges.

## What I got wrong

My first profile returned zero. It omitted important routines. Checking mappings later exposed three calls that had never existed, despite the other tests passing.

Then the model put an invented date under FACT. My first fix stamped the tool input correctly but lost the date before rendering; three tests passed over that gap. The checks now exercise the note the owner actually reads.

A final audit found that the deployed controls lagged behind the local code and the daily collector did not call the runtime. I connected the full path, generated the shared controls, and captured the actual cloud results. Each failure changed the implementation.

## What I would do next

Validate the mappings against a real shop integration, evaluate missed changes on fresh history, and add private storage and reviewer authentication. That is the next step from this inspectable build to a service an owner can rely on.

## Build journal

Three articles on AWS Builder Center follow the measurements, deployment and controls behind Still Working.

1. [56 supplier changes, two notes for a shop owner](https://builder.aws.com/content/3JJRAyrMXkMC2Lu1LWkrVIA2uOJ/agents-for-humans-56-supplier-changes-two-notes-for-a-shop-owner-agentsforhumans)
2. [My agent was deployed, but the daily job did not call it](https://builder.aws.com/content/3JJSOz6E2j2Lmw1hKsUFM8Af92f/agents-for-humans-my-agent-was-deployed-but-the-daily-job-did-not-call-it-agentsforhumans)
3. [My agent invented a date and filed it under FACT](https://builder.aws.com/content/3JJShEzJy72ITitAAsHKmPL6HLe/agents-for-humans-my-agent-invented-a-date-and-filed-it-under-fact-agentsforhumans)

## Disclosure

Maya, Priya and the shop are illustrative. Supplier publications and captured AWS responses are real. I refined the profile and repeat rule using this history; the ratio measures retrospective notification volume, not accuracy or customer savings. Published contracts establish what changed in the publication, not whether an integration failed. The review example uses simulated choices, and live decisions require operator import. No customer testing has been conducted.

I previously built a CI job comparing a generated artifact against a live vendor API. No code from it is included here. Its lessons informed the separation between a vendor change and a failed monitoring job. This project is MIT licensed.
