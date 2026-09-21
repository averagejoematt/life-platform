# module-size-exception: canonical registry (#3615) — WEEK_SURFACES / ABSENCE_SURFACES /
# RATE_CONSUMERS are tables of per-surface rows plus thin accessors. Growth is linear in the
# number of SURFACES, and splitting it would create a second place to look up "who narrates
# this week", which is the drift it exists to end. See docs/ENGINEERING_STANDARDS.md §2.
"""week_narration_registry.py — every surface that narrates a WEEK, and the facts they must agree on (#3615 boxes 2+3).

THE CLAUSE THIS SERVES, AND WHY PROSE COULD NOT HOLD IT
  "No page contradicts another page's account of the same week" had no instrument over
  its SET. Every contradiction on the 2026-09-05 review — #3518, #3526, #3520, #3521,
  #3515 — was found by a HUMAN reading two pages side by side, and every fix landed on
  its specimen, which is #3594's diagnosis exactly. A specimen fix leaves the next pair
  of pages free to disagree tomorrow.

WHAT A ROW COMMITS TO
  A `Surface` is something a reader can load that RESTATES a week fact. Each row names
  the producer that owns it, how to fetch it, and — per fact — the path where that
  surface's OWN rendered value lives. Nothing here recomputes a fact: the gate reads
  what the surface actually serves, from its own producer (ADR-104/105). A gate that
  re-derived the number would grade its own arithmetic, agree with itself, and be blind
  to precisely the class of defect it exists to catch (the "comparison gate blind when
  both sides agree" lesson).

DATED vs INVARIANT FACTS, WHICH IS THE WHOLE TRICK
  `cycle_genesis`, `baseline_weight_lbs` and `goal_weight_lbs` are INVARIANT inside a
  cycle: every surface that renders one must render the SAME one, full stop. `day_n`,
  `week_label` and `current_weight_lbs` are DATED: a chronicle installment published
  last Tuesday legitimately says "Week 2" while today's cockpit says Week 3. So dated
  facts are compared only WITHIN an as-of date — each observation carries the as-of the
  surface itself stamps. Comparing them across dates would manufacture reds out of
  perfectly honest archive pages, and that false alarm is how a gate gets muted.

THE ABSENCE HALF (box 3)
  `ABSENCE_SURFACES` are the surfaces that narrate a PAUSED or LAGGING source. The rule
  is the one `source_registry.availability_facet()` already states and that #3516 wired
  into the coach inventory only: a source that cannot report needs its DURATION and its
  CAUSE, and the cause must come from the registry's own facets. Live evidence that the
  rule was unguarded, 2026-09-21: `/api/source_freshness` rendered garmin `status:
  paused` with `last_update: null` and no duration at all, while `/api/status` rendered
  the same source as "Pipeline may need attention — was flowing regularly but stopped
  97d ago. Check auth/webhook." One source, two surfaces, two different stories, one of
  them a sync-failure fiction about a source paused by ADR-074.

  `RATE_CONSUMERS` carries the other half of ADR-105's bar: a surface that shows a RATE
  must also show its n and whether it is provisional.

THE TWO RATCHETS
  `WEEK_SURFACES` may only grow. `UNREGISTERED_PRODUCERS` — modules that restate a week
  fact but have no nightly-fetchable artifact — may only SHRINK, and every entry states
  why. `tests/test_week_agreement_3615.py` holds both, and sweeps the source tree for
  producers emitting the fact keys so a new narrating surface cannot be born silent.

Pure data + pure accessors: no AWS, no network, no clock. The walk lives in
`week_agreement_qa.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── the fact vocabulary ──────────────────────────────────────────────────────
FACT_CYCLE_GENESIS = "cycle_genesis"
FACT_DAY_N = "day_n"
FACT_WEEK_LABEL = "week_label"
FACT_BASELINE_WEIGHT = "baseline_weight_lbs"
FACT_CURRENT_WEIGHT = "current_weight_lbs"
FACT_GOAL_WEIGHT = "goal_weight_lbs"


@dataclass(frozen=True)
class Fact:
    id: str
    label: str
    dated: bool  # True = compared only within one as-of date
    tolerance: float  # absolute; 0 = exact string/int match
    unit: str


FACTS = {
    FACT_CYCLE_GENESIS: Fact(FACT_CYCLE_GENESIS, "cycle genesis date", dated=False, tolerance=0.0, unit="date"),
    FACT_BASELINE_WEIGHT: Fact(FACT_BASELINE_WEIGHT, "baseline (start) weight", dated=False, tolerance=0.55, unit="lbs"),
    FACT_GOAL_WEIGHT: Fact(FACT_GOAL_WEIGHT, "named plan figure: goal weight", dated=False, tolerance=0.55, unit="lbs"),
    FACT_DAY_N: Fact(FACT_DAY_N, "cycle day number", dated=True, tolerance=0.0, unit="day"),
    FACT_WEEK_LABEL: Fact(FACT_WEEK_LABEL, "week label", dated=True, tolerance=0.0, unit="label"),
    # 0.55 lb: the widest legitimate divergence between two surfaces rendering the same
    # weigh-in, because /api/snapshot rounds to a whole pound for the vitals glyph
    # (317 vs 316.9) while /api/journey serves one decimal. Anything past half a pound
    # is two different readings, not two roundings of one.
    FACT_CURRENT_WEIGHT: Fact(FACT_CURRENT_WEIGHT, "current weight", dated=True, tolerance=0.55, unit="lbs"),
}

#: The output-dict key literals that MAKE a module a week-narrating producer. The
#: derivation sweep in tests/test_week_agreement_3615.py greps for exactly these, so the
#: registry and the guard can never disagree about what counts as narrating a week.
FACT_KEY_LITERALS = (
    "day_n",
    "day_number",
    "week_n",
    "week_label",
    "start_weight_lbs",
    "current_weight_lbs",
    "goal_weight_lbs",
)

#: Directories swept for those literals (first-party producers only).
PRODUCER_DIRS = ("lambdas/web", "lambdas/emails", "lambdas/compute", "lambdas/content", "lambdas/coach")


@dataclass(frozen=True)
class FactRef:
    """Where ONE surface renders one fact, in its own served payload."""

    path: str  # dotted path into the fetched payload (after `select`)
    as_of_path: Optional[str] = None  # the surface's own stamp for a dated fact
    transform: Optional[str] = None  # named transform in week_agreement_qa._TRANSFORMS


@dataclass(frozen=True)
class Surface:
    id: str
    label: str
    producer: str  # the repo path that OWNS this payload
    kind: str  # "http_json"
    locator: str  # url path, or "derive:<name>"
    facts: tuple  # ((fact_id, FactRef), ...)
    select: Optional[str] = None  # named reducer applied before fact paths resolve
    default_as_of_path: Optional[str] = "_meta.generated_at"  # PT date of the payload itself


WEEK_SURFACES: tuple = (
    Surface(
        id="api_journey",
        label="/api/journey — the home hero + story door's week account",
        producer="lambdas/web/site_api_journey.py",
        kind="http_json",
        locator="/api/journey",
        facts=(
            (FACT_CYCLE_GENESIS, FactRef("journey.started_date")),
            (FACT_BASELINE_WEIGHT, FactRef("journey.start_weight_lbs")),
            (FACT_GOAL_WEIGHT, FactRef("journey.goal_weight_lbs")),
            (FACT_DAY_N, FactRef("journey.day_n")),
            (FACT_WEEK_LABEL, FactRef("journey.week_n", transform="week_label_from_n")),
            (FACT_CURRENT_WEIGHT, FactRef("journey.current_weight_lbs", as_of_path="journey.last_weighin_date")),
        ),
    ),
    Surface(
        id="api_timeline",
        label="/api/timeline — the milestone timeline",
        producer="lambdas/web/site_api_journey.py::timeline",
        kind="http_json",
        locator="/api/timeline",
        facts=(
            (FACT_CYCLE_GENESIS, FactRef("timeline.journey_start")),
            (FACT_BASELINE_WEIGHT, FactRef("timeline.start_weight")),
            (FACT_GOAL_WEIGHT, FactRef("timeline.goal_weight")),
            (FACT_CURRENT_WEIGHT, FactRef("timeline.weights", transform="last_weight_point")),
        ),
    ),
    Surface(
        id="api_pulse",
        label="/api/pulse — the cockpit's daily pulse",
        producer="lambdas/web/site_api_pulse.py",
        kind="http_json",
        locator="/api/pulse",
        facts=((FACT_DAY_N, FactRef("pulse.day_number", as_of_path="pulse.date")),),
    ),
    Surface(
        id="api_fingerprint",
        label="/api/fingerprint — the daily fingerprint glyph",
        producer="lambdas/web/site_api_fingerprint.py",
        kind="http_json",
        locator="/api/fingerprint",
        facts=((FACT_DAY_N, FactRef("fingerprint.day_number", as_of_path="fingerprint.date")),),
    ),
    Surface(
        id="api_snapshot",
        label="/api/snapshot — the vitals glyph row",
        producer="lambdas/web/site_api_body.py::snapshot",
        kind="http_json",
        locator="/api/snapshot",
        facts=((FACT_CURRENT_WEIGHT, FactRef("vitals.vitals.weight_lbs", as_of_path="vitals.vitals.weight_as_of")),),
        default_as_of_path="vitals._meta.generated_at",
    ),
    Surface(
        id="api_recap",
        label="/api/recap — the 'previously on' cold open",
        producer="lambdas/emails/chronicle_recap.py (served via site_api handle_recap)",
        kind="http_json",
        locator="/api/recap",
        facts=((FACT_WEEK_LABEL, FactRef("recap.as_of_week", as_of_path="recap.as_of", transform="week_label_from_n")),),
    ),
    Surface(
        id="journal_manifest",
        label="/journal/posts.json — the newest chronicle installment as the manifest states it",
        producer="lambdas/emails/chronicle_store.py → generated/journal/posts.json",
        kind="http_json",
        locator="/journal/posts.json",
        select="newest_post",
        facts=(
            (FACT_WEEK_LABEL, FactRef("label", as_of_path="date")),
            (FACT_CURRENT_WEIGHT, FactRef("stats_line", as_of_path="date", transform="stats_line_weight")),
        ),
        default_as_of_path=None,
    ),
    Surface(
        id="share_kit",
        label="the newest installment's share kit (the copy that goes off-platform)",
        producer="lambdas/content/chronicle_share_kit.py",
        kind="http_json",
        locator="derive:newest_post_share_kit_url",
        facts=(
            (FACT_WEEK_LABEL, FactRef("label", as_of_path="date")),
            (FACT_CURRENT_WEIGHT, FactRef("stats_line", as_of_path="date", transform="stats_line_weight")),
        ),
        default_as_of_path=None,
    ),
    Surface(
        id="api_source_freshness",
        label="/api/source_freshness — the public pipeline board's experiment anchor",
        producer="lambdas/web/site_api_freshness.py",
        kind="http_json",
        locator="/api/source_freshness",
        facts=((FACT_CYCLE_GENESIS, FactRef("experiment.genesis")),),
    ),
)

#: Modules that restate a week fact but have NO nightly-fetchable served artifact, each
#: with the reason. SHRINK-ONLY: every entry is a surface the agreement gate cannot see,
#: so the honest move is to give it an artifact and register it, never to add a name here.
#: The ratchet is in tests/test_week_agreement_3615.py.
UNREGISTERED_PRODUCERS = {
    "lambdas/emails/daily_brief_lambda.py": "narrates the week in EMAIL — no served artifact to fetch nightly; the brief's figures come from the same producers the registered surfaces serve (#3615 residual)",
    "lambdas/emails/monthly_digest_lambda.py": "monthly EMAIL; renders the plan's goal figure only, and no served copy exists",
    "lambdas/emails/nutrition_review_lambda.py": "EMAIL; renders the goal figure inside nutrition copy, no served copy",
    "lambdas/emails/weekly_plate_lambda.py": "EMAIL; renders the goal figure inside the weekly plate, no served copy",
    "lambdas/web/recap_card_lambda.py": "renders day_n into a PNG share card — the fact is pixels, not a payload a nightly gate can parse (#3941)",
    "lambdas/web/site_api_diary.py": "day_number is the diary entry's OWN archival day stamp (#2957 archival_frame), not a claim about the current week",
    "lambdas/web/site_api_nutrition.py": "current_weight_lbs is an INPUT to a macro calculation here, not a rendered week claim",
    "lambdas/web/site_api_thirdwall.py": "week_label is the archival frame on a dated lab note (#2957), not the live week",
    "lambdas/compute/character_sheet_lambda.py": "week_label is stamped onto a stored character record; the served surface that renders it is registered separately",
    "lambdas/content/site_writer.py": "writes stored site JSON consumed by the registered /api surfaces — grading it and them would double-count one producer",
    "lambdas/coach/coach_narrative_orchestrator.py": "day_n is prompt CONTEXT handed to a coach, not a rendered claim",
    "lambdas/coach/progress_capture.py": "week_n keys a stored progress record; no served rendering of its own",
}


# ── the absence half (box 3) ─────────────────────────────────────────────────
@dataclass(frozen=True)
class AbsenceSurface:
    """A surface that narrates a paused/lagging source's silence."""

    id: str
    label: str
    producer: str
    locator: str
    extractor: str  # named extractor in week_agreement_qa._ABSENCE_EXTRACTORS


