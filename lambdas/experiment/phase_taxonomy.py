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
        from common.constants import EXPERIMENT_PHASE_CURRENT

        stamp["phase"] = EXPERIMENT_PHASE_CURRENT
    try:
        from coach.coach_checkin import read_cycle  # cached, fail-soft SSM read (CHECKIN# precedent)

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
    "time_affluence": RAW_TIMESERIES,  # #1408: Time-Affluence Meter — weekly 1-item probe (DATE# rows, a
    # logged self-report fact, the durable spine) PLUS idempotently-recomputable derived rows (PROXY#/EDGE#
    # written weekly by the hypothesis engine). Classed with its probe like felt_probe/macrofactor_meals: the
    # derived rows recompute from scratch each Sunday, so keeping them across a reset costs nothing and they
    # stay date-stamped/navigable. NB: pk carries non-DATE# suffixes (PROXY#<sunday>, EDGE#<sunday>) —
    # _source_of() resolves them all to this entry.
    "flourishing": RAW_TIMESERIES,  # #1403: daily PERMA projection over journal enrichment (flourishing.py) — fact layer, follows the notion parent
    "todoist": RAW_TIMESERIES,
    "weather": RAW_TIMESERIES,
    "macrofactor": RAW_TIMESERIES,
    "macrofactor_workouts": RAW_TIMESERIES,  # #485: dead ~4mo (no writer) — historical rows kept, still exported
    "hevy": RAW_TIMESERIES,  # live strength source (hourly, ADR-060) — #485 repointed brief/digest here
    "notion": RAW_TIMESERIES,  # journal entries — user-authored facts
    "journal_quotes": RAW_TIMESERIES,  # #1568/ADR-142: consent-per-line verbatim quote marks — owner
    # consent artifacts frozen at mark time (exact approved text). Follows the notion parent: kept
    # forever, genesis-anchored on read; revocation is an explicit unmark, never a reset wipe.
    "youtube": RAW_TIMESERIES,  # #1669: inbound social — Matthew's own posts, a logged fact layer
    "bluesky": RAW_TIMESERIES,  # #1676: inbound social — Matthew's own posts, a logged fact layer
    "mastodon": RAW_TIMESERIES,  # #1676: inbound social — Matthew's own posts, a logged fact layer
    # (kept forever, genesis-anchored on read) like notion; provenance (`origin`) lives on the row.
    "food_delivery": RAW_TIMESERIES,  # behavioral archive (incl. longest-ever streak)
    "sick_days": RAW_TIMESERIES,
    "measurements": RAW_TIMESERIES,  # ADR-077 dec B: body fact like weight; GA, not hidden
    "day_grade": RAW_TIMESERIES,  # ADR-077 dec C: keep series for Replay; GA clamps cockpit
    "state_of_mind": RAW_TIMESERIES,  # affect self-report series
    "mood": RAW_TIMESERIES,
    "evening_ritual": RAW_TIMESERIES,  # ADR-124 one-tap connection self-report (born cycle 11; same class as state_of_mind)
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
    "coach_corrections": CROSS_PHASE,  # #1689 (epic #1687 "The Coach Correction Loop"): Matthew's
    # class-tagged corrections to weekly AI-review-pack items (`lambdas/coach_corrections.py`,
    # pk USER#matthew#SOURCE#coach_corrections / sk CORRECTION#<date>#<id8>). Same rationale as
    # "calibration"/EVALRET#: a correction is a durable statement about the coaching MACHINERY's
    # error, not a property of the current experiment run — wiping it at reset would destroy the
    # exact feedback the prompt-memory/gate/pattern-extraction downstream stages (#1690/#1691/S5/S6)
    # need to keep the same class of error from recurring across cycles.
    # #1384 (epic #1080): the semantic-recall embedding index (Titan-v2 vectors over
    # chronicle/coach/journal docs, one item per doc). CROSS_PHASE is LOAD-BEARING for
    # the feature: cross-reset recall is the entire point ("when did I feel like this
    # before?"), so the index must survive resets and stay visible to a raw Query (no
    # phase filter). Each item carries its own `cycle` stamp, so a precedent from cycle
    # N is still labeled cycle N in cycle N+1 — the archive stays navigable, not wiped.
    "recall_embeddings": CROSS_PHASE,
    "eyeball_estimate": CROSS_PHASE,  # #1390 (epic #1080): meal-photo Haiku macro ESTIMATES + their
    # grades against MacroFactor truth (`lambdas/eyeball_calibration.py`, pk
    # USER#matthew#SOURCE#eyeball_estimate / sk ESTIMATE#|GRADE#<date>#<id8>). Same rationale as
    # "calibration"/"coach_corrections": the reliability record measures the MODEL's eyeballing
    # accuracy across the whole cross-cycle history, not a property of the current run — wiping it
    # at reset would discard the accumulating error distribution the public chart is built on.
    # (These are graded probes, NEVER nutrition data — see the isolation guard in that module.)
    "milestones": CROSS_PHASE,  # #1626: the durable MILESTONE# event ledger (milestone_ledger.py —
    # write-once on first crossing, global cooldown, permanent hysteresis; written by
    # daily-metrics-compute only). CROSS_PHASE, deliberately, and the contrast with
    # "achievements" (EXPERIMENT_SCOPED, below) is the point: a badge asserts present STATE
    # ("you hold a 30-day streak") whose supporting evidence is phase-filtered and resets with
    # the run, so its first-earn record must reset with it (#1624). A milestone event asserts a
    # dated PAST FACT ("the trailing 7-day mean first went under 250 lbs on date D") — true
    # forever regardless of cycle, same family as weight_episodes/calibration. The no-re-fire
    # guarantee ("a rung crossed is a rung consumed, forever") is load-bearing ACROSS resets:
    # wipe this partition and the same rung re-announces in cycle N+1 — exactly the defect
    # #1626 exists to remove. Records carry a cycle stamp only (no phase attribute, the
    # weight_episodes precedent) and ledger reads take NO phase filter.
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
    # #1624: the achievement first-earn ledger (BADGE#<id> — written once, on first
    # crossing, by daily-metrics-compute; read by /api/achievements). EXPERIMENT_SCOPED,
    # deliberately, and the argument is worth keeping: EVERY badge condition is
    # evaluated over phase-filtered, current-cycle data — the Tier 0 streak restarts at
    # 0, the character level returns to 1, completed experiments and challenges are
    # tombstoned. A CROSS_PHASE first-earn would therefore keep asserting "Week Warrior,
    # earned 2026-03-14" while the streak that earned it is hidden from the very same
    # endpoint: a claim whose evidence the site has withdrawn. That is the mirror image
    # of the dishonesty #1624 exists to remove. Same shape as "ledger" above — the
    # per-cycle record resets, and the wipe cycle-stamps it so cycle N's badges stay
    # navigable in the archive rather than being destroyed.
    "achievements": EXPERIMENT_SCOPED,
    "diary_reactions": EXPERIMENT_SCOPED,  # #1574/#1756/#1675: the coach's short public reaction to
    # something Matthew said — a V3-consented Video Diary / Solo Recording entry, or (#1675) a
    # membrane-cleared public social post (coach/coach_diary_reaction.py, sk
    # DATE#<date>#<channel>#<entry_uid>). ONE partition for both channels, deliberately: the
    # reaction machinery is shared, so its reset semantics are shared too and #1675 needed no new
    # registration here. Derived coach NARRATIVE — same class as every other generated coach
    # output (ai_analysis, chronicle, state_of_matthew): it is written against the current cycle's
    # coaching voice and reads back through the phase-filtered /api/diary_reactions query, so it
    # tags + tombstones + cycle-stamps at restart. NB the SOURCE RECORD it reacts to (notion, or
    # the ingested social post) is RAW_TIMESERIES and is kept forever — the human's words survive
    # the reset; only the machine's reaction to them resets with the run.
    "diary_claims": EXPERIMENT_SCOPED,  # #1841: the on-tape claims ledger — falsifiable claims the
    # SUBJECT made on camera, code-admitted by diary_claims.admit_claim and graded by the same daily
    # coach-prediction-evaluator as every coach prediction (sk PREDICTION#<stated_date>#<slug>).
    # EXPERIMENT_SCOPED for the same reason predictions are: a claim is a forecast about THIS run's
    # cycle ("if I get through the next 30, 60 days"), its grade-by date is anchored to this
    # experiment's calendar, and its verdict is only meaningful against this cycle's data. A restart
    # cycle-stamps and tombstones it so cycle N's on-tape record stays navigable in the archive. NB
    # the SOURCE ENTRY the claim points at (notion) is RAW_TIMESERIES and is kept forever — his words
    # survive the reset; only the ledger's forecast bookkeeping resets with the run.
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
    "qa_predict_dark": SYSTEM_STATE,  # #1953: qa-smoke's predict-the-week dark-streak counter (one
    # STATE#predict_dark row) — pure nightly-QA bookkeeping; a reset moves genesis, so the check's own
    # live-cycle gate goes fail-closed-ok and any stale streak self-expires (non-consecutive => 1).
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
    (lambda pk, sk: pk == "ENSEMBLE#docket", EXPERIMENT_SCOPED),  # #1386 dispute docket (OPEN#/RESOLVED#)
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
    # #1670: the outbound-broadcast ledger (BROADCAST_ORIGIN#{channel} / POST#{post_id}).
    # Provenance truth that must survive a reset (a platform post from cycle N is still
    # platform-authored in cycle N+1) and is never run intelligence — so SYSTEM_STATE:
    # the phase machinery ignores it entirely (no tag, no wipe, no filter), like SUBSCRIBE#.
    (lambda pk, sk: pk.startswith("BROADCAST_ORIGIN#"), SYSTEM_STATE),
    # #1845: the diary-publication ledger (DIARY_PUBLISH#{channel} / POST#{post_id}) —
    # which cut of which session went to which surface, and the entry it came from.
    # SYSTEM_STATE for the same reason as BROADCAST_ORIGIN# above: publication is
    # historical fact, not run intelligence. A cut published in cycle 11 was still
    # published in cycle 12, and wiping the ledger at a reset would orphan the inbound
    # posts already stamped with its provenance. Distinct partition from
    # BROADCAST_ORIGIN# on purpose — a diary cut is Matthew on camera, published by
    # hand, NOT a platform-authored syndication echo (see lambdas/diary_publish.py).
    (lambda pk, sk: pk.startswith("DIARY_PUBLISH#"), SYSTEM_STATE),
    (lambda pk, sk: pk.startswith("VOTES#"), SYSTEM_STATE),
    (lambda pk, sk: pk.startswith("EXPERIMENT_FOLLOWS"), SYSTEM_STATE),
    # #1394/#1819: the cohort-strip pool (COHORT#{metric}#{week} / SUBMIT#{ip_hash}) —
    # anonymous reader-submitted single numbers pooled into a k-anonymity histogram.
    # SYSTEM_STATE, not EXPERIMENT_SCOPED: this is audience data about the READER
    # population (like VOTES#/CHALLENGE_FOLLOWS above), not Matthew's own
    # experiment-derived intelligence — a submitted number isn't invalidated by a
    # cycle boundary the same way a derived score is, and the weekly cohort_config
    # key can straddle a reset. The phase machinery ignores it entirely (no tag, no
    # wipe, no filter): unclassified, this pk family raises KeyError in
    # restart_pipeline.py's step-0 census preflight the moment the first reader
    # submits — blocking every future reset until the fix lands (the bug this rule
    # closes, filed adversarially before any live COHORT# row existed).
    (lambda pk, sk: pk.startswith("COHORT#"), SYSTEM_STATE),
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


