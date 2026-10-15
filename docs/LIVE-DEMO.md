# Run the stock warning live

This demonstration executes the current matcher and deployed agent now. Its input is Square's recorded 14 July 2026 publication change and the illustrative shop profile. It starts with an empty, isolated delivery ledger. It does not collect a new supplier change, modify the daily page, or reuse a saved model response.

## Before you run it

Install the dependencies from the [README](../README.md) and deploy using [runtime/README.md](../runtime/README.md). Your AWS identity needs permission to invoke that runtime and its default endpoint. Set its ARN:

```bash
export STILL_WORKING_RUNTIME_ARN="<your AgentCore runtime ARN>"
```

If your credentials come from `aws login`, complete the browser sign-in first. Boto3 may need the CLI credentials exported into the current shell:

```bash
eval "$(aws configure export-credentials --format env)"
```

Keep credentials and sign-in screens out of any screenshot or recording. Run the model-free preflight:

```bash
python tools/cloud.py
```

Expected: `AgentCore reached: shared-v1, no model, no note.` This verifies the credentials of the caller running the command. In GitHub Actions that is the OIDC role; locally it is your AWS identity.

## The command

```bash
python tools/live_demo.py --output /tmp/still-working-live.json
```

The terminal shows the current UTC time, historical input label, and two fresh AWS calls:

1. **Stock warning:** one rendered note, one agent run, and the note's actual first line. Model wording and response time can vary.
2. **Same change, returned ledger:** repeat held, zero agent runs, no second note, unchanged ledger.

The command only reports verification after both responses satisfy those checks. A provider failure, refused note or incorrect ledger raises an error. It does not substitute a recorded response or retry secretly. Normal cloud charges apply.

The JSON file contains the exact inputs, results, timings, and hashes of the source history and profile. Each command starts a new isolated demo ledger; it is safe to repeat without changing the daily delivery state. The second invocation uses the ledger returned by the first within that run.

## Timing

Run it once first to see how long the cloud calls take. Allow roughly 30 seconds, but go by the measured time rather than assuming one. Browser results elsewhere on the site are captured responses and are labelled that way.

## If it fails

Expired access: sign in again and export credentials. Access denied: check the runtime and default endpoint permissions. A refused note or failed repeat check is a failure to investigate, not a successful run. The existing browser replay remains available, explicitly labelled as recorded evidence.
