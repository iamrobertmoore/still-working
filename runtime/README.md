# Still Working runtime

The deployed judgement layer accepts a deterministic assessment, not a general chat prompt. Maya is an illustrative shop owner. A note explains a potential consequence of a published change, not a confirmed production outage.

## Develop and deploy

From the repository root, with the Python dependencies installed:

```bash
python tools/sync_runtime.py
python tools/sync_runtime.py --check
python -m pytest tests/ -q
python runtime/app/StillWorking/test_entrypoint.py
cd runtime
agentcore deploy --dry-run --yes
agentcore deploy --yes
```

Use the existing project configuration to update the runtime in place. Do not rename resources or edit generated CDK files. Read [the runtime instructions](AGENTS.md) before changing resource configuration. AWS credentials and the AgentCore CLI are required for deployment.

## Invoke

From `runtime/`, using the installed AgentCore CLI:

```bash
agentcore invoke --prompt-file app/StillWorking/sample-impact.json
```

The sample is a historical assessment. Relative dates are anchored to its supplied `days_ago`; do not present it as today's live supplier change.

The runtime also accepts `{"impact": <assessment>}` directly. The authenticated caller supplies `delivery_history` and must persist the returned ledger with any rendered note. Unrelated changes and repeated routines build no model. Low confidence returns `held_for_a_person`. A refused note never becomes a delivery.

## Daily connection

The workflow invokes this runtime through GitHub OIDC. To inspect the exact role and policy before provisioning:

```bash
python tools/configure_delivery.py --runtime-arn "<your runtime ARN>"
```

Run that command from the repository root. Add `--apply` to provision the dedicated invocation-only role and set the two non-secret GitHub repository variables. The role trusts only the repository's main branch and grants invocation on the supplied runtime. It does not grant model, deployment or account administration permissions.

`tools/replay.py` captures real responses for every historical record. `tools/render_replay.py` publishes those saved responses without calling AWS. The optional local scripted agent, streaming and morning roundup examples are separate from the deployed daily path.

The `agent_runs` response counter counts Strands agent executions that use a model. It is not a count of individual Bedrock requests inside the tool loop. Earlier replay recordings called this field `model_invocations`; those original responses are preserved with an explicit counter definition.

Human reviews are accepted only through the authenticated caller, keyed to the exact assessed case. See [the review workflow](../docs/REVIEW.md). A review is supplied input, not proof of reviewer identity or customer validation.
