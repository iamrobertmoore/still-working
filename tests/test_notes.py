"""The note Maya gets, and the house style enforced where the note is produced.

A model asked nicely to avoid em dashes will mostly avoid them, which is not the same as
avoiding them. Style is a property of the format, so it is applied by the formatter.
"""
from __future__ import annotations

import pytest

from agent.notes import MayaNote, house_style


def note(**kw):
    base = dict(still_working=False,
                headline="Your orders stopped going into the accounts on Tuesday.",
                what_happened="The till software removed the way it hands over an order.",
                what_it_costs="Ines reconciles from this.",
                how_late_normally="three weeks", what_to_do="Forward the part below.",
                forward_to="Priya", for_the_developer=["square: GET /v2/orders/{order_id} removed"])
    base.update(kw)
    return MayaNote(**base)


# ---------------------------------------------------------------- typography

@pytest.mark.parametrize("written,expected", [
    ("a — b", "a, b"),
    ("a—b", "a, b"),
    ("a – b", "a, b"),
    ("a–b", "a, b"),
    ("a  —  b", "a, b"),
    ("no dashes here", "no dashes here"),
    ("a - b", "a - b"),
])
def test_house_style_replaces_long_dashes_and_leaves_hyphens_alone(written, expected):
    assert house_style(written) == expected


def test_house_style_survives_an_empty_string():
    assert house_style("") == ""
    assert house_style(None) == ""


@pytest.mark.parametrize("field", ["headline", "what_happened", "what_it_costs",
                                   "how_late_normally", "what_to_do"])
def test_a_dash_in_any_field_is_removed_from_the_rendered_note(field):
    rendered = note(**{field: "before — after"}).render()
    assert "—" not in rendered
    assert "before, after" in rendered


def test_a_dash_in_the_developer_section_is_removed_too():
    rendered = note(for_the_developer=["square — removed"]).render()
    assert "—" not in rendered


def test_a_dash_in_the_uncertainty_line_is_removed_too():
    rendered = note(uncertain=True, uncertainty="maybe – maybe not").render()
    assert "–" not in rendered


# ---------------------------------------------------------------- shape

def test_the_quiet_note_is_two_lines():
    rendered = MayaNote(still_working=True, headline="", what_happened="",
                        what_it_costs="", how_late_normally="", what_to_do="",
                        forward_to="").render()
    assert rendered.splitlines() == ["Still working.", "Nothing that matters to you changed."]


def test_the_first_line_is_the_headline_not_a_label():
    rendered = note().render()
    assert rendered.splitlines()[0].startswith("Your orders stopped")


def test_the_note_says_what_it_costs_her():
    assert "What it costs you:" in note().render()


def test_the_note_says_how_late_she_would_otherwise_have_found_out():
    assert "How late you would normally find out:" in note().render()


def test_the_note_names_the_person_who_fixes_things():
    assert "forward this part to Priya" in note().render()


def test_the_developer_detail_is_present_and_indented():
    rendered = note().render()
    assert "  square: GET /v2/orders/{order_id} removed" in rendered


def test_the_developer_section_comes_last():
    rendered = note().render()
    assert rendered.index("forward this part to") > rendered.index("What to do:")


def test_uncertainty_is_stated_above_the_line_in_her_language():
    rendered = note(uncertain=True, uncertainty="I am not sure the Monday figure uses this.").render()
    assert "I am not certain about this." in rendered
    assert rendered.index("I am not certain") < rendered.index("forward this part to")


def test_a_certain_note_does_not_mention_uncertainty():
    assert "I am not certain" not in note().render()


def test_a_note_with_no_developer_detail_still_renders():
    assert "forward this part to Priya" in note(for_the_developer=[]).render()


# ---------------------------------------------------------------- her vocabulary

@pytest.mark.parametrize("word", ["endpoint", "parameter", "API", "webhook", "OAuth", "JSON"])
def test_the_part_maya_reads_keeps_the_suppliers_vocabulary_out(word):
    """This one is honest about what it is.

    The formatter does not strip vendor vocabulary, and it should not: it cannot tell a
    useful sentence from a jargon one. Keeping it out is the system prompt's job and the
    profile's job, and what this asserts is that the note's own structure puts everything
    technical below the line. The fixture is deliberately the shape a real note takes.
    """
    rendered = note(for_the_developer=[f"square: {word} location_id removed"]).render()
    above, below = rendered.split("--- forward this part to")
    assert word.lower() not in above.lower(), "vendor vocabulary reached her half"
    assert word.lower() in below.lower(), "the fixture did not actually contain the word"


def test_the_part_priya_reads_is_allowed_the_suppliers_vocabulary():
    rendered = note(for_the_developer=["parameter location_id removed"]).render()
    below = rendered.split("--- forward this part to")[1]
    assert "parameter" in below
