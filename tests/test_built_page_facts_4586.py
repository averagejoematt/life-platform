"""tests/test_built_page_facts_4586.py — the one fact of "How it's built" that outlived the page (#4586, epic #4580).

The page lived at site/next/v8/built/ and was retired with the rest of the /next/ preview (#6223); the checks that read
its bytes (the tier bands, the incident figures, the draft label, noindex) left with it. Its module,
site/assets/js/ck_built.js, is still shipped, and the build-cap sentence it exports is still held to the cap module here.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "site" / "assets" / "js" / "ck_built.js"


def test_the_build_cap_sentence_matches_the_laptop_cap_module():
    """The page says what stops building-and-testing spend (red team round 7: the control
    was real, #4623, and the page omitted it). The two amounts are the cap module's."""
    src = (ROOT / "lambdas" / "ai" / "dev_session_cap.py").read_text()
    run = float(re.search(r"^PER_RUN_USD = ([0-9.]+)", src, re.M).group(1))
    day = float(re.search(r"^PER_DAY_USD = ([0-9.]+)", src, re.M).group(1))
    sentence = re.search(r'export const BUILD_CAP = "([^"]+)"', MODULE.read_text()).group(1)
    assert f"${run:g} in one run" in sentence and f"${day:g} in any 24 hours" in sentence, sentence
