"""The headline numbers, asserted.

Every figure in the README, on Maya's screen and in the video comes from here. A claim
nobody re-derives is a claim that drifts, and this project is mostly an argument about a
ratio, so the ratio is a test.

These are computed from contracts/changes.jsonl, which the scheduled job appends to every
morning. The numbers will move as the suppliers move. When they do, this file fails, and
the README gets corrected rather than quietly becoming untrue.
"""
from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from tools.impact import BREAKING_KINDS, assess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUIET_DAYS = 5


@pytest.fixture(scope="module")
def rows():
    path = os.path.join(ROOT, "contracts", "changes.jsonl")
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def reaching(business, rows):
    return [r for r in rows if assess(business, r)["reaches_maya"]]


def test_the_history_spans_at_least_five_months(rows):
    dates = sorted(r["date"] for r in rows)
    span = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days
    assert span >= 145, span


def test_the_history_covers_all_four_suppliers(rows):
    assert {r["vendor"] for r in rows} == {"stripe", "square", "xero", "shipengine"}


def test_the_suppliers_changed_things_on_many_separate_days(rows):
    assert len({r["date"] for r in rows}) >= 20


def test_most_changes_are_additive(rows):
    total = sum(r["total_count"] for r in rows)
    breaking = sum(r["breaking_count"] for r in rows)
    assert breaking < total / 4, (breaking, total)


def test_every_breaking_change_is_one_of_the_three_kinds(rows):
    for row in rows:
        for change in row["changes"]:
            if change["breaking"]:
                assert change["kind"] in BREAKING_KINDS, change


def test_only_a_handful_of_days_reach_maya_at_all(business, rows, reaching):
    assert 0 < len(reaching) <= len(rows) / 3


def test_the_three_days_that_reach_her_are_the_ones_i_claim(reaching):
    assert [(r["date"], r["vendor"]) for r in reaching] == [
        ("2026-04-24", "xero"), ("2026-04-29", "xero"), ("2026-07-14", "square")]


def test_the_april_pair_is_the_same_routine_twice(business, reaching):
    april = [r for r in reaching if r["date"].startswith("2026-04")]
    names = [{x["routine_id"] for x in assess(business, r)["routines_touched"]
              if x["has_breaking_change"]} for r in april]
    assert names[0] == names[1] == {"paying-the-team"}


def test_the_second_april_day_is_inside_the_quiet_window(reaching):
    first, second = (dt.date.fromisoformat(r["date"])
                     for r in reaching if r["date"].startswith("2026-04"))
    assert (second - first).days <= QUIET_DAYS


def interruptions(business, reaching) -> int:
    """Days she is actually interrupted, after the repeat rule in agent/memory.py."""
    told: list[tuple[dt.date, str]] = []
    count = 0
    for row in reaching:
        when = dt.date.fromisoformat(row["date"])
        names = {x["routine_id"] for x in assess(business, row)["routines_touched"]
                 if x["has_breaking_change"]}
        if any(n in names and 0 <= (when - d).days <= QUIET_DAYS for d, n in told):
            continue
        count += 1
        told += [(when, n) for n in names]
    return count


def test_after_the_repeat_rule_she_is_interrupted_twice_in_five_months(business, reaching):
    assert interruptions(business, reaching) == 2


def test_the_repeat_rule_removes_exactly_one_of_the_three(business, reaching):
    assert len(reaching) - interruptions(business, reaching) == 1


def test_the_signal_ratio_is_under_four_percent(business, rows, reaching):
    """The headline claim, computed rather than asserted from notes."""
    total = sum(r["total_count"] for r in rows)
    ratio = interruptions(business, reaching) / total
    assert ratio < 0.04, f"{ratio:.1%}"


def test_set_membership_alone_would_have_interrupted_her_more_often(business, rows, reaching):
    """Without the repeat rule the number is higher. That is what the rule is for."""
    assert len(reaching) > interruptions(business, reaching)


def test_every_day_that_reaches_her_names_a_routine_in_her_own_words(business, reaching):
    for row in reaching:
        touched = [x for x in assess(business, row)["routines_touched"]
                   if x["has_breaking_change"]]
        assert touched
        for entry in touched:
            assert entry["what_maya_calls_it"]
            assert "/" not in entry["what_maya_calls_it"], "that is a call name, not her words"


