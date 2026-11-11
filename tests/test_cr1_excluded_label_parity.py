"""The CR1 page carries the producer's exclusion-category words itself (owner 2026-11-10).

The wire gate blanks a served ``excluded_by_category`` label when a withheld grader note quotes the same engine
text, so ``www/src/lib/calibration.js`` mirrors ``web.verification_fields.EXCLUDED_CATEGORIES``. This pins the
mirror to the producer: every category key has the page's own words, verbatim.
"""

import re
from pathlib import Path

from web import verification_fields as vf

JS = Path(__file__).resolve().parents[1] / "www" / "src" / "lib" / "calibration.js"


def _page_words() -> dict[str, str]:
    block = re.search(r"const EXCLUDED_WORDS = \{(.*?)\n\};", JS.read_text(), re.S)
    assert block, "EXCLUDED_WORDS not found in calibration.js"
    return dict(re.findall(r'^\s+([a-z_]+): "([^"]*)",$', block.group(1), re.M))


def test_every_producer_category_has_the_same_words_on_the_page():
    words = _page_words()
    missing = {k for k, _ in vf.EXCLUDED_CATEGORIES} - set(words)
    assert not missing, f"page lacks words for {sorted(missing)}"
    for key, label in vf.EXCLUDED_CATEGORIES:
        assert words[key] == label, f"{key}: page {words[key]!r} != producer {label!r}"


def test_the_parity_check_catches_a_drifted_label():
    words = dict(_page_words())
    words["opinion"] = "something else"
    assert any(words[k] != v for k, v in vf.EXCLUDED_CATEGORIES)
