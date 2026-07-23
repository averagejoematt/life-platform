"""source_registry.py — THE canonical data-source registry (#392, facets #498).

One place a source's identity, staleness threshold, behavioral-vs-infrastructure
classification, and (since #498) every other per-source facet live. Derived by:
  - lambdas/emails/freshness_checker_lambda.py  (StaleSourceCount → the paging
    slo-source-freshness alarm)
  - lambdas/web/site_api_data.py                (/api/source_freshness — the
    public pipeline board)
  - mcp/tools_labs.py::tool_get_freshness_status (operator MCP view)
  - lambdas/operational/pipeline_health_check_lambda.py (active-API + best-effort
    sets — was two hand-rolled lists, X-10)
  - lambdas/operational/qa_smoke_lambda.py      (required/optional/paused QA tiers
    — was three hand-rolled lists, X-10)
  - lambdas/operational/data_reconciliation_lambda.py (expected-days-per-week —
    was a hand-rolled tuple list, X-10)
  - mcp/config.py::SOURCES                      (queryable partition ids)
  - scripts/v4_build_data_sources.py            (site/data/data_sources.json is
    GENERATED from here — it self-labeled "single source of truth" while being a
    stale March copy missing hevy, X-10)

The freshness trio used to hand-mirror this data under "KEEP IN SYNC" comments and
drifted: withings/strava were classified infrastructure everywhere, macrofactor
was behavioral publicly but infrastructure in the checker, and the MCP mirror
still carried the pre-triage food_delivery 90-day threshold. Result: a quiet
logging stretch held the paging alarm red for days — training the operator to
ignore the one alarm class that once hid a six-week outage. #498 extends the same
cure to the remaining enumerations; `tests/test_source_enumeration_drift.py` is
the linter that keeps any module from growing its own list again.

Classification rule:
  behavioral      — a record exists only when Matthew DOES something (weighs in,
                    exercises, lifts, logs food, measures, journals). Staleness
                    is a logging lapse: reported honestly on every surface,
                    never paged.
  infrastructure  — the pipe runs without his participation (worn device,
                    webhook, scheduled API pull). Staleness means something
                    broke: pages via StaleSourceCount.

The tie-breaker is the sync mechanics, not the vendor: Whoop is worn 24/7 so
its data flows passively (infra), while Withings only produces a record when he
steps on the scale and Strava only when he moves (behavioral, even though both
sync themselves once the behavior happens).

Raw-S3 reality (X-9): the raw/ zone is three-generation fractured — legacy
`raw/{source}/` (todoist, weather), live `raw/matthew/{source}/…` (most), and
flat UUID-keyed `raw/hevy/{id}.json`. Each source's `raw_layout` documents its
ACTUAL shape. Do NOT mass-move: raw/* is a delete-protected prefix (ADR-046),
and replay tooling should read the layout from here instead of guessing.

Ships inside every function bundle (deploy/build_bundle.py, #781) so the
MCP and site-api Lambdas resolve it; stacks that bundle lambdas/ get the same
file at /var/task, which shadows the layer copy harmlessly.
"""

from typing import Any, cast

# Default staleness threshold when a source has no override (hours). The
# checker may still override its own default via the STALE_HOURS env var.
DEFAULT_STALE_HOURS = 48