# ── #2113: the read-side companion to is_wipeable ────────────────────────────
#
# `is_wipeable` answers "does the reset ARCHIVE this?". Nothing answered the
# obvious sibling — "may a reader still present this as CURRENT?" — so every
# generic reader in the codebase decided for itself, and one of them decided
# wrong. `ai_expert_analyzer_lambda._latest_item` reads `computed_metrics` with an
# unbounded newest-first `Limit: 1`, so in the hours after cycle 12's genesis
# (before that day's daily-metrics-compute had run) it returned the pilot-tagged
# 08-02 record. `grounded_generation.authoritative_facts_block` rendered it as
# "Latest Whoop recovery: 59%" under a hard rule telling the narrator to state
# that exact value, and the sleep and training cards published 59% recovery /
# 42 ms HRV against a cockpit serving 44% / 35 ms — under a "day one" frame.
#
# The class registry already held the answer; the read never asked it. Putting the
# rule HERE rather than in the caller is the point: a reader added later inherits
# the right behaviour from the source's own class instead of from whoever wrote
# the call, and there is exactly one definition to keep honest.
#
# The bound is a KEY floor, deliberately, never a FilterExpression. DynamoDB
# applies `Limit` BEFORE a filter (#1203/#2089), so filtering a `Limit: 1` read
# would drop the newest row for reasons unrelated to the cycle.
#
# Only EXPERIMENT_SCOPED is bounded:
#   * EXPERIMENT_SCOPED is exactly what the reset tombstones — a pre-genesis row
#     does not speak for this cycle.
#   * CROSS_PHASE (labs, dexa) and SYSTEM_STATE (journal_analysis) are invisible
#     to the phase machinery and are read across cycles BY DESIGN — the labs coach
#     reads full draw history on purpose.
#   * RAW_TIMESERIES keeps whatever window the caller asked for: the body's
#     timeseries does not reset when the experiment does, and the date window is
#     what bounds it, not the phase tag (#2089).


