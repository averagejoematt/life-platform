"""tests/test_tension_prose_markdown_strip_2385.py — #2385: markdown emphasis
tokens must never reach readers as literal asterisks in public tension prose.

The integrator digest's disagreement prose (position_a/position_b/lead_call) is
AI-authored; prompt rules alone can't guarantee structure, and the front-end
(`site/assets/js/coaching.js` tensionsHTML) esc()-renders these fields verbatim
as plain text. The deterministic fix is a strip at the serving seam —
`web.site_api_coach_stance._team_tensions` — one place, all consumers, and it
covers stored history written before the fix shipped.

Mutation proof: with `_strip_md_emphasis` removed (or made a passthrough) the
token-bearing fixture below leaks literal ``**``/``*`` pairs into the served
payload and `test_served_tension_prose_has_no_emphasis_tokens` fails.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from web import site_api_coach_stance as stance  # noqa: E402

# The live leak that motivated #2385 (verified in /api/coach_team), plus the
# other emphasis forms the writers can emit.
_FIXTURE_DIGEST = {
    "generated_at": "2026-08-07T12:00:00Z",
    "disagreements": [
        {
            "topic": "**nutrition** vs *mind*",
            "coaches_involved": ["nutrition_coach", "mind_coach"],
            "position_a": "Weight stability over six days without logs *appears* to confirm adherence",
            "position_b": "Absence of logs is __absence of evidence__, not adherence",
            "lead_call": "Treat unlogged days as ***unknown***, not compliant",
        }
    ],
}

_PROSE_FIELDS = ("topic", "position_a", "position_b", "resolution")


def _served_tensions():
    return stance._team_tensions(_g={"_integrator_digest": lambda: _FIXTURE_DIGEST})


def test_served_tension_prose_has_no_emphasis_tokens():
    out = _served_tensions()
    assert len(out) == 1
    t = out[0]
    for field in _PROSE_FIELDS:
        val = t[field]
        assert isinstance(val, str)
        assert "**" not in val, f"{field} leaked bold tokens: {val!r}"
        assert "*" not in val, f"{field} leaked emphasis tokens: {val!r}"
        assert "__" not in val, f"{field} leaked underscore-bold tokens: {val!r}"


def test_words_survive_and_no_html_is_injected():
    t = _served_tensions()[0]
    # The strip keeps the words — it converts nothing to markup (no innerHTML risk).
    assert t["position_a"] == "Weight stability over six days without logs appears to confirm adherence"
    assert t["position_b"] == "Absence of logs is absence of evidence, not adherence"
    assert t["resolution"] == "Treat unlogged days as unknown, not compliant"
    assert t["topic"] == "nutrition vs mind"
    for field in _PROSE_FIELDS:
        assert "<" not in t[field] and ">" not in t[field]


def test_strip_leaves_honest_asterisks_and_non_strings_alone():
    strip = stance._strip_md_emphasis
    # Unpaired / arithmetic asterisks are not markdown — keep them.
    assert strip("5*10kg at RPE 8") == "5*10kg at RPE 8"
    assert strip("a lone ** dangler") == "a lone ** dangler"
    # snake_case survives (single underscores are not treated as emphasis).
    assert strip("read the raw_layout facet") == "read the raw_layout facet"
    # Optional fields pass through untouched.
    assert strip(None) is None
    assert strip(42) == 42


def test_empty_and_missing_digest_still_honest_empty():
    assert stance._team_tensions(_g={"_integrator_digest": lambda: None}) == []
    assert stance._team_tensions(_g={"_integrator_digest": lambda: {"disagreements": []}}) == []
