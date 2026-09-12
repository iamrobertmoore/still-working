"""The note Maya gets, and the only format she ever sees.

Rules this format exists to enforce:

* The first line is a consequence, not a change. "Your orders stopped going into the
  accounts", never "endpoint_removed on GET /v2/orders/{order_id}".
* No vendor API vocabulary above the line. No endpoint, no parameter, no version.
* The technical detail is present, complete, and clearly addressed to someone else. Maya
  forwards it. She does not read it. Putting it in the note rather than leaving it out is
  what makes the note actionable by a person who cannot fix the problem herself.
* Uncertainty is stated in her language too. If the agent is not sure her Monday figure
  comes from the thing that changed, it says so rather than sounding confident.
* The date is not the model's to write. It is stamped in from the supplier's own record,
  and a note that asserts any other date is refused rather than rendered. See
  `dates_mentioned` and `wrong_dates_in` below, and the note in `agent/still_working.py`
  about the morning a model subtracted 51 days from 14 July, got 24 May, and filed it
  under the word FACT.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Maya's note has a house style. A model asked nicely to follow one will mostly follow it,
# which is not the same as following it. Style is a property of the format, so it is
# enforced where the format is produced rather than requested in a prompt and hoped for.
_DASHES = re.compile(r"\s*[\u2014\u2013]\s*")

MONTHS = ("january february march april may june july august september october november "
          "december").split()
# Month names are matched capitalised only, on purpose. "May" is a month and "may" is a
# modal verb, and "it may 3 times fail" is not a date. English prose capitalises months,
# so requiring it costs nothing real and removes a whole class of false positive.
_MONTH_RE = "|".join(m.capitalize() for m in MONTHS) + "|" + \
            "|".join(m[:3].capitalize() for m in MONTHS)

# The ISO form is bounded so that a date which is part of a longer token is not a date.
# Stripe's contract version is `2026-08-26.dahlia` and it belongs in the note; a path like
# `GET /v1/reports/2026-08-26` does too. Neither is a claim about when something happened,
# and refusing a note for quoting one would block a real warning.
_DATE_IN_TEXT = re.compile(
    r"(?<![\w/-])(?<!\.\w)(?<!\.\w\w)(\d{4}-\d{2}-\d{2})(?![\w/-])(?!\.\w)"
    r"|\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTH_RE + r")\b"
    r"|\b(" + _MONTH_RE + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b")


def _month(name: str) -> int:
    return next(i for i, m in enumerate(MONTHS, 1) if m.startswith(name.lower()[:3]))


def dates_mentioned(text: str) -> set[tuple[int, int]]:
    """Every (month, day) a piece of text actually asserts.

    A bare month name is not a date. "In December it is worse" is a season, not a claim
    about when something happened, so it must not trip the check. Maya's own profile says
    "every hour of downtime is a day of trading in December", and that sentence ends up in
    her notes.

    Neither is a version string, a path containing a date, or a lowercase "may".

    What this deliberately still catches is a note that names a second real date. "This is
    the second time since 24 April" is a true sentence the model is not allowed to write,
    because the system cannot tell it apart from the one that started all this, which was
    a date the model had calculated itself and got wrong. The refusal says so and asks for
    relative words instead, and the model writes it again without the date.
    """
    found: set[tuple[int, int]] = set()
    for iso, day_first, month_after, month_first, day_after in _DATE_IN_TEXT.findall(text or ""):
        if iso:
            _, m, d = iso.split("-")
            found.add((int(m), int(d)))
        elif day_first:
            found.add((_month(month_after), int(day_first)))
        elif month_first:
            found.add((_month(month_first), int(day_after)))
    return found


def in_words(iso: str | None) -> str:
    """The supplier's date, as Maya would read it."""
    if not iso:
        return "an unknown date"
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {MONTHS[m - 1].capitalize()} {y}"
    except (ValueError, IndexError):
        return iso


def wrong_dates_in(text: str, allowed_iso: str | None) -> set[tuple[int, int]]:
    """Dates the note asserts that are not the day the supplier made the change.

    With no allowed date there is nothing to check against, and an unchecked note is
    better than a note refused for failing a check that could not run.
    """
    if not allowed_iso:
        return set()
    try:
        _, m, d = (int(x) for x in allowed_iso.split("-"))
    except ValueError:
        return set()
    return dates_mentioned(text) - {(m, d)}


def house_style(text: str) -> str:
    """Normalise typography. Currently: no em or en dashes anywhere in Maya's note."""
    return _DASHES.sub(", ", text or "")


@dataclass
class MayaNote:
    still_working: bool
    headline: str
    what_happened: str
    what_it_costs: str
    how_late_normally: str
    what_to_do: str
    forward_to: str
    uncertain: bool = False
    uncertainty: str = ""
    for_the_developer: list[str] = field(default_factory=list)
    # Stamped in by the system, never written by the model. See StampTheFacts.
    change_date: str = ""
    days_ago: int | None = None

    def when(self) -> str:
        """The date, from the supplier's record, in Maya's words.

        This line exists so the model never has to produce a date at all. It was given
        one and a number of days once, did the subtraction itself, got it wrong, and
        wrote the result down under the word FACT.
        """
        words = in_words(self.change_date)
        if self.days_ago is None:
            return words
        if self.days_ago == 0:
            return f"today, {words}"
        if self.days_ago == 1:
            return f"yesterday, {words}"
        if self.days_ago < 14:
            return f"{self.days_ago} days ago, on {words}"
        if self.days_ago < 60:
            return f"about {self.days_ago // 7} weeks ago, on {words}"
        return f"about {self.days_ago // 30} months ago, on {words}"

    def render(self) -> str:
        if self.still_working:
            return "Still working.\nNothing that matters to you changed."

        out = self._render_raw()
        cleaned = house_style(out)
        assert "\u2014" not in cleaned and "\u2013" not in cleaned, "house style not applied"
        return cleaned

    def _render_raw(self) -> str:
        lines = [
            self.headline,
            "",
            self.what_happened,
            "",
        ]
        if self.change_date:
            lines.append(f"When it happened: {self.when()}")
        lines += [
            f"What it costs you: {self.what_it_costs}",
            f"How late you would normally find out: {self.how_late_normally}",
        ]
        if self.uncertain:
            lines += ["", f"I am not certain about this. {self.uncertainty}"]
        lines += ["", f"What to do: {self.what_to_do}", "", f"--- forward this part to {self.forward_to} ---"]
        lines += [f"  {d}" for d in self.for_the_developer]
        return "\n".join(lines)
