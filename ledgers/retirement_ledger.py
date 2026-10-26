"""ledgers/retirement_ledger.py — what each charter story REMOVES, by name (#5141, epic #5134).

THE PROBLEM (platform build-and-cost review, 2026-10-18)
  The charter epics (#5067 training, #5091-#5094 nutrition) add machinery story by story,
  and no story was required to say what it retires — so the platform only grew. Removal
  candidates were named in open issues (the 1500 kcal constant #5095, the dark feeds #5108,
  the legacy routine generator) with nothing that tracked them to a status.

THE SHAPE (the one registry; every consumer derives from it)
  `RETIREMENTS` — one row per named removal, keyed by a stable slug. Fields:
      what     — the thing removed, named concretely enough to grep for
      story    — the issue that owns the removal (int), or None for a keep row with no story
      status   — one of `STATUSES`:
                   planned  a story names it and has not shipped it
                   retired  removed; `pr` + `date` record where and when
                   demoted  kept but switched off / reduced to a ritual (the ADR-074 `paused`
                            posture, the PROPORTIONALITY `Dormant` posture)
                   kept     deliberately NOT retired; `reason` says why, `retire_when` what
                            would change that
      pr, date — the merged PR and its merge date (UTC, YYYY-MM-DD) for retired/demoted rows
      record   — the evidence, quoted or paraphrased from the PR/issue text. A row exists only
                 where that text SAYS the thing was removed — never inferred from a diff.
      feed     — for a dark feed, the `source_registry` id it accounts for (see below)
      posture_row — True when the removal is a standing subsystem with its own row in the
                 `docs/PROPORTIONALITY.md` Retired table (the contract test joins the two)

  `ADDS_ONLY` — PRs/stories recorded as retiring nothing, with the reason, so "nothing" is a
  stated fact rather than a silence.

WHO READS IT
  * `scripts/check_backlog_hygiene.py::rule_retires_section` — a charter story (a member of
    a `scripts/backlog_waves.json` wave) states a `## Retires` line in its body, OR has a row
    here. Blocking for stories filed on/after its effective date; advisory (named, one line)
    for the older ones.
  * `scripts/check_backlog_hygiene.py::rule_retirement_ledger_liveness` — a `planned` row
    whose story is no longer open is stale: the story closed and the ledger never learned
    whether the removal shipped. The dead-man for this ledger.
  * `tests/test_retirement_ledger_5141.py` — the shape, the wave reasons, the PROPORTIONALITY
    join, the dark-feed coverage and the append-only ratchet.

WAVES (acceptance box 3)
  A wave in `scripts/backlog_waves.json` RETIRES when at least one planned/retired/demoted row
  here belongs to it (`backlog_next.wave_of` on the row's story — derived, never hand-listed
  on the wave). A wave with none carries `adds_only_reason` in its own entry; a wave that
  does retire must NOT carry one (a stale "adds only" claim is a lie the test refuses).
  The wave file is the waves' tracking record — no wave has a tracking issue of its own.

DARK FEEDS (acceptance box 4)
  Every `source_registry` source with the `paused` facet has exactly one row here naming it
  in `feed`, so a newly paused feed cannot go dark without a retire-or-keep decision.

RATCHET
  Keys are append-only (the seeded key set is pinned in tests/test_retirement_ledger_5141.py): a row changes status,
  it never disappears, and a `retired` row never goes back to `planned`. A planned removal
  that is abandoned becomes `kept` with its reason — the decision stays readable.
"""

LEDGER_START = "2026-10-23"  # the day #5141 seeded this file; the PROPORTIONALITY join binds from here

STATUSES = ("planned", "retired", "demoted", "kept")

