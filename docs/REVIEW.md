# A review before an interruption

Maya is illustrative. This review flow is for the developer who can establish whether the integration actually uses a supplier call.

[Try the recorded example](https://iamrobertmoore.github.io/still-working/review/) or [open the published pending queue](https://iamrobertmoore.github.io/still-working/review/live.html).

The example uses a real historical Square publication. Its mapping confidence is deliberately lowered to exercise the review gate. The reviewer choices are simulated inputs. The displayed branches are actual captured AgentCore responses, not live inference triggered by the browser and not customer validation.

## What the reviewer can do

- Confirm that this routine uses the affected call. The agent may assess and render a note; date, repeat and delivery controls still apply.
- Dismiss the case because this change does not affect the routine. No model is invoked and no delivery is invented.
- Remain unsure. The case stays pending. No approval file is produced.

A reviewer supplies a name and the reason for the decision. That name is not identity-verified. The page downloads a JSON file; it cannot mutate the shared queue or invoke AWS.

## Apply a real review

The published queue is regenerated from the daily caller's pending state. A project operator reviews the downloaded file and imports it from the repository root:

```bash
python tools/review.py --apply /path/to/still-working-review.json
```

The importer checks the case against the current pending queue, validates every decision before writing, and refuses example files, stale or unknown cases, duplicate entries and conflicting decisions. It writes `contracts/reviews.json`. Commit that file so the daily workflow can read it on its next run. A manual workflow run can process it sooner.

The authenticated caller attaches the accepted reviews to its next assessment of the pending record. AgentCore applies the decision before invoking a model. A confirmed low-confidence case can pass the delivery gate; a dismissed one does not create a note. A failed or refused note stays pending. The daily page and queue regenerate after delivery.

Each case identifier covers the supplier, date and complete assessed routine. Changing a dependency, confidence or business consequence invalidates a previous approval. A review of one case does not silently modify the entire shop profile or approve a future supplier change.

This is an operator-mediated review flow for a public demonstration. It is not a hosted, authenticated team inbox. Use illustrative details in this repository; a real customer product would need private storage and reviewer authentication.

## Inspect or reproduce the cloud evidence

[The saved review proof](review/proof.json) contains the initial hold, approval, dismissal and subsequent repeat. The original 23-record historical replay is separate and unchanged.

With AWS invocation access and `STILL_WORKING_RUNTIME_ARN` set, from the repository root:

```bash
python tools/record_review.py
python tools/render_review.py
```

This runs four real runtime invocations, including one agent run using a model. The review choices are still declared demonstration inputs. The tool saves evidence only after all four expected behaviours pass.
