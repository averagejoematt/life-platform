"""
relationship_engine.py — #536: the deterministic RELATIONSHIP#state writer.

RELATIONSHIP#state has been *read* since the Coach Intelligence launch
(coach/coach_history_summarizer.py, coach/coach_observatory_renderer.py) but no
writer ever existed — the rapport arc was a permanent empty default. This module
is that writer's pure, unit-testable core: given the coach's current relationship
record and a bundle of deterministic signals, it computes the next record. No LLM
is involved anywhere in this file (ADR-062 spirit / epic #526 guardrail) — every
transition is a rule with a documented coefficient, and the record carries its own
audit trail (`phase_history`) so the arc is inspectable, not asserted.

Signals consumed (all already written elsewhere in the platform — this module
only combines them):
  - a generation cycle happening at all (coach_state_updater invokes this once per
    coach output) — the baseline "Matthew is still reading this coach" signal
  - board Q&A the coach answered (INTERACTION# records, #531)
  - commitments graded kept/broken since the last update (COMMITMENT#, #532)
  - predictions graded confirmed/refuted since the last update (PREDICTION#)
  - elapsed silence — no generation cycle in a while decays rapport

Read shape (must stay stable — two existing readers destructure these fields
without modification, per SCHEMA.md "RELATIONSHIP#state fields"):
  coach_id, rapport_level, interaction_count, journey_phase, phase_history,
  first_interaction_date, last_interaction_date, tenure_days, trust_signals,
  context_summary, updated_at.
"""

from datetime import date as _date

# ══════════════════════════════════════════════════════════════════════════════
# TUNABLE CONSTANTS — every number here is a documented rule, not a fit
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_RAPPORT = 0.15  # a brand-new relationship starts "clinical", not zero
MIN_RAPPORT = 0.05  # never fully bottoms out — there's always *some* rapport
MAX_RAPPORT = 1.0

# Steady engagement (one generation cycle Matthew is presumed to read) nudges
# rapport a fraction of the remaining distance to 1.0 — diminishing returns so
# rapport can't be inflated by raw volume alone.
ENGAGEMENT_FRACTION = 0.03

# Silence decay — no generation cycle for this many days starts eroding rapport;
# below the grace window, silence is normal (weekly cadences, travel, etc.).
SILENCE_GRACE_DAYS = 10
DECAY_PER_IDLE_DAY = 0.01
MAX_DECAY_PER_RUN = 0.20

# Reader-initiated engagement (public board Q&A the coach answered) is a
# stronger signal than a passive generation cycle.
BOARD_QA_BONUS = 0.02

# Commitments are the strongest signal — Matthew explicitly acting (or not) on
# the coach's advice is the clearest evidence of the relationship's substance.
COMMIT_KEPT_BONUS = 0.05
COMMIT_BROKEN_PENALTY = 0.04

# Prediction accuracy is a competence signal (does Matthew trust this coach's
# calls?), so it moves rapport more gently than a kept/broken commitment.
PRED_CONFIRMED_BONUS = 0.02
PRED_REFUTED_PENALTY = 0.015

# Phase thresholds — clinical -> familiar -> invested. All three axes named in
# the epic (tenure, interaction count, rapport) gate "invested"; "familiar" only
# needs interaction count + rapport (tenure lags rapport in a fast-engaging case).
PHASE_CLINICAL = "clinical"
PHASE_FAMILIAR = "familiar"
PHASE_INVESTED = "invested"

FAMILIAR_MIN_INTERACTIONS = 5
FAMILIAR_MIN_RAPPORT = 0.30
INVESTED_MIN_INTERACTIONS = 15
INVESTED_MIN_RAPPORT = 0.60
INVESTED_MIN_TENURE_DAYS = 30

MAX_PHASE_HISTORY = 20
MAX_TRUST_SIGNALS = 8


def _parse_date(s):
    if not s:
        return None
    try:
        return _date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _phase_for(rapport: float, interaction_count: int, tenure_days: int) -> str:
    """Deterministic phase classification — no LLM, just the thresholds above."""
    if interaction_count >= INVESTED_MIN_INTERACTIONS and rapport >= INVESTED_MIN_RAPPORT and tenure_days >= INVESTED_MIN_TENURE_DAYS:
        return PHASE_INVESTED
    if interaction_count >= FAMILIAR_MIN_INTERACTIONS and rapport >= FAMILIAR_MIN_RAPPORT:
        return PHASE_FAMILIAR
    return PHASE_CLINICAL


def default_relationship_state(coach_id: str, generation_date: str) -> dict:
    """The record for a coach's very first cycle — a genuinely new relationship."""
    return {
        "coach_id": coach_id,
        "rapport_level": DEFAULT_RAPPORT,
        "interaction_count": 0,
        "journey_phase": PHASE_CLINICAL,
        "phase_history": [],
        "first_interaction_date": generation_date,
        "last_interaction_date": None,
        "tenure_days": 0,
        "trust_signals": [],
        "context_summary": f"{coach_id}: new relationship, no cycles yet.",
        "updated_at": None,
    }


