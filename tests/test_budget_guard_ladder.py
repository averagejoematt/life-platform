"""
ADR-100 + ADR-125 — the degradation ladder sacrifices by AUDIENCE, readers last.

Simulated budget-tier escalation pins the band order (ADR-125, as amended
2026-08-03 by #1927):
  band 1 INTERNAL/dev AI          (ensemble, coherence_semantic, chronicle_editor, ...)
  band 2 reader NARRATIVE content (coach_narrative, state_of_matthew, chronicle, ...)
  band 3 irreducible reader       (website_ai = /api/ask+board_ask, daily_brief_ai)
       + OPERATOR-TRUTH CI gates  (reader_truth_qa, visual_ai_qa)

The teeth: internal AI must pause a full tier before any reader-facing surface,
and the PUBLIC ask endpoints (+ the daily brief) degrade LAST — so a future edit
can't quietly make the reader product the first casualty of growth again (the
pre-ADR-125 defect, where coach_narrative paused at tier 1 while dev re-runs, the
actual June breach cause, kept spending).

The #1927 teeth: the two AI CI gates must NOT sit in the first band to die. They
were at cutoff 1 and therefore dark for 26 of 30 measured days while still
reporting green — a gate whose availability is decided by month-boundary spend
arithmetic is not a gate. They now pause only where Bedrock stops entirely.
"""

import os
import re
import sys

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
sys.path.insert(0, _LAMBDAS)
sys.path.insert(0, os.path.join(_LAMBDAS, "operational"))

import cost_governor_lambda  # noqa: E402
from ai import budget_guard  # noqa: E402

# The audience bands, as the ladder intends them (pause-tier per feature).
_INTERNAL = (
    "ensemble",
    "coherence_semantic",
    "chronicle_editor",
    "eyeball_estimate",
    "conversation_enrichment",  # #1577: conversational-corpus Haiku sweep — analysis layer, pauses first
)
_READER_NARRATIVE = (
    "coach_narrative",
    "state_of_matthew",
    "daily_debrief",
    "chronicle",
    "semantic_recall",
    "horizons_retrospective",
    "coach_diary_reaction",
    "coach_nudge",  # #1382: proactive decision-moment nudge — band 2, tier ≥2 silences (AC2)
)
_IRREDUCIBLE_READER = ("website_ai", "daily_brief_ai")
# #1927: the AI halves of the deploy pipeline's own QA. Not "internal QA" — they
# answer the OPERATOR's question ("is the deploy that just landed safe?"), which is
# upstream of every reader surface, and they are per-deploy + bounded rather than
# per-day + open-ended. They pause at the hard stop, i.e. exactly when Bedrock
# stops for everything.
_OPERATOR_TRUTH = ("reader_truth_qa", "visual_ai_qa")


def _at_tier(monkeypatch, tier):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)


def test_tier0_everything_runs(monkeypatch):
    _at_tier(monkeypatch, 0)
    for f in budget_guard._FEATURE_CUTOFF:
        assert budget_guard.allow(f), f


def test_tier1_internal_ai_pauses_first(monkeypatch):
    """Band 1: internal/dev AI is off, but NOTHING a reader reads pauses yet."""
    _at_tier(monkeypatch, 1)
    for f in _INTERNAL:
        assert not budget_guard.allow(f), f"{f} (internal) must pause at tier 1"
    for f in _READER_NARRATIVE + _IRREDUCIBLE_READER:
        assert budget_guard.allow(f), f"{f} (reader) must still run at tier 1"
    for f in _OPERATOR_TRUTH:
        assert budget_guard.allow(f), f"{f} (CI gate) must still run at tier 1 — #1927"


def test_tier2_reader_narrative_pauses_but_readers_still_answered(monkeypatch):
    """Band 2: narrative content is off, yet the ADR-100 teeth hold — the ask
    endpoints (where the budget defense previously went dark) STILL answer."""
    _at_tier(monkeypatch, 2)
    for f in _INTERNAL + _READER_NARRATIVE:
        assert not budget_guard.allow(f), f"{f} must be paused by tier 2"
    for f in _IRREDUCIBLE_READER:
        assert budget_guard.allow(f), f"{f} must degrade last (ADR-100)"
    for f in _OPERATOR_TRUTH:
        assert budget_guard.allow(f), f"{f} (CI gate) must still run at tier 2 — #1927"


def test_tier3_hard_stop_blocks_everything(monkeypatch):
    _at_tier(monkeypatch, 3)
    for f in budget_guard._FEATURE_CUTOFF:
        assert not budget_guard.allow(f), f


