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
alongside `phase=pilot` + `tombstone=true`.

At write time, the intelligence output writers on the tagger-blind partitions
stamp their own provenance via `experiment_stamp()` (#1233):
  - COACH#* (OUTPUT#/TRACE#/VOICE#/COMMITMENT#/STANCE#/… via coach_state_updater +
    coach_history_summarizer), ENSEMBLE#* and COACH#computation RESULTS# (via
    coach_ensemble_digest + coach_computation_engine) carry `phase=<current>` +
    `cycle=<current>`.
  - NARRATIVE#arc (coach_computation_engine) carries `cycle=<current>` ONLY — that
    partition's `phase` attribute is the narrative-arc STATE, not the taxonomy
    phase, so it is left intact.
Other experiment_scoped writers (e.g. daily INSIGHT# rows) still rely on the
wipe/tagger for provenance. The stamp is read-safe: the current phase value matches
the `with_phase_filter` current-phase clause, so a freshly stamped row stays visible
exactly as an unstamped one did.

v1.0.0 — 2026-06-07 (ADR-077; supersedes the ad-hoc lists in the restart tools)
v1.1.0 — 2026-07-18 (#1233; add experiment_stamp() for write-time provenance)
"""

from __future__ import annotations


def experiment_stamp(ssm_client=None, include_phase: bool = True) -> dict:
    """Write-time provenance stamp for EXPERIMENT_SCOPED intelligence writes (#1233).

    Returns ``{"phase": <current>, "cycle": <n>}`` (phase from
    constants.EXPERIMENT_PHASE_CURRENT) so records on the tagger-blind
    COACH#/ENSEMBLE#/NARRATIVE# partitions describe their own reset generation at
    write time, instead of provenance resting entirely on the reset-time wipe.

    Pass ``include_phase=False`` for the NARRATIVE#arc partition, whose `phase`
    attribute already means the narrative-arc STATE (e.g. "building"), NOT the
    taxonomy phase — those records take the cycle stamp only so the arc semantic is
    preserved.

    The cycle is read from SSM /life-platform/experiment-cycle via
    ``coach_checkin.read_cycle()`` — cached once per warm container (the cycle only
    changes on a reset), so this adds no per-put_item SSM call after the first read.

    Fail-soft, by contract: if the cycle can't be read (missing param/grant, no AWS,
    import failure) the stamp carries ``phase`` only (or nothing when include_phase
    is False), and this NEVER raises. A provenance stamp must never break a write.
    """
    stamp: dict = {}
    if include_phase:
        from constants import EXPERIMENT_PHASE_CURRENT

        stamp["phase"] = EXPERIMENT_PHASE_CURRENT
    try:
        from coach_checkin import read_cycle  # cached, fail-soft SSM read (CHECKIN# precedent)

        cycle = read_cycle(ssm_client)
        if cycle is not None:
            stamp["cycle"] = int(cycle)
    except Exception:  # noqa: BLE001 — fail-soft: provenance never breaks a write
        pass
    return stamp


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
    "habit_causality": RAW_TIMESERIES,  # #422: user-authored why/trigger/reward per habit-day — a logged fact, kept forever
    "private_intake": RAW_TIMESERIES,  # #1405: Matthew-private evening intake count — logged fact, cross-cycle physiology, NEVER public-served
    "felt_probe": RAW_TIMESERIES,  # #1409: weekly felt-reality probe (Sunday one-tap, 0-4×3) — self-report fact; calibration reads it cycle-stamped
    "flourishing": RAW_TIMESERIES,  # #1403: daily PERMA projection over journal enrichment (flourishing.py) — fact layer, follows the notion parent
    "todoist": RAW_TIMESERIES,
    "weather": RAW_TIMESERIES,
    "macrofactor": RAW_TIMESERIES,
    "macrofactor_workouts": RAW_TIMESERIES,  # #485: dead ~4mo (no writer) — historical rows kept, still exported
    "hevy": RAW_TIMESERIES,  # live strength source (hourly, ADR-060) — #485 repointed brief/digest here
    "notion": RAW_TIMESERIES,  # journal entries — user-authored facts
    "food_delivery": RAW_TIMESERIES,  # behavioral archive (incl. longest-ever streak)
    "sick_days": RAW_TIMESERIES,
    "measurements": RAW_TIMESERIES,  # ADR-077 dec B: body fact like weight; GA, not hidden
    "day_grade": RAW_TIMESERIES,  # ADR-077 dec C: keep series for Replay; GA clamps cockpit
    "state_of_mind": RAW_TIMESERIES,  # affect self-report series
    "mood": RAW_TIMESERIES,
    "travel": RAW_TIMESERIES,
    "interactions": RAW_TIMESERIES,
    "exposures": RAW_TIMESERIES,
    "temptations": RAW_TIMESERIES,  # accountability/identity log (resisted-temptation facts)
    "macrofactor_meals": RAW_TIMESERIES,  # #951: derived meal projection over the raw macrofactor
    # food log (meal_projection.py — idempotent, never mutates raw). It's a fact layer (meals
    # eaten), so it follows its parent partition's class: kept forever, genesis-anchored on read.
    "training_notes": RAW_TIMESERIES,  # #951: exercise-keyed projection of Matthew's own Hevy
    # notes (training_notes.py — "frozen-as-data", raw sovereign). User-authored facts like
    # notion; follows the raw hevy parent. NB pk carries a suffix (…#training_notes#EXERCISE#<id>,
    # plus #CACHE/#USAGE LLM bookkeeping) — _source_of() resolves all of them to this entry.
    "food_responses": RAW_TIMESERIES,  # #951: logged per-food glycemic-response facts (MCP/CGM)
    "life_events": RAW_TIMESERIES,  # #951: user-logged life-event annotations (site vitals timeline)
    "ruck_log": RAW_TIMESERIES,  # #951: logged ruck workouts (MCP)
    # — CROSS_PHASE: clinical truths + durable anchors (never touch) —
    "labs": CROSS_PHASE,
    "dexa": CROSS_PHASE,
    "genome": CROSS_PHASE,
    "supplements": CROSS_PHASE,  # ADR-077 dec A: medication-safety — never hide
    "chronicling": CROSS_PHASE,  # ADR-077 dec D: frozen pre-platform "before" archive
    "subscribers": CROSS_PHASE,  # audience identity
    "calibration": CROSS_PHASE,  # #530/ADR-105: hypothesis-resolution ledger — the engine's
    # long-run scoreboard ("do high-confidence bets confirm more often?") is a measurement of
    # the PLATFORM, not of a cycle; wiping it at reset would destroy the only data that can
    # answer the calibration question. Rows carry pre_registered_at so per-cycle views filter by date.
    "benchmarks": CROSS_PHASE,  # BENCH-1 (ADR-089): cut-benchmarking history — each row is a
    # completed-cut episode measured against the literature. Like "calibration", it's a long-run
    # cross-cycle record (the whole point is comparing cuts across resets), so it survives every reset.
    "weight_episodes": CROSS_PHASE,  # #930/#951: BENCH-1 detected loss/regain episodes over the
    # full 14-year withings history (episode_detect_lambda). The writer's contract is explicit:
    # cross-phase reference data, written WITHOUT a phase attribute so a reset never wipes them —
    # same rationale as "benchmarks" (comparing cuts across resets is the point).
    "training_reference": CROSS_PHASE,  # #930/#951: BENCH-1 proven by-band prescription singleton,
    # derived from the same 14-year history — cross-phase reference like weight_episodes.
    "effect_fits": CROSS_PHASE,  # #1411/ADR-105: quarterly cross-pillar effect fits (FIT#<date> —
    # lagged-pair r, block-bootstrap CI, BH-FDR, n_eff, fitted|authored-prior verdicts). Like
    # "calibration", it measures the PLATFORM's priors against the whole cross-cycle history —
    # wiping it at reset would un-earn every badge and destroy the only record of priors that
    # failed to confirm (/method/wrong publishes those as findings).
    # — EXPERIMENT_SCOPED: derived intelligence/progress (tag + wipe + cycle-stamp) —
    "character_sheet": EXPERIMENT_SCOPED,  # RPG-style derived scores; wiped "all" + rebuilt
    "character_receipt": EXPERIMENT_SCOPED,  # #1373: audit-grade progression receipts — one per
    # character_sheet compute day (inputs + rule outputs + replay digest). Derived from the same
    # run as its sheet, so it follows character_sheet's class exactly: tagged + tombstoned +
    # cycle-stamped at restart, phase-filtered on read. Dated drill-down reads may include
    # archived receipts deliberately (history is cross-cycle, provenance-labeled).
    "habit_scores": EXPERIMENT_SCOPED,  # see vice_streaks split note in ADR-077 dec G
    "computed_metrics": EXPERIMENT_SCOPED,
    "forecast": EXPERIMENT_SCOPED,  # #541: daily EWMA expectations — derived, recomputed every
    # morning; graded outcomes live in the CROSS_PHASE calibration ledger, so wiping the raw
    # forecasts at reset loses nothing the scoreboard needs.
    "state_of_matthew": EXPERIMENT_SCOPED,  # #552: weekly synthesis of forecast+hypotheses+
    # coach-consensus+calibration into one narrated brief — derived, recomputed weekly; nothing
    # it cites is lost by wiping it (the source records it summarizes have their own classes).
    "computed_insights": EXPERIMENT_SCOPED,
    "adaptive_mode": EXPERIMENT_SCOPED,
    "engagement_state": EXPERIMENT_SCOPED,  # presence / quiet-stretch state; resets with the cycle
    "circadian": EXPERIMENT_SCOPED,
    "anomalies": EXPERIMENT_SCOPED,
    "weekly_correlations": EXPERIMENT_SCOPED,
    "scenarios": EXPERIMENT_SCOPED,  # #550: nightly what-followed distributions — recomputed daily
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
    "sleep_unified": SYSTEM_STATE,  # dead: #487/ADR-113 retired the reconciler — no writer, no
    # reader. Orphan records kept (never wiped/served); classed here so the reset tooling still
    # traverses them without raising. Was RAW_TIMESERIES when the reconciler wrote it.
    "coach_gen_cache": SYSTEM_STATE,  # #951: gate-passed generation cache (generation_cache.py,
    # ADR-126) — one overwritten row per (coach, output_type); the semantic fingerprint self-busts
    # on any input change (incl. a reset), so the phase machinery can ignore it.
    "ingest_liveness": SYSTEM_STATE,  # #951: daily pipeline-health snapshot (pipeline_health_check)
    "personal_baselines": SYSTEM_STATE,  # #951: SNAPSHOT#LATEST percentile bands (#543/ADR-105) —
    # fully recomputable monthly from raw_timeseries; consumers floor-guard to constants if absent.
    "deletion_log": SYSTEM_STATE,  # #951: USER#admin GDPR-deletion audit records
    # (delete_user_data_lambda) — ops audit trail, never traversed by the restart tooling.
    "experiment_suggestions": SYSTEM_STATE,  # #951: reader-submitted suggestions awaiting
    # moderation (site_api_social) — audience state like VOTES#/CHALLENGE_FOLLOWS, kept across resets.
    "email_digest": SYSTEM_STATE,  # #951: between-chronicle digest change-marker
    # (between_chronicle_lambda, STATE#between_chronicle) — pure dedup state.
}

# platform_memory is split BY CATEGORY: durable user facts are cross-phase;
# coach running-state categories are experiment-scoped (tombstoned at restart).
# The split MUST agree with the `durable` flag in the canonical category
# registry (lambdas/platform_memory.py, #1482) — drift gate in
# tests/test_platform_memory_block.py.
MEMORY_DURABLE_CATEGORIES = frozenset(
    {
        "baseline_snapshot",
        "re_entry",
        "cycle_marker",
        "cycle",
        # #1482 conversation-derived durable user facts — qualitative life
        # context survives an experiment reset (same reasoning as CHECKIN#).
        "life_context",
        "constraints_preferences",
    }
)
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
    (lambda pk, sk: pk == "ENSEMBLE#dispute", EXPERIMENT_SCOPED),  # #540 inter-coach threads
    (lambda pk, sk: pk == "ENSEMBLE#influence_graph", SYSTEM_STATE),  # static config
    (lambda pk, sk: pk == "NARRATIVE#arc", EXPERIMENT_SCOPED),
    # #946: Elena's narrative running state (open THREADs, pending CALLBACKs,
    # MOTIF#state, STANCE#) is per-cycle story continuity — pending callbacks
    # surviving a reset would "pay off" promises the new cycle's readers never
    # saw. Classified per-persona for now; the general PERSONA#* class ruling
    # stays with #930.
    (lambda pk, sk: pk == "PERSONA#elena", EXPERIMENT_SCOPED),
    # #545: the blind voice-fidelity scoreboard measures the COACHING ENGINE's design
    # (can a blind panel tell coaches apart), not a property of the current experiment
    # run — same rationale as the CROSS_PHASE "calibration" source (SOURCE_CLASS above):
    # it's a long-run scoreboard that must survive a reset, even though the OUTPUT#
    # records it samples FROM (pk COACH#*, above) are themselves experiment-scoped.
    (lambda pk, sk: pk.startswith("VOICEFIDELITY#"), CROSS_PHASE),
    # #812/#744: retained ADR-104 gate verdict/regeneration pairs — the honesty
    # layer's own eval dataset (eval_retention.py, harvested monthly into the
    # golden-surface fixture packs). Same rationale as VOICEFIDELITY# above: it
    # measures the honesty MACHINERY's behavior, not a property of the current
    # experiment run, so it survives a reset. Records carry their own ~180d TTL.
    (lambda pk, sk: pk.startswith("EVALRET#"), CROSS_PHASE),
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
    # Challenge-follow interest records (site_api_social.handle_challenge_follow) —
    # reader emails awaiting a "challenge started" notification. Audience state like
    # SUBSCRIBE#/VOTES#: kept across resets, ignored by the phase machinery.
    (lambda pk, sk: pk.startswith("CHALLENGE_FOLLOWS"), SYSTEM_STATE),
    # ── #930/#951: the ops pk families, classified deliberately (all were previously
    # unclassified — classify() raised). None are traversed by the restart tooling
    # (the tagger scans USER#…#SOURCE# only); these rules make the registry total.
    # Grading-liveness watermark (coach_prediction_evaluator STATE#last_decided) — an
    # ops gauge marker ("days since last decided" alarm input), not run intelligence.
    (lambda pk, sk: pk.startswith("EVALUATOR#"), SYSTEM_STATE),
    (lambda pk, sk: pk.startswith("RATE#"), SYSTEM_STATE),  # per-IP TTL rate buckets (rate_limiter)
    (lambda pk, sk: pk.startswith("BOARDSESS#"), SYSTEM_STATE),  # TTL'd board Q&A sessions (#546)
    (lambda pk, sk: pk.startswith("CANARY#"), SYSTEM_STATE),  # synthetic-monitor state (canary_lambda)
    (lambda pk, sk: pk.startswith("SYSTEM#"), SYSTEM_STATE),  # ops namespace (SYSTEM#dlq-ledger)
    (lambda pk, sk: pk.startswith("OAUTH#"), SYSTEM_STATE),  # TTL'd MCP auth codes + session bearers (#779/#909)
    # Narrator persona state for personas OTHER than Elena (PERSONA#margaret editor
    # state, etc.). Durable narrative identity that deliberately spans cycles — this
    # classification preserves the de-facto behavior (never touched); wiping these
    # personas at reset would be a new decision needing its own wipe wiring (like
    # ENSEMBLE#dispute in #918), not a default.
    #   NB (#1248): PERSONA#elena is the EXCEPTION and is handled by the earlier
    #   first-match rule above (EXPERIMENT_SCOPED, #946) — her per-cycle story state
    #   (open THREADs, pending CALLBACKs) is wiped at reset, NOT carried across cycles.
    #   (The prior comment here wrongly claimed the reset "carried Elena straight into
    #   EP0"; DDB confirms all PERSONA#elena rows tombstone at restart. The general
    #   PERSONA#* class ruling stays with #930.)
    (lambda pk, sk: pk.startswith("PERSONA#"), CROSS_PHASE),
]


def _source_of(pk: str) -> str | None:
    """Return the base <source> from a USER#...#SOURCE#<source> pk, else None.

    Some families carry a suffix after the base source — the part after the first
    '#' is a sub-key, not a distinct source: email_log#<type> (email type),
    training_notes#EXERCISE#<id> / #CACHE / #USAGE (per-exercise partitions + LLM
    bookkeeping). The base is everything before the first '#'.
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