def reads_current_cycle_only(pk: str, **kw) -> bool:
    """True when a read for `pk` must be bounded to the current cycle (#2113).

    Fail-soft and conservative in the SAFE direction: `classify` raises on an
    unknown source by design, so nothing defaults silently — an unclassified
    source keeps whatever window the caller asked for rather than being narrowed
    by a rule that has not actually been applied to it.
    """
    try:
        return classify(pk, **kw) == EXPERIMENT_SCOPED
    except Exception:  # noqa: BLE001 — unknown/unclassifiable: leave the read alone
        return False


def cycle_read_floor(pk: str, floor: str | None = None, genesis: str | None = None) -> str | None:
    """The earliest date a read of `pk` may return, or `floor` unchanged.

    Returns the later of `floor` and the current cycle's genesis for
    EXPERIMENT_SCOPED partitions; `floor` untouched for every other class. Pass
    ``floor=None`` for an unbounded reader to get back either the genesis (bound
    it) or None (leave it unbounded).

    `genesis` is resolved at CALL time from the live ``EXPERIMENT_START_DATE`` so
    a re-anchor — or a test's monkeypatch — lands without a module reload. ISO
    dates compare correctly as strings, so no parsing is needed.
    """
    if not reads_current_cycle_only(pk):
        return floor
    if genesis is None:
        try:
            from common import constants as _c

            genesis = str(_c.EXPERIMENT_START_DATE)
        except Exception:  # noqa: BLE001 — fail-soft: never break a read over this
            return floor
    return max(floor, genesis) if floor else genesis


