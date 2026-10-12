"""#4834 - the deficit-sustainability count badge sits on --ember-wash at the --fs-h3 floor (19px, not
'large text'); plain --ember measured 4.43:1 there in the light theme. It must not go back to bare --ember."""

import re
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "site" / "assets" / "css" / "tokens.css"


def test_dsx_count_is_not_bare_ember():
    m = re.search(r"^\.dsx-count\s*\{([^}]*)\}", CSS.read_text(), re.M)
    assert m, ".dsx-count rule missing"
    color = re.search(r"color:\s*([^;]+);", m.group(1)).group(1).strip()
    assert color != "var(--ember)", "bare --ember on --ember-wash is 4.43:1 light (#4834)"
    assert "var(--ink)" in color, "the badge must be pulled toward --ink to clear 4.5:1"