def test_band_ordering_is_strict_internal_lt_narrative_lt_reader():
    """Structural: every internal feature pauses strictly before every reader
    narrative feature, which pauses before every irreducible reader promise."""
    cut = budget_guard._FEATURE_CUTOFF
    hardest_internal = max(cut[f] for f in _INTERNAL)
    softest_narrative = min(cut[f] for f in _READER_NARRATIVE)
    hardest_narrative = max(cut[f] for f in _READER_NARRATIVE)
    softest_reader = min(cut[f] for f in _IRREDUCIBLE_READER)
    assert hardest_internal < softest_narrative, "internal AI must pause before reader narrative"
    assert hardest_narrative < softest_reader, "reader narrative must pause before the irreducible reader surface"


def test_all_gated_features_are_classified():
    """No feature may drift back into the default (cutoff 3) bucket unclassified —
    the coherence_semantic bug (internal QA silently outliving readers) recurs
    exactly that way."""
    classified = set(_INTERNAL + _READER_NARRATIVE + _IRREDUCIBLE_READER + _OPERATOR_TRUTH)
    assert set(budget_guard._FEATURE_CUTOFF) == classified


def test_ask_endpoint_and_daily_brief_are_the_last_to_go():
    cut = budget_guard._FEATURE_CUTOFF
    assert cut["website_ai"] == budget_guard._HARD_STOP_TIER
    assert cut["daily_brief_ai"] == budget_guard._HARD_STOP_TIER
    for f in _INTERNAL + _READER_NARRATIVE:
        assert cut[f] < budget_guard._HARD_STOP_TIER, f"{f} must not survive to the hard stop"


# ── #1927: the two AI CI gates are out of the first band to die ──────────────
# The measured defect: cutoff 1 for both, tier >= 1 for 26 of 30 days, both
# reporting green throughout because a gate that does not run finds nothing.


def test_ci_gates_are_the_derived_set_not_a_hand_list():
    """The names come from budget_guard.CI_GATE_FEATURES; both must be real
    ladder entries (a typo'd name would silently gate nothing)."""
    assert set(budget_guard.CI_GATE_FEATURES) == set(_OPERATOR_TRUTH)
    for f in budget_guard.CI_GATE_FEATURES:
        assert f in budget_guard._FEATURE_CUTOFF, f"{f} is not a classified feature"


def test_ci_gates_outlive_every_internal_and_narrative_feature():
    cut = budget_guard._FEATURE_CUTOFF
    softest_gate = min(cut[f] for f in _OPERATOR_TRUTH)
    assert softest_gate > max(cut[f] for f in _INTERNAL), "a CI gate must not pause with internal/dev AI (#1927)"
    assert softest_gate > max(cut[f] for f in _READER_NARRATIVE), "a CI gate must outlive the reader narrative band"


def test_ci_gates_run_at_every_tier_below_the_hard_stop(monkeypatch):
    """The durable property: no budget state short of 'Bedrock is off entirely'
    may silence a deploy gate. At the measured burn tier 1 is where the platform
    lives, so anything below the hard stop means 'usually dark'."""
    for tier in (0, 1, 2):
        _at_tier(monkeypatch, tier)
        for f in _OPERATOR_TRUTH:
            assert budget_guard.allow(f), f"{f} must run at tier {tier}"
    _at_tier(monkeypatch, 3)
    for f in _OPERATOR_TRUTH:
        assert not budget_guard.allow(f), f"{f} must pause at the hard stop (honestly, not by BudgetExceeded)"


def test_ci_gates_are_listed_deliberately_not_defaulted():
    """A feature absent from the map defaults to cutoff 3 too — that accident was
    the pre-ADR-125 coherence_semantic bug. Assert these are PRESENT, so the
    tier-3 placement is a decision the map records rather than an omission."""
    for f in _OPERATOR_TRUTH:
        assert f in budget_guard._FEATURE_CUTOFF
        assert budget_guard._FEATURE_CUTOFF[f] == budget_guard._HARD_STOP_TIER


# ── #1231: the cost_governor tier-change ALERT copy must mirror _FEATURE_CUTOFF ──
# _alert() emails Matthew _TIER_LABELS[new]; when those labels describe the
# pre-ADR-125 ladder (tier-2 "public website AI paused (/api/ask)"), the on-call
# is told the ask endpoint is down when it is not, and never hears which reader
# narrative actually paused. These derive the expected band from _FEATURE_CUTOFF
# so a future re-band of budget_guard forces the labels to move in lockstep.


def _tier_of(feature):
    return budget_guard._FEATURE_CUTOFF[feature]


