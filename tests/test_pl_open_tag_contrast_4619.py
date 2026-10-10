"""#4619 — the /story/panel/ ledger's undecided tag must not set --ink-faint text on an --ink-faint wash
(axe color-contrast failed on the live sweep)."""

import re
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "site" / "assets" / "css" / "story.css"


def test_pl_open_tag_text_is_not_ink_faint():
    rules = re.findall(r"\.pl-open \.pl-tag\s*\{([^}]*)\}", CSS.read_text())
    assert rules, ".pl-open .pl-tag rule missing"
    for body in rules:
        m = re.search(r"(?<![-\w])color:\s*([^;]+);", body)
        assert m, "no text colour declared"
        assert "ink-faint" not in m.group(1), f"low-contrast text colour on tinted tag: {m.group(1)}"
