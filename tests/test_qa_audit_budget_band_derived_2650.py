"""#2650 — the QA audit's budget-darkness claim must come from the table the runtime enforces.

`scripts/qa_audit.py` asserted, as a **prose literal**, that band one paused the AI-vision
and reader-truth layers. The file never imported `budget_guard`.

`lambdas/ai/budget_guard._FEATURE_CUTOFF` sets `reader_truth_qa: 3` and `visual_ai_qa: 3`.
#1927 moved them out of band 1 (ADR-125 amendment 2026-08-03) for a specific reason: sitting
in band 1 left them **dark 26 of 30 days while still reporting green**. So at the live tier
the gates DO run and the audit said they did not — and `/qa` instructs the operator to run
`qa_audit` first, which makes this the first thing read in a QA session.

A drift-detection instrument that had itself drifted, on the exact fact it exists to report.

GUARD THE SET, NOT THE INSTANCE. The fix is not "change 1 to 3" — that is the same literal
with a better value, and it would drift again the next time a band moves. `budget_gate_bands()`
reads `_FEATURE_CUTOFF` (the table `allow()` enforces) over `CI_GATE_FEATURES` (the set
budget_guard itself declares to be CI gates), so neither the gate names nor their bands are
written in the audit at all. The issue's second box asks for exactly this, and
`test_moving_a_cutoff_in_the_source_table_moves_the_report` is the proof: it patches the
table and asserts the report follows.

TWO THINGS THAT WOULD HAVE MADE THE FIX QUIETLY INERT, both caught by running it rather than
reading it:

  * SSM returns the tier as a **string**. `isinstance("1", int)` is False, so the first
    version printed no ACTIVE/PAUSED verdict at all under `--live` — the exact half of the
    issue that matters most, silently missing while the derived bands looked right.
  * A comment quoting the old literal still matched the issue's fourth box
    (`grep -n 'tier >= 1' scripts/qa_audit.py` returns nothing). The box is about the
    literal being gone, and a comment reciting it is a literal a future grep will find.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from ai import budget_guard  # noqa: E402

qa_audit = importlib.import_module("qa_audit")

AUDIT_SRC = (pathlib.Path(_REPO) / "scripts" / "qa_audit.py").read_text()


# ── the derivation ───────────────────────────────────────────────────────────


def test_the_bands_come_from_budget_guards_own_table():
    bands = dict(qa_audit.budget_gate_bands())
    assert bands, "no CI gate bands derived — the import silently failed"
    for gate in budget_guard.CI_GATE_FEATURES:
        assert bands[gate] == budget_guard._FEATURE_CUTOFF[gate]


def test_the_gate_set_is_budget_guards_own_declaration():
    """The NAMES are derived too. A hand-written pair would miss a third CI gate."""
    assert set(dict(qa_audit.budget_gate_bands())) == set(budget_guard.CI_GATE_FEATURES)


def test_moving_a_cutoff_in_the_source_table_moves_the_report(monkeypatch):
    """Acceptance box 2 — guard the SET, not the instance.

    This is the assertion that distinguishes a derived report from a literal with a better
    value. Patch the table, and the audit's own output must follow it without any edit.
    """
    gate = budget_guard.CI_GATE_FEATURES[0]
    original = budget_guard._FEATURE_CUTOFF[gate]
    planted = 1 if original != 1 else 2
    monkeypatch.setitem(budget_guard._FEATURE_CUTOFF, gate, planted)

    detail = qa_audit._budget_pause_detail({"budget_tier": "1"})
    assert f"{gate}: pauses at tier >= {planted}" in detail, detail
    assert f"{gate}: pauses at tier >= {original}" not in detail


def test_the_live_verdict_follows_the_planted_band(monkeypatch):
    """Not just the printed number — the ACTIVE/PAUSED conclusion drawn from it."""
    gate = budget_guard.CI_GATE_FEATURES[0]
    monkeypatch.setitem(budget_guard._FEATURE_CUTOFF, gate, 1)
    assert f"{gate}: pauses at tier >= 1 — PAUSED now" in qa_audit._budget_pause_detail({"budget_tier": "1"})
    monkeypatch.setitem(budget_guard._FEATURE_CUTOFF, gate, 3)
    assert f"{gate}: pauses at tier >= 3 — ACTIVE now" in qa_audit._budget_pause_detail({"budget_tier": "1"})


# ── the live half, which the first draft silently lost ───────────────────────


def test_the_tier_is_read_as_a_string_because_ssm_returns_one():
    """SSM hands back "1", not 1. `isinstance("1", int)` is False, so a naive int check
    printed no verdict at all — the half of this issue that matters most, missing."""
    detail = qa_audit._budget_pause_detail({"budget_tier": "1"})
    assert "ACTIVE now" in detail, detail
    assert "live tier now: 1" in detail


@pytest.mark.parametrize("tier,expected", [("0", "ACTIVE"), ("1", "ACTIVE"), ("2", "ACTIVE"), ("3", "PAUSED"), (3, "PAUSED")])
def test_the_verdict_is_right_at_every_tier(tier, expected):
    """At the shipped cutoff of 3, only tier 3 pauses — the #1927 ruling, end to end."""
    detail = qa_audit._budget_pause_detail({"budget_tier": tier})
    for gate in budget_guard.CI_GATE_FEATURES:
        assert f"{gate}: pauses at tier >= 3 — {expected} now" in detail, detail


def test_no_verdict_is_claimed_when_the_tier_was_not_read():
    """Offline, the bands are still derived but no ACTIVE/PAUSED claim is made — an
    unread tier must not become an implied one."""
    detail = qa_audit._budget_pause_detail({})
    assert "pauses at tier >= 3" in detail
    assert "ACTIVE now" not in detail and "PAUSED now" not in detail
    assert "no ACTIVE/PAUSED verdict is claimed" in detail


@pytest.mark.parametrize("bad", [None, "", "unset", "n/a"])
def test_an_unparseable_tier_is_treated_as_unread_not_as_zero(bad):
    """Zero is the safest-looking wrong answer here: it would report every gate ACTIVE."""
    detail = qa_audit._budget_pause_detail({"budget_tier": bad})
    assert "ACTIVE now" not in detail and "PAUSED now" not in detail


def test_an_unimportable_budget_guard_says_so_rather_than_guessing(monkeypatch):
    """A missing import is exactly how a literal creeps back. Say 'not derived' instead."""
    monkeypatch.setattr(qa_audit, "budget_gate_bands", lambda: None)
    detail = qa_audit._budget_pause_detail({"budget_tier": "1"})
    assert "NOT DERIVED" in detail
    assert "pauses at tier" not in detail


# ── the issue's own greps ────────────────────────────────────────────────────


def test_no_band_one_literal_survives_anywhere_in_the_file():
    """Acceptance box 4, run as the issue words it — including in comments, because a
    comment reciting the old claim is a literal the next grep will find."""
    assert "tier >= 1" not in AUDIT_SRC


def test_the_audit_actually_imports_budget_guard():
    """The root cause was an absent import, so its presence is the thing to pin."""
    assert "budget_guard" in AUDIT_SRC


def test_the_shipped_bands_are_the_1927_ruling():
    """A canary on the fact this issue is about — if either gate returns to band 1 without
    an ADR amendment, this is where it surfaces."""
    for gate in ("reader_truth_qa", "visual_ai_qa"):
        assert budget_guard._FEATURE_CUTOFF[gate] == 3, f"{gate} left band 3 — was that an ADR-125 amendment?"