def test_alert_labels_do_not_claim_ask_paused_before_its_real_cutoff():
    """The ask endpoints pause at cut['website_ai'] (tier 3). No LOWER tier's alert
    label may claim the ask endpoint is paused — the exact pre-ADR-125 defect where
    the tier-2 email said '/api/ask' was down while it still answered."""
    ask_tier = _tier_of("website_ai")
    labels = cost_governor_lambda._TIER_LABELS
    for tier, label in labels.items():
        mentions_ask = "/api/ask" in label or "board_ask" in label
        if tier < ask_tier:
            assert not mentions_ask, f"tier-{tier} label falsely names the ask endpoint (real cutoff is tier {ask_tier}): {label!r}"


def test_reader_narrative_tier_label_names_the_narrative_pause():
    """coach_narrative pauses at tier 2 (_FEATURE_CUTOFF); the tier-2 label must
    say a reader narrative paused, not omit it (the stale label named only the ask
    endpoint)."""
    narr_tier = _tier_of("coach_narrative")
    assert narr_tier == _tier_of("state_of_matthew") == _tier_of("chronicle")
    label = cost_governor_lambda._TIER_LABELS[narr_tier].lower()
    assert any(
        k in label for k in ("reader narrative", "coach commentary", "coach", "state of matthew", "chronicle")
    ), f"tier-{narr_tier} label must name the reader-narrative pause: {label!r}"
    assert "/api/ask" not in label and "board_ask" not in label, f"tier-{narr_tier} label must NOT claim the ask endpoint paused: {label!r}"


def test_hard_stop_tier_label_is_the_one_that_names_the_ask_endpoints():
    """The label for the tier where website_ai actually pauses is the one that must
    name the ask endpoints."""
    ask_tier = _tier_of("website_ai")
    label = cost_governor_lambda._TIER_LABELS[ask_tier]
    assert "/api/ask" in label, f"tier-{ask_tier} label must name the ask endpoint that pauses there: {label!r}"


def test_internal_tier_label_names_internal_ai():
    """Band 1 (internal/dev AI) pauses first; its alert label should say so, not
    describe heavy coach AI (the stale copy)."""
    internal_tier = max(_tier_of(f) for f in _INTERNAL)
    label = cost_governor_lambda._TIER_LABELS[internal_tier].lower()
    assert any(
        k in label for k in ("internal", "dev ai", "ensemble", "coherence")
    ), f"tier-{internal_tier} label must name the internal/dev AI pause: {label!r}"


# ── #2000: best-effort prose guard — a docstring naming "feature X pauses at
# tier N" must agree with the LIVE budget_guard._FEATURE_CUTOFF table. This is
# the class behind the coach_memoir_lambda.py bug (comment said "tier-1 pause"
# for coach_narrative while budget_guard has it at 2, ADR-125): a comment
# citing a feature+tier pair goes stale silently because nothing re-checks it
# against the table it's describing. Best-effort by design (a regex over
# prose, not a parser) — it only asserts on the specific
# `budget_guard.allow("<feature>")` ... `tier-N pause` phrasing this repo
# actually uses; it does not claim to catch every possible stale-comment shape.

_FEATURE_TIER_COMMENT_RE = re.compile(r'budget_guard\.allow\(\s*["\'](\w+)["\']\s*\)(.{0,160})', re.DOTALL)
_TIER_MENTION_RE = re.compile(r"tier[- ](\d+)\+?\s*pause")


def _scan_feature_tier_comments():
    """Walk lambdas/ for `budget_guard.allow("feature")` followed (within a
    short window of trailing prose) by a "tier-N pause" claim. Returns a list
    of (path, feature, claimed_tier) tuples."""
    found = []
    for root, _dirs, files in os.walk(_LAMBDAS):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for m in _FEATURE_TIER_COMMENT_RE.finditer(text):
                feature, tail = m.groups()
                tm = _TIER_MENTION_RE.search(tail)
                if tm:
                    found.append((os.path.relpath(path, _LAMBDAS), feature, int(tm.group(1))))
    return found


def test_feature_tier_prose_matches_live_cutoff_table():
    """Every `budget_guard.allow("<feature>")` call whose nearby comment claims
    a "tier-N pause" must name the tier that FEATURE_CUTOFF actually assigns
    that feature — catches the coach_memoir_lambda.py class (#2000) where the
    prose said tier-1 but the live table says tier-2."""
    hits = _scan_feature_tier_comments()
    assert hits, "expected to find at least one 'budget_guard.allow(...) ... tier-N pause' comment to check"
    cut = budget_guard._FEATURE_CUTOFF
    for path, feature, claimed_tier in hits:
        assert feature in cut, f"{path}: comment names unclassified feature {feature!r}"
        assert claimed_tier == cut[feature], (
            f"{path}: comment claims {feature!r} pauses at tier-{claimed_tier}, "
            f"but budget_guard._FEATURE_CUTOFF[{feature!r}] == {cut[feature]} — stale prose (#2000 class)"
        )
