#!/usr/bin/env python3
"""tests/test_platform_stats_honesty_3690.py — the hand-maintained public stats must
still be true.

THE DEFECT (measured live, 2026-09-07)
  `/method/platform/` served `review_grade: "A"` while the newest full review graded
  **zero** lenses at A — the 2026-09-05 baseline is B+ 9 · B 3 · B- 3 · C+ 2 across 17
  lenses. `site_pages` said 77 against 93 registered. `active_secrets` said 21 against 28
  in the system model.

  `lambdas/web/site_api_common.py:213` classes these as "JUDGMENT / live-AWS — hand-
  maintained here, never rewritten by the sync", and that is a reasonable class: a grade
  is a judgement and cannot be AST-discovered from source the way `lambdas` or
  `test_count` are. But "not auto-derivable" was silently treated as "not checkable",
  and the consequence is that the numbers sitting beside five CI-gated counters were the
  only ones nobody re-read. The platform's most-quoted credibility figure was its least
  guarded value.

WHY THIS FILE AND NOT AN EXTENSION OF sync_doc_metadata
  `deploy/doc_platform_counts.py` rewrites **integer literals** in the generated
  `platform_counts.py`. A grade is a string and lives in the hand-merged module, so
  routing it through that writer would mean extending an int-only writer AND moving a
  judgement field into a generated file that branches must not edit — more machinery for
  a value that changes about six times a year.

  The proportionate shape is this: keep the field hand-maintained, and make it FAIL when
  it stops matching its real source. A human still writes the letter; CI decides whether
  the letter is still true. That is the ratchet primitive applied to a judgement.

WHAT EACH FIELD IS CHECKED AGAINST
  review_grade   → the modal lens grade in the newest docs/reviews/*_grades_*.json
  site_pages     → len(tests/qa_manifest.MANIFEST), the single page registry
  active_secrets → model/platform_model.json cost_surface.secrets

  `review_count`, `board_technical` and `board_product` are deliberately NOT checked, and
  the gap is stated rather than left implicit: nothing in the repo enumerates "reviews",
  and `docs/BOARDS.md`'s rosters are prose tables whose live source is an S3 config. A
  check that guessed at those would be worse than none — it would report green about a
  number it had not actually verified, which is the defect this file exists to end.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _stats() -> dict:
    from web.site_api_common import PLATFORM_STATS

    return PLATFORM_STATS


def _newest_grades() -> tuple[str, dict]:
    """(date, lenses) of the newest graded review carrying a `lenses` mapping."""
    cands = []
    for f in glob.glob(os.path.join(_REPO, "docs", "reviews", "*grades*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(d.get("lenses"), dict) and d.get("date"):
            cands.append((d["date"], d))
    if not cands:
        pytest.skip("no graded review with a lenses mapping in docs/reviews/")
    date, doc = sorted(cands, key=lambda t: t[0])[-1]
    return date, doc["lenses"]


def _grade_counts(lenses: dict) -> Counter:
    return Counter(v["grade"] for v in lenses.values() if isinstance(v, dict) and v.get("grade"))


# ── review_grade — the one that was wrong in public ──────────────────────────
def test_review_grade_is_the_modal_lens_grade_of_the_newest_review():
    date, lenses = _newest_grades()
    counts = _grade_counts(lenses)
    modal = counts.most_common(1)[0][0]
    served = _stats()["review_grade"]
    assert served == modal, (
        f"PLATFORM_STATS['review_grade'] is {served!r} but the newest review ({date}) has "
        f"modal grade {modal!r} — distribution {dict(counts.most_common())}. "
        "This value is served publicly at /method/platform/; update it, or update this "
        "test's rule if the definition of the headline grade has genuinely changed."
    )


def test_review_grade_is_a_grade_the_review_actually_awarded():
    """The stronger, blunter assertion, and the one that would have caught 'A'.

    Even if the headline rule changed from modal to something else, the served grade must
    be a grade SOME lens actually holds. 'A' passed no such test because no such test
    existed: zero lenses were at A, and the site said A for weeks.
    """
    date, lenses = _newest_grades()
    counts = _grade_counts(lenses)
    served = _stats()["review_grade"]
    assert served in counts, (
        f"PLATFORM_STATS['review_grade'] is {served!r}, which NO lens holds in the newest "
        f"review ({date}). Grades awarded: {dict(counts.most_common())}."
    )


def test_the_distribution_is_served_beside_the_letter():
    """A single letter cannot honestly summarise 17 lenses. The page carries the spread
    so a reader can see what the letter is standing in for (ADR-104)."""
    s = _stats()
    assert s.get("review_grade_distribution"), "the grade distribution must be served beside the letter"
    date, lenses = _newest_grades()
    counts = _grade_counts(lenses)
    dist = s["review_grade_distribution"]
    assert str(len(lenses)) in dist, f"the distribution string must state the lens count ({len(lenses)}): {dist!r}"
    assert date in dist, f"the distribution string must state the review date ({date}): {dist!r}"
    for grade, n in counts.items():
        assert grade in dist, f"grade {grade!r} ({n} lenses) is missing from the served distribution: {dist!r}"


# ── the two count fields that were also wrong ────────────────────────────────
def test_site_pages_matches_the_single_page_registry():
    import qa_manifest

    served = _stats()["site_pages"]
    actual = len(qa_manifest.MANIFEST)
    assert served == actual, (
        f"PLATFORM_STATS['site_pages'] is {served} but tests/qa_manifest.py registers {actual}. "
        "qa_manifest is the single page registry four consumers derive from; it is the number."
    )


def test_active_secrets_matches_the_system_model():
    with open(os.path.join(_REPO, "model", "platform_model.json"), encoding="utf-8") as fh:
        model = json.load(fh)
    actual = (model.get("cost_surface") or {}).get("secrets")
    if actual is None:
        pytest.skip("model carries no cost_surface.secrets")
    served = _stats()["active_secrets"]
    assert served == actual, (
        f"PLATFORM_STATS['active_secrets'] is {served} but model/platform_model.json " f"cost_surface.secrets is {actual}."
    )


# ── the stated gap ───────────────────────────────────────────────────────────
def test_the_unchecked_fields_are_named_rather_than_forgotten():
    """`review_count` and the two board counts have no derivable source, and this file
    says so in its docstring rather than leaving a reader to infer coverage from silence.

    If one of them ever acquires a real source, it belongs above and this list shrinks.
    """
    doc = sys.modules[__name__].__doc__ or ""
    for field in ("review_count", "board_technical", "board_product"):
        assert field in doc, f"{field} is unchecked and must be named as a stated gap in this file's docstring"
    # And they must still exist — a silently deleted field would make the gap vacuous.
    s = _stats()
    for field in ("review_count", "board_technical", "board_product"):
        assert field in s, f"{field} vanished from PLATFORM_STATS; update this file's stated gap"
