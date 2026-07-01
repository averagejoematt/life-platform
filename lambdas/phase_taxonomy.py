"""
phase_taxonomy.py — single source of truth for experiment-restart data semantics.

Every record type in the life-platform DynamoDB table belongs to exactly one
of four classes. Both restart tools (deploy/restart_phase_tag.py, the tagger;
deploy/restart_intelligence_wipe.py, the wipe) and the read paths derive their
behavior from this registry instead of hand-maintained pk lists — the divergence
between those lists was the root cause of every leak found in the 2026-06-07
schema audit (ADR-077).

The four classes
----------------
- CROSS_PHASE      Clinical/identity truths + durable anchors. NEVER tagged,
                   NEVER wiped, NEVER phase-filtered. (labs, dexa, genome,
                   supplements/meds, the frozen pre-platform `chronicling`
                   archive, subscribers, profile, durable platform memories.)
- RAW_TIMESERIES   Measured/logged facts. Kept forever; current-experiment
                   views are GENESIS-ANCHORED (date-clamped to EXPERIMENT_START),
                   not hidden. Phase tags are harmless/optional. (whoop, withings,
                   the day_grade series, body measurements, journal, hevy, etc.)
- EXPERIMENT_SCOPED Derived intelligence + progress artifacts that are only
                   meaningful inside the run that produced them. TAGGED +
                   WIPED (tombstoned, never deleted) at restart, phase-filtered
                   on read. Stamped with the CYCLE number at archive time so the
                   archive is navigable by reset generation. (insights, hypotheses,
                   experiments, challenges, coach intelligence, day-grade-derived
                   scores, the chronicle narrative, etc.)
- SYSTEM_STATE     Ops/infra/cache/TTL records. The phase machinery IGNORES them
                   entirely — no tag, no wipe, no filter. (caches, rate limits,
                   pipeline health, routine indices, dedup trackers, dead
                   partitions.)

Cycle stamping
--------------
On restart, the wipe stamps `cycle=<closing run number>` (read from SSM
/life-platform/experiment-cycle) onto every EXPERIMENT_SCOPED record it archives,
alongside `phase=pilot` + `tombstone=true`. Going forward, experiment_scoped
writers stamp `cycle=<current>` + `phase=experiment` at write time so records are
self-describing even on partitions the tagger cannot reach.

v1.0.0 — 2026-06-07 (ADR-077; supersedes the ad-hoc lists in the restart tools)
"""

from __future__ import annotations

CROSS_PHASE = "cross_phase"
RAW_TIMESERIES = "raw_timeseries"
EXPERIMENT_SCOPED = "experiment_scoped"
SYSTEM_STATE = "system_state"

VALID_CLASSES = frozenset({CROSS_PHASE, RAW_TIMESERIES, EXPERIMENT_SCOPED, SYSTEM_STATE})

