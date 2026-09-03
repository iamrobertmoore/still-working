#!/usr/bin/env python3
"""Find out which Bedrock model ids actually work, rather than guessing from a list.

`list-foundation-models` returns ids that cannot all be invoked directly. Some need a
cross-region inference profile prefix (eu., us.), some are listed but not enabled on the
account. The only way to know is to call each one and see.

Run this once, take the first id that says OK, and put it in agent/still_working.py.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Verified by running this script against eu-west-2 on 2 September 2026. The prefix rule
# is not uniform: the newer models refuse the bare id and need the eu. inference profile,
# and claude-3-7-sonnet is the other way round. You cannot work this out from the docs,
# and list-foundation-models returns all of them without distinction.
CANDIDATES = [
    "eu.anthropic.claude-sonnet-4-6",                 # verified working
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",    # verified working, and cheapest
    "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",   # verified working
    "anthropic.claude-3-7-sonnet-20250219-v1:0",      # verified working, bare id only
    "anthropic.claude-sonnet-4-6",                    # verified NOT working: on-demand throughput
    "anthropic.claude-haiku-4-5-20251001-v1:0",       # verified NOT working: on-demand throughput
    "eu.anthropic.claude-3-7-sonnet-20250219-v1:0",   # verified NOT working: invalid identifier
]


HINTS = {
    "MissingDependencyException": (
        "boto3 cannot use the credential provider in your AWS config. `aws login` writes a\n"
        "  provider that the bundled CLI understands and plain boto3 does not. Sidestep it:\n"
        "      eval \"$(aws configure export-credentials --format env)\"\n"
        "  then run this again. Temporary credentials, nothing stored, expires on its own."),
    "UnrecognizedClientException": (
        "Credentials resolved but the token is not valid for this account or region.\n"
        "  Re-run `aws login`, then export them as above."),
    "ExpiredTokenException": (
        "The temporary credentials have expired. Re-run `aws login` and re-export."),
    "still expired": (
        "The `aws login` session itself has expired, not just the exported copy.\n"
        "  Exported variables are a snapshot and never refresh. Stale ones in the shell\n"
        "  also shadow a fresh login, so unset them first:\n"
        "      unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \\\n"
        "            AWS_CREDENTIAL_EXPIRATION\n"
        "      aws login\n"
        "      eval \"$(aws configure export-credentials --format env)\""),
    "use case details": (
        "Account-level gate, nothing to do with the model id or your credentials.\n"
        "  NOTE: the Model access console page is RETIRED and does not offer this form.\n"
        "  Two working routes as of 2 September 2026:\n"
        "    console: Model catalog, pick an Anthropic model, open the playground\n"
        "             .../bedrock/home?region=eu-west-2#/model-catalog\n"
        "    api:     aws bedrock put-use-case-for-model-access --form-data fileb://form.json\n"
        "             then aws bedrock get-use-case-for-model-access to confirm\n"
        "             formData keys: companyName, companyWebsite, intendedUsers,\n"
        "             industryOption, otherIndustryOption, useCases\n"
        "  Submitted once per account. Access is granted immediately on success, but the\n"
        "  check is eventually consistent: on 2 September the same four ids answered\n"
        "  normally and then failed this way two minutes later with nothing changed."),
    "AccessDeniedException": (
        "Credentials are fine, the account is not entitled to this model.\n"
        "  Bedrock console, Model access, request the Anthropic models."),
    "ValidationException": (
        "The id is wrong for this region. Try the cross-region inference profile form,\n"
        "  which is the region prefix plus the id, for example eu.<id>."),
    "NoCredentialsError": (
        "No credentials at all. Run `aws login`, then\n"
        "      eval \"$(aws configure export-credentials --format env)\""),
}


def credential_lifetime() -> str:
    """How long the exported credentials have left.

    `aws configure export-credentials --format env` sets AWS_CREDENTIAL_EXPIRATION. The
    variables are a snapshot and never refresh, so knowing this up front is the difference
    between a clean re-login now and a confusing failure halfway through a run.
    """
    import datetime as dt
    raw = os.environ.get("AWS_CREDENTIAL_EXPIRATION")
    if not raw:
        return "expiry unknown (no AWS_CREDENTIAL_EXPIRATION set)"
    try:
        expires = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return f"expiry unparseable: {raw!r}"
    left = expires - dt.datetime.now(dt.timezone.utc)
    mins = int(left.total_seconds() // 60)
    if mins < 0:
        return f"EXPIRED {-mins} minutes ago, at {expires:%H:%M UTC}"
    if mins < 20:
        return f"expires in {mins} minutes, at {expires:%H:%M UTC}. Re-login before a long run"
    return f"expires in {mins // 60}h {mins % 60}m, at {expires:%H:%M UTC}"


def preflight(region: str) -> bool:
    """Check credentials resolve BEFORE blaming the model ids.

    The first version of this script reported eight identical model failures for what was
    a single credentials problem, and truncated the message that said so. Diagnose the
    layer underneath first, and never cut an error message short.
    """
    try:
        import boto3
        who = boto3.client("sts", region_name=region).get_caller_identity()
        print(f"credentials OK  account {who['Account']}  {who['Arn']}")
        print(f"                {credential_lifetime()}")
        if who["Arn"].endswith(":root"):
            print("                NOTE: this is the account root user. Works, but AWS")
            print("                advises against it for API calls, and it will matter")
            print("                more once AgentCore starts creating resources.")
        return True
    except Exception as exc:
        name = type(exc).__name__
        print(f"credentials FAILED  {name}")
        print(f"  {exc}")
        hint = next((h for k, h in HINTS.items() if k in name or k in str(exc)), None)
        if hint:
            print(f"\n  {hint}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="eu-west-2")
    ap.add_argument("--models", nargs="*", default=CANDIDATES)
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args()

    from strands import Agent
    from strands.models.bedrock import BedrockModel

    print(f"region {args.region}\n")
    if not args.skip_preflight and not preflight(args.region):
        print("\nStopping here. Fix the credentials first, or the model results below would")
        print("all say the same thing for a reason that has nothing to do with the models.")
        return 2
    print()
    working = []
    for model_id in args.models:
        started = time.time()
        try:
            agent = Agent(
                model=BedrockModel(model_id=model_id, region_name=args.region, max_tokens=64),
                system_prompt="Answer in exactly three words.",
                callback_handler=None,
            )
            reply = str(agent("Is the shop still working?")).strip().replace("\n", " ")
            print(f"  OK    {model_id}\n            {time.time()-started:.1f}s  {reply[:70]!r}")
            working.append(model_id)
        except Exception as exc:
            name = type(exc).__name__
            print(f"  FAIL  {model_id}")
            print(f"            {name}: {exc}")          # never truncate an error message
            hint = next((h for k, h in HINTS.items() if k in name or k in str(exc)), None)
            if hint:
                print(f"            hint: {hint}")
                if (name in ("MissingDependencyException", "NoCredentialsError",
                             "UnrecognizedClientException", "ExpiredTokenException")
                        or "use case details" in str(exc)):
                    print("\n  Every id will fail the same way until that is fixed. Stopping.")
                    return 2

    print()
    if working:
        print("Use this one:")
        print(f"    {working[0]}")
        print()
        print("Set it with:")
        print(f'    export STILL_WORKING_MODEL="{working[0]}"')
        return 0
    print("Nothing worked. The hint under each failure says why. If they all say the same")
    print("thing, it is one problem underneath rather than eight model problems.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
