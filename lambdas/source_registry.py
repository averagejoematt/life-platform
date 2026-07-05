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

Ships in the shared layer (build_layer.sh MODULES + ci/lambda_map.json) so the
MCP and site-api Lambdas resolve it; stacks that bundle lambdas/ get the same
file at /var/task, which shadows the layer copy harmlessly.
"""

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
#   raw_layout     the ACTUAL raw-S3 shape: {prefix, scheme[, note]} where scheme is
#                  'date-tree' ({prefix}/{YYYY}/{MM}/{DD}.json), 'flat-uuid'
#                  ({prefix}/{id}.json), or 'timestamped'; None = no raw archive.
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
        "raw_layout": {"prefix": "raw/matthew/whoop", "scheme": "date-tree"},
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
        "raw_layout": {"prefix": "raw/matthew/withings/measurements", "scheme": "date-tree"},
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
        "raw_layout": {"prefix": "raw/matthew/strava/activities", "scheme": "date-tree"},
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
        "metrics": "Sleep stages, bed temperature, HR/HRV",
        "posture": "portfolio",
        "raw_layout": {"prefix": "raw/matthew/eightsleep", "scheme": "date-tree"},
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
        "raw_layout": {"prefix": "raw/todoist", "scheme": "date-tree", "note": "legacy layout — no user segment (X-9)"},
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
        "raw_layout": {"prefix": "raw/matthew/habitify", "scheme": "date-tree"},
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
        "raw_layout": {"prefix": "raw/matthew/garmin", "scheme": "date-tree"},
    },
    "notion": {
        "label": "Notion",
        "checker_label": "Notion journal",
        "desc": "Journal entries",
        "category": "Inputs",
        "behavioral": True,  # journaling is the behavior
        "stale_hours": None,
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
        "raw_layout": {"prefix": "raw/matthew/notion", "scheme": "date-tree", "note": "per-page: DD-<page_id>.json"},
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
        "raw_layout": {"prefix": "raw/weather", "scheme": "date-tree", "note": "legacy layout — no user segment (X-9)"},
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


def catalog_entries() -> list:
    """Public data-source catalogue rows for site/data/data_sources.json
    (generated by scripts/v4_build_data_sources.py — never hand-edited).
    Sorted: load-bearing first, then by label."""
    posture_rank = {"load-bearing": 0, "portfolio": 1, "paused": 2, "archive": 3}
    rows = []
    for k, v in SOURCE_REGISTRY.items():
        if not v.get("metrics"):
            continue  # transport pipes aren't data sources
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