ABSENCE_SURFACES: tuple = (
    AbsenceSurface(
        id="api_source_freshness",
        label="/api/source_freshness — the public pipeline board",
        producer="lambdas/web/site_api_freshness.py",
        locator="/api/source_freshness",
        extractor="freshness_rows",
    ),
    AbsenceSurface(
        id="api_status",
        label="/api/status — the platform-health panel's data-source components",
        producer="lambdas/web/site_api_status.py",
        locator="/api/status",
        extractor="status_components",
    ),
)

#: Language that attributes a silence to a BROKEN PIPE. Forbidden on a source the
#: registry itself says cannot report (paused) or is expected to lag: those are the two
#: live fictions #3516 found, in the platform's own words.
SYNC_FAILURE_PHRASES = (
    "check auth",
    "webhook",
    "may need attention",
    "needs attention",
    "isn't syncing",
    "is not syncing",
    "sync failure",
    "failed to sync",
    "pipeline error",
)

#: A duration must be RENDERED, not implied. These are the shapes a surface may use.
DURATION_FIELDS = ("days_dark", "days_paused", "age_hours", "stale_hours", "last_update", "last_sync_relative")


# ── the rate half (box 3, second clause) ─────────────────────────────────────
@dataclass(frozen=True)
class RateConsumer:
    id: str
    label: str
    producer: str
    locator: str
    rate_path: str
    n_path: str
    provisional_path: str


RATE_CONSUMERS: tuple = (
    RateConsumer(
        id="api_journey_weekly_rate",
        label="/api/journey weekly_rate_lbs — the headline rate the projection is built on",
        producer="lambdas/web/site_api_journey.py",
        locator="/api/journey",
        rate_path="journey.weekly_rate_lbs",
        n_path="journey.weighin_count",
        provisional_path="journey.rate_provisional",
    ),
)


# ── accessors ────────────────────────────────────────────────────────────────
# Same minimalism as hook_registry: the walk reads WEEK_SURFACES / ABSENCE_SURFACES /
# RATE_CONSUMERS directly, and the derivation guard's producer-claim resolution lives in
# tests/test_week_agreement_3615.py — its only caller.
def surfaces() -> tuple:
    return WEEK_SURFACES
