"""tests/test_prop_achievement_rules.py — property-based (Hypothesis) proofs of the
badge-threshold engine (lambdas/achievement_rules.py), #1664 / epic #1648.

achievement_rules is pure (decimal/typing only; the DDB read/write helpers take an
injected table + phase_filter, but evaluate / render / unlock_hint /
derive_first_earn_date are pure threshold logic). The invariants proven here are the
module's own honesty contract:

  * progress never revokes a live badge (evaluate is monotone in the earn direction);
  * a stored first-earn wins — a recorded badge stays earned regardless of signals
    (water weight cannot take a badge away);
  * earned_date is NEVER manufactured (None unless the stored record supplies one);
  * derive_first_earn_date returns the EARLIEST honest crossing, and None for any
    non-derivable signal.
"""

import os
import sys

from hypothesis import given, settings, strategies as st

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import achievement_rules as ar  # noqa: E402

# gte-driven numeric signals (higher => more earned) and the one lt signal
# (current_weight: lower => more earned).
_GTE_SIGNALS = (
    "current_streak",
    "days_tracked",
    "current_level",
    "lost_lbs",
    "completed_exps",
    "completed_challenges",
    "perfect_challenges",
)
_BOOL_SIGNALS = ("exp_streak_3", "exp_all_pillars", "hypothesis_confirmed")

_signals_strategy = st.fixed_dictionaries(
    {
        **{k: st.integers(min_value=0, max_value=500) for k in _GTE_SIGNALS},
        "current_weight": st.integers(min_value=150, max_value=400),
        **{k: st.booleans() for k in _BOOL_SIGNALS},
    }
)


@given(signals=_signals_strategy)
@settings(max_examples=200)
def test_evaluate_keys_and_never_badge(signals):
    result = ar.evaluate(signals)
    assert set(result) == set(ar.BADGE_IDS)
    # `never`-comparator badge (hypothesis_confirmed) is unreachable by this engine.
    assert result["hypothesis_confirmed"] is False


@given(signals=_signals_strategy, bump=st.integers(min_value=0, max_value=200))
@settings(max_examples=200)
def test_progress_never_revokes_a_badge(signals, bump):
    base = ar.evaluate(signals)
    boosted = dict(signals)
    for k in _GTE_SIGNALS:
        boosted[k] = signals[k] + bump
    boosted["current_weight"] = signals["current_weight"] - bump  # lose weight => earn lt badges
    for k in _BOOL_SIGNALS:
        boosted[k] = True  # a boolean can only turn on
    after = ar.evaluate(boosted)
    for badge_id, was_earned in base.items():
        if was_earned:
            assert after[badge_id], f"{badge_id} un-earned by progress"


@given(signals=_signals_strategy)
@settings(max_examples=100)
def test_render_length_and_order(signals):
    rows = ar.render(signals, {})
    assert [r["id"] for r in rows] == list(ar.BADGE_IDS)
    assert len(rows) == len(ar.BADGE_RULES)


@given(signals=_signals_strategy, badge_id=st.sampled_from(ar.BADGE_IDS), earned_date=st.one_of(st.none(), st.just("2026-01-15")))
@settings(max_examples=200)
def test_stored_first_earn_wins_and_date_not_manufactured(signals, badge_id, earned_date):
    record = {"earned_date": earned_date, "date_basis": ar.BASIS_UNDETERMINED}
    rows = {r["id"]: r for r in ar.render(signals, {badge_id: record})}
    # A stored record forces earned=True regardless of the live signal...
    assert rows[badge_id]["earned"] is True
    # ...and the earned_date is exactly the record's (never invented).
    assert rows[badge_id]["earned_date"] == earned_date


@given(signals=_signals_strategy)
@settings(max_examples=100)
def test_empty_first_earns_never_manufactures_a_date(signals):
    for row in ar.render(signals, {}):
        assert row["earned_date"] is None


@given(
    rule=st.sampled_from([r for r in ar.BADGE_RULES if r.signal in ar.DERIVABLE_SIGNALS and r.comparator == "gte"]),
    series=st.lists(st.tuples(st.integers(min_value=1, max_value=28), st.integers(min_value=0, max_value=500)), min_size=0, max_size=12),
)
@settings(max_examples=200)
def test_derive_first_earn_is_earliest_crossing(rule, series):
    dated = [(f"2026-02-{d:02d}", v) for d, v in series]
    histories = {rule.signal: dated}
    got = ar.derive_first_earn_date(rule, histories)
    crossings = sorted(date for date, val in dated if val >= rule.threshold)
    assert got == (crossings[0] if crossings else None)


@given(
    rule=st.sampled_from([r for r in ar.BADGE_RULES if r.signal not in ar.DERIVABLE_SIGNALS]),
    histories=st.dictionaries(
        keys=st.sampled_from(sorted(ar.DERIVABLE_SIGNALS)),
        values=st.lists(st.tuples(st.just("2026-03-01"), st.integers(0, 500)), max_size=3),
        max_size=3,
    ),
)
@settings(max_examples=100)
def test_non_derivable_signal_never_dated(rule, histories):
    assert ar.derive_first_earn_date(rule, histories) is None


@given(rule=st.sampled_from(ar.BADGE_RULES), signals=_signals_strategy)
@settings(max_examples=200)
def test_unlock_hint_contract(rule, signals):
    # static hints are unconditional; earned non-static badges show no hint.
    hint_earned = ar.unlock_hint(rule, signals, earned=True)
    if rule.hint_kind is None:
        assert hint_earned is None
    elif rule.hint_kind == "static":
        assert hint_earned == rule.hint_text
    else:
        assert hint_earned is None