# Convenience: the experiment-scoped SOURCE names (for the wipe's source iteration).
SCOPED_SOURCES = tuple(sorted(s for s, c in SOURCE_CLASS.items() if c == EXPERIMENT_SCOPED))
CROSS_PHASE_SOURCES = tuple(sorted(s for s, c in SOURCE_CLASS.items() if c == CROSS_PHASE))
SYSTEM_STATE_SOURCES = tuple(sorted(s for s, c in SOURCE_CLASS.items() if c == SYSTEM_STATE))
RAW_TIMESERIES_SOURCES = tuple(sorted(s for s, c in SOURCE_CLASS.items() if c == RAW_TIMESERIES))


# ─────────────────────────────────────────────────────────────────────────────
# The pre-registered-bet ledger invariant (#1978)
# ─────────────────────────────────────────────────────────────────────────────
# EXPERIMENT_SCOPED bets (HYPOTHESIS# rows, coach PREDICTION# rows) are tombstoned
# by the wipe, which hides them from every phase-filtered read forever. ADR-077
# justifies that on the promise that the outcome survives in the CROSS_PHASE
# calibration ledger, and #1199 made the reset keep that promise going forward.
#
# But "forward" was doing load-bearing work: nothing ever ASSERTED the promise, so
# a bet that slipped past the void step (anything tombstoned before #1199 landed,
# plus anything whose void row got clobbered — see void_row_sk) went phase-hidden
# while still `pending`, unreachable by the grader and absent from the ledger. That
# is a pre-registered bet the platform made and then quietly stopped counting.
#
# The invariant, stated once and enforced by find_unvoided_open_bets():
#
#     no record may be BOTH open-status AND tombstoned AND absent from the
#     calibration void ledger — every bet resolves to graded or voided.
#
# Same posture as classify()'s unknown-source KeyError: the registry refuses to let
# a case default silently. Deliberately pure (no boto3, no I/O) so the reset tools,
# the reconcile script and the test suite all assert the identical rule.