# Per-source fields:
#   label          public board label
#   checker_label  the name used in freshness emails / alert lines
#   desc           public board description
#   category       public board grouping (Wearables / Inputs / Manual logs)
#   behavioral     True = staleness is a logging lapse, never pages
#   stale_hours    override of DEFAULT_STALE_HOURS (None = default)
#   paused         intentionally off — shown as "paused", never counted stale
#   monitored      False = MCP-visibility only; excluded from the checker and
#                  the public board (currently just notion)
#
# #498 facets (X-10 — the hand-rolled enumerations these replace are noted per helper):
#   freshness      False = on NO freshness surface (checker/board/MCP) — registry-
#                  resident for the other facets only (supplements, dropbox;
#                  weather joined the freshness surfaces proper in #470).
#                  Default True.
#   partition      False = no `USER#…#SOURCE#<key>` DDB partition (dropbox is a
#                  transport pipe; its tracker lives elsewhere). Default True.
#   active_api     scheduled API *pull* that must attempt at least daily — the
#                  silent-auth-rot / 44-day-outage class (pipeline_health_check).
#   best_effort    known-brittle by an accepted upstream cause; evaluated + logged
#                  but excluded from UnhealthySourceCount (pipeline_health_check).
#   expected_days  expected record days per week for gap reconciliation
#                  (data_reconciliation); None = event-driven, gaps are behavior.
#   qa_tier        'required' (missing yesterday = FAIL) | 'optional' (warn) |
#                  None (not checked). Paused sources render ⏸ regardless (qa_smoke).
#   method         how the data arrives — public catalogue text (data_sources.json).
#   metrics        what the source measures — public catalogue text.
#   posture        value-per-source verdict from the 2026-07 data-source health
#                  review: 'load-bearing' | 'portfolio' | 'paused' | 'archive'.
#   raw_layout     the ACTUAL raw-S3 shape: {prefix, scheme, filename[, note]} where
#                  scheme is 'date-tree' ({prefix}/{YYYY}/{MM}/{filename}), 'flat-uuid'
#                  ({prefix}/{id}.json), or 'timestamped'; None = no raw archive.
#                  filename names the ACTUAL leaf form — do NOT assume {DD}.json. Every
#                  current date-tree write is 'YYYY-MM-DD.json'; the SIMP-2 framework
#                  migration flipped the legacy 'DD.json' form to the full date mid-2026
#                  IN-PLACE within the same date tree (#1256), so pre-2026 objects on the
#                  flipped sources (todoist, garmin) still carry 'DD.json'. Read this
#                  facet — never construct a key from the prefix alone.
#   provider_reconcile
#                  True = OPT-IN source-of-truth reconciliation (DI-2/TR-07): a
#                  daily job diffs the PROVIDER API against stored records and
#                  emits MissingActivityCount{Source=<key>} — the one check that
#                  sees a silent drop the DDB high-water mark hides. Only sources
#                  whose provider exposes a queryable record list AND that aren't
#                  rate-limit-degraded qualify; garmin is EXPLICITLY excluded
#                  (ADR-123). Default absent/False. Read by provider_reconcile_source_ids().
#   capture_channel  the manual capture channel that fills this source by hand
#                  (#746, Matthew's decision — the three manual channels are HAE,
#                  Notion, MCP conversation): 'hae' (Health Auto Export webhook —
#                  CGM / water / BP / State of Mind), 'notion' (journal), 'mcp'
#                  (logged in an MCP conversation — measurements, food delivery).
#                  Absent = an automatic pipe (worn device / scheduled API pull)
#                  with no human in the capture loop. Only capture_channel sources
#                  are eligible for the evening nudge's gentle "gone quiet" mention
#                  and the public "manual source dark N days" degraded stamp — a
#                  dead Whoop token is a device outage the nudge can't fix, so it
#                  never lands here. Read by manual_capture_sources().
#   engagement_channel  (#914) the presence / quiet-stretch channel this source
#                  feeds (engagement_core.compute_presence — the "is Matthew still
#                  logging?" instrument, a DIFFERENT axis from freshness):
#                  {label, stale_days[, presence_predicate][, primary]}.
#                    label       reader-facing channel noun ("food", "training", …)
#                    stale_days  lag-adjusted days before the channel reads quiet
#                    presence_predicate  name of the engagement_core predicate that
#                                decides whether a DDB record counts as Matthew
#                                actually LOGGING that day (default: any record).
#                                habitify needs one because its pull writes a
#                                record EVERY day even at total_completed=0 — a
#                                14-day zero-completion stall read as gap_days=0.
#                    primary     True on exactly ONE channel (macrofactor/food) —
#                                the headline gap anchor.
#                  Replaces engagement_core's hand-rolled MANUAL_CHANNELS +
#                  CHANNEL_STALE_DAYS (the #498 drift class). Presence is a
#                  BEHAVIORAL surface: it narrates, it never pages — adding this
#                  facet must not touch any checker/paging projection.
#   hae_datatypes  (apple_health only) per-sub-datatype liveness thresholds for the
#                  streams that all share the ONE apple_health partition, so a
#                  partition-level "fresh" can hide a months-dark sensor (D-4/#468).
#                  Migrated here from freshness_checker by #746 so every source
#                  threshold lives in this one registry. Each: {key, label, fields
#                  (any-of presence signals), stale_days, manual}. `manual` marks
#                  the streams Matthew captures by hand (CGM/water/BP/State of Mind)
#                  vs the passive device streams (steps/workouts) — only the manual
#                  ones are nudge-eligible. Read by hae_datatype_thresholds().
SOURCE_REGISTRY = {
    "whoop": {
        "label": "Whoop",
        "checker_label": "Whoop recovery/sleep",
        "desc": "Recovery, sleep, HRV",
        "category": "Wearables",
        "behavioral": False,  # worn 24/7 — data flows without participation
        "stale_hours": None,
        "active_api": True,
        "expected_days": 7,
        "qa_tier": "required",
        "method": "OAuth API pull, hourly",
        "metrics": "Recovery, sleep, HRV, resting HR, strain",
        "posture": "load-bearing",
        "raw_layout": {"prefix": "raw/matthew/whoop", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"},
        # TR-07 (#415): opt-in provider-diff reconciliation. Whoop runs hourly with
        # no rate-limit breaker, so a daily trailing-window diff (sleeps + workouts)
        # against the API is cheap and catches the late-workout / dropped-day silent
        # drop the DDB-only checks are blind to. whoop_lambda._reconcile.
        "provider_reconcile": True,
    },
    "withings": {
        "label": "Withings",
        "checker_label": "Withings weight/body comp",
        "desc": "Weight & body composition",
        "category": "Wearables",
        # A record only exists when he steps on the scale. The scale syncs
        # itself, but the weigh-in is the behavior — a skipped week is a lapse,
        # not an outage. (Was infra on every surface; held the alarm red.)
        "behavioral": True,
        # Weigh-ins are sporadic (often ~weekly); a missed week before alerting.
        "stale_hours": 7 * 24,
        "active_api": True,
        "expected_days": 5,
        "qa_tier": "optional",  # weigh-ins are sporadic — a missing day is behavior
        "method": "OAuth API pull, hourly",
        "metrics": "Weight, body composition",
        "posture": "load-bearing",
        "raw_layout": {"prefix": "raw/matthew/withings/measurements", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"},
        # #914: weigh-ins are a manual engagement channel — he has to step on the
        # scale. Sporadic (~weekly is healthy), so a lenient ~10d before "quiet".
        "engagement_channel": {"label": "measurement", "stale_days": 10},
    },
    "strava": {
        "label": "Strava",
        "checker_label": "Strava activities",
        "desc": "Activities & walks",
        "category": "Wearables",
        # Activities only exist when he exercises — a rest stretch is a lapse.
        "behavioral": True,
        "stale_hours": None,
        "active_api": True,
        "expected_days": 5,
        "qa_tier": "optional",  # workouts are event-driven — a missing day is behavior
        "method": "OAuth API pull, hourly",
        "metrics": "Activities, walks, heart rate",
        "posture": "load-bearing",
        "raw_layout": {"prefix": "raw/matthew/strava/activities", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"},
        # DI-2: the original source-of-truth reconciler (the Jun-2026 evening-walk
        # fix). strava_lambda._reconcile, wired in ingestion_stack. TR-07 generalized
        # this facet so whoop opts in the same way.
        "provider_reconcile": True,
    },
    "eightsleep": {
        "label": "Eight Sleep",
        "checker_label": "Eight Sleep",
        "desc": "Sleep stages, HR, HRV",
        "category": "Wearables",
        "behavioral": False,  # he sleeps on it every night — passive
        "stale_hours": None,
        "active_api": True,
        "expected_days": 7,
        "qa_tier": "optional",
        "method": "API pull, hourly",
        "metrics": "Sleep stages, HR/HRV, restlessness",  # bed temp retired — ADR-118, #489
        "posture": "portfolio",
        "raw_layout": {"prefix": "raw/matthew/eightsleep", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"},
    },
    "apple_health": {
        "label": "Apple Health",
        "checker_label": "Apple Health",
        "desc": "Steps & active energy",
        "category": "Wearables",
        "behavioral": False,  # HAE webhook automations — passive
        "stale_hours": None,
        "active_api": False,  # webhook push — no cron to go stale
        "expected_days": 7,
        "qa_tier": "required",
        "method": "Health Auto Export webhook, near-real-time",
        "metrics": "Steps, active energy, CGM, blood pressure, state of mind",
        "posture": "load-bearing",
        "raw_layout": {
            "prefix": "raw/matthew/health_auto_export",
            "scheme": "timestamped",
            "note": "sub-datatypes also land at raw/matthew/{cgm_readings,blood_pressure,state_of_mind,workouts}/",
        },
        # #746: the manual HAE capture channel. The partition itself is passive
        # (steps/water keep it alive), but the CGM/BP/State-of-Mind streams below
        # are hand-captured — Matthew wears a sensor, takes a reading, logs a mood.
        "capture_channel": "hae",
        # #746 (migrated from freshness_checker HAE_DATATYPES, D-4/#468): per-stream
        # liveness thresholds. Every HAE datatype lands in this SAME partition, so
        # partition-level "fresh" hides a sensor that went dark weeks ago while
        # steps/water keep writing. `fields` = any-of presence signals; `stale_days`
        # = the stream's own capture cadence (tuned #468 against 45-day HAE
        # telemetry); `manual` = Matthew captures it by hand (nudge-eligible) vs a
        # passive device stream. A lapse reports honestly, it never pages.
        "hae_datatypes": [
            # CGM: a sensor session runs continuously for ~10-14d then needs a new
            # sensor applied — 3d dark means the session lapsed and none was reapplied.
            {
                "key": "cgm",
                "label": "CGM (glucose)",
                "fields": ["blood_glucose_avg", "blood_glucose_readings_count"],
                "stale_days": 3,
                "manual": True,
            },
            # BP: spot-checked, not daily — a fortnight is a lenient "haven't cuffed in a while".
            {
                "key": "blood_pressure",
                "label": "Blood pressure",
                "fields": ["blood_pressure_systolic", "blood_pressure_diastolic"],
                "stale_days": 14,
                "manual": True,
            },
            # State of Mind: How-We-Feel check-ins are sporadic; 14d before it reads dark.
            {
                "key": "state_of_mind",
                "label": "State of Mind",
                "fields": ["som_avg_valence", "som_check_in_count", "som_mood_count"],
                "stale_days": 14,
                "manual": True,
            },
            # Workouts/recovery: passive Apple Watch capture — device stream, not hand-logged.
            {
                "key": "workouts",
                "label": "Workouts / recovery",
                "fields": ["recovery_workout_minutes", "breathwork_minutes"],
                "stale_days": 10,
                "manual": False,
            },
            # Water: logged in-app most days — 3d dark means the habit lapsed.
            {"key": "water", "label": "Water", "fields": ["water_intake_ml", "water_intake_oz"], "stale_days": 3, "manual": True},
            # Steps: passive device activity — a 413-dropped stream is a pipe fault, not a lapse.
            {"key": "steps", "label": "Steps / activity", "fields": ["steps"], "stale_days": 2, "manual": False},
        ],
    },
    "todoist": {
        "label": "Todoist",
        "checker_label": "Todoist tasks",
        "desc": "Tasks completed",
        "category": "Inputs",
        "behavioral": False,  # scheduled API pull
        # #471 (X-5): records are dated by completed DAY and ingestion runs 1x
        # daily, so the freshest record's age at its worst HEALTHY moment (just
        # before the next daily run, record dated the day before yesterday) is
        # ~62h. The old 48h threshold false-staled request-time surfaces (the
        # public board + MCP) ~14h every day; the paging alarm only stayed quiet
        # because its cron happened to sample outside the window. 72h is the
        # tightest bound that can't false-fire and still pages a real outage
        # within a day of the pipe breaking.
        "stale_hours": 72,
        "active_api": True,
        "expected_days": 7,
        "qa_tier": None,
        "method": "API pull, 1x daily (14:00 UTC)",
        "metrics": "Tasks completed",
        "posture": "portfolio",
        "raw_layout": {
            "prefix": "raw/todoist",
            "scheme": "date-tree",
            "filename": "YYYY-MM-DD.json",
            "note": "legacy — no user segment (X-9); filename flipped DD→YYYY-MM-DD at SIMP-2, pre-2026 objects are DD.json (#1256)",
        },
    },
    "habitify": {
        "label": "Habitify",
        "checker_label": "Habitify habits",
        "desc": "Daily habit completions",
        "category": "Inputs",
        "behavioral": False,  # scheduled API pull writes a record daily
        "stale_hours": None,
        "active_api": True,
        "expected_days": 7,
        "qa_tier": "required",
        "method": "API pull, hourly",
        "metrics": "Daily habit completions",
        "posture": "load-bearing",
        "raw_layout": {"prefix": "raw/matthew/habitify", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"},
        # #914: the pull writes a record EVERY day (behavioral: False above is the
        # PIPE's classification) — presence must count only days he actually
        # completed a habit, or a total zero-completion stall reads as gap_days=0.
        "engagement_channel": {"label": "habits", "stale_days": 2, "presence_predicate": "habitify_completed"},
    },
    "macrofactor": {
        "label": "MacroFactor",
        "checker_label": "MacroFactor nutrition",
        "desc": "Nutrition log — manual end-of-day upload, ~24h behind by design",
        "category": "Manual logs",
        "behavioral": True,  # manual diary export — a skipped upload is a lapse
        # Manual-ish upload (not every day) — lenient threshold avoids
        # false-stale; the format-drift check is the real guard.
        "stale_hours": 96,
        "active_api": False,  # arrives via the Dropbox poller, not its own pull
        "expected_days": 6,
        "qa_tier": None,
        "method": "Manual CSV export via Dropbox poller, ~24h behind by design",
        "metrics": "Calories, macros, meals",
        "posture": "load-bearing",
        "raw_layout": None,  # CSVs land via the dropbox transport, not a raw/ archive
        # #914: the PRIMARY presence anchor — the daily-expected manual channel and
        # the first, most reliable thing to stop when routine breaks.
        "engagement_channel": {"label": "food", "stale_days": 2, "primary": True},
    },
    "hevy": {
        "label": "Hevy",
        "checker_label": "Hevy strength sets",
        "desc": "Strength sets — logged when he lifts",
        "category": "Manual logs",
        "behavioral": True,  # a rest week must not read as an outage
        "stale_hours": 7 * 24,
        "active_api": True,
        "expected_days": None,  # lifting is event-driven — gaps are training structure
        "qa_tier": None,
        "method": "API-key pull, hourly 12–23 UTC",
        "metrics": "Strength sets, reps, load, rest times",
        "posture": "load-bearing",
        "raw_layout": {"prefix": "raw/hevy", "scheme": "flat-uuid", "note": "workout-UUID keyed, no date tree (X-9)"},
        # #914: lifting has legit rest days — lenient so a rest day never reads as
        # falling off (the interactive workout channel; macrofactor_workouts is a mirror).
        "engagement_channel": {"label": "training", "stale_days": 4},
    },
    "measurements": {
        "label": "Tape measure",
        "checker_label": "Tape measure check-ins",
        "desc": "Body measurements",
        "category": "Manual logs",
        "behavioral": True,
        "stale_hours": 60 * 24,  # 60 days — one missed session before alert
        "active_api": False,
        "expected_days": None,
        "qa_tier": None,
        "method": "Manual entry via MCP",
        "metrics": "Body tape measurements",
        "posture": "portfolio",
        "raw_layout": None,
        "capture_channel": "mcp",  # #746: entered by hand in an MCP conversation
    },
    "food_delivery": {
        "label": "Food delivery",
        "checker_label": "Food delivery behavioral signal",
        "desc": "Delivery behavioral signal",
        "category": "Manual logs",
        "behavioral": True,
        # 14 days (was 90 — masked a 77-day gap, 2026-03-13 triage).
        "stale_hours": 14 * 24,
        "active_api": False,
        "expected_days": None,
        "qa_tier": None,
        "method": "Manual log",
        "metrics": "Delivery-order behavioral signal (incl. longest-ever streak)",
        "posture": "portfolio",
        "raw_layout": None,
        "capture_channel": "mcp",  # #746: logged by hand in an MCP conversation
    },
    "garmin": {
        "label": "Garmin",
        "checker_label": "Garmin biometrics",
        "desc": "Biometrics — paused (vendor anti-automation, ADR-074)",
        "category": "Wearables",
        "behavioral": False,
        "stale_hours": None,
        # PAUSED 2026-06-03 — Garmin's anti-automation crackdown 429-blocks
        # server-side OAuth refresh from datacenter IPs. See ADR-074.
        "paused": True,
        "active_api": True,
        # Best-effort: still evaluated + logged, excluded from UnhealthySourceCount
        # so the accepted 429 failure can't mask a real source death (2026-06-19).
        "best_effort": True,
        "expected_days": 5,
        "qa_tier": None,  # paused sources render ⏸ from the paused flag
        "method": "OAuth API pull, 4x daily — paused (ADR-074)",
        "metrics": "Stress, body battery, steps",
        "posture": "paused",
        "raw_layout": {
            "prefix": "raw/matthew/garmin",
            "scheme": "date-tree",
            "filename": "YYYY-MM-DD.json",
            "note": "filename flipped DD.json→YYYY-MM-DD.json mid-tree at SIMP-2 (2026); pre-2026 objects are DD.json (#1256)",
        },
        # TR-07 (#415): NO provider_reconcile facet — deliberate. Garmin is paused
        # (ADR-074, datacenter-IP 429 block) and even when live is capped at 4x/day
        # under the OAuth rate limit + best_effort. A reconciler would spend that
        # scarce request budget re-listing what ingestion already can't reliably
        # fetch, and would false-alarm on the accepted-degraded state. The honest
        # answer is DON'T reconcile — recorded as ADR-123. Revisit only if Garmin
        # ingestion itself is restored to a healthy cadence.
    },
    "notion": {
        "label": "Notion",
        "checker_label": "Notion journal",
        "desc": "Journal entries",
        "category": "Inputs",
        "behavioral": True,  # journaling is the behavior
        # #746: derived from the real journaling cadence in DDB — distinct entry
        # days over Feb–May 2026 (…03-29, 04-01, 04-04, 05-02, 05-03, 05-16, 05-25)
        # show a median gap of ~9-10 days with occasional ~26-28d stretches.
        # 14 days is the "it's been about two weeks" mark the evening nudge uses
        # for its gentle mention — lenient enough not to nag a normal fortnight
        # gap. behavioral + monitored:False, so this NEVER pages; the threshold
        # only drives the kind nudge (#746) and the public "dark N days" stamp.
        "stale_hours": 14 * 24,
        "capture_channel": "notion",
        # Visible to the operator MCP view only — never paged, not on the
        # public board (the board mirrors the checker's monitored set).
        "monitored": False,
        "active_api": True,
        "expected_days": 5,
        # was checked as a phantom "journal" partition in qa_smoke — the real
        # partition is notion (X-10; the check is warn-only either way).
        "qa_tier": "optional",
        "method": "API pull (journal database), hourly",
        "metrics": "Journal entries — the subjective layer",
        "posture": "portfolio",
        # #476/X-7: raw archive added — date-tree with a per-page suffix
        # (raw/matthew/notion/YYYY/MM/DD-<page_id>.json), since a day holds many entries.
        "raw_layout": {
            "prefix": "raw/matthew/notion",
            "scheme": "date-tree",
            "filename": "DD-<page_id>.json",
            "note": "per-page filename, not a plain date",
        },
        # #914: journaling is inherently intermittent — lenient tolerance. (Presence's
        # 4d "quiet" mark is narrative-only and deliberately tighter than the 14d
        # evening-nudge threshold above — different surface, different kindness.)
        "engagement_channel": {"label": "journal", "stale_days": 4},
    },
    # ── #1669 (epic #1668): inbound social ingestion — YouTube, the reference source.
    #    Modelled on `notion` (a behavioral, API-pulled, many-items-per-day source), but
    #    registry-resident for FACETS ONLY until the owner provisions the channel id
    #    (life-platform/youtube secret `channel_id` or YOUTUBE_CHANNEL_ID env). Keeping
    #    freshness:False + monitored:False + active_api:False keeps a not-yet-provisioned
    #    source off every freshness/QA/liveness surface (so it can't false-page while it
    #    has no data); flip active_api:True (and drop freshness:False) once the channel id
    #    is live and the first videos land. The raw_layout IS live from day one because
    #    the ingestion Lambda writes per-post raw archives immediately.
    "youtube": {
        "label": "YouTube",
        "checker_label": "YouTube posts",
        "desc": "Inbound social — Matthew's own YouTube videos (public voice)",
        "category": "Inputs",
        "behavioral": True,  # public posting is the behavior
        "stale_hours": None,
        "freshness": False,  # registry-resident until the channel id is provisioned (#1669)
        "monitored": False,  # never paged; not on the public board yet
        "active_api": False,  # keyless RSS pull; flip True once the channel id is live
        "expected_days": None,  # sporadic — not a reconciliation source
        "qa_tier": None,
        "method": "Keyless per-channel RSS pull (framework), hourly",
        "metrics": "Video posts — the outbound public voice, ingested back in",
        "posture": "portfolio",
        # #1682 follow-up: deliberately NO capture_channel. YouTube is a scheduled,
        # keyless RSS pull with no human in the capture loop — per this registry's
        # contract (see the capture_channel doc above) an automatic pipe must not
        # carry one. A stray capture_channel here mislabelled youtube as a manual
        # "you forgot to log" source in evening nudges / coach check-ins / the data
        # API, and tripped test_capture_channels_are_matthews_three.
        # Not on the public /data/ + gear catalogues yet — the source is wired but
        # awaits owner channel-id provisioning + the S4 display story (epic #1668).
        "catalog": False,
        # Suffixed per-post layout (many videos per day) — mirrors the notion per-page
        # archive. The ingestion Lambda writes one file per video; the framework also
        # writes an incidental per-day feed snapshot (audit copy) under the same tree.
        "raw_layout": {
            "prefix": "raw/matthew/youtube",
            "scheme": "date-tree",
            "filename": "YYYY-MM-DD-<video_id>.json",
            "note": "per-post filename (many videos per day); a per-day feed snapshot (YYYY-MM-DD.json) is also written for audit",
        },
    },
    "weather": {
        "label": "Weather",
        "checker_label": "Weather",
        "desc": "Seattle daily weather",
        "category": "Inputs",
        # #470: scheduled API pull, no participation required — infra, so an
        # outage pages instead of hiding behind a shrugged-off "logging lapse".
        # Was freshness: False (registry-resident for facets only, like
        # supplements/dropbox below) — a dead weather pipe was invisible on
        # every surface (checker/board/MCP). Default 48h threshold comfortably
        # covers the 2x-daily cron without false-staling.
        "behavioral": False,
        "stale_hours": None,
        "active_api": True,
        "expected_days": 7,
        "qa_tier": None,
        "method": "Open-Meteo API pull, 2x daily",
        "metrics": "Temperature, precipitation, daylight",
        "posture": "portfolio",
        "raw_layout": {
            "prefix": "raw/weather",
            "scheme": "date-tree",
            "filename": "YYYY-MM-DD.json",
            "note": "legacy layout — no user segment (X-9)",
        },
    },
    # ── #498: registry-resident for facets only — freshness: False keeps every
    #    existing freshness surface (checker / public board / MCP view) unchanged. ──
    "supplements": {
        "label": "Supplements",
        "checker_label": "Supplements",
        "desc": "Supplement & medication log",
        "category": "Manual logs",
        "behavioral": True,
        "stale_hours": None,
        "freshness": False,
        "active_api": False,
        "expected_days": 7,
        "qa_tier": "optional",
        "method": "Habitify bridge (name-mapped habits)",
        "metrics": "Supplement & medication adherence",
        "posture": "load-bearing",  # medication-safety — never hide (ADR-077 dec A)
        "raw_layout": None,
    },
    "dropbox": {
        "label": "Dropbox poller",
        "checker_label": "Dropbox poll",
        "desc": "MacroFactor CSV transport",
        "category": "Inputs",
        "behavioral": False,
        "stale_hours": None,
        "freshness": False,
        "partition": False,  # a transport pipe — its tracker partition is SYSTEM_STATE
        "active_api": True,
        "expected_days": None,
        "qa_tier": None,
        "method": "Dropbox API poll (MacroFactor CSV transport)",
        "metrics": None,
        "posture": "load-bearing",  # nutrition's transport
        "raw_layout": None,
    },
}

# Non-ingestion DDB partitions the MCP raw-data tools may query (clinical truths,
# archives, derived scores, HAE sub-partitions). Joined with the registry's
# partition-bearing keys by mcp_source_ids() — was mcp/config.SOURCES (X-10).
EXTRA_QUERYABLE_PARTITIONS = (
    "chronicling",
    "labs",
    "dexa",
    "genome",
    "state_of_mind",
    "habit_scores",
    "health_auto_export",
    "dropbox_poll",
)


def _freshness_pool():
    """Sources that participate in freshness surfaces at all (#498: weather/
    supplements/dropbox are registry-resident for facets only)."""
    return {k: v for k, v in SOURCE_REGISTRY.items() if v.get("freshness", True)}


def _active_monitored():
    return {k: v for k, v in _freshness_pool().items() if not v.get("paused") and v.get("monitored", True)}


def checker_sources() -> dict:
    """{key: checker_label} for the sources the freshness checker monitors."""
    return {k: v["checker_label"] for k, v in _active_monitored().items()}


def stale_hours_overrides(keys=None) -> dict:
    """{key: hours} for sources with a non-default threshold."""
    pool = SOURCE_REGISTRY if keys is None else {k: SOURCE_REGISTRY[k] for k in keys if k in SOURCE_REGISTRY}
    return {k: v["stale_hours"] for k, v in pool.items() if v["stale_hours"] is not None}


def behavioral_source_keys() -> set:
    """Monitored sources whose staleness is a logging lapse — never pages."""
    return {k for k, v in _active_monitored().items() if v["behavioral"]}


def public_board_sources() -> dict:
    """Active registry for /api/source_freshness (label/desc/category/behavioral)."""
    return {
        k: {"label": v["label"], "desc": v["desc"], "category": v["category"], "behavioral": v["behavioral"]}
        for k, v in _active_monitored().items()
    }


def public_paused_sources() -> dict:
    """Paused sources for the public board — shown, never counted stale."""
    return {k: {"label": v["label"], "desc": v["desc"], "category": v["category"]} for k, v in _freshness_pool().items() if v.get("paused")}


def mcp_sources() -> dict:
    """{key: checker_label} for the operator MCP view — everything on a freshness
    surface, including paused (resolve_source_state reports its true paused/
    rate-limited state) and MCP-only sources like notion."""
    return {k: v["checker_label"] for k, v in _freshness_pool().items()}


# ── #498 facet helpers — each replaces a named hand-rolled enumeration ─────────


def active_api_source_ids() -> list:
    """Scheduled API pulls that must attempt at least daily — the silent-auth-rot
    class. Replaces pipeline_health_check.ACTIVE_API_SOURCES."""
    return sorted(k for k, v in SOURCE_REGISTRY.items() if v.get("active_api"))


def best_effort_source_ids() -> set:
    """Known-brittle by accepted upstream cause — evaluated, never counted
    unhealthy. Replaces pipeline_health_check.BEST_EFFORT_SOURCES."""
    return {k for k, v in SOURCE_REGISTRY.items() if v.get("best_effort")}


def reconciliation_sources() -> list:
    """[(key, expected_days_per_week, desc)] for gap reconciliation over source
    partitions. Replaces the source rows of data_reconciliation.SOURCES (the
    computed partitions stay local to that lambda — they are compute outputs,
    not sources)."""
    return [(k, v["expected_days"], v["desc"]) for k, v in SOURCE_REGISTRY.items() if v.get("expected_days") and v.get("partition", True)]


def provider_reconcile_source_ids() -> list:
    """Sources with OPT-IN source-of-truth reconciliation (DI-2/TR-07): the daily
    provider-API diff that catches a silent drop the DDB high-water mark hides.
    garmin is deliberately absent (ADR-123 — rate-limited/paused, not worth it)."""
    return sorted(k for k, v in SOURCE_REGISTRY.items() if v.get("provider_reconcile"))


def qa_required() -> list:
    """[(key, label)] whose missing-yesterday record is a QA FAILURE.
    Replaces qa_smoke.REQUIRED."""
    return [(k, v["desc"]) for k, v in SOURCE_REGISTRY.items() if v.get("qa_tier") == "required" and not v.get("paused")]


def qa_optional() -> list:
    """[(key, label)] checked but warn-only (event-driven / manual sources).
    Replaces qa_smoke.OPTIONAL."""
    return [(k, v["desc"]) for k, v in SOURCE_REGISTRY.items() if v.get("qa_tier") == "optional" and not v.get("paused")]


def qa_paused() -> list:
    """[(key, note)] intentionally off — shown ⏸, never a fault.
    Replaces qa_smoke.PAUSED."""
    return [(k, v["desc"]) for k, v in SOURCE_REGISTRY.items() if v.get("paused")]


def mcp_source_ids() -> list:
    """Queryable source-partition ids for the MCP raw-data tools: every registry
    source with a DDB partition + the extra non-ingestion partitions.
    Replaces mcp/config.SOURCES."""
    keys = {k for k, v in SOURCE_REGISTRY.items() if v.get("partition", True)}
    return sorted(keys | set(EXTRA_QUERYABLE_PARTITIONS))


def raw_layouts() -> dict:
    """{key: raw_layout} for sources with a raw-S3 archive — the X-9 three-
    generation reality, documented instead of guessed. No mass-move."""
    return {k: v["raw_layout"] for k, v in SOURCE_REGISTRY.items() if v.get("raw_layout")}


# ── #914: presence / quiet-stretch channels — registry-owned ───────────────────
# The severity ladder's thresholds live HERE, next to the engagement_channel facet
# definitions, so channel config and escalation policy are read from one place
# (engagement_core imports both). Presence NARRATES, it never pages (behavioral rule).
#
#   none  — present / light / planned pause: nothing to escalate.
#   soft  — quiet (primary gap 2-4d): a nudge-worthy lull.
#   loud  — dark (primary gap ≥ ENGAGEMENT_SEVERITY_LOUD_DARK_DAYS): a real stall
#           every narrative surface must acknowledge (the acknowledgment gate arms).
#   alarm — dark ≥ ENGAGEMENT_SEVERITY_ALARM_DARK_DAYS, OR
#           ≥ ENGAGEMENT_SEVERITY_ALARM_QUIET_CHANNELS channels quiet
#           ≥ ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS days: the stall IS the
#           story — narratives must open on it.
ENGAGEMENT_SEVERITY_LOUD_DARK_DAYS = 5
ENGAGEMENT_SEVERITY_ALARM_DARK_DAYS = 10
ENGAGEMENT_SEVERITY_ALARM_QUIET_CHANNELS = 3
ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS = 7


def engagement_channels() -> dict:
    """{key: {label, stale_days, presence_predicate, primary}} for the manual
    engagement channels (#914) — the sources that STOP when Matthew disengages.
    Replaces engagement_core's hand-rolled MANUAL_CHANNELS + CHANNEL_STALE_DAYS
    (the #498 drift class). presence_predicate is a NAME resolved by
    engagement_core.PRESENCE_PREDICATES (None = any DDB record counts)."""
    out = {}
    for k, v in SOURCE_REGISTRY.items():
        # cast: the registry's heterogeneous dict values infer as `object`; each
        # engagement_channel entry is a str-keyed sub-dict (no runtime effect).
        ch = cast("dict[str, Any]", v.get("engagement_channel"))
        if not ch:
            continue
        out[k] = {
            "label": ch["label"],
            "stale_days": ch["stale_days"],
            "presence_predicate": ch.get("presence_predicate"),
            "primary": bool(ch.get("primary")),
        }
    return out


def engagement_primary_channel() -> str:
    """The single primary presence anchor (macrofactor/food)."""
    for k, v in engagement_channels().items():
        if v["primary"]:
            return k
    raise ValueError("no engagement_channel is marked primary")


# ── #746: manual-source reliability — staleness surfaced kindly ────────────────


def manual_capture_sources(channel: str = None) -> dict:
    """{key: {label, channel, stale_hours}} for the manual-capture sources — the
    HAE / Notion / MCP-conversation channels Matthew fills by hand (#746,
    Matthew's decision).

    These are the ONLY sources eligible for the evening nudge's gentle "gone
    quiet" mention and the public "manual source dark N days" degraded stamp. An
    automatic pipe (worn device, scheduled pull) has no capture_channel, so a
    device outage — a dead Whoop token the nudge can't fix — is structurally
    excluded from both surfaces. Pass `channel` to filter to one lane
    ('hae' | 'notion' | 'mcp'). `stale_hours` falls back to the registry default."""
    out = {}
    for k, v in SOURCE_REGISTRY.items():
        ch = v.get("capture_channel")
        if not ch or (channel and ch != channel):
            continue
        sh = v.get("stale_hours")
        out[k] = {"label": v["label"], "channel": ch, "stale_hours": sh if sh is not None else DEFAULT_STALE_HOURS}
    return out


def hae_datatype_thresholds() -> list:
    """Per-HAE-sub-datatype liveness thresholds (CGM/water/BP/State of Mind/
    steps/workouts) — the streams that share the single apple_health partition, so
    a partition-level "fresh" can hide a months-dark sensor (D-4/#468). Migrated
    here from freshness_checker by #746 so every source threshold lives in this one
    registry. Each: {key, label, fields, stale_days, manual}. The checker's
    HAE_DATATYPES aliases this; compute_datatype_liveness reads it."""
    return [dict(d) for d in cast("list[dict[str, Any]]", SOURCE_REGISTRY["apple_health"].get("hae_datatypes", []))]


def manual_hae_datatype_keys() -> set:
    """The HAE sub-datatypes Matthew captures by hand (CGM/water/BP/State of Mind)
    — nudge-eligible, unlike the passive device streams (steps/workouts) which a
    reminder-to-log can't fix (#746)."""
    return {d["key"] for d in cast("list[dict[str, Any]]", SOURCE_REGISTRY["apple_health"].get("hae_datatypes", [])) if d.get("manual")}


def catalog_entries() -> list:
    """Public data-source catalogue rows for site/data/data_sources.json
    (generated by scripts/v4_build_data_sources.py — never hand-edited).
    Sorted: load-bearing first, then by label."""
    posture_rank = {"load-bearing": 0, "portfolio": 1, "paused": 2, "archive": 3}
    rows = []
    for k, v in SOURCE_REGISTRY.items():
        if not v.get("metrics"):
            continue  # transport pipes aren't data sources
        if v.get("catalog") is False:
            continue  # #1669: wired but not yet publicly advertised (e.g. awaiting owner provisioning)
        rows.append(
            {
                "id": k,
                "name": v["label"],
                "category": v["category"],
                "metrics": v["metrics"],
                "method": v["method"],
                "posture": v["posture"],
            }
        )
    return sorted(rows, key=lambda r: (posture_rank.get(r["posture"], 9), r["name"]))
