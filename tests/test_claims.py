"""The claims the documents make, checked against the code that has to back them.

A hackathon submission is read by people who will spot a contradiction between the README
and the source in about ten seconds, and it is the cheapest possible way to lose their
trust. Every claim here was wrong at some point today.
"""
from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = ("README.md", "ARCHITECTURE.md", "DEVPOST.md")


def read(name: str) -> str:
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def deployed_model_id():
    src = read(os.path.join("runtime", "app", "StillWorking", "model", "load.py"))
    found = re.findall(r'"((?:global|us|eu|apac)\.anthropic\.[a-z0-9.\-:]+)"', src)
    assert found, "no model id in the deployed bundle's loader"
    return found[0]


def test_the_local_agent_defaults_to_the_model_the_bundle_deploys():
    """They were different models, in different regions, for a fortnight."""
    from agent.still_working import BEDROCK_MODEL
    src = read(os.path.join("runtime", "app", "StillWorking", "model", "load.py"))
    assert BEDROCK_MODEL in src, (BEDROCK_MODEL, "not the id the bundle uses")


@pytest.mark.parametrize("doc", DOCS)
def test_no_document_names_a_model_the_code_does_not_use(doc, deployed_model_id):
    text = read(doc)
    for claimed in re.findall(r"claude-sonnet-[0-9a-z.\-]+", text):
        assert claimed in deployed_model_id, (doc, claimed, deployed_model_id)


@pytest.mark.parametrize("doc", DOCS)
def test_no_document_claims_a_region_the_code_does_not_use(doc):
    from agent.still_working import AWS_REGION
    text = read(doc)
    for claimed in set(re.findall(r"\b(?:us|eu|ap)-[a-z]+-\d\b", text)):
        assert claimed == AWS_REGION, (doc, claimed, AWS_REGION)


def test_the_diagram_names_the_same_region_as_the_code():
    from agent.still_working import AWS_REGION
    svg = read(os.path.join("docs", "architecture.svg"))
    for claimed in set(re.findall(r"\b(?:us|eu|ap)-[a-z]+-\d\b", svg)):
        assert claimed == AWS_REGION, (claimed, AWS_REGION)


@pytest.mark.parametrize("doc", DOCS + (os.path.join("docs", "architecture.svg"),))
def test_no_document_uses_a_long_dash(doc):
    text = read(doc)
    assert "—" not in text and "–" not in text, doc


@pytest.mark.parametrize("doc", DOCS)
def test_no_document_speaks_for_a_team(doc):
    """One person built this. "We" would be a small lie in a document about honesty."""
    text = read(doc)
    for line in text.splitlines():
        if line.strip().startswith(("|", "    ", "\t", "```")):
            continue
        assert not re.search(r"\bwe\b|\bour\b", line, re.I), (doc, line.strip()[:70])


@pytest.mark.parametrize("doc", DOCS)
def test_every_document_names_maya_in_its_first_page(doc):
    assert "Maya" in read(doc)[:1500], doc


def test_the_test_count_in_the_documents_is_not_an_overstatement():
    """Better to say fewer than there are than one more."""
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    actual = int(re.search(r"(\d+) tests? collected", out).group(1))
    for doc in DOCS:
        for claimed in re.findall(r"(\d+)\s+(?:pytest\s+)?(?:tests|cases)", read(doc)):
            assert int(claimed) <= actual, (doc, claimed, actual)


def test_the_architecture_diagram_is_valid_and_referenced():
    import xml.etree.ElementTree as ET
    path = os.path.join(ROOT, "docs", "architecture.svg")
    ET.parse(path)
    assert "docs/architecture.svg" in read("README.md")
    assert "docs/architecture.svg" in read("ARCHITECTURE.md")


def test_the_readme_links_that_point_into_the_repository_all_exist():
    text = read("README.md") + read("ARCHITECTURE.md") + read("DEVPOST.md")
    for target in set(re.findall(r"\]\((?!https?:|#)([^)#]+)", text)):
        assert os.path.exists(os.path.join(ROOT, os.path.normpath(target))), target


def test_the_deployed_bundle_and_the_local_agent_agree_on_the_house_style():
    """Two copies, on purpose. A copy that has drifted is worse than no copy."""
    import importlib.util
    import sys
    bundle = os.path.join(ROOT, "runtime", "app", "StillWorking")
    if bundle not in sys.path:
        sys.path.insert(0, bundle)
    pytest.importorskip("bedrock_agentcore")
    spec = importlib.util.spec_from_file_location("deployed_claims",
                                                  os.path.join(bundle, "main.py"))
    deployed = importlib.util.module_from_spec(spec)
    # Registered before execution because the module defines a dataclass, and dataclasses
    # resolve their own annotations through sys.modules at class creation time.
    sys.modules[spec.name] = deployed
    spec.loader.exec_module(deployed)
    from agent.notes import dates_mentioned, house_style
    for text in ["a — b", "a–b", "a - b", "plain", ""]:
        assert deployed.house_style(text) == house_style(text), text
    for text in ["on 2026-05-24", "on 14 July", "trading in December", "July 14th", ""]:
        assert deployed.dates_mentioned(text) == dates_mentioned(text), text


# ---------------------------------------------------------------- prose that drifts

@pytest.mark.parametrize("doc", DOCS + (os.path.join("docs", "architecture.svg"),))
def test_no_document_reports_a_different_number_of_interruptions(doc):
    """ARCHITECTURE said three while everything else said twice."""
    from tools.impact import figures
    n = figures()["interruptions"]
    words = {2: ("twice", "two interruptions"), 3: ("three times", "three interruptions")}
    wrong = [w for count, forms in words.items() if count != n for w in forms]
    text = read(doc).lower()
    for phrase in wrong:
        assert f"interrupted {phrase}" not in text, (doc, phrase)
        assert f"{phrase} in five months" not in text, (doc, phrase)


@pytest.mark.parametrize("doc", DOCS)
def test_no_document_understates_how_many_kinds_of_change_are_detected(doc):
    import re as _re
    src = read(os.path.join("tools", "snapshot.py"))
    kinds = set(_re.findall(r'"kind": "([a-z_]+)"', src))
    words = {6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
    text = read(doc).lower()
    for count, word in words.items():
        if count < len(kinds):
            assert f"{word} kinds are detected" not in text, (doc, word, len(kinds))
            assert f"{word} kinds of change are detected" not in text, (doc, word)


def test_the_documents_say_how_many_suppliers_publish_a_moving_version():
    """Two, said the README. Three do."""
    import json as _json
    moving = set()
    with open(os.path.join(ROOT, "contracts", "changes.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            row = _json.loads(line)
            if any(c["kind"] == "version_string_changed" for c in row["changes"]):
                moving.add(row["vendor"])
    words = {1: "One", 2: "Two", 3: "Three", 4: "All four"}
    text = read("README.md")
    for count, word in words.items():
        if count != len(moving):
            assert f"{word} of those stamp a version that moves" not in text, (word, moving)


def test_the_readme_note_matches_the_actual_cloud_recording():
    """The public example must preserve the captured response, including its wording."""
    import json
    data = json.loads(read("docs/replay/recordings.json"))
    note = next(c["result"]["note"] for c in data["cases"]
                if c["record"]["date"] == "2026-07-14" and c["record"]["vendor"] == "square")
    blocks = re.findall(r"```\n(.*?)```", read("README.md"), re.S)
    assert note.strip() in [b.strip() for b in blocks]