# Statuses that mean "this bet has not resolved yet". Everything else (confirmed,
# refuted, inconclusive, archived, …) is a terminal grade and needs no void row.
OPEN_BET_STATUSES = frozenset({"pending", "confirming"})

# kind → the calibration ledger's record_type for its void row.
VOID_RECORD_TYPES = {"hypothesis": "hypothesis_void", "prediction": "prediction_void"}

# The date #1199 (grade-or-void at reset) landed. Used only to CLASSIFY an orphan as
# historical-backlog vs. a live escape — never to excuse one.
PREREG_VOID_FIX_LANDED = "2026-07-17"


def is_open_bet(item: dict) -> bool:
    """True when a bet's status is still unresolved (no terminal grade)."""
    return str(item.get("status", "")).strip().lower() in OPEN_BET_STATUSES


def bet_registered_at(kind: str, bet: dict) -> str:
    """The bet's own pre-registration stamp — the half of its identity that its
    slug does NOT carry.

    Mirrors what restart_pipeline.build_void_calib_item writes into the void row's
    `pre_registered_at`, so a bet and its ledger row agree by construction:
    hypotheses use pre_registered_at (falling back to created_at for rows written
    before the field existed), predictions use created_date.
    """
    if kind == "hypothesis":
        return str(bet.get("pre_registered_at") or bet.get("created_at") or "")
    return str(bet.get("created_date") or bet.get("created_at") or "")


def bet_id_of(kind: str, bet: dict) -> str:
    """The bet's slug, falling back to the sk suffix (mirrors build_void_calib_item)."""
    prefix = "HYPOTHESIS#" if kind == "hypothesis" else "PREDICTION#"
    field = "hypothesis_id" if kind == "hypothesis" else "prediction_id"
    return str(bet.get(field) or str(bet.get("sk", "")).replace(prefix, ""))


def bet_ledger_key(kind: str, bet: dict) -> tuple:
    """Identity of a bet IN the calibration ledger: (record_type, coach, id, registered_at).

    The registration stamp is part of the key on purpose. `hypothesis_id` alone is
    NOT unique — the genesis pre-registration re-uses the same slugs every cycle
    (genesis_prereg_h1/h2), so slug-only matching silently treats one cycle's void
    row as proof that a different cycle's identically-named bet was resolved.
    """
    return (VOID_RECORD_TYPES.get(kind, kind), str(bet.get("coach_id") or ""), bet_id_of(kind, bet), bet_registered_at(kind, bet))


def void_row_ledger_key(row: dict) -> tuple | None:
    """The same identity read off a CALIB# void row, or None if it isn't one."""
    rt = str(row.get("record_type") or "")
    if rt not in VOID_RECORD_TYPES.values():
        return None
    bet_id = str(row.get("hypothesis_id") or row.get("prediction_id") or "")
    return (rt, str(row.get("coach_id") or ""), bet_id, str(row.get("pre_registered_at") or ""))