RETIREMENTS = {
    # ── retired / demoted on 2026-10-23 (the backfill the #5141 lane was briefed with) ──
    "coach-daily-reflection": {
        "what": "the per-coach CC-08 daily reflection in `coach-daily-reflection` (Haiku call + stricter retry, "
        "the #2889 reuse slot, the ER-03/#2430 gate on it, the `generated/coach_daily.json` write, the "
        "`coach_daily_reflection` model route)",
        "story": 4583,
        "status": "retired",
        "pr": 5263,
        "date": "2026-10-23",
        "record": "PR #5263 §1: 'The per-coach CC-08 reflection is removed' — owner ruling on #4583, 'Retire the old daily "
        "reflection notes. The move becomes each coach's single daily voice.' Saves up to 7 Haiku calls a day.",
        "posture_row": True,
    },
    "food-delivery-daily-feed": {
        "what": "the `food_delivery` source as a live daily feed — paused between uploads, reduced to a 6-monthly CSV "
        "upload ritual with a calibration-cadence reminder",
        "story": 5108,
        "status": "demoted",
        "pr": 5261,
        "date": "2026-10-23",
        "record": "PR #5261 §2: 'food delivery is a 6-monthly upload ritual' — paused since 2026-10-19, the owner confirmed "
        "it STAYS paused between uploads and an upload never un-pauses it; the daily-brief/character-sheet streak "
        "modifier returns None without reading (#5006/#5108).",
        "feed": "food_delivery",
    },
    "partner-email-journal-section": {
        "what": "the partner email's journal-fed 'what's happening underneath' (Reeves) section and its dark Notion "
        "journal reads (mood, themes, avoidance, quotes)",
        "story": 5125,
        "status": "retired",
        "pr": 5264,
        "date": "2026-10-23",
        "record": "PR #5264 (#5125 R5): 'The dark Notion journal reads (mood, themes, avoidance, quotes) are removed. The "
        "journal-fed \"what's happening underneath\" (Reeves) section is retired.'",
    },
    "titration-payback-cap": {
        "what": "the rest-day payback cap in the calorie titration (`payback_rule`, `uplift_grain_kcal`, "
        "`_payback_capped_uplift`) and the carb floor's `typical_g`",
        "story": 5091,
        "status": "retired",
        "pr": 5265,
        "date": "2026-10-23",
        "record": "PR #5265 (owner rulings quoted from #5091): 'The payback cap is gone: `payback_rule` and "
        "`uplift_grain_kcal` are removed' ... 'no payback cap (`_payback_capped_uplift` removed)'; "
        "'`typical_g` is retired to null'.",
    },
    "lifting-rpe-caps": {
        "what": "the lifting RPE caps written by `standing_constraints.gate_lines` / `gate_cue` (from 2026-10-19; older "
        "drafts byte-identical)",
        "story": 5167,
        "status": "retired",
        "pr": 5266,
        "date": "2026-10-23",
        "record": "PR #5266 §3: '#5167: retire the lifting RPE caps (the date split)' — `lifting_caps_retired_from: "
        '"2026-10-19"`; from that day no RPE cap is written, the charter\'s `effort_ceilings` bands are named instead.',
    },
    "character-steps-8000-fallback": {
        "what": "the character sheet's hard 8000-step fallback target (`lambdas/health/character_engine.py`)",
        "story": 5056,
        "status": "retired",
        "pr": 5280,
        "date": "2026-10-24",
        "record": "PR #5280: '`lambdas/health/character_engine.py` fallback 8000 | **Removed.**' — 'The hard 8000 "
        "fallback is gone: no target now means the score is absent.' The steps target reads the charter's "
        "12,000 / 15,000 rule.",
    },
    # ── earlier charter retirements, recorded so each retiring wave is derivable ──
    "scheduled-program-week-6-deload": {
        "what": "the scheduled program-week-6 / 2026-11-04 deload (`owner_redlines` `at_program_week: 6`, "
        "`program_structure.DELOAD_RULE`, the `session_sequence` due-week loop)",
        "story": 5070,
        "status": "retired",
        "pr": 5145,
        "date": "2026-10-19",
        "record": "PR #5145: owner ruling 2026-10-18 'no scheduled or automatic deload'; '`at_program_week: 6` — removed', "
        "'`DELOAD_RULE` — removed', 'the `dl_start`/`due_week` loop is gone'.",
    },
    "hand-copied-rate-targets": {
        "what": "the hand-copied rate targets `site_api_nutrition._TARGET_RATE_LB_WK` (with the published "
        "`target_rate_lb_wk` / `required_deficit_kcal` / `gap_kcal`) and `story_dossier.RATE_FLAG_LB_WK = 2.5`",
        "story": 5074,
        "status": "retired",
        "pr": 5154,
        "date": "2026-10-19",
        "record": "PR #5154: '`site_api_nutrition._TARGET_RATE_LB_WK` — removed, no public target'; "
        "'`story_dossier.RATE_FLAG_LB_WK` — removed'. The band is read from the charter through `training/rate_band.py`.",
    },
    # ── planned: a story names the removal and has not shipped it ──
    "plan-daily-calories-constant-1500": {
        "what": "the hand constant `PLAN_DAILY_CALORIES_TARGET = 1500` and its separate readers (scoring, character "
        "sheet, the three emails) — replaced by one calorie resolver. The VALUE stays ~1,500 (owner ruling R1, "
        "PR #5265); what retires is the constant as a second source of the number.",
        "story": 5095,
        "status": "retired",
        "pr": 5190,
        "date": "2026-10-19",
        "record": "PR #5190 removed `PLAN_DAILY_CALORIES_TARGET` from lambdas/ (git log -S); #5095 closed on live proof "
        "2026-10-25 (one resolver, every surface reads health.calorie_target).",
    },
    "personal-board-text-and-training-coach-config": {
        "what": "the 'Personal Board' role-play text (`.claude/skills/daily-debrief/SKILL.md`, the coach-session prompt) "
        "and the retired `config/coaches/training_coach.json` + `training_coach_stance.json`",
        "story": 5071,
        "status": "retired",
        "pr": 5366,
        "date": "2026-10-25",
        "record": '#5071 acceptance: \'The "Personal Board" role-play text and the stale retired training_coach config '
        "are removed' (Set: 4 retirement targets).",
    },
    "two-1500-prompted-meal-emails": {
        "what": "the two LLM meal emails prompted with a stale 1500 kcal (`weekly_plate_lambda.py`, "
        "`nutrition_review_lambda.py`) — retired or rewired onto the deterministic menu",
        "story": 5103,
        "status": "planned",
        "record": "#5103 acceptance: 'The two 1500-prompted emails are retired or rewired'.",
    },
    "zone2-same-session-union-find": {
        "what": "the zone-2 reader's own cross-source session rule — `_same_session` / `_groups` in "
        "`lambdas/training/zone2_minutes.py` (START_WINDOW_MIN=15 / CONTAINMENT_SHARE=0.8 union-find that chained a "
        "whole gym visit into one session) — replaced by `training.workout_identity.resolve_workout_identities`",
        "story": 5369,
        "status": "planned",
        "record": "#5369 ## Retires: 'The zone2-local `_same_session` / `_groups` rule (zone2_minutes.py:262, :278) once "
        "routed through `workout_identity`'. Removed in the #5369 lane PR (Refs #5369); flips to retired with the PR "
        "number and merge date when it lands on main.",
    },
    "farmers-carry-programmed-key": {
        "what": "`farmers_carry` as a separate programmed catalog key (`config/movement_catalog.json`) — the custom Hevy 'Farmers Carry' "
        "template (ce871c4e…) the B3 ruling programmed and the owner never logged. Folds into `farmers_walk` (Hevy's standard "
        "'Farmers Walk', 50C613D0, the template he logs); `training.movement_catalog.RETIRED_KEYS` keeps a stored routine that still "
        "names the old key readable. The custom template stays on his Hevy account (the platform never deletes templates).",
        "story": 5372,
        "status": "planned",
        "record": "#5372 `## Retires`: '`farmers_carry` as a separate programmed key ... Folds into `farmers_walk`; the custom Hevy "
        "template is left alone on the owner's account.' Flip to `retired` with the merged PR and its merge date.",
    },
    # ── kept, with the reason (acceptance box 4: the legacy routine generator) ──
    "program-v04-revert-generator": {
        "what": "the frozen v0.4 plan (`lambdas/training/program_v04.py`, `program_v04.build_session` as the "
        "nightly predraft's `v04` plan source)",
        "story": 5080,
        "status": "kept",
        "reason": "#5080 keeps v0.4 as the side-by-side shadow and the one-command revert for the charter plan ('flip back "
        "to v0.4 with one command if a wave misbehaves'); `program_v04.py` also keeps v0.4's structure as history so "
        "sessions logged before the 2026-10-19 cut-over are credited with the role they were served as.",
        "retire_when": "a story filed after #5080's live proof (three nights side by side, a tested flip) retires the `v04` "
        "plan source; the history half of `program_v04.py` stays as `program_v03.py` does.",
    },
    "program-v03-history": {
        "what": "`lambdas/training/program_v03.py` (TRAINING_PROGRAM v0.3, superseded 2026-09-24)",
        "story": None,
        "status": "kept",
        "reason": "nothing in it steers a prescription; it keeps v0.3's definitions verbatim so a routine, plan or adherence "
        "row written under v0.3 reads against its own program, and `load_ramp.block_1_start()` reads its block-1 date "
        "(module docstring).",
        "retire_when": "no row written under v0.3 is read any more and `load_ramp` reads the block-1 date elsewhere.",
    },
    "public-meal-endpoints": {
        "what": "`/api/frequent_meals` and `/api/protein_sources` (the #5112 'removed, whitelisted or aggregated' box)",
        "story": 5112,
        "status": "kept",
        "reason": "owner ruling R5 (PR #5261): both stay public; a food name appears only if it is on the owner-approved "
        "`APPROVED_FOOD_NAMES` list (ships empty, fails closed) — whitelisted, not removed.",
        "retire_when": "the owner rules the endpoints off the public site.",
    },
    # ── the dark feeds: every `paused` registry source (acceptance box 4) ──
    "garmin-direct-api": {
        "what": "the Garmin direct-API ingestion function (Garmin data now arrives through Strava)",
        "story": 4640,
        "status": "retired",
        "date": "2026-10-11",
        "record": "source_registry `garmin` method: 'Delivered through Strava — direct-API function retired 2026-10-11 "
        "(#4640, ADR-074)'. The registry entry stays as the paused tombstone.",
        "feed": "garmin",
    },
    "youtube-schedule": {
        "what": "the scheduled YouTube social-ingestion pull (function kept, invoke by hand)",
        "story": 4644,
        "status": "retired",
        "date": "2026-10-17",
        "record": "source_registry `youtube`: owner Q39 2026-10-17 (#4644) 'no — retire the three schedules'; 0 rows in 756 "
        "scheduled runs across the three feeds.",
        "feed": "youtube",
    },
    "bluesky-schedule": {
        "what": "the scheduled Bluesky social-ingestion pull (function kept, invoke by hand)",
        "story": 4644,
        "status": "retired",
        "date": "2026-10-17",
        "record": "source_registry `bluesky`: owner Q39 2026-10-17 (#4644) 'no — retire the three schedules'.",
        "feed": "bluesky",
    },
    "mastodon-schedule": {
        "what": "the scheduled Mastodon social-ingestion pull (function kept, invoke by hand)",
        "story": 4644,
        "status": "retired",
        "date": "2026-10-17",
        "record": "source_registry `mastodon`: owner Q39 2026-10-17 (#4644) 'no — retire the three schedules'.",
        "feed": "mastodon",
    },
}

ADDS_ONLY = {
    "pr-5226-charter-twin-list": {
        "story": 5220,
        "pr": 5226,
        "date": "2026-10-24",
        "reason": "adds one scoped `CharterTwinList` statement (`s3:ListBucket`, prefix `config/coaching/*`) so an absent "
        "private charter twin answers 404 instead of 403; an alarm-accuracy fix with nothing to retire.",
    },
}