def test_the_quiet_days_are_genuinely_quiet(business, rows, reaching):
    """On every recorded day that did not reach her, the agent would say two words."""
    quiet = [r for r in rows if r not in reaching]
    assert len(quiet) > 15
    for row in quiet:
        assert assess(business, row)["reaches_maya"] is False


# ---------------------------------------------------------------- the README block

def test_the_readme_measurement_matches_the_record():
    """The README's numbers are generated, so they cannot say something the data does not.

    The block lives between markers and the scheduled job rewrites it on every run, the
    same way it rewrites Maya's screen. This asserts the file on disk is current.
    """
    from tools.impact import README_END, README_START, readme_block
    with open(os.path.join(ROOT, "README.md"), "r", encoding="utf-8") as fh:
        text = fh.read()
    assert README_START in text and README_END in text
    on_disk = text[text.index(README_START):text.index(README_END) + len(README_END)]
    assert on_disk == readme_block(), (
        "the README measurement is stale. Run `python tools/impact.py --readme`.")


def test_the_generated_block_never_contains_a_long_dash():
    from tools.impact import readme_block
    block = readme_block()
    assert "—" not in block and "–" not in block


def test_the_generated_block_names_each_routine_in_her_own_words():
    from tools.impact import figures
    for _, _, names, _, _ in figures()["rows"]:
        assert names and "/" not in names


def test_the_figures_agree_with_the_interruption_count(business, reaching):
    from tools.impact import figures
    assert figures()["interruptions"] == interruptions(business, reaching)


def test_the_figures_agree_with_the_reaching_count(reaching):
    from tools.impact import figures
    assert figures()["reaching"] == len(reaching)


def test_the_held_row_is_the_one_inside_the_quiet_window():
    from tools.impact import figures
    held = [r for r in figures()["rows"] if r[3] == "held"]
    assert len(held) == 1
    assert held[0][0] == "2026-04-29"
    assert held[0][4] == 5


# ---------------------------------------------------------------- the generated blocks

def test_the_readme_supplier_table_matches_the_snapshots_on_disk():
    """Hand-typed until 11 September, by which point three of its cells were wrong."""
    from tools.impact import VENDORS_END, VENDORS_START, vendors_block
    text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert VENDORS_START in text and VENDORS_END in text
    on_disk = text[text.index(VENDORS_START):text.index(VENDORS_END) + len(VENDORS_END)]
    assert on_disk == vendors_block(), (
        "the README supplier table is stale. Run `python tools/impact.py --readme`.")


def test_the_supplier_table_reports_every_supplier_being_watched(business):
    from tools.impact import vendors_block
    block = vendors_block()
    for vendor in ("Stripe", "Square", "Xero", "ShipEngine"):
        assert vendor in block, vendor


def test_the_record_is_read_in_date_order_however_it_is_stored(business, rows, tmp_path):
    """The log is append only, so a backfill after a daily run puts old rows last.

    Unsorted, the repeat rule saw the second Xero deletion before the first and reported
    three interruptions instead of two.
    """
    import json as _json
    import shutil
    from tools import impact as impact_module
    staging = tmp_path / "repo"
    shutil.copytree(os.path.join(ROOT, "contracts"), staging / "contracts")
    (staging / "contracts" / "changes.jsonl").write_text(
        "\n".join(_json.dumps(r) for r in reversed(rows)) + "\n")
    real_root = impact_module.ROOT
    try:
        impact_module.ROOT = str(staging)
        got = impact_module.figures(business)
    finally:
        impact_module.ROOT = real_root
    assert got["interruptions"] == 2, got["interruptions"]
    assert [r[3] for r in got["rows"]] == ["sent", "held", "sent"], got["rows"]


def test_the_held_row_reports_days_since_she_was_told_not_since_the_last_event():
    """With a third break of the same routine in the window the two answers differ."""
    import datetime as _dt
    from tools.impact import QUIET_DAYS
    told = [(_dt.date(2026, 4, 24), "paying-the-team")]
    # 26 April is held. 28 April is also held, and the gap she cares about is to the 24th.
    for day, expected in ((26, 2), (28, 4)):
        when = _dt.date(2026, 4, day)
        earlier = [d for d, n in told if n == "paying-the-team"
                   and 0 <= (when - d).days <= QUIET_DAYS]
        assert (when - max(earlier)).days == expected, day
