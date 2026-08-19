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

from datetime import date
from typing import Any, cast

# #1677: the CLOSED platforms' entries + their `inbound_mode` value, kept in a sibling
# (one registry, spliced in below) — see source_registry_closed_social.py.
from ingestion.source_registry_closed_social import CLOSED_SOCIAL_PASTE_SOURCES, INBOUND_PASTE_ONLY  # noqa: F401

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
#                  facet — never construct a key from the prefix alone; `raw_date_key()`
#                  builds the per-day key for you. A source that fans out into several
#                  raw trees (apple_health's HAE datatypes) carries them as a
#                  `sub_layouts` sub-dict, each with its own prefix/scheme/filename
#                  (#2278 — a prose `note` is not something a reader can resolve).
#   inbound_mode   (#1677) how a record can arrive AT ALL. Absent = a fetch of some kind
#                  exists. 'paste-only' = the closed platforms (X/Instagram/TikTok):
#                  no client, no secret, no token path in this repo — the owner pastes
#                  or nothing arrives. Read by paste_only_source_ids(); do NOT infer it
#                  from active_api:False, which only means "not yet polling".
#   social_channel True = an inbound social/broadcast channel (epic #1668): Matthew's own
#                  public voice ingested back in, whether fetched (youtube/bluesky/
#                  mastodon) or paste-only (x/instagram/tiktok). #2806/#2807/#2808: the
#                  ONE vocabulary for "which channels does social enrichment/the
#                  broadcast feed/the daily-brief coach context cover" — it had drifted
#                  into three hand-typed copies (SOCIAL_CHANNELS in ingestion_stack.py,
#                  _BROADCAST_SOURCES in site_api_social.py, daily_brief_lambda's env
#                  fallback), and the paste-only three were uniquely missing from all of
#                  them. Read by social_channel_source_ids(); paste_only_source_ids() is
#                  a strict subset by construction.
#   provider_reconcile
#                  True = OPT-IN source-of-truth reconciliation (DI-2/TR-07): a
#                  daily job diffs the PROVIDER API against stored records and
#                  emits MissingActivityCount{Source=<key>} — the one check that
#                  sees a silent drop the DDB high-water mark hides. Only sources
#                  whose provider exposes a queryable record list AND that aren't
#                  rate-limit-degraded qualify; garmin is EXPLICITLY excluded
#                  (ADR-123). Default absent/False. Read by provider_reconcile_source_ids().
#   oauth          (#1960) True = a CREDENTIALED API pull whose auth can DIE — an
#                  OAuth token that expires/gets revoked, or a static API key that
#                  gets rotated. This is exactly the set that routes through
#                  common/auth_breaker (directly or via the SIMP-2 framework's
#                  breaker hooks) and can therefore emit
#                  LifePlatform/OAuth IngestAuthHealthy = 0. Keyless pulls are
#                  False by omission: weather (Open-Meteo, no key) and youtube
#                  (per-channel RSS) have no credential to expire, so a per-source
#                  auth alarm on them could never fire. Webhook / manual sources
#                  (apple_health, measurements, food_delivery, supplements) have no
#                  outbound credential at all. Read by oauth_source_ids() —
#                  tests/test_oauth_alarm_coverage.py derives the required
#                  per-source alarm set from it, so a NEW credentialed source with
#                  no alarm fails CI instead of dying silently.
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
# Annotated explicitly: splicing in the closed-social section (#1677) otherwise widens
# the inferred value type to `object` and reds every facet helper under mypy.
SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "whoop": {
        "label": "Whoop",
        "checker_label": "Whoop recovery/sleep",
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
        "desc": "Recovery, sleep, HRV",
        "category": "Wearables",
        "behavioral": False,  # worn 24/7 — data flows without participation
        "stale_hours": None,
        "active_api": True,
        "expected_days": 7,
        "qa_tier": "required",
        "method": "OAuth API pull, 5x daily",
        "metrics": "Recovery, sleep, HRV, resting HR, strain",
        "posture": "load-bearing",
        "raw_layout": {"prefix": "raw/matthew/whoop", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"},
        # TR-07 (#415): opt-in provider-diff reconciliation. Whoop pulls 5x daily
        # (#2204 — the hourly cron spent a refresh-token rotation every run) with
        # no rate-limit breaker, so a daily trailing-window diff (sleeps + workouts)
        # against the API is cheap and catches the late-workout / dropped-day silent
        # drop the DDB-only checks are blind to. whoop_lambda._reconcile.
        "provider_reconcile": True,
    },
    "withings": {
        "label": "Withings",
        "checker_label": "Withings weight/body comp",
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
            "note": "sub-datatypes also land at raw/matthew/{cgm_readings,blood_pressure,state_of_mind,workouts}/ — see sub_layouts",
            # #2278: the note above was prose only, so every reader of an HAE
            # sub-datatype hand-built its key from it — and one (the dormant BP
            # reader in mcp/tools_lifestyle.py) dropped the user segment entirely
            # and read a prefix nothing has ever written. These are the four
            # sub-streams health_auto_export_lambda.py fans out to; each is its
            # own date tree with a DD.json leaf (NOT the YYYY-MM-DD.json form the
            # SIMP-2 framework sources flipped to). Resolve via raw_date_key().
            "sub_layouts": {
                "cgm_readings": {"prefix": "raw/matthew/cgm_readings", "scheme": "date-tree", "filename": "DD.json"},
                "blood_pressure": {"prefix": "raw/matthew/blood_pressure", "scheme": "date-tree", "filename": "DD.json"},
                "state_of_mind": {"prefix": "raw/matthew/state_of_mind", "scheme": "date-tree", "filename": "DD.json"},
                "workouts": {"prefix": "raw/matthew/workouts", "scheme": "date-tree", "filename": "DD.json"},
            },
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
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
        # The facet said None ("CSVs land via the dropbox transport, not a raw/
        # archive") while macrofactor_lambda.archive_raw() has written a raw/ copy of
        # EVERY upload since 2026-02 — verified 2026-08-08: 48 objects under this
        # prefix. X-9's contract is that replay tooling READS the layout instead of
        # guessing, and a facet that denies a live archive is worse than a wrong one.
        # Documented, never moved (raw/* is delete-protected, ADR-046).
        "raw_layout": {
            "prefix": "raw/matthew/macrofactor",
            "scheme": "date-tree",
            "filename": "<uploaded-filename>.csv",
            # No per-day key exists: the YYYY/MM partition is the INGEST month (the
            # archive is stamped at upload time, not from the CSV's dates — one file
            # carries many days), and the leaf keeps whatever MacroFactor named the
            # export. raw_date_key() therefore raises on this source by design.
            "note": "ingest-month tree, uploaded filename as the leaf — one CSV holds many days, so there is no per-day key",
            # Each detected CSV format archives under its own subfolder (the nutrition
            # diary at the root). `unknown` is the #469 forensic path.
            "sub_layouts": {
                "workouts": {
                    "prefix": "raw/matthew/macrofactor/workouts",
                    "scheme": "date-tree",
                    "filename": "<uploaded-filename>.csv",
                },
                "daily_summary": {
                    "prefix": "raw/matthew/macrofactor/daily_summary",
                    "scheme": "date-tree",
                    "filename": "<uploaded-filename>.csv",
                },
                "unknown": {
                    "prefix": "raw/matthew/macrofactor/unknown",
                    "scheme": "date-tree",
                    "filename": "<uploaded-filename>.csv",
                    "note": "#469 forensic archive for an unrecognised export format, written just before the handler raises",
                },
                "exports": {
                    "prefix": "raw/matthew/macrofactor/exports",
                    "scheme": "date-tree",
                    "filename": "<uploaded-filename>.csv",
                    "note": "historical — written by the 2026-02 one-off backfill, not by the current lambda",
                },
            },
        },
        # #914: the PRIMARY presence anchor — the daily-expected manual channel and
        # the first, most reliable thing to stop when routine breaks.
        "engagement_channel": {"label": "food", "stale_days": 2, "primary": True},
    },
    "hevy": {
        "label": "Hevy",
        "checker_label": "Hevy strength sets",
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
        "social_channel": True,  # #2806/#2807/#2808: registry vocabulary for social/broadcast channels
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
    # ── #1676 (epic #1668): inbound social ingestion — Bluesky, extending the youtube
    #    reference source (#1669) to a second open platform. Same registry-resident,
    #    facets-only shape until the owner provisions the handle (life-platform/bluesky
    #    secret `handle` or BLUESKY_HANDLE env). Keeping freshness:False +
    #    monitored:False + active_api:False keeps a not-yet-provisioned source off every
    #    freshness/QA/liveness surface; flip active_api:True (and drop freshness:False)
    #    once the handle is live and the first posts land. The raw_layout IS live from
    #    day one because the ingestion Lambda writes per-post raw archives immediately.
    "bluesky": {
        "label": "Bluesky",
        "checker_label": "Bluesky posts",
        "desc": "Inbound social — Matthew's own Bluesky posts (public voice)",
        "category": "Inputs",
        "behavioral": True,  # public posting is the behavior
        "social_channel": True,  # #2806/#2807/#2808: registry vocabulary for social/broadcast channels
        "stale_hours": None,
        "freshness": False,  # registry-resident until the handle is provisioned (#1676)
        "monitored": False,  # never paged; not on the public board yet
        "active_api": False,  # keyless public AppView pull; flip True once the handle is live
        "expected_days": None,  # sporadic — not a reconciliation source
        "qa_tier": None,
        "method": "Keyless public AppView pull (framework), hourly",
        "metrics": "Posts — the outbound public voice, ingested back in",
        "posture": "portfolio",
        # Deliberately NO capture_channel — same #1682 rationale as youtube: a
        # scheduled, keyless pull with no human in the capture loop must not carry
        # one (would mislabel it a manual "you forgot to log" source).
        # Not on the public /data/ + gear catalogues yet — the source is wired but
        # awaits owner handle provisioning + the S4 display story (epic #1668).
        "catalog": False,
        # Suffixed per-post layout (many posts per day) — mirrors youtube.
        "raw_layout": {
            "prefix": "raw/matthew/bluesky",
            "scheme": "date-tree",
            "filename": "YYYY-MM-DD-<post_id>.json",
            "note": "per-post filename (many posts per day); a per-day feed snapshot (YYYY-MM-DD.json) is also written for audit",
        },
    },
    # ── #1676 (epic #1668): inbound social ingestion — Mastodon, extending the youtube
    #    reference source (#1669) to a third open platform (alongside bluesky). Same
    #    registry-resident, facets-only shape until the owner provisions the instance +
    #    handle (life-platform/mastodon secret `instance`/`handle` or
    #    MASTODON_INSTANCE/MASTODON_HANDLE env). Keeping freshness:False +
    #    monitored:False + active_api:False keeps a not-yet-provisioned source off every
    #    freshness/QA/liveness surface; flip active_api:True (and drop freshness:False)
    #    once the account is live and the first posts land. The raw_layout IS live from
    #    day one because the ingestion Lambda writes per-post raw archives immediately.
    "mastodon": {
        "label": "Mastodon",
        "checker_label": "Mastodon posts",
        "desc": "Inbound social — Matthew's own Mastodon posts (public voice)",
        "category": "Inputs",
        "behavioral": True,  # public posting is the behavior
        "social_channel": True,  # #2806/#2807/#2808: registry vocabulary for social/broadcast channels
        "stale_hours": None,
        "freshness": False,  # registry-resident until the instance/handle is provisioned (#1676)
        "monitored": False,  # never paged; not on the public board yet
        "active_api": False,  # keyless public REST pull; flip True once the account is live
        "expected_days": None,  # sporadic — not a reconciliation source
        "qa_tier": None,
        "method": "Keyless public REST pull (framework), hourly",
        "metrics": "Posts — the outbound public voice, ingested back in",
        "posture": "portfolio",
        # Deliberately NO capture_channel — same #1682 rationale as youtube.
        # Not on the public /data/ + gear catalogues yet — the source is wired but
        # awaits owner instance/handle provisioning + the S4 display story (epic #1668).
        "catalog": False,
        # Suffixed per-post layout (many posts per day) — mirrors youtube/bluesky.
        "raw_layout": {
            "prefix": "raw/matthew/mastodon",
            "scheme": "date-tree",
            "filename": "YYYY-MM-DD-<post_id>.json",
            "note": "per-post filename (many posts per day); a per-day feed snapshot (YYYY-MM-DD.json) is also written for audit",
        },
    },
    # #1677 (epic #1668): the closed platforms — X, Instagram, TikTok. Paste-only, no
    # token; their entries and the rationale live in source_registry_closed_social.py,
    # spliced in here so SOURCE_REGISTRY stays the one dict every consumer reads.
    **CLOSED_SOCIAL_PASTE_SOURCES,
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
        "metrics": "Temperature, precipitation, daylight, conditions, sunrise/sunset, AQI",
        "posture": "portfolio",
        "raw_layout": {
            "prefix": "raw/weather",
            "scheme": "date-tree",
            "filename": "YYYY-MM-DD.json",
            "note": (
                "legacy layout — no user segment (X-9). Gap 2026-03-10 → 2026-08 (#1949): the "
                "03-09 IAM migration dropped the role's PutObject grant and the framework "
                "swallowed the AccessDenied; grant restored + failure unswallowed 2026-08-02. "
                "The gap is refetchable from Open-Meteo's archive API if ever needed (DDB was "
                "never affected)."
            ),
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
        "oauth": True,  # #1960: credentialed pull — auth can die, routes through auth_breaker
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
    "time_affluence",  # #1408: weekly Time-Affluence proxy (PROXY#/EDGE#) + probe (DATE#) — derived, no ingestion
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


# ── #2326: the quiet notice for load-bearing behavioral sources ────────────────
# DECISION (2026-08-09, #2326): YES — a source classified `behavioral: True` AND
# `posture: load-bearing` gets a NON-PAGING quiet notice once it has been silent
# far longer than its stale_hours. MacroFactor went 45 days dark (cycle 12 had
# zero nutrition data) while the Dropbox poller ran healthy — "behavioral means
# never page" had in practice also become "never mention": nothing an operator
# reads said so. The notice lives in the daily brief (a calm "quiet inputs"
# block, rendered by daily_brief_lambda next to the WR-48 Data Status banner).
#
# Explicitly NOT a reclassification to infrastructure: that would route these
# sources into StaleSourceCount and page the slo-source-freshness alarm on a
# correct rest state (a skipped weigh-in, a rest week) — the exact
# mis-classification the header of this file warns about, and the drift #392
# cured. `behavioral` stays True; the notice NEVER feeds a paging path.
#
# Distinct-signal contract: the `stale_hours` facets above are canonical and
# encode each WRITER's cadence (nutrition ~24h-lagged by design, weigh-ins
# ~weekly). The quiet threshold does not re-state or re-tune them — it derives:
# quiet_after_days = max(QUIET_NOTICE_MIN_DAYS, stale_hours × QUIET_NOTICE_FACTOR),
# i.e. "quiet for several multiples of a normal lapse", strictly beyond the
# staleness threshold, so a normal rest stretch never surfaces.
QUIET_NOTICE_FACTOR = 3
QUIET_NOTICE_MIN_DAYS = 14


def quiet_watch_sources() -> dict:
    """{key: {label, checker_label, quiet_after_days}} for every source whose
    facets are `behavioral: True` AND `posture: load-bearing` (#2326) — derived,
    never hand-typed. Only facet-level exclusions apply: `partition: False`
    (nothing to query) and `paused` (intentionally off). Note this deliberately
    ignores the `freshness`/`monitored` surface facets: supplements is
    freshness-surface-exempt (#498) yet medication-safety load-bearing (ADR-077
    dec A), and the quiet notice is precisely the surface of last resort."""
    out = {}
    for k, v in SOURCE_REGISTRY.items():
        if not v["behavioral"] or v.get("posture") != "load-bearing":
            continue
        if v.get("partition") is False or v.get("paused"):
            continue
        sh = v["stale_hours"] if v["stale_hours"] is not None else DEFAULT_STALE_HOURS
        out[k] = {
            "label": v["label"],
            "checker_label": v["checker_label"],
            "quiet_after_days": max(QUIET_NOTICE_MIN_DAYS, int(sh * QUIET_NOTICE_FACTOR / 24)),
        }
    return out


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


def paste_only_source_ids() -> list:
    """Closed platforms whose ONLY inbound path is a manual paste (#1677, epic #1668).

    Read by the paste ingestion Lambda so its channel set can never drift from the
    registry. See source_registry_closed_social.py for what the facet commits to.
    """
    return sorted(k for k, v in SOURCE_REGISTRY.items() if v.get("inbound_mode") == INBOUND_PASTE_ONLY)


def social_channel_source_ids() -> list:
    """Every inbound social/broadcast channel (epic #1668) — the three fetched, open
    platforms (youtube/bluesky/mastodon) UNION the three paste-only closed platforms
    (x/instagram/tiktok, `paste_only_source_ids()`). `paste_only_source_ids()` is a
    strict subset by construction: every paste-only source also carries
    `social_channel: True`.

    THE one registry-derived vocabulary for "which channels count as social" (#2806/
    #2807/#2808) — three consumers had each hand-typed their own copy and drifted
    apart, uniquely excluding the paste-only three (the closed platforms landed after
    the enrichment lambda's env and the site's `_BROADCAST_SOURCES` tuple were last
    hand-edited, #1677): the enrichment lambda's `SOCIAL_CHANNELS` env
    (`cdk/stacks/ingestion_stack.py`, now derived at synth time), the broadcast feed +
    membrane dashboard's `_BROADCAST_SOURCES` (`lambdas/web/site_api_social.py`), and
    the daily brief's coach-context channel read (`lambdas/emails/daily_brief_lambda.py`).
    """
    return sorted(k for k, v in SOURCE_REGISTRY.items() if v.get("social_channel"))


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


def oauth_source_ids() -> list:
    """Credentialed API pulls whose AUTH can die (#1960) — the set that routes
    through common/auth_breaker and can emit IngestAuthHealthy = 0, so the set
    that needs per-source auth alarm coverage. Keyless pulls (weather, youtube)
    and webhook/manual sources are excluded: no credential, nothing to expire.
    Authority for tests/test_oauth_alarm_coverage.py."""
    return sorted(k for k, v in SOURCE_REGISTRY.items() if v.get("oauth"))


def oauth_digest_only_source_ids() -> set:
    """OAuth sources whose auth alarm must route to the DAILY DIGEST rather than
    the URGENT page (#1960). Two registry-derived reasons, no hand-list:

      * `paused` / `best_effort` — the failure is an ACCEPTED upstream condition.
        ADR-074 removed `garmin-auth-unhealthy-24h` from paging for exactly this:
        a permanently-red alarm for an unfixable state trains the operator to
        ignore the channel. Restoring per-source coverage must not restore that.
      * `monitored: False` — operator-MCP visibility only (notion), never on a
        paging surface.

    Everything else pages: a dead credential on a monitored, live source is
    actionable within the hour."""
    return {
        k
        for k, v in SOURCE_REGISTRY.items()
        if v.get("oauth") and (v.get("paused") or v.get("best_effort") or not v.get("monitored", True))
    }


def qa_required() -> list:
    """[(key, label)] whose missing-yesterday record is a QA FAILURE.
    Replaces qa_smoke.REQUIRED."""
    return [(k, v["desc"]) for k, v in SOURCE_REGISTRY.items() if v.get("qa_tier") == "required" and not v.get("paused")]


def qa_required_oauth_source_ids() -> set:
    """#1934: the intersection that matters for auth-breaker paging — a source
    that is BOTH credentialed (auth can die, routes through auth_breaker) AND
    qa_required (a missing day is never "just behavior", it's a platform QA
    failure). A latched breaker on one of these must raise a DEDICATED
    `ingest-auth-unhealthy-{source}` signal, not just the weaker
    `ingest-consecutive-failures-{source}` family — that family needs 3
    consecutive failing runs (~2-3h delay) and conflates auth failures with
    transport/parse/throttle ones, so an operator can't tell "credential dead,
    rotate it" from "the upstream API had a rough hour" without opening logs.

    whoop was exactly this gap: qa_required, the platform's only fully-passive
    daily source, previously covered only by ingest-consecutive-failures-whoop
    (ER-01, 2026-06-12) — habitify (the other qa_required OAuth source) already
    had the dedicated alarm via #1960. Authority for
    tests/test_oauth_alarm_coverage.py."""
    required = {k for k, _ in qa_required()}
    return set(oauth_source_ids()) & required


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


def raw_layout_for(source: str, sub: str | None = None) -> dict:
    """The raw_layout facet for `source` (or one of its `sub_layouts`, e.g.
    apple_health's per-datatype HAE trees).

    Raises rather than guessing: an unknown source, a source with no raw
    archive, or an unknown sub-stream is a caller bug, and the X-9 failure mode
    (#1256/#2278) is precisely a plausible-looking key that resolves to nothing.
    """
    try:
        entry = SOURCE_REGISTRY[source]
    except KeyError:
        raise KeyError(f"raw_layout_for: unknown source {source!r}") from None
    layout = cast("dict[str, Any] | None", entry.get("raw_layout"))
    if not layout:
        raise ValueError(f"raw_layout_for: source {source!r} has no raw-S3 archive")
    if sub is None:
        return layout
    subs = cast("dict[str, Any]", layout.get("sub_layouts") or {})
    try:
        return cast("dict[str, Any]", subs[sub])
    except KeyError:
        raise KeyError(f"raw_layout_for: source {source!r} has no raw sub-layout {sub!r} (have: {sorted(subs)})") from None


def raw_date_key(source: str, date_str: str, sub: str | None = None) -> str:
    """The ACTUAL raw-S3 key holding one day of `source` — X-9/#1256's cure.

    The raw/ zone is three-generation fractured in BOTH the prefix (user-segmented
    vs legacy vs flat) and the leaf filename (`YYYY-MM-DD.json` vs `DD.json`), so a
    hand-built key is a coin flip. #2278 is what that costs: a reader that omitted
    the user segment read a prefix nothing has ever written, and — because the
    caller swallowed NoSuchKey — reported "no readings on file" instead of failing.

    Every field here comes from the source's own `raw_layout`. `date_str` is
    ISO `YYYY-MM-DD` and is validated, so a malformed date raises instead of
    silently addressing a nonexistent object.
    """
    layout = raw_layout_for(source, sub)
    scheme = layout.get("scheme")
    if scheme != "date-tree":
        raise ValueError(f"raw_date_key: {source!r}{'/' + sub if sub else ''} is {scheme!r}, not a date tree — no per-day key exists")
    day = date.fromisoformat(date_str)
    filename = layout.get("filename")
    if filename == "YYYY-MM-DD.json":
        leaf = f"{day:%Y-%m-%d}.json"
    elif filename == "DD.json":
        leaf = f"{day:%d}.json"
    else:
        raise ValueError(f"raw_date_key: unhandled leaf filename {filename!r} for {source!r}")
    return f"{layout['prefix']}/{day:%Y}/{day:%m}/{leaf}"


def raw_year_prefix(source: str, year: int, sub: str | None = None) -> str:
    """The S3 listing prefix for one YEAR of `source` — `raw_date_key`'s sibling (#2286).

    A caller enumerating "which days exist" wants a prefix, not a key, and had no
    registry-resolved way to get one — so `mcp/tools_cgm.py` hand-built
    ``f"raw/{USER_ID}/cgm_readings/{year}/"`` and then reversed the same literal to
    parse the date back out of each key. Two hand-built forms of the same fact, either
    of which goes silently empty if the layout moves: exactly #2278's failure, which
    reported "no readings on file" rather than raising.

    Restricted to `date-tree` sources on purpose. A flat or timestamped archive has no
    per-year prefix, and inventing one would hand back a plausible string that lists
    nothing — the X-9 trap this function exists to close.
    """
    layout = raw_layout_for(source, sub)
    scheme = layout.get("scheme")
    if scheme != "date-tree":
        raise ValueError(
            f"raw_year_prefix: {source!r}{'/' + sub if sub else ''} is {scheme!r}, not a date tree — it has no per-year prefix"
        )
    return f"{layout['prefix']}/{int(year):04d}/"


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
