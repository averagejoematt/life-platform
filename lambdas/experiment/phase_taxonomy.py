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

Ruling — provenance in a no-reset world (#4040, 2026-09-22)
-------------------------------------------------------------
Under the owner's 2026-09-21 no-further-resets ruling (ADR-077 amendment, PR #4037),
`deploy/restart_phase_tag.py` (the tagger) never runs again as part of a reset, and it
was the ONLY thing that stamped `phase=pilot` onto a pre-genesis `EXPERIMENT_SCOPED`
row. A row written after the tagger's last run, dated before genesis, keeps whatever
phase it was born with (often none, sometimes the CURRENT phase constant) forever —
measured 2026-09-22: 16 such rows over 45,896 scanned (`deploy/restart_verify.py`'s
#3513 check).

**Standing home: the nightly leg, not write-time-only.** `experiment_stamp_for` (below)
remains the right call for any writer that can itself emit a back-dated row — the
chronicle publish path, `anomalies`, `recap_cards` — but it only helps writers that call
it, going forward. It cannot repair a row a writer already emitted wrong, and it does
nothing for a writer nobody has touched. `data:coach_ensemble_phase_stamp_coverage`
(`lambdas/operational/qa_smoke_lambda.py`) is therefore widened to WARN, by name and with
rows, on any `EXPERIMENT_SCOPED` row dated before genesis whose `phase` is not `pilot` —
whether unstamped or mis-stamped — every night, so a recurrence is a WARN, never silence
(`experiment.pk_census.scoped_stamp_audit`'s `mis_stamped` leaf). The nightly leg is
READ-ONLY, matching every other leg in that module; the correction itself is
`deploy/phase_stamp_sweep.py` (dry-run by default, `--apply` to write), which Queries
each `EXPERIMENT_SCOPED` SOURCE# partition individually (bounded per-family reads, never
a full-table scan) and sets `phase=pilot` on any row dated before genesis that isn't
already `pilot`. One-off `restart_phase_tag.py --apply` remains an acceptable FIRST run
over the historical backlog; the sweep script (or the nightly WARN + an operator running
it) is the standing mechanism from here.

**Served-lead-in exemption.** A chronicle row is not "pre-genesis and current" merely
because its `sk` predates genesis — a reset re-dates a carried-forward lead-in by writing
a new `date` ATTRIBUTE and leaving the `sk` alone (`lambdas/operational/
chronicle_manifest_qa.py`, #3650), so a served lead-in's `sk` can be a year old while its
`date` attribute (and the live journal manifest) say otherwise. **Incident, 2026-09-22:**
`deploy/reconcile_countdown_gap.py --apply` tombstoned the served `DATE#2026-09-05`
lead-in on exactly this reasoning ("pre-genesis, therefore stale"); both
`chronicle:manifest_provenance` and `recall:corpus_freshness` went red 14h later because
the live manifest kept serving the now-archived row and every later post's derived
`/journal/posts/week-N/` sequence shifted. The stamp was reverted the same night. RULING:
a chronicle row the manifest QA's own matcher (`chronicle_manifest_qa._match`, keyed on
the served post's `date` + `title`, exposed as `served_chronicle_keys`) resolves to a
live post is CURRENT by design regardless of its `sk` date, and is excluded from both the
nightly WARN and the sweep script by construction — never guessed at, never reconciled
away. Only a chronicle row the manifest does NOT serve is a candidate for correction.

v1.0.0 — 2026-06-07 (ADR-077; supersedes the ad-hoc lists in the restart tools)
v1.1.0 — 2026-07-18 (#1233; add experiment_stamp() for write-time provenance)
v1.2.0 — 2026-09-05 (#3598; the stamp derives phase + cycle from the WRITE'S DATE
          against CYCLE_GENESES — a countdown-window write is pilot/closing-cycle,
          never the experiment)
v1.3.0 — 2026-09-22 (#4040; the no-reset-world provenance ruling above — the nightly
          leg is the standing home, `pre_genesis_scoped_violation` is the shared
          predicate, served chronicle lead-ins are exempt by construction)
v1.4.0 — 2026-09-22/23 (#4059; a row's PHASE-PROVENANCE date is its creation/opening
          instant — `created_at` / `opened_date` / an sk-embedded timestamp — never an
          `outcome_date`, `resolved_at`, a re-stamped `cycle`, or a content-reference
          `date`. `provenance_date()` below is the one derivation the tagger, check 21,
          the nightly leg and `phase_stamp_sweep.py` all read; the sweep's surface was
          widened to Query the COACH# partitions it used to miss entirely.)
"""

from __future__ import annotations

_GENESES_CACHE: dict = {"value": None}
_ABANDONED_CACHE: dict = {"value": None}


def _cycle_geneses() -> dict | None:
    """The cycle → genesis registry (site_api_data.CYCLE_GENESES), imported lazily
    and fail-soft like coach_domain_facts / og_moments do. Only a successful import
    is cached (the #1948 rule: a failed read must not latch). None when unavailable."""
    if _GENESES_CACHE["value"] is None:
        try:
            from web.site_api_data import CYCLE_GENESES

            _GENESES_CACHE["value"] = {int(k): str(v)[:10] for k, v in CYCLE_GENESES.items()}
        except Exception:  # noqa: BLE001 — provenance never breaks a write
            return None
    return _GENESES_CACHE["value"]


def _abandoned_geneses() -> dict | None:
    """The abandoned-genesis alias map (site_api_data.ABANDONED_GENESES): a genesis date
    that was WRITTEN into the record and then re-anchored -> the cycle it was opening.

    Imported lazily and fail-soft exactly like `_cycle_geneses` above, and cached only on
    success (the #1948 rule: a failed read must not latch). None when unavailable — which
    degrades a resolution to "unknown", never to a wrong cycle."""
    if _ABANDONED_CACHE["value"] is None:
        try:
            from web.site_api_data import ABANDONED_GENESES

            _ABANDONED_CACHE["value"] = {str(k)[:10]: int(v) for k, v in ABANDONED_GENESES.items()}
        except Exception:  # noqa: BLE001 — provenance never breaks a write
            return None
    return _ABANDONED_CACHE["value"]


def _write_date() -> str:
    """The write's own calendar day — Pacific, the calendar every genesis is declared in
    (#2506/#2675: the site AND the gate clock are PT; #2811: never a UTC day here). The
    callers wrap this in their fail-soft try, so an import failure costs the phase
    claim, never the write."""
    from common.pacific_time import pacific_today

    return pacific_today()


def cycle_for_date(as_of: str, cycle_geneses: dict | None) -> int | None:
    """The cycle a date belongs to: the highest cycle whose genesis is <= `as_of`
    (the same rule as site_api_freshness._carried_from_cycle, #2002). None for an
    empty/unavailable registry or a date before cycle 1 — reported, never invented."""
    if not cycle_geneses:
        return None
    d = str(as_of)[:10]
    best = None
    for n, genesis in sorted(cycle_geneses.items(), key=lambda kv: str(kv[1])[:10]):
        if d >= str(genesis)[:10]:
            best = int(n)
        else:
            break
    return best


def experiment_stamp(ssm_client=None, include_phase: bool = True, *, as_of: str | None = None, cycle_geneses: dict | None = None) -> dict:
    """Write-time provenance stamp for EXPERIMENT_SCOPED intelligence writes (#1233).

    Returns ``{"phase": <pilot|current>, "cycle": <n>}`` so records on the tagger-blind
    COACH#/ENSEMBLE#/NARRATIVE# partitions describe their own reset generation at
    write time, instead of provenance resting entirely on the reset-time wipe.

    #3598 — BOTH values derive from the write's own date (``as_of``, default: the
    Pacific calendar day the write happens on):
      * ``phase`` is ``pilot`` when ``as_of < EXPERIMENT_START_DATE`` and the current
        phase otherwise. Until this change the stamp returned the constant phase
        unconditionally, so every write in the countdown window between a reset and
        its genesis (10 of the 24 cycle-16 predictions served on Day 1) was stamped as
        the experiment. ``pilot`` is hidden by every existing read filter — no new
        PRESTART value, nothing for a reader to learn.
      * ``cycle`` is the cycle whose genesis window contains ``as_of`` (CYCLE_GENESES,
        the explicit registry), NOT SSM /life-platform/experiment-cycle — the reset
        bumps SSM BEFORE genesis, so SSM names the NEXT cycle throughout the countdown.
        Pass ``cycle_geneses`` to pin the registry (tests); the SSM read survives only
        as the fallback for a POST-genesis write when the registry is unavailable (there
        it agrees with the registry by construction). Pre-genesis with no registry → no
        cycle: an unknown provenance is reported, never invented (ADR-104).

    Pass ``include_phase=False`` for the NARRATIVE#arc partition, whose `phase`
    attribute already means the narrative-arc STATE (e.g. "building"), NOT the
    taxonomy phase — those records take the cycle stamp only so the arc semantic is
    preserved.

    Fail-soft, by contract: whatever cannot be derived is omitted, and this NEVER
    raises. A provenance stamp must never break a write.
    """
    stamp: dict = {}
    try:
        from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE

        as_of = str(as_of)[:10] if as_of else _write_date()  # a caller's ISO instant is trimmed to its day; the default IS a day
        pre_genesis = as_of < EXPERIMENT_START_DATE
        if include_phase:
            stamp["phase"] = "pilot" if pre_genesis else EXPERIMENT_PHASE_CURRENT
    except Exception:  # noqa: BLE001 — constants unavailable: no phase claim at all
        as_of, pre_genesis = (str(as_of)[:10] if as_of else ""), False
    try:
        cycle = cycle_for_date(as_of, cycle_geneses if cycle_geneses is not None else _cycle_geneses())
        if cycle is None and not pre_genesis:
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
    # #1677: the closed platforms. Paste-captured rather than fetched, but the SAME fact
    # layer — a post he made is a logged fact however it reached the table, and the staged
    # PASTE# rows live in these very partitions, so one classification covers both.
    "x": RAW_TIMESERIES,
    "instagram": RAW_TIMESERIES,
    "tiktok": RAW_TIMESERIES,
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
    "progress_photos": CROSS_PHASE,  # #3757: body photos. CROSS_PHASE for two reasons that both
    # hold on their own: a before/after that spans attempts is the entire point of taking them (a
    # reset erasing attempt 16's photos would destroy exactly the comparison they exist for), and
    # unlike every RAW_TIMESERIES source they are UNRECOMPUTABLE — no API can re-emit a photo of a
    # body on a day that has passed. Sibling of "dexa" above: a durable body fact, not a cycle fact.
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
    # #4036: owner dismissals of derived PAIN FLAGS (DISMISSAL#<site>#<YYYY-MM-DD>, written by
    # mcp/tools_training_notes.py::tool_get_exercise_notes, action='dismiss'). Ruling 2026-09-21, ADR-077:
    # CROSS_PHASE, not SYSTEM_STATE and not EXPERIMENT_SCOPED. It is Matthew's own statement
    # about his BODY — the same class as "labs", "progress_photos" and "coach_corrections" —
    # and it is the record that stops a stale flag benching a lift against his word. An
    # experiment reset that wiped it would silently re-arm every site he has already said is
    # resolved, at exactly the moment nobody remembers he said it; and unlike a derived
    # score it cannot be recomputed from anything, because the input was a sentence he spoke
    # once. NEVER tagged, never wiped, never phase-filtered.
    "training_constraints": CROSS_PHASE,
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
    "recap_cards": EXPERIMENT_SCOPED,  # #3860 (owner ruling 2026-09-17): the #3741 daily recap
    # card's render/delivery log — one DATE# row per day carrying day_n, beat, grade, outcome,
    # delivered and the rendered card's s3_key. EXPERIMENT_SCOPED because every row is day_n-scoped
    # to ONE cycle (the live partition reads day_n 1..10 across cycle 17): a cycle-17 card says
    # "Day 6" and is meaningless against cycle 18's day numbering, so carrying it forward would make
    # a fresh cycle look like it has history — the exact failure the class exists to prevent.
    # Contrast "journal_quotes" (RAW_TIMESERIES) above, which is the closest sibling and was the
    # real argument on the other side: a quote is a frozen artifact of Matthew's own words, true
    # forever; a recap card is a statement ABOUT a numbered day of a numbered run.
    # THE S3 OBJECT (this issue's box 2, ruled explicitly): the card is KEPT, not deleted. The wipe
    # tombstones (UpdateItem adds a flag) rather than deleting, so the archived row survives and
    # still carries its s3_key — the object is REFERENCED by the archive, never orphaned, and
    # deleting it would break exactly the cycle-N navigability tombstoning exists to preserve.
    # There is no privacy leg to this: cards live under `recap/`, deliberately NOT `generated/`
    # (recap_card_lambda.py:55-61, asserted in tests/test_recap_card_private_3741.py), and an
    # unsigned GET of a live card returns 403 where generated/public_stats.json returns 200.
    # — SYSTEM_STATE: ops/infra/cache/dead (phase machinery ignores) —
    "journal_analysis": SYSTEM_STATE,  # regenerating Haiku cache (TTL 180d)
    "health_check": SYSTEM_STATE,
    # #3615/#4015 wrote this partition on 2026-09-21 (the nightly hook-liveness matrix, one row per
    # PT day keyed by cycle_day) with NO rule here — the first reset REHEARSAL under the owner's
    # no-further-resets ruling (2026-09-21, ADR-077 amendment) aborted at the census preflight on
    # exactly this family. Ruling (session AQ, 2026-09-22): SYSTEM_STATE — an operational
    # instrument's own output, regenerated every night from live probes, never evidence about the
    # experiment; it survives a reset and is read genesis-anchored like every other census.
    "qa_hook_matrix": SYSTEM_STATE,
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
    # #4078: chat writes queued for Matthew's approval (`coach/pending_writes.py`, PENDING#<ts>-<hash>).
    # Ruled SYSTEM_STATE before the first row exists: the queue is a workflow buffer, not a fact about
    # the experiment — an approved item's payload lands in its TARGET partition under that partition's
    # own class. An open item is an owner decision outstanding and must survive a reset untouched and
    # unfiltered (the same reasoning as experiment_suggestions above); SYSTEM_STATE is the class the
    # phase machinery ignores entirely. Resolved rows self-expire via `ttl`; open rows never do.
    "pending_writes": SYSTEM_STATE,
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
    # Coaching-team v2 (2026-08-10, owner request): the TEXTING RELATIONSHIP
    # survives an experiment reset. A chat thread with a coach — its turns, the
    # compressed CHAT#summary long memory, and RELATIONSHIP#state — is a
    # relationship with a person, not an artifact of the current cycle; wiping
    # it at a reset would make every coach a stranger each Monday. Evaluated
    # BEFORE the blanket COACH#* rule (first match wins).
    (lambda pk, sk: pk.startswith("COACH#") and sk.startswith("CHAT#"), CROSS_PHASE),
    # #2487 rides this same rule ON PURPOSE: RELATIONSHIP#bits (the inside-
    # references ledger) is a fact about the pair, not about the cycle it was
    # born in. A reset re-anchors the EXPERIMENT; it does not un-say a shared
    # joke, so a bit must survive one exactly as RELATIONSHIP#state does.
    (lambda pk, sk: pk.startswith("COACH#") and sk.startswith("RELATIONSHIP#"), CROSS_PHASE),
    # Telegram update_id dedupe rows: transport plumbing with a 24h self-TTL —
    # system state, never tagged, never wiped by a reset.
    (lambda pk, sk: pk.startswith("COACH#") and sk.startswith("DEDUPE#"), SYSTEM_STATE),
    # #2490: the event-outbound write-once claims (COACH#outbound_events /
    # EVENT#<id>) — a dedupe tracker with a 90-day self-TTL, same class as the row
    # above. It matters that a reset does NOT wipe these: the claim records that a
    # coach already TEXTED him about a lift PR, and a wiped claim would let the
    # next sweep say the same thing twice. "I already said this" is not an
    # artifact of the cycle that produced it.
    (lambda pk, sk: pk == "COACH#outbound_events" and sk.startswith("EVENT#"), SYSTEM_STATE),
    # #3514 (DA-2): the two DELIVERY ledgers on the COACH# namespace. Both were caught by
    # the blanket COACH#* rule below and so classified EXPERIMENT_SCOPED — wipeable on
    # paper — while sitting outside COACH_PARTITIONS, outside assert_registry_coverage and
    # outside the nightly stamp audit. The result was the worst of both: rows the registry
    # said a reset must archive, that no reset has ever touched, across three cycles.
    #
    # They are the SAME SHAPE as COACH#outbound_events directly above, which the registry
    # already rules SYSTEM_STATE on exactly this reasoning, and the live rows say so:
    #   COACH#nudge_ledger   DAY#<date>  {trigger_type, coach_id, status, attempted_at,
    #                                     expired_at, graded, error}   — per-day nudge
    #                                     attempt/outcome bookkeeping with an expiry.
    #   COACH#outbound_ledger DAY#<date> {total, referrals, ttl}       — per-day outbound
    #                                     send counters with a self-TTL.
    # Neither holds coach INTELLIGENCE (no narrative, no forecast, no graded claim); both
    # are rate-limit/delivery accounting whose whole purpose is "how much have I already
    # sent today". Carrying a reset into them would either destroy a live send counter or
    # re-open a spend window mid-day. "I already sent N today" is not an artifact of the
    # cycle that produced it — the same sentence that settles outbound_events.
    (lambda pk, sk: pk in ("COACH#nudge_ledger", "COACH#outbound_ledger"), SYSTEM_STATE),
    # Coach intelligence tier — all experiment-scoped.
    #   #3900 ruling (2026-09-20): COACH#commitments/TALLY#current is EXPERIMENT_SCOPED, not
    #   SYSTEM_STATE. It is a rolling tally, but of THIS cycle's graded commitments (the payload
    #   carries a `season` block), its only reader already defers to singleton_visible (#3514),
    #   and the reset wipe already archives it — a write-time stamp makes the writer agree with
    #   both. It was the one unstamped row on the partition (live 2026-09-19).
    (lambda pk, sk: pk.startswith("COACH#"), EXPERIMENT_SCOPED),
    (lambda pk, sk: pk == "ENSEMBLE#digest", EXPERIMENT_SCOPED),
    (lambda pk, sk: pk == "ENSEMBLE#disagreements", EXPERIMENT_SCOPED),
    (lambda pk, sk: pk == "ENSEMBLE#dispute", EXPERIMENT_SCOPED),  # #540 inter-coach threads
    (lambda pk, sk: pk == "ENSEMBLE#docket", EXPERIMENT_SCOPED),  # #1386 dispute docket (OPEN#/RESOLVED#)
    (lambda pk, sk: pk == "ENSEMBLE#influence_graph", SYSTEM_STATE),  # static config
    #   #3900 ruling (2026-09-20): EXPERIMENT_SCOPED for BOTH sks, stamped two ways. STATE#current
    #   carries the narrative-arc state in `phase` (a non-taxonomy value, e.g. "setback"), so the
    #   writer stamps it cycle-only (include_phase=False, #1233 — the overload is the reason, and
    #   the reader guards it with singleton_visible). HISTORY#<date> rows carry `transition`, not
    #   an arc state, so they take the full stamp — the older ones already carry `phase: pilot`
    #   from the reset wipes; only each cycle's newest was left served-as-current by a cycle-only
    #   stamp. The nightly audit treats a NARRATIVE#arc row with a `phase` as stamped either way.
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
    # #2539: the coach-chat simulation scoreboard — the sibling measure to
    # VOICEFIDELITY# above. That one asks whether the coaches are distinguishable
    # from EACH OTHER; this one asks whether they are distinguishable from a
    # PERSON. Same rationale for the same classification: it scores the coaching
    # engine's design across cycles, so a reset must not erase the trend. It has no
    # experiment-scoped source records at all — the conversations it summarizes are
    # synthetic and were never written to the table (the sim is read-only by
    # construction, coach_chat_sim.py).
    (lambda pk, sk: pk.startswith("COACHSIM#"), CROSS_PHASE),
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
    # #3760: one-time viewer-link nonces (PROGRESS_LINK#<nonce>). Spent-token exhaust with a
    # TTL, exactly the OAUTH#/BOARDSESS# shape — the PHOTOS are CROSS_PHASE (see the
    # progress_photos source ruling above), but the thing that proves a link was already
    # redeemed is auth state and carries nothing about the experiment.
    (lambda pk, sk: pk.startswith("PROGRESS_LINK#"), SYSTEM_STATE),
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


def should_phase_stamp(pk: str, sk: str = "") -> bool:
    """#2520: may a *write-time phase stamp* be put on the row at (pk, sk)?

    The one question both the #1970 backfill (deploy/backfill_coach_ensemble_
    phase_stamps.py) and its nightly audit (qa_smoke_lambda's
    check_coach_ensemble_phase_stamp_coverage) ask, so neither can drift from the
    taxonomy the way both did: they were written when COACH#*/ENSEMBLE#* held only
    EXPERIMENT_SCOPED rows and so treated "unstamped" as "needs a stamp" for the
    WHOLE partition. ADR-153 then put CROSS_PHASE `CHAT#`/`RELATIONSHIP#` and
    SYSTEM_STATE `DEDUPE#` rows on those same partitions, where the ABSENCE of a
    stamp is the correct, load-bearing state — stamping one marks Matthew's coach
    conversation history for deletion at the next reset.

    Derived from classify(), never from an sk allow/denylist, so a new sk class on
    an audited partition is classified rather than assumed. An unclassified pk/sk
    raises KeyError out of classify() deliberately: a caller must make that visible,
    never default it to True. The stamp is written under
    attribute_not_exists(phase), so a wrong one is not reversible by re-running.
    """
    return is_taggable(classify(pk, sk))


# #4059 — the two COACH# shapes whose own sk/attrs also carry a date that is NOT their
# provenance: a dispute-docket verdict's sk (once it collides with a stale prediction_id
# scheme) or its `outcome_date`/`resolved_at`, and a coach thread's own `date` attribute
# when that attribute is a CONTENT reference rather than the row's opening. Shape-gated
# (not a blanket override) so every other EXPERIMENT_SCOPED family keeps reading its
# `date` attribute first exactly as it always has — only these two write a same-row
# outcome/reference date ALONGSIDE their real provenance.
_PROVENANCE_SHAPE_COACH_SK_PREFIXES = ("PREDICTION#docket-", "THREAD#")


def _is_provenance_sensitive_shape(pk: str, sk: str) -> bool:
    if pk.startswith("COACH#"):
        return sk.startswith(_PROVENANCE_SHAPE_COACH_SK_PREFIXES)
    return sk.startswith("SOURCE#coach_thread")


def provenance_date(item: dict) -> str | None:
    """#4059 — a row's PHASE-PROVENANCE date: when it was CREATED or OPENED, never when
    it was resolved, re-stamped, or what it merely references.

    RULING (dated, 2026-09-22/23 owner chat): a dispute-docket verdict opened before
    genesis and graded after it is still a pre-genesis row — "archive it with its cycle
    even when its outcome window falls after genesis". Ten live `COACH#explorer_coach`/
    `COACH#nutrition_coach` `PREDICTION#docket-*` rows carried `created_at
    2026-08-03T17:41:16Z` (a month before the 2026-09-06 genesis) yet `cycle=17,
    phase=experiment` — because the shared predicate was fed `outcome_date`/`resolved_at`/
    the re-stamped `cycle`, never the docket's own open time
    (`lambdas/coach/dispute_docket.py::_write_docket_prediction` sets `created_at =
    docket.get("opened_at", "")`, the true provenance, right beside `outcome_date` and
    `resolved_at`, which are not). Symmetrically, nine live `USER#matthew` /
    `SOURCE#coach_thread#training_coach#...#pain` rows (created 2026-09-19, squarely
    IN cycle 17) were flagged by a full-attribute read of the OTHER predicate input: their
    `date` attribute carries the underlying Hevy note's 2022–2023 workout date — a
    CONTENT reference (`lambdas/training/training_notes.py::elevate_pain` sets `"date":
    item.get("date")`, the pain note's own workout day, not when the coach thread itself
    was opened) — while `created_at` (the write's own timestamp) is the row's real
    provenance.

    Reads ONLY `opened_date` then `created_at`, and ONLY for the shapes #4059 named
    (`_is_provenance_sensitive_shape`) — every other EXPERIMENT_SCOPED family keeps
    reading its `date` attribute / sk / timestamp-fallback order unchanged
    (`restart_phase_tag.extract_date`, `restart_intelligence_wipe.extract_date`,
    `pk_census.row_date` all call this FIRST and fall back to their own generic order
    when it returns None) — never `outcome_date`, `resolved_at`, or `cycle`, whatever a
    caller's item happens to carry under those names. Returns None for a non-matching
    shape or an unparseable/absent value; callers fall back to their generic order rather
    than guessing.
    """
    if not _is_provenance_sensitive_shape(str(item.get("pk", "")), str(item.get("sk", ""))):
        return None
    import re as _re

    for attr in ("opened_date", "created_at"):
        v = item.get(attr)
        if isinstance(v, str):
            m = _re.match(r"(\d{4}-\d{2}-\d{2})", v)
            if m:
                return m.group(1)
    return None


def pre_genesis_scoped_violation(pk: str, sk: str, phase, item_date: str | None, genesis: str) -> bool:
    """#4040 — THE shared predicate: is (pk, sk) an `EXPERIMENT_SCOPED` row dated before
    `genesis` whose `phase` is not `pilot`?

    True for BOTH shapes the no-reset world produces: unstamped (`phase` is `None`) and
    mis-stamped (`phase` is set to the current-phase constant, or anything else that
    isn't `pilot`) — the tagger used to correct either at reset time; nothing does now.
    `item_date`/`genesis` are `YYYY-MM-DD` strings compared lexically (ISO dates sort
    correctly as strings) — pass the date already extracted from the row (this function
    does not read `item`, so it stays testable without a row shape opinion).

    Three callers share this: `deploy/restart_verify.py` check 21 (`pre_genesis_
    unstamped`), the nightly `data:coach_ensemble_phase_stamp_coverage` leg
    (`experiment.pk_census.scoped_stamp_audit`'s `mis_stamped` leaf), and
    `deploy/phase_stamp_sweep.py` (the corrector). One predicate so a fix to the rule
    reaches all three; guard the SET, not the instance.

    DELIBERATELY DOES NOT KNOW ABOUT THE SERVED-LEAD-IN EXEMPTION (see the v1.3.0 ruling
    above) — a caller subtracts `chronicle_manifest_qa.served_chronicle_keys()` from its
    result set BEFORE reporting or correcting a True verdict. Keeping the manifest read
    (S3 + a DDB query) out of this pure function is what makes the mutation control
    possible: disabling the date comparison here must break ONLY the date logic, not
    silently swallow it behind a network call.
    """
    try:
        if classify(pk, sk) != EXPERIMENT_SCOPED:
            return False
    except KeyError:
        return False
    if not item_date or item_date >= genesis:
        return False
    return phase != "pilot"


def experiment_stamp_for(pk: str, sk: str = "", **kwargs) -> dict:
    """#3514 (DA-6): the write-time stamp for THIS row — `{}` when its class forbids one.

    THE DEFECT THIS CLOSES
      `should_phase_stamp()` above has said since #2520 which rows may carry a write-time
      phase stamp. **No writer consulted it.** Every stamping writer called the unguarded
      `experiment_stamp()` and merged the result into whatever it was putting, so a
      CROSS_PHASE row got the same `phase`/`cycle` as an EXPERIMENT_SCOPED one. Live on
      2026-09-17, before the fix: 7 `COACH#*/RELATIONSHIP#state` rows and 15 `CHAT#` rows
      carried scoped provenance — a stamp that marks Matthew's coach conversation history
      as belonging to one cycle, on the exact partitions ADR-153 made cross-phase so it
      would survive every reset.

      The predicate was right and unread. That is why this wrapper exists instead of a
      per-writer `if`: an `if` at 10 call sites is 10 chances to forget the 11th.

    WHY `{}` AND NOT A PARTIAL STAMP
      The reconcile that cleaned the live rows (deploy/reconcile_provenance_2026_09.py,
      group A) removes `phase` AND `cycle` AND every `tombstone*` attribute, because the
      CROSS_PHASE contract is "never tagged, never wiped, never phase-filtered" — a bare
      `cycle` on such a row is the same category error as a bare `phase`. The writer's
      behaviour and the reconcile's must agree exactly, or the next write re-creates what
      the reconcile just removed.

    AN UNCLASSIFIABLE ROW
      `classify()` raises KeyError on an unknown pk, deliberately, and `should_phase_stamp`
      documents that a caller must make that visible and "never default it to True". This
      returns `{}` and logs LOUD rather than propagating, because every caller is a
      fail-soft writer whose `except` would swallow the KeyError as a failed PUT and LOSE
      THE ROW — trading a provenance defect for a data-loss one. Unstamped-and-announced is
      the recoverable direction: the #3513 class (an unstamped scoped row) is repairable by
      a reconcile pass, a dropped write is not. The totality census
      (experiment.pk_census) is the instrument that turns that log line into a verdict.

    `kwargs` pass through to `experiment_stamp` (`include_phase`, `as_of`, `cycle_geneses`,
    `ssm_client`) so this is a drop-in at every existing call site.
    """
    try:
        if not should_phase_stamp(pk, sk):
            return {}
    except KeyError as e:
        import logging

        logging.getLogger(__name__).warning(
            "[#3514] experiment_stamp_for: pk=%r sk=%r is UNCLASSIFIED by phase_taxonomy (%s) — "
            "writing it WITHOUT provenance rather than guessing. Add it to SOURCE_CLASS/_PK_RULES; "
            "experiment.pk_census reports this family nightly.",
            pk,
            sk,
            e,
        )
        return {}
    return experiment_stamp(**kwargs)


# The attributes a reset (or a write-time stamp) puts on a row to say WHICH run it
# belongs to. On a CROSS_PHASE row every one of them is wrong by construction — the
# class is "never tagged, never wiped, never phase-filtered".
#
# #3915 (2026-09-20) narrows that sentence where it was too wide, WITHOUT changing this
# predicate: measured over the live table, all 3,185 flagged cross-phase rows carry
# `cycle` and only `cycle`, and on three families (calibration, recall_embeddings,
# milestones) a bare cycle is a LABEL their own SOURCE_CLASS comments above require and a
# reader consumes — nothing filters, wipes or tombstones on it. The per-family ruling
# therefore lives one layer up, in `pk_census.CROSS_PHASE_PROVENANCE_RULINGS`, which reads
# this function and then says whether the attribute it found was sanctioned. This one
# stays the wide, mechanical answer to "what provenance is on this row" so every
# instrument still starts from the same list.
PROVENANCE_ATTRS = ("phase", "cycle", "tombstone", "tombstoned_at", "tombstoned_reason")


def forbidden_provenance(pk: str, sk: str, item: dict) -> list[str]:
    """#3514: the provenance attributes on `item` that its CLASS forbids.

    The single predicate three instruments share, so none of them can drift from the
    others the way the writer and the audit already did:
      * `experiment_stamp_for` (the writer) — never writes one of these.
      * `deploy/reconcile_provenance_2026_09.py` group A (the one-off) — removes them.
      * `qa_smoke_lambda.check_coach_ensemble_phase_stamp_coverage` (the nightly) — WARNs.

    Scoped to CROSS_PHASE deliberately, which is exactly the reconcile's own group-A
    selector. A stamp on a SYSTEM_STATE row is untidy but inert (the phase machinery
    ignores that class entirely); a stamp on a CROSS_PHASE row marks Matthew's coach
    conversation history as belonging to one cycle, which is the thing ADR-153 exists to
    prevent. Returns [] rather than raising for an unclassifiable row — the totality
    census (experiment.pk_census) is the instrument that reports those, and an audit that
    raises on one row stops reporting the other ten thousand.
    """
    try:
        if classify(pk, sk) != CROSS_PHASE:
            return []
    except KeyError:
        return []
    return [a for a in PROVENANCE_ATTRS if item.get(a) is not None]


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


def opening_cycle_for_genesis(genesis: str | None, cycle_geneses: dict, abandoned_geneses: dict | None = None) -> int | None:
    """The cycle a genesis OPENED, or None when the date is in neither registry.

    Two registries, because a genesis can be written into the record and then moved:

      * `cycle_geneses` — cycle number → genesis date (site_api_data.CYCLE_GENESES), the
        live anchor of each cycle.
      * `abandoned_geneses` — genesis date → the cycle it was opening
        (site_api_data.ABANDONED_GENESES): a date a reset actually RAN on and stamped rows
        with before the anchor moved. #3621: the cycle-16 re-anchor was corrected in place
        from 2026-09-04 to 2026-09-05, but the wipe's `tombstoned_reason` is written with
        if_not_exists (#1202) so the Friday date survives on 328 rows forever, by design.
        Passing `None` consults the live alias map; pass `{}` for "aliases off" (the
        pre-#3621 behaviour, which is also the mutation control in the test).

    Separated from `closing_cycle_for_genesis` so a caller can tell "this genesis is not
    in the record at all" (None here) from "cycle 1 has no predecessor" (1 here, None
    there) — a distinction the census in deploy/restart_verify.py is built on, and one a
    single function returning None for both cannot express (ADR-104).
    """
    if not genesis:
        return None
    key = str(genesis)[:10]
    for cycle, gen in cycle_geneses.items():
        if str(gen)[:10] == key:
            return int(cycle)
    aliases = _abandoned_geneses() if abandoned_geneses is None else abandoned_geneses
    if aliases and key in aliases:
        return int(aliases[key])
    return None


def closing_cycle_for_genesis(genesis: str | None, cycle_geneses: dict, abandoned_geneses: dict | None = None) -> int | None:
    """The cycle that a reset CLOSED, given the genesis it opened.

    `cycle_geneses` maps cycle number → genesis date (site_api_data.CYCLE_GENESES).
    The reset that opens cycle N closes cycle N-1 — which is exactly the number the
    wipe stamps onto the records it archives. Returns None for an unregistered or
    unknown genesis (cycle 1 has no predecessor).

    #3621: an ABANDONED genesis resolves too — see `opening_cycle_for_genesis`.
    """
    opening = opening_cycle_for_genesis(genesis, cycle_geneses, abandoned_geneses)
    if opening is None or opening <= 1:
        return None
    return opening - 1
