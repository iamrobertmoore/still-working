#!/usr/bin/env python3
"""Configure keyless GitHub-to-AgentCore delivery for this repository only.

Print the exact policies by default. --apply creates a dedicated, invocation-only role
and publishes its ARN as a non-secret repository variable. Existing unrelated roles
and policies are never edited.
"""
from __future__ import annotations

import argparse
import json
import subprocess


def gh_json(*args):
    return json.loads(subprocess.check_output(["gh", "api", *args], text=True))


def main():
    import boto3
    from botocore.exceptions import ClientError
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--runtime-arn", required=True)
    ap.add_argument("--repo", default="iamrobertmoore/still-working")
    args = ap.parse_args()
    account = boto3.client("sts").get_caller_identity()["Account"]
    if args.runtime_arn.split(":")[4] != account:
        raise ValueError("Runtime must belong to the signed-in account")
    oidc = gh_json(f"repos/{args.repo}/actions/oidc/customization/sub")
    if not oidc.get("use_default"):
        raise ValueError("Repository uses a custom OIDC subject. Review it before granting access.")
    prefix = oidc.get("sub_claim_prefix", f"repo:{args.repo}")
    provider = f"arn:aws:iam::{account}:oidc-provider/token.actions.githubusercontent.com"
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
             "Principal": {"Federated": provider}, "Action": "sts:AssumeRoleWithWebIdentity",
             "Condition": {"StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                            "token.actions.githubusercontent.com:sub": prefix + ":ref:refs/heads/main"}}}]}
    policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
              "Action": ["bedrock-agentcore:InvokeAgentRuntime"], "Resource": [args.runtime_arn, args.runtime_arn + "/runtime-endpoint/DEFAULT"]}]}
    name = "StillWorkingGitHubDelivery"
    print(json.dumps({"role": name, "trust": trust, "permissions": policy}, indent=2))
    if not args.apply:
        return
    iam = boto3.client("iam")
    providers = iam.list_open_id_connect_providers()["OpenIDConnectProviderList"]
    if provider not in [p["Arn"] for p in providers]:
        iam.create_open_id_connect_provider(Url="https://token.actions.githubusercontent.com",
                                             ClientIDList=["sts.amazonaws.com"])
    try:
        role = iam.get_role(RoleName=name)["Role"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        role = iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust),
                               Description="Invoke Still Working from its main-branch scheduled job only",
                               MaxSessionDuration=3600)["Role"]
    else:
        if role["AssumeRolePolicyDocument"] != trust:
            raise RuntimeError("Existing role has a different trust policy. Refusing to replace it.")
    iam.put_role_policy(RoleName=name, PolicyName="InvokeStillWorkingOnly", PolicyDocument=json.dumps(policy))
    for key, value in {"STILL_WORKING_ROLE_ARN": role["Arn"],
                       "STILL_WORKING_RUNTIME_ARN": args.runtime_arn}.items():
        subprocess.run(["gh", "variable", "set", key, "--repo", args.repo, "--body", value], check=True)
    print("Configured keyless invocation for this repository's main branch only.")


if __name__ == "__main__":
    main()