def void_row_sk(genesis: str, kind: str, bet: dict) -> str:
    """Collision-proof sk for a void row: CALIB#<genesis>#void#<hyp|pred>#<id>[#<8hex>].

    The original #1199 key was (genesis, slug) only — which is why two of the
    post-#1199 orphans exist. The 2026-07-20 reset voided that cycle's genesis
    pre-registration pair, then a same-genesis re-run voided the NEW pair, whose
    slugs are byte-identical (genesis_prereg_h1/h2); the second put_item overwrote
    the first and the earlier pair's only ledger record vanished. Folding a digest
    of the registration stamp into the key makes each bet's row its own, while
    staying idempotent (same bet + same genesis → same sk).
    """
    import hashlib

    tag = "hyp" if kind == "hypothesis" else "pred"
    coach = str(bet.get("coach_id") or "")
    base = f"CALIB#{genesis}#void#{tag}#" + (f"{coach}#" if tag == "pred" else "") + bet_id_of(kind, bet)
    registered = bet_registered_at(kind, bet)
    if not registered:
        return base
    return base + "#" + hashlib.sha256(registered.encode("utf-8")).hexdigest()[:8]


def find_unvoided_open_bets(bets, void_rows) -> list:
    """THE invariant. Return every (kind, bet) that is open-status AND tombstoned AND
    has no matching row in the calibration void ledger — i.e. every pre-registered bet
    the platform hid without ever resolving it. An empty list is the healthy state.

    `bets` is an iterable of (kind, item); `void_rows` is the CALIB# partition.
    Untombstoned open bets are excluded: they are still live and visible to the
    grader, and the reset's own void step is what will resolve them.
    """
    voided = {k for k in (void_row_ledger_key(r) for r in void_rows) if k is not None}
    return [(kind, bet) for kind, bet in bets if is_open_bet(bet) and bet.get("tombstone") and bet_ledger_key(kind, bet) not in voided]


def assert_no_unvoided_open_bets(bets, void_rows) -> int:
    """Raise ValueError naming the breach when the invariant fails; else return 0.

    Same refuse-to-default posture as classify()'s unknown-source KeyError — the
    reset asserts the promise ADR-077 makes instead of assuming it.
    """
    orphans = find_unvoided_open_bets(bets, void_rows)
    if not orphans:
        return 0
    by_kind: dict[str, int] = {}
    for kind, _ in orphans:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
    raise ValueError(
        f"phase_taxonomy: pre-registered-bet ledger invariant BREACHED — {len(orphans)} open+tombstoned "
        f"bet(s) with no calibration void row ({breakdown}). ADR-077 only sanctions hiding a bet if its "
        f"outcome survives in the CROSS_PHASE ledger. Reconcile with "
        f"`python3 deploy/reconcile_prereg_voids.py --apply` (#1978), then re-run."
    )


def closing_genesis_of(bet: dict) -> str | None:
    """The genesis of the reset that tombstoned this bet, from its own provenance.

    The wipe writes `tombstoned_reason = experiment_restart_<YYYY-MM-DD>`; the
    `tombstoned_at` date is the fallback. Returns None when neither is readable —
    the caller must then void with an explicitly unknown stamp rather than guess
    (ADR-104: an unknown provenance is reported, never invented).
    """
    import re as _re

    m = _re.search(r"experiment_restart_(\d{4}-\d{2}-\d{2})", str(bet.get("tombstoned_reason") or ""))
    if m:
        return m.group(1)
    stamp = str(bet.get("tombstoned_at") or "")[:10]
    return stamp if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp) else None


def closing_cycle_for_genesis(genesis: str | None, cycle_geneses: dict) -> int | None:
    """The cycle that a reset CLOSED, given the genesis it opened.

    `cycle_geneses` maps cycle number → genesis date (site_api_data.CYCLE_GENESES).
    The reset that opens cycle N closes cycle N-1 — which is exactly the number the
    wipe stamps onto the records it archives. Returns None for an unregistered or
    unknown genesis (cycle 1 has no predecessor).
    """
    if not genesis:
        return None
    for cycle, gen in cycle_geneses.items():
        if gen == genesis:
            return int(cycle) - 1 if int(cycle) > 1 else None
    return None