# ── Classification by SOURCE name (pk = USER#matthew#SOURCE#<source>) ──────────
# This is the bulk of the table. Sources absent here raise in classify() so a
# new source can never silently default to the wrong behavior (the test enforces
# that every live source is listed).
SOURCE_CLASS: dict[str, str] = {
    # — RAW_TIMESERIES: measured/logged facts (genesis-anchored on read) —
    "whoop": RAW_TIMESERIES,
    "withings": RAW_TIMESERIES,
    "strava": RAW_TIMESERIES,
    "garmin": RAW_TIMESERIES,
    "apple_health": RAW_TIMESERIES,
    "eightsleep": RAW_TIMESERIES,
    "habitify": RAW_TIMESERIES,  # raw completion; habit_scores is the derived one
    "todoist": RAW_TIMESERIES,
    "weather": RAW_TIMESERIES,
    "macrofactor": RAW_TIMESERIES,
    "macrofactor_workouts": RAW_TIMESERIES,
    "hevy": RAW_TIMESERIES,
    "notion": RAW_TIMESERIES,  # journal entries — user-authored facts
    "food_delivery": RAW_TIMESERIES,  # behavioral archive (incl. longest-ever streak)
    "sick_days": RAW_TIMESERIES,
    "measurements": RAW_TIMESERIES,  # ADR-077 dec B: body fact like weight; GA, not hidden
    "day_grade": RAW_TIMESERIES,  # ADR-077 dec C: keep series for Replay; GA clamps cockpit
    "sleep_unified": RAW_TIMESERIES,  # reconciled best-estimate of the night, not a verdict
    "state_of_mind": RAW_TIMESERIES,  # affect self-report series
    "mood": RAW_TIMESERIES,
    "travel": RAW_TIMESERIES,
    "interactions": RAW_TIMESERIES,
    "exposures": RAW_TIMESERIES,
    "temptations": RAW_TIMESERIES,  # accountability/identity log (resisted-temptation facts)
    # — CROSS_PHASE: clinical truths + durable anchors (never touch) —
    "labs": CROSS_PHASE,
    "dexa": CROSS_PHASE,
    "genome": CROSS_PHASE,
    "supplements": CROSS_PHASE,  # ADR-077 dec A: medication-safety — never hide
    "chronicling": CROSS_PHASE,  # ADR-077 dec D: frozen pre-platform "before" archive
    "subscribers": CROSS_PHASE,  # audience identity
    # — EXPERIMENT_SCOPED: derived intelligence/progress (tag + wipe + cycle-stamp) —
    "character_sheet": EXPERIMENT_SCOPED,  # RPG-style derived scores; wiped "all" + rebuilt
    "habit_scores": EXPERIMENT_SCOPED,  # see vice_streaks split note in ADR-077 dec G
    "computed_metrics": EXPERIMENT_SCOPED,
    "computed_insights": EXPERIMENT_SCOPED,
    "adaptive_mode": EXPERIMENT_SCOPED,
    "engagement_state": EXPERIMENT_SCOPED,  # presence / quiet-stretch state; resets with the cycle
    "circadian": EXPERIMENT_SCOPED,
    "anomalies": EXPERIMENT_SCOPED,
    "weekly_correlations": EXPERIMENT_SCOPED,
    "what_changed": EXPERIMENT_SCOPED,  # SS-08 monthly delta + first-seen ledger; resets with cycle
    "centenarian_progress": EXPERIMENT_SCOPED,
    "nutrition_review": EXPERIMENT_SCOPED,
    "chronicle": EXPERIMENT_SCOPED,  # the Wednesday narrative (curated carry-forward at restart)
    "panelcast": EXPERIMENT_SCOPED,  # The Panel podcast series_state (open bets, recent topics) — resets with the cycle
    "insights": EXPERIMENT_SCOPED,
    "hypotheses": EXPERIMENT_SCOPED,
    "experiments": EXPERIMENT_SCOPED,
    "challenges": EXPERIMENT_SCOPED,
    "protocols": EXPERIMENT_SCOPED,
    "field_notes": EXPERIMENT_SCOPED,
    "discovery_annotations": EXPERIMENT_SCOPED,
    "ledger": EXPERIMENT_SCOPED,  # TOTALS#current resets; txns tombstone + LIFETIME# (dec F)
    "ai_analysis": EXPERIMENT_SCOPED,
    "decisions": EXPERIMENT_SCOPED,
    "rewards": EXPERIMENT_SCOPED,
    "coach_actions": EXPERIMENT_SCOPED,
    # — SYSTEM_STATE: ops/infra/cache/dead (phase machinery ignores) —
    "journal_analysis": SYSTEM_STATE,  # regenerating Haiku cache (TTL 180d)
    "health_check": SYSTEM_STATE,
    "dropbox_tracker": SYSTEM_STATE,
    "hevy_id_map": SYSTEM_STATE,
    "routine_index": SYSTEM_STATE,
    "email_log": SYSTEM_STATE,  # ADR-077 dec E: immutable sent-mail archive, GA on read
    "google_calendar": SYSTEM_STATE,  # dead: no writer (ADR-077 finding 7)
    "composite_scores": SYSTEM_STATE,  # dead: ADR-025 removed partition
}

# platform_memory is split BY CATEGORY: durable user facts are cross-phase;
# coach running-state categories are experiment-scoped (tombstoned at restart).
MEMORY_DURABLE_CATEGORIES = frozenset({"baseline_snapshot", "re_entry", "cycle_marker", "cycle"})
MEMORY_SCOPED_CATEGORIES = frozenset(
    {
        "failure_pattern",
        "failure_patterns",  # ADR-077 finding 4: both spellings
        "what_worked",
        "coaching_calibration",
        "personal_curves",
        "weekly_plate",
        "journey_milestone",
        "insight",
        "experiment_result",
        "intention_tracking",
        "hypothesis_monitoring",
    }
)

# ── Classification for non-SOURCE pks (full pk or pk prefix) ───────────────────
# Evaluated in order; first match wins. Each entry: (predicate(pk, sk) -> bool, class).
_PK_RULES: list = [
    # Coach intelligence tier — all experiment-scoped.
    (lambda pk, sk: pk.startswith("COACH#"), EXPERIMENT_SCOPED),
    (lambda pk, sk: pk == "ENSEMBLE#digest", EXPERIMENT_SCOPED),
    (lambda pk, sk: pk == "ENSEMBLE#disagreements", EXPERIMENT_SCOPED),
    (lambda pk, sk: pk == "ENSEMBLE#influence_graph", SYSTEM_STATE),  # static config
    (lambda pk, sk: pk == "NARRATIVE#arc", EXPERIMENT_SCOPED),
    # Reading / Mind pillar (ADR-097). Durable identity data — a person's library and
    # reading history must survive an experiment reset, so it is CROSS_PHASE (never
    # tagged, never wiped, never phase-filtered). Covers BOOK#<id> and every READING#
    # pk: READING#<id>, READING#REC, READING#PROFILE, READING#IDEA#<id>.
    (lambda pk, sk: pk.startswith("BOOK#"), CROSS_PHASE),
    (lambda pk, sk: pk.startswith("READING#"), CROSS_PHASE),
    # Bare USER#matthew pk — coach conversation memory leaks live here (ADR-077 finding 1).
    (lambda pk, sk: pk == "USER#matthew" and sk.startswith("SOURCE#coach_thread"), EXPERIMENT_SCOPED),
    (lambda pk, sk: pk == "USER#matthew" and sk.startswith("SOURCE#intelligence_quality"), SYSTEM_STATE),
    (lambda pk, sk: pk == "USER#matthew" and sk.startswith("PROFILE#"), CROSS_PHASE),
    # Durable restart-cycle memory (ADR-077 finding 3 — make protection explicit).
    (lambda pk, sk: pk == "USER#matthew#MEMORY", CROSS_PHASE),
    # Versioned routine IR audit trail + ops state.
    (lambda pk, sk: pk.startswith("USER#matthew#ROUTINE#"), SYSTEM_STATE),
    (lambda pk, sk: pk == "USER#system", SYSTEM_STATE),
    # Presentation/cache/infra.
    (lambda pk, sk: pk == "PULSE", SYSTEM_STATE),
    (lambda pk, sk: pk.startswith("CACHE#"), SYSTEM_STATE),
    (lambda pk, sk: pk.startswith("SUBSCRIBE#"), SYSTEM_STATE),
    (lambda pk, sk: pk.startswith("VOTES#"), SYSTEM_STATE),
    (lambda pk, sk: pk.startswith("EXPERIMENT_FOLLOWS"), SYSTEM_STATE),
]


