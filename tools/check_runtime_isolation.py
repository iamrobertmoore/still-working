#!/usr/bin/env python3
"""Assert the deployed bundle does not reach back into this repository.

runtime/ is deployed on its own. Anything it imports from the repository root will work
on a laptop, pass every local test, and fail the moment it is running in AgentCore with
only its own directory present.

This exists because I did exactly that: wrote the entrypoint self-contained, then wrote
its test with `sys.path.insert(0, "/root/afh/repo")` and imported the model double from
the repository. It passed in the sandbox it was written in and nowhere else.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(ROOT, "runtime")

# Packages that live in this repository and must never be imported by the bundle.
REPO_PACKAGES = {"agent", "tools", "business", "contracts"}

BAD_ABS = re.compile(r"""['"](/(?:root|home|Users)/[^'"]*)['"]""")
IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)


def main() -> int:
    if not os.path.isdir(RUNTIME):
        print("runtime/ not present, nothing to check")
        return 0

    problems: list[str] = []
    checked = 0

    for base, dirs, files in os.walk(RUNTIME):
        dirs[:] = [d for d in dirs
                   if d not in {".venv", "node_modules", "__pycache__", ".git", "cdk.out"}]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, ROOT)
            checked += 1
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()

            for match in BAD_ABS.finditer(src):
                problems.append(f"{rel}: absolute path {match.group(1)!r}")

            for frm, imp in IMPORT.findall(src):
                top = (frm or imp).split(".")[0]
                if top in REPO_PACKAGES:
                    problems.append(f"{rel}: imports {top!r}, which lives in the repository "
                                    "root and will not be present in the deployed bundle")

    if problems:
        print(f"runtime isolation FAILED, {len(problems)} problem(s) in {checked} files:",
              file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    print(f"runtime isolation OK: {checked} files, no repository imports, no absolute paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
