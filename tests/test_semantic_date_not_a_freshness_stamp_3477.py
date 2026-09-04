"""tests/test_semantic_date_not_a_freshness_stamp_3477.py — #3477.

WHAT HAPPENED. `restart_pipeline.py`'s last step is `sync_doc_metadata.py --apply`,
folded in by #1287 precisely so a reset converges its own genesis/cycle doc literals.
On the cycle-16 re-anchor (2026-09-03) it ran, reported "Applied 1 change(s)", and left
`docs/SCHEMA.md`'s genesis anchor claiming the OUTGOING genesis — which then redded
`check_doc_facts.py` and three `test_wiki_checkers` cases on the very commit of the reset
artifacts. The reset exited 0 over it.

THE CAUSE. #2986 ("no manufactured freshness") defers any rewrite that
`differs_only_by_date_stamp` — masks every YYYY-MM-DD and compares — so a run cannot
re-stamp a doc's `Last updated:` line it did not earn. Correct, and the hold was applied
to EVERY rule. But a genesis anchor is a SEMANTIC FACT about the experiment, not a
freshness stamp, and

    "... EXPERIMENT_START_DATE (currently 2026-09-01)"
    "... EXPERIMENT_START_DATE (currently 2026-09-04)"

differs only by a date. So the one rule that exists to converge the genesis literal was
structurally unable to fire. `CLAUDE.md`'s twin escaped only by accident: it carries the
cycle number too, so masking leaves `cycle 15` vs `cycle 16` visible.

THE FIX, AND WHY IT IS THE SET AND NOT THE INSTANCE. The distinction already existed —
`doc_restamp_guard.stamped_rules()` defines a freshness-stamp rule as one whose template
carries `STAMP_PLACEHOLDER` — it just was not consulted where the decision is made. The
deferral now asks that question. These tests pin BOTH directions, because narrowing a
guard is only safe if the thing it was actually built for still holds:

  * a semantic-date rule (no `{date}`) must be APPLIED — the #3477 defect;
  * a freshness-stamp rule (`{date}`) must still be HELD — #2986's whole point.

A test that only checked the first would license deleting the guard.
"""

from __future__ import annotations

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import doc_restamp_guard as guard  # noqa: E402
import sync_doc_metadata as sdm  # noqa: E402

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _semantic_date_rules():
    """Rules whose replacement carries a date-valued FACT but no freshness stamp."""
    out = []
    for doc, pattern, template in sdm.RULES:
        if guard.STAMP_PLACEHOLDER in template:
            continue
        if "{experiment_genesis}" in template or _DATE.search(template):
            out.append((doc, pattern, template))
    return out


def test_the_genesis_anchor_is_a_semantic_date_not_a_freshness_stamp():
    """The rule that converges the genesis literal must not look like a `Last updated:`."""
    semantic = _semantic_date_rules()
    docs = {d for d, _, _ in semantic}
    assert "docs/SCHEMA.md" in docs, "the SCHEMA.md genesis anchor rule vanished — #3477 regressed or the rule moved"
    for doc, _, template in semantic:
        assert guard.STAMP_PLACEHOLDER not in template, f"{doc}: a semantic-date rule must not carry the freshness placeholder"


def test_a_semantic_date_change_is_not_deferred_as_a_restamp():
    """THE #3477 DEFECT, as an executable claim.

    The genesis anchor's old and new text differ only by a date, so
    `differs_only_by_date_stamp` is True for it — that is not the bug. The bug was
    ACTING on that alone. The freshness predicate must separate the two."""
    old = "Record dated on or after EXPERIMENT_START_DATE (currently 2026-09-01)"
    new = "Record dated on or after EXPERIMENT_START_DATE (currently 2026-09-04)"
    assert guard.differs_only_by_date_stamp(old, new), "masking premise changed — this test's setup is stale"

    template = "Record dated on or after EXPERIMENT_START_DATE (currently {experiment_genesis})"
    assert guard.STAMP_PLACEHOLDER not in template, "a genesis anchor must never be classified as a freshness stamp"


def test_a_real_freshness_stamp_is_still_held():
    """#2986's positive control. Narrowing the hold may not disarm it."""
    stamped = guard.stamped_rules(sdm.RULES)
    assert stamped, "no freshness-stamp rules found — the guard has gone blind"
    for _doc, _pattern, template in stamped:
        assert guard.STAMP_PLACEHOLDER in template
    old = "**Last updated:** 2026-09-01 (v1 — 76 MCP tools)"
    new = "**Last updated:** 2026-09-04 (v1 — 76 MCP tools)"
    assert guard.differs_only_by_date_stamp(old, new), "a pure re-stamp must still read as date-only"


def test_the_deferral_site_consults_the_freshness_predicate():
    """The wire, not a restatement of it: the narrowing must live where the decision is
    made. A future refactor that drops the predicate and keeps this file's other tests
    green would re-open #3477 silently."""
    src = open(os.path.join(_REPO, "deploy", "sync_doc_metadata.py"), encoding="utf-8").read()

    # The CONDITION, not a nearby window. A window-scoped grep is vacuous here: reverting
    # the fix leaves the `is_freshness_stamp = ...` assignment in place a line above, so a
    # proximity check passes over the exact defect it is meant to catch (proved by
    # mutation while writing this file — the first version of this guard did not fire).
    cond = None
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("if ") and "differs_only_by_date_stamp(old_match.group(0)" in stripped:
            cond = stripped
            break
    assert cond is not None, "the deferral `if` moved — re-point this guard"
    assert "is_freshness_stamp and " in cond, (
        "the date-only deferral is no longer GATED on the rule being a FRESHNESS stamp — "
        f"#3477 re-opens: a semantic date fact (the genesis anchor) would be held and never written.\n  condition: {cond}"
    )