def _source_of(pk: str) -> str | None:
    """Return the base <source> from a USER#...#SOURCE#<source> pk, else None.

    The email_log family uses pks like SOURCE#email_log#daily_brief — the part
    after the first '#' is the email type, not a distinct source, so the base is
    `email_log`. No other source contains a '#'.
    """
    marker = "#SOURCE#"
    idx = pk.find(marker)
    if idx == -1:
        return None
    raw = pk[idx + len(marker) :]
    return raw.split("#", 1)[0]


def classify(pk: str, sk: str = "", *, category: str | None = None, memory_type: str | None = None) -> str:
    """Return the taxonomy class for a record.

    For platform_memory pass `category` (or `memory_type`) so the per-category
    split applies; otherwise classification is by source/pk alone.

    Raises KeyError for an unknown SOURCE# source — a new source must be added to
    SOURCE_CLASS deliberately (the test enforces full live coverage), never
    silently defaulted.
    """
    source = _source_of(pk)
    if source is not None:
        if source == "platform_memory":
            cat = category or memory_type
            if cat in MEMORY_DURABLE_CATEGORIES:
                return CROSS_PHASE
            if cat in MEMORY_SCOPED_CATEGORIES:
                return EXPERIMENT_SCOPED
            # SK-derived fallback: MEMORY#<category>#<date>
            if sk.startswith("MEMORY#"):
                derived = sk.split("#", 2)[1] if sk.count("#") >= 1 else ""
                if derived in MEMORY_DURABLE_CATEGORIES:
                    return CROSS_PHASE
                if derived in MEMORY_SCOPED_CATEGORIES:
                    return EXPERIMENT_SCOPED
            # Unknown memory category → treat as scoped (safe: tombstoned, recoverable).
            return EXPERIMENT_SCOPED
        try:
            return SOURCE_CLASS[source]
        except KeyError:
            raise KeyError(
                f"phase_taxonomy: unknown SOURCE source '{source}' (pk={pk!r}). " f"Add it to SOURCE_CLASS — do not let it default."
            )
    for predicate, cls in _PK_RULES:
        if predicate(pk, sk):
            return cls
    raise KeyError(f"phase_taxonomy: unclassified pk {pk!r} (sk={sk!r}). Add a rule to _PK_RULES.")


# ── Derived sets the restart tools consume (replaces their hand-rolled lists) ──


def is_taggable(cls: str) -> bool:
    """EXPERIMENT_SCOPED is tagged pilot/experiment at restart. RAW_TIMESERIES may
    be tagged (harmless) but isn't required. CROSS_PHASE / SYSTEM_STATE never."""
    return cls == EXPERIMENT_SCOPED


def is_wipeable(cls: str) -> bool:
    """Only EXPERIMENT_SCOPED records are archived (tombstoned + cycle-stamped)."""
    return cls == EXPERIMENT_SCOPED


def never_touch(cls: str) -> bool:
    """CROSS_PHASE and SYSTEM_STATE are invisible to the phase machinery."""
    return cls in (CROSS_PHASE, SYSTEM_STATE)


# Convenience: the experiment-scoped SOURCE names (for the wipe's source iteration).
SCOPED_SOURCES = tuple(sorted(s for s, c in SOURCE_CLASS.items() if c == EXPERIMENT_SCOPED))
CROSS_PHASE_SOURCES = tuple(sorted(s for s, c in SOURCE_CLASS.items() if c == CROSS_PHASE))
SYSTEM_STATE_SOURCES = tuple(sorted(s for s, c in SOURCE_CLASS.items() if c == SYSTEM_STATE))
RAW_TIMESERIES_SOURCES = tuple(sorted(s for s, c in SOURCE_CLASS.items() if c == RAW_TIMESERIES))
