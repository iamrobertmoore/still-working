"""The note Maya gets, and the only format she ever sees.

Rules this format exists to enforce:

* The first line is a consequence, not a change. "Your orders stopped going into the
  accounts", never "param_removed on GET /v2/orders".
* No vendor API vocabulary above the line. No endpoint, no parameter, no version.
* The technical detail is present, complete, and clearly addressed to someone else. Maya
  forwards it. She does not read it. Putting it in the note rather than leaving it out is
  what makes the note actionable by a person who cannot fix the problem herself.
* Uncertainty is stated in her language too. If the agent is not sure her Monday figure
  comes from the thing that changed, it says so rather than sounding confident.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Maya's note has a house style. A model asked nicely to follow one will mostly follow it,
# which is not the same as following it. Style is a property of the format, so it is
# enforced where the format is produced rather than requested in a prompt and hoped for.
_DASHES = re.compile(r"\s*[\u2014\u2013]\s*")


def house_style(text: str) -> str:
    """Normalise typography. Currently: no em or en dashes anywhere in Maya's note."""
    return _DASHES.sub(", ", text or "")


@dataclass
class MayaNote:
    still_working: bool
    routine: str
    headline: str
    what_happened: str
    what_it_costs: str
    how_late_normally: str
    what_to_do: str
    forward_to: str
    uncertain: bool = False
    uncertainty: str = ""
    for_the_developer: list[str] = field(default_factory=list)

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
            f"What it costs you: {self.what_it_costs}",
            f"How late you would normally find out: {self.how_late_normally}",
        ]
        if self.uncertain:
            lines += ["", f"I am not certain about this. {self.uncertainty}"]
        lines += ["", f"What to do: {self.what_to_do}", "", f"--- forward this part to {self.forward_to} ---"]
        lines += [f"  {d}" for d in self.for_the_developer]
        return "\n".join(lines)
