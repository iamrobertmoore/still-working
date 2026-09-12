# Still Working

**Maya is an illustrative shop owner. The supplier history and captured cloud responses are real.**

**Tagline:** A quiet eye on your business. Supplier changes become a note you can act on.

**Track:** Professional Agents

**Live project:** https://iamrobertmoore.github.io/still-working/

**Recorded cloud replay:** https://iamrobertmoore.github.io/still-working/replay/

**Source:** https://github.com/iamrobertmoore/still-working

**Architecture:** [diagram](docs/architecture.svg) and [technical explanation](ARCHITECTURE.md)

## Inspiration

A shop can keep taking payments while a background integration stops copying orders into the accounts. The owner finds out from a bookkeeper weeks later. The supplier's technical publication might contain the warning, but the person who needs it cannot use a list of changed API calls.

I designed for Maya, an illustrative owner of a twelve-person homeware shop. She has a freelance developer, Priya, but no one watching four suppliers every morning. The problem is getting one useful warning to Maya without making her read fifty irrelevant ones.

## What it does

Still Working reads the public contracts of Stripe, Square, Xero and ShipEngine. It matches changes to eight business routines, then uses an agent to explain what might be affected and what to ask Priya to check.

The owner's note leads with a possible business consequence. Technical evidence sits below “forward this part to Priya”. On quiet days there is no model invocation. Repeated notices are held by a delivery ledger, and uncertain mappings can wait for a person.

The daily page is deliberately calm. A browser replay exposes the warning, the held repeat, and every captured decision without an AWS login. A review workbench lets someone who knows the integration confirm, dismiss or leave an uncertain match pending. Case-specific files are accepted only after operator import; the public example cannot mutate the live queue.

## How I built it

The collector and matcher are deterministic Python. Strands Agents handles the judgement and note-writing on AWS Bedrock AgentCore, using Bedrock in `us-east-1`.

Strands interventions sit around the only delivery tool. They stamp dates the system already knows, deny irrelevant or repeated notes, and hold low-confidence mappings. A refused tool call is never counted as a delivered note. The deployed bundle is generated from the same canonical controls as the local agent, with a check that fails on drift.

A scheduled GitHub Actions job fetches the contracts, authenticates to AgentCore using a repository-scoped OIDC role, saves approved notes and the delivery ledger, and regenerates GitHub Pages. Missing credentials fail loudly. No AWS key is stored in the repository.

## What I can demonstrate

Across a 150-day span, the reconstructed history contains 56 individual changes in 23 supplier-day records across 22 calendar dates. Nine changes have a potentially breaking shape. Three records match a possible risk to the illustrative shop's routines.

The actual deployed replay renders two notes. The second payroll warning is held because the same routine was flagged five days earlier. Only those two note-producing cases invoke the model.

**That ratio is the product.** It measures how much demands the owner's attention in this retrospective example. It is not measured accuracy, proof of a prevented outage, or customer savings. Maya and Priya are fictional, and the profile was refined after looking at this history.

## Challenges and what I learned

My first profile returned zero. It was too thin to cover the shop I claimed to be protecting. Comparing mappings against supplier publications later exposed three calls that had never existed, despite the rest of the tests passing.

Then the model put a wrong date beneath the word FACT. It had subtracted a relative age from a date already supplied. I moved known facts out of the model's authority and made contradictory dates a refused tool call.

The final audit exposed another gap: the local controls had advanced beyond the deployed bundle, and the daily collector was not invoking the cloud agent. I fixed both and replayed the full history against the actual runtime. A deployment and a passing local suite are not, by themselves, evidence that the intended product path runs.

## What is next

Validate the mappings against an actual shop integration, add private reviewer authentication, and evaluate missed changes on fresh history. Published contracts cannot prove deployed behaviour, and the detector covers a limited set of structural changes. I have not conducted customer testing.

## Disclosure

I previously built a CI job comparing a generated artifact against a live vendor API. No code from it is included here. Its lessons informed the separation between a vendor change and a failed monitoring job. This project is MIT licensed.
