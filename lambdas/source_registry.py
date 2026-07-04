"""source_registry.py — THE canonical data-source registry (#392).

One place a source's identity, staleness threshold, and behavioral-vs-
infrastructure classification live. Derived by:
  - lambdas/emails/freshness_checker_lambda.py  (StaleSourceCount → the paging
    slo-source-freshness alarm)
  - lambdas/web/site_api_data.py                (/api/source_freshness — the
    public pipeline board)
  - mcp/tools_labs.py::tool_get_freshness_status (operator MCP view)

These three used to hand-mirror this data under "KEEP IN SYNC" comments and
drifted: withings/strava were classified infrastructure everywhere, macrofactor
was behavioral publicly but infrastructure in the checker, and the MCP mirror
still carried the pre-triage food_delivery 90-day threshold. Result: a quiet
logging stretch held the paging alarm red for days — training the operator to
ignore the one alarm class that once hid a six-week outage.

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
SOURCE_REGISTRY = {
    "whoop": {
        "label": "Whoop",
        "checker_label": "Whoop recovery/sleep",
        "desc": "Recovery, sleep, HRV",
        "category": "Wearables",
        "behavioral": False,  # worn 24/7 — data flows without participation
        "stale_hours": None,
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
    },
    "strava": {
        "label": "Strava",
        "checker_label": "Strava activities",
        "desc": "Activities & walks",
        "category": "Wearables",
        # Activities only exist when he exercises — a rest stretch is a lapse.
        "behavioral": True,
        "stale_hours": None,
    },
    "eightsleep": {
        "label": "Eight Sleep",
        "checker_label": "Eight Sleep",
        "desc": "Sleep stages, HR, HRV",
        "category": "Wearables",
        "behavioral": False,  # he sleeps on it every night — passive
        "stale_hours": None,
    },
    "apple_health": {
        "label": "Apple Health",
        "checker_label": "Apple Health",
        "desc": "Steps & active energy",
        "category": "Wearables",
        "behavioral": False,  # HAE webhook automations — passive
        "stale_hours": None,
    },
    "todoist": {
        "label": "Todoist",
        "checker_label": "Todoist tasks",
        "desc": "Tasks completed",
        "category": "Inputs",
        "behavioral": False,  # scheduled API pull
        # Records are dated by completed DAY and the freshest is always
        # "yesterday", so a 24h default false-fires every afternoon. 48h still
        # catches a genuine 2-day outage.
        "stale_hours": 48,
    },
    "habitify": {
        "label": "Habitify",
        "checker_label": "Habitify habits",
        "desc": "Daily habit completions",
        "category": "Inputs",
        "behavioral": False,  # scheduled API pull writes a record daily
        "stale_hours": None,
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
    },
    "hevy": {
        "label": "Hevy",
        "checker_label": "Hevy strength sets",
        "desc": "Strength sets — logged when he lifts",
        "category": "Manual logs",
        "behavioral": True,  # a rest week must not read as an outage
        "stale_hours": 7 * 24,
    },
    "measurements": {
        "label": "Tape measure",
        "checker_label": "Tape measure check-ins",
        "desc": "Body measurements",
        "category": "Manual logs",
        "behavioral": True,
        "stale_hours": 60 * 24,  # 60 days — one missed session before alert
    },
    "food_delivery": {
        "label": "Food delivery",
        "checker_label": "Food delivery behavioral signal",
        "desc": "Delivery behavioral signal",
        "category": "Manual logs",
        "behavioral": True,
        # 14 days (was 90 — masked a 77-day gap, 2026-03-13 triage).
        "stale_hours": 14 * 24,
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
    },
}


def _active_monitored():
    return {k: v for k, v in SOURCE_REGISTRY.items() if not v.get("paused") and v.get("monitored", True)}


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
    return {k: {"label": v["label"], "desc": v["desc"], "category": v["category"]} for k, v in SOURCE_REGISTRY.items() if v.get("paused")}


def mcp_sources() -> dict:
    """{key: checker_label} for the operator MCP view — everything, including
    paused (resolve_source_state reports its true paused/rate-limited state)
    and MCP-only sources like notion."""
    return {k: v["checker_label"] for k, v in SOURCE_REGISTRY.items()}