def compute_relationship_update(current: dict | None, coach_id: str, generation_date: str, signals: dict, now_iso: str) -> dict:
    """Pure function: (current RELATIONSHIP#state, new signals) -> next state.

    `signals` — all counts of NEW events since the record's `last_interaction_date`
    (the caller is responsible for bounding queries to that cursor so this function
    never double-counts):
      - board_interactions: int — new INTERACTION# (board Q&A) records
      - kept_commitments / broken_commitments: int — newly-graded COMMITMENT#s
      - confirmed_predictions / refuted_predictions: int — newly-graded PREDICTION#s

    Deterministic and side-effect free — safe to unit test without DynamoDB.
    """
    if not current:
        current = default_relationship_state(coach_id, generation_date)

    rapport = float(current.get("rapport_level", DEFAULT_RAPPORT))
    interaction_count = int(current.get("interaction_count", 0))
    first_interaction_date = current.get("first_interaction_date") or generation_date
    last_interaction_date = current.get("last_interaction_date")
    prev_phase = current.get("journey_phase", PHASE_CLINICAL)
    phase_history = list(current.get("phase_history", []))
    trust_signals = list(current.get("trust_signals", []))

    gen_d = _parse_date(generation_date)
    last_d = _parse_date(last_interaction_date)
    same_cycle = bool(gen_d and last_d and gen_d == last_d)

    new_signals = []

    # ── Baseline engagement / silence decay (mutually exclusive per cycle) ──
    if not same_cycle:
        if last_d and gen_d:
            idle_days = (gen_d - last_d).days
        else:
            idle_days = 0

        if idle_days > SILENCE_GRACE_DAYS:
            decay = min((idle_days - SILENCE_GRACE_DAYS) * DECAY_PER_IDLE_DAY, MAX_DECAY_PER_RUN)
            rapport -= decay
            new_signals.append(f"{idle_days}d silence — rapport decayed {decay:.3f}")
        else:
            rapport += (MAX_RAPPORT - rapport) * ENGAGEMENT_FRACTION
        interaction_count += 1

    # ── Reader-initiated engagement ──
    board_n = int(signals.get("board_interactions", 0) or 0)
    if board_n:
        rapport += board_n * BOARD_QA_BONUS
        interaction_count += board_n
        new_signals.append(f"answered {board_n} reader question(s) on the public board")

    # ── Commitment follow-through ──
    kept_n = int(signals.get("kept_commitments", 0) or 0)
    broken_n = int(signals.get("broken_commitments", 0) or 0)
    if kept_n:
        rapport += kept_n * COMMIT_KEPT_BONUS
        interaction_count += kept_n
        new_signals.append(f"kept {kept_n} commitment(s)")
    if broken_n:
        rapport -= broken_n * COMMIT_BROKEN_PENALTY
        interaction_count += broken_n
        new_signals.append(f"broke {broken_n} commitment(s)")

    # ── Prediction track record ──
    confirmed_n = int(signals.get("confirmed_predictions", 0) or 0)
    refuted_n = int(signals.get("refuted_predictions", 0) or 0)
    if confirmed_n:
        rapport += confirmed_n * PRED_CONFIRMED_BONUS
        new_signals.append(f"{confirmed_n} prediction(s) confirmed")
    if refuted_n:
        rapport -= refuted_n * PRED_REFUTED_PENALTY
        new_signals.append(f"{refuted_n} prediction(s) refuted")

    rapport = max(MIN_RAPPORT, min(MAX_RAPPORT, rapport))

    tenure_days = 0
    first_d = _parse_date(first_interaction_date)
    if first_d and gen_d:
        tenure_days = max(0, (gen_d - first_d).days)

    journey_phase = _phase_for(rapport, interaction_count, tenure_days)

    if journey_phase != prev_phase:
        phase_history.append(
            {
                "phase": journey_phase,
                "date": generation_date,
                "rapport_level": round(rapport, 3),
                "interaction_count": interaction_count,
            }
        )
        phase_history = phase_history[-MAX_PHASE_HISTORY:]

    if new_signals:
        trust_signals.extend(f"[{generation_date}] {s}" for s in new_signals)
        trust_signals = trust_signals[-MAX_TRUST_SIGNALS:]

    context_summary = f"{coach_id}: {journey_phase} ({rapport:.2f} rapport, " f"{interaction_count} interactions across {tenure_days}d)"

    return {
        "coach_id": coach_id,
        "rapport_level": round(rapport, 4),
        "interaction_count": interaction_count,
        "journey_phase": journey_phase,
        "phase_history": phase_history,
        "first_interaction_date": first_interaction_date,
        "last_interaction_date": generation_date,
        "tenure_days": tenure_days,
        "trust_signals": trust_signals,
        "context_summary": context_summary,
        "updated_at": now_iso,
    }
