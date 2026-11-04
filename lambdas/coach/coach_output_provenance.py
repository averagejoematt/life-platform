"""coach_output_provenance.py — the source families of a coach v2 read, derived from its context (owner ruling 2026-11-03).

``common.narrative_provenance`` decides publication from what a text was MADE FROM. This module is where the coach
v2 pipeline (the scheduled daily brief's seven coach reads) works that out, from the context it actually assembled —
never from a hand-written per-coach list:

  * ``brief_provenance`` — the narrative orchestrator's generation brief. Every component ``_gather_all_state``
    returns has an entry in ``STATE_PARTS``; a component that is a stored narrative row (another coach's compressed
    state, the ensemble digest, the coach's own threads, calls, commitments, stance, voice state) contributes ITS
    provenance (``NP.merge_upstream``: ``unrecorded`` until that row carries one). The parts the orchestrator renders
    only for some coaches (the journal mood signal, the presence signal, the active protocols) are passed as rendered.
  * ``pipeline_provenance`` — the generation prompt (``ai_calls._run_coach_v2_pipeline``). ``PROMPT_INPUTS`` names
    every value the system prompt and user message interpolate; ``tests/test_coach_output_provenance.py`` parses the
    pipeline and fails when a name is interpolated that this registry does not classify, or when a runtime block is
    not handed to ``pipeline_provenance``. The domain data's families are the ``data`` keys its builder READS
    (``_KeyRecorder``), so a builder that starts reading a new key changes the stamp by itself.
  * ``updater_record`` — the record ``coach_state_updater`` writes on every row it derives from the read (OUTPUT#,
    THREAD#, PREDICTION#, COMMITMENT#, VOICE#, TRACE#): the producer's record merged with the extractor's own input
    (the voice spec). A caller that sent no record (``inter_coach_dialogue_lambda``, an older pipeline, a reuse of a
    cached read stored before the stamp) gets ``unrecorded`` — withheld, fail closed.

Nothing here removes an input from a prompt: a private family on the stamp withholds the text publicly and the row
stays stored for the owner's own tools ("private data should remain available to authorized coaching and analysis
systems without becoming eligible for public publication"). Which inputs make each coach private is printed by
``scripts/coach_provenance_dry_run.py`` — the content decision is the owner's.

An unknown name is never public: a ``data`` key, a domain field, a computation source or a recall kind this module
does not map is stamped under its own name, which ``narrative_provenance`` does not classify, so the row is withheld.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable, Optional

from common import narrative_provenance as NP

PRODUCER_ORCHESTRATOR = "coach.coach_narrative_orchestrator"
PRODUCER_PIPELINE = "ai.coach_v2_pipeline"
PRODUCER_UPDATER = "coach.coach_state_updater"
PRODUCER_DIGEST = "coach.coach_ensemble_digest"

PERSONA = "persona"  # the voice spec, the prompt templates, the reader rules: code and config, not data

# ── presence: a statement that a source has / has not been logged is that source's PRESENCE family ───────────────
# (the journal's presence is private — `journal_presence` — whatever is said about it)
PRESENCE_FAMILIES = {"notion": "journal_presence", "macrofactor": "food_log_presence", "hevy": "training_log_presence"}


def presence_family(source_id: Any) -> str:
    return PRESENCE_FAMILIES.get(str(source_id), str(source_id))


# ── the daily-brief `data` dict (daily_brief_lambda.gather_daily_data): key -> the families its value is read from ──
DATA_KEY_FAMILIES: dict[str, tuple] = {
    "date": (),  # the brief's data day — a date, no source content
    "whoop": ("whoop",),
    "whoop_today": ("whoop",),
    "whoop_7d": ("whoop",),
    "primary_whoop": ("whoop",),
    "sleep": ("whoop",),  # _normalize_whoop_sleep(whoop): Whoop is the sleep source of truth
    "hrv": ("whoop",),
    "rhr": ("whoop",),
    "sleep_debt_7d_hrs": ("whoop",),
    "eightsleep": ("eightsleep",),
    "apple": ("apple_health",),
    "apple_health": ("apple_health",),
    "apple_7d": ("apple_health",),
    "cgm": ("apple_health",),
    "macrofactor": ("macrofactor",),
    "nutrition": ("macrofactor",),
    "macrofactor_window": ("macrofactor",),
    "strava": ("strava",),
    "strava_7d": ("strava",),
    "strava_60d": ("strava",),
    "tsb": ("strava",),
    "garmin": ("garmin",),
    "habitify": ("habitify",),
    "habitify_7d": ("habitify",),
    "mf_workouts": ("hevy",),
    "hevy": ("hevy",),
    "withings": ("withings",),
    "latest_weight": ("withings",),
    "weight_recency": ("withings",),
    "week_ago_weight": ("withings",),
    "avatar_weight": ("withings",),
    "dexa": ("dexa",),
    "measurements": ("measurements",),
    "labs": ("labs",),
    "supplements_today": ("supplements",),
    "supplements_7d": ("supplements",),
    "weather_yesterday": ("weather",),
    "weather_today": ("weather",),
    "journal": ("journal",),
    "journal_entries": ("journal",),
    "state_of_mind": ("state_of_mind",),
    "som": ("state_of_mind",),
    "computed_metrics": ("computed_metrics",),
    "computed_insights": ("computed_insights",),  # AI-written guidance (a NARRATIVE source) — unclassified, withheld
    "social_posts": ("social_posts",),  # enriched public posts — no classification in narrative_provenance: withheld
    "experiments": ("experiments",),
    "hevy_recent": ("hevy",),  # brief_domain_inputs.gather — the physical block's Hevy window
    "active_experiments": ("experiments",),
    "experiment_names": ("experiments",),
    # weekly_correlation_compute pairs State of Mind valence and a values-lived count coded from journal text.
    "weekly_correlations": ("computed_metrics", "state_of_mind", "journal"),
}


def data_key_families(key: Any) -> tuple:
    """Families of one ``data`` key; an unmapped key is its own (unclassified) family."""
    return DATA_KEY_FAMILIES.get(str(key), (f"data:{key}",))


class _KeyRecorder(dict):
    """A dict that records which top-level keys are read. Iterating it records EVERY key (stricter, never looser)."""

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.read: set = set()

    def get(self, key: Any, default: Any = None) -> Any:
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key: Any) -> Any:
        self.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key: Any) -> bool:
        self.read.add(key)
        return super().__contains__(key)

    def __iter__(self):
        self.read.update(super().keys())
        return super().__iter__()

    def keys(self):
        self.read.update(super().keys())
        return super().keys()

    def items(self):
        self.read.update(super().keys())
        return super().items()

    def values(self):
        self.read.update(super().keys())
        return super().values()


def keys_read(builder: Callable[[dict], Any], data: Optional[dict]) -> set:
    """The ``data`` keys ``builder`` reads. A builder that raises reads 'everything' (fail toward the stricter set)."""
    rec = _KeyRecorder(data or {})
    try:
        builder(rec)
    except Exception:  # noqa: BLE001 — unknown is the full set
        rec.read.update((data or {}).keys())
    return rec.read


# The coach-input boundary (`coach_input_facts.coach_inputs`) adds these fields to every coach's domain data.
COACH_INPUT_FIELD_FAMILIES: dict[str, tuple] = {
    "logging_record": ("macrofactor", "food_log_presence"),  # the served nutrition logging record
    "charter_context": ("experiments", "macrofactor"),  # the nutrition charter, its rules and the calorie target
    "wake_time_rule": ("experiments",),  # the charter's wake-time rule
    "morning_note": ("morning_note",),
    "clinical_context": ("clinical_public_rules",),  # `published=True`: the guardrails only (ADR-155 amendment)
}


def domain_families(builder: Optional[Callable[[dict], Any]], data: Optional[dict], domain_data: Any) -> list:
    """Families of the domain-data block: what its builder read from ``data``, plus the coach-input fields present."""
    fams: set = set()
    if builder is None:
        fams.add(NP.UNRECORDED)  # the builder is not known: its inputs are not either
    else:
        for key in keys_read(builder, data):
            fams.update(data_key_families(key))
    if isinstance(domain_data, dict):
        for field in domain_data:
            fams.update(COACH_INPUT_FIELD_FAMILIES.get(field, ()))
    return sorted(fams)


# ── the computation engine's results (COACH#computation RESULTS#): source -> families, metric overrides ──────────
COMPUTATION_SOURCE_FAMILIES: dict[str, tuple] = {
    "whoop": ("whoop",),
    "withings": ("withings",),
    "macrofactor": ("macrofactor",),
    "apple_health": ("apple_health",),
    "strava": ("strava",),
    "eightsleep": ("eightsleep",),
}


def _steps_families() -> tuple:
    """The resolved-steps pseudo-source carries every source the steps truth facet names (common.metric_truth)."""
    from common.metric_truth import resolved_source_id, steps_sources

    COMPUTATION_SOURCE_FAMILIES[resolved_source_id("steps")] = tuple(steps_sources())
    return tuple(steps_sources())


_steps_families()
# A metric whose value is a different family from the row it rides on.
COMPUTATION_METRIC_FAMILIES: dict[str, tuple] = {
    "som_avg_valence": ("state_of_mind",),  # Apple Health's State of Mind valence — owner-only (SOURCE_TIERS)
}


def _names(word: str, text: str) -> bool:
    # A bare-word match, so a package stored as a JSON STRING (escaped quotes) is read the same as a dict.
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", text) is not None


def computation_families(text: str) -> list:
    """Families of a rendered computation-results text: every engine source and override metric it names."""
    fams: set = set()
    for source, families in COMPUTATION_SOURCE_FAMILIES.items():
        if _names(source, text):
            fams.update(families)
    for metric, families in COMPUTATION_METRIC_FAMILIES.items():
        if _names(metric, text):
            fams.update(families)
    return sorted(fams)


def _all_computation_families() -> list:
    out: set = set()
    for fams in list(COMPUTATION_SOURCE_FAMILIES.values()) + list(COMPUTATION_METRIC_FAMILIES.values()):
        out.update(fams)
    return sorted(out)


# ── the engagement (presence) signal: one family per manual channel the registry names ────────────────────────────
def engagement_families() -> list:
    try:
        from ingestion.source_registry import engagement_channels

        channels = list(engagement_channels())
    except Exception:  # noqa: BLE001 — the channel set unknown: so is the signal's provenance
        return [NP.UNRECORDED]
    return sorted({presence_family(c) for c in channels} | {"whoop"})  # + the passive read (wearables still flowing)


# ── the orchestrator's state components ─────────────────────────────────────────────────────────────────────────
def _is_row(value: Any) -> bool:
    return isinstance(value, dict) and "pk" in value


def _row_or(default_families: Iterable[str]) -> Callable[[Any], tuple]:
    """A stored narrative row contributes its own provenance; the built-in default (no ``pk``) is code."""

    def resolve(value: Any) -> tuple:
        if _is_row(value):
            return [], [value]
        return (list(default_families) if value else []), []

    return resolve


def _rows(value: Any) -> tuple:
    rows = list(value.values()) if isinstance(value, dict) else list(value or [])
    return [], [r for r in rows if isinstance(r, dict)]


def _graded(value: Any) -> tuple:
    # Counts are graded results; a resolved call's condition/reason line and the corrected-call lines are row TEXT
    # whose provenance the read does not carry.
    fams = ["prediction_ledger"]
    if isinstance(value, dict) and (value.get("cited") or value.get("notes")):
        fams.append(NP.UNRECORDED)
    return fams, []


def _protocols(value: Any) -> tuple:
    fams = []
    if isinstance(value, dict):
        if value.get("challenges"):
            fams.append(NP.UNRECORDED)  # challenge names are written by the challenge generator (a narrative source)
        if value.get("experiments"):
            fams.append("experiments")
    return fams, []


def _arc(value: Any) -> tuple:
    # NARRATIVE#arc is the computation engine's arc detection over every trend it computes.
    return (_all_computation_families() if _is_row(value) else (["experiments"] if value else [])), []


STATE_PARTS: dict[str, Callable[[Any], tuple]] = {
    "graded_record": _graded,
    "target_compressed": _row_or([PERSONA]),
    "other_compressed": _rows,
    "ensemble_digest": _row_or([PERSONA]),
    "influence_graph": lambda v: ([PERSONA] if v else [], []),  # coach config (ENSEMBLE#influence_graph / S3)
    "computation_results": lambda v: (computation_families(json.dumps(v, sort_keys=True, default=str)) if v else [], []),
    "narrative_arc": _arc,
    "voice_state": _row_or([PERSONA]),
    "open_threads": _rows,
    "active_predictions": _rows,
    "evaluated_prediction_count": lambda v: (["prediction_ledger"], []),
    "due_commitments": _rows,
    "resolved_commitments": _rows,
    "commitment_record": lambda v: (["prediction_ledger"], []),
    "current_stance": lambda v: ([], [v]) if v else ([], []),
    # Rendered only for some coaches / days — the caller passes the RENDERED value (None when not rendered).
    "site_protocols": _protocols,
    "engagement_signal": lambda v: (engagement_families() if v else [], []),
    "journal_mood": lambda v: (["journal", "mood_read"] if v else [], []),
}


def brief_provenance(state: dict, *, rendered: Optional[dict] = None, fallback: Any = None) -> dict:
    """The orchestrator's record for one coach's brief. ``rendered`` overrides a component with what was actually
    put in the prompt; ``fallback`` is the stored brief served in place of the model's (its own record is merged).
    A state component this registry does not know makes the brief ``unrecorded``."""
    rendered = rendered or {}
    fams: set = {PERSONA}
    upstream: list = []
    for key, value in (state or {}).items():
        resolver = STATE_PARTS.get(key)
        if resolver is None:
            fams.add(NP.UNRECORDED)
            continue
        f, up = resolver(rendered[key] if key in rendered else value)
        fams.update(f)
        upstream.extend(up)
    if fallback is not None:
        upstream.append(fallback)
    return NP.stamp(fams, producer=PRODUCER_ORCHESTRATOR, upstream=upstream)


# ── the generation prompt ────────────────────────────────────────────────────────────────────────────────────────
def _brief(envelope: Any) -> list:
    return NP.merge_upstream(envelope)


def _nonempty(*families: str) -> Callable[[Any], list]:
    return lambda text: list(families) if text else []


def _facts(text: Any) -> list:
    if not text:
        return []
    fams = ["computed_metrics"]
    if "MODEL EXPECTATIONS" in str(text):
        fams += forecast_families()
    return fams


def forecast_families() -> list:
    """The sources the forecast engine forecasts from (its METRICS registry); unknown -> unrecorded."""
    try:
        from compute.forecast_engine_lambda import METRICS

        return sorted({str(m["source"]) for m in METRICS})
    except Exception:  # noqa: BLE001
        return [NP.UNRECORDED]


RECALL_KIND_FAMILIES: dict[str, str] = {
    "journal": "journal",
    "coach_output": NP.UNRECORDED,  # the corpus row is a snippet of a stored coach read, its record not carried
    "chronicle": "chronicle",  # owner-approved installments — no classification in narrative_provenance: withheld
}


def _recall(value: Any) -> list:
    block, precedents = value if isinstance(value, tuple) else (value, None)
    if not block:
        return []
    kinds = [str((p or {}).get("kind") or "") for p in precedents or []]
    if not kinds:
        return [NP.UNRECORDED]
    return sorted({RECALL_KIND_FAMILIES.get(k, f"recall:{k}") for k in kinds})


def _inventory(text: Any) -> list:
    """The DATA SOURCES AVAILABLE block states, for every row, whether that source has data: its presence family."""
    if not text:
        return []
    from coach.coach_brief_input_gate import INVENTORY_ROWS

    return sorted({presence_family(source_id or keys[0]) for name, keys, source_id in INVENTORY_ROWS if name in str(text)})


def _computation(value: Any) -> list:
    trends = (value or {}).get("trends", {}) if isinstance(value, dict) else {}
    return computation_families(json.dumps(trends, indent=2, default=str)[:2000])  # the slice the prompt carries


# Every name the v2 prompt (system_prompt + user_message + the corrections block) interpolates -> its families.
# A tuple is static (code/config); a string names the ``pipeline_provenance`` keyword that carries the runtime value.
PROMPT_INPUTS: dict[str, Any] = {
    "voice_spec": (PERSONA,),
    "voice_rules": (PERSONA,),
    "decision_style": (PERSONA,),
    "_forbidden": (PERSONA,),
    "few_shot_block": (PERSONA,),
    "_reader_rules": (PERSONA,),
    "domain_label": (PERSONA,),
    "EXPERIMENT_BASELINE_WEIGHT_LBS": ("experiments",),
    "EXPERIMENT_START_DATE": ("experiments",),
    "charter_goal_lines": ("experiments",),
    "_disruption_language_line": ("sick_days",),  # the published-safe whole-day disruption line
    "brief": "brief",
    "voice_guidance": "brief",  # a field of the brief
    "_facts_block": "facts_block",
    "_journal_mood_block": "journal_mood_block",
    "_cycle_boundary_block": "cycle_boundary_block",
    "_memory_block": "memory_block",
    "_recall_block": "recall",
    "_data_inventory": "data_inventory",
    "domain_data": "domain_data",
    "comp_results": "comp_results",
    "corrections_block": "corrections_block",
}

RUNTIME_RESOLVERS: dict[str, Callable[[Any], list]] = {
    "brief": _brief,
    "facts_block": _facts,
    "journal_mood_block": _nonempty("journal", "mood_read"),
    "cycle_boundary_block": _nonempty("experiments"),
    "memory_block": _nonempty("platform_memory"),
    "recall": _recall,
    "data_inventory": _inventory,
    "comp_results": _computation,
    "corrections_block": _nonempty("coach_corrections"),  # owner corrections ledger — unclassified: withheld
}


def _builder_for(coach_id: str) -> Optional[Callable[[dict], Any]]:
    try:
        from ai import ai_context
    except Exception:  # noqa: BLE001
        return None
    return getattr(ai_context, BUILDERS.get(coach_id, ""), None)


# coach -> its domain-data builder (``ai_calls.call_<coach>_v2``); pinned against the pipeline by the contract test.
BUILDERS: dict[str, str] = {
    "sleep_coach": "_build_sleep_data",
    "nutrition_coach": "_build_nutrition_data",
    "mind_coach": "_build_mind_data",
    "physical_coach": "_build_physical_data",
    "glucose_coach": "_build_glucose_data",
    "labs_coach": "_build_labs_data",
    "explorer_coach": "_build_explorer_data",
}


# A runtime input is read from the pipeline's own variable of the interpolated name — except the brief, whose record
# rides the orchestrator's ENVELOPE (`generation_brief`), not the inner brief the prompt dumps.
_VARIABLE_OF = {"brief": "generation_brief"}


def prompt_blocks(variables: dict) -> dict:
    """The ``pipeline_provenance`` keywords, read from the generation's own variables (``locals()`` at the call):
    the stamp reads the very values the prompt interpolated. A variable that is absent is not supplied — and an
    input not supplied is ``unrecorded``."""
    out: dict = {}
    for name, spec in PROMPT_INPUTS.items():
        if not isinstance(spec, str) or spec in out:
            continue
        var = _VARIABLE_OF.get(spec, name)
        if var in variables:
            out[spec] = (variables[var], variables.get("_recall_precedents")) if spec == "recall" else variables[var]
    return out


def pipeline_families(coach_id: str, data: Optional[dict], **blocks: Any) -> dict:
    """``{family: [the prompt inputs that carry it]}`` for one coach v2 generation — the dry run prints this."""
    out: dict = {}

    def add(fams: Iterable[str], name: str) -> None:
        for f in fams:
            out.setdefault(f, set()).add(name)

    for name, spec in PROMPT_INPUTS.items():
        if isinstance(spec, tuple):
            add(spec, name)
    for kw in sorted(set(v for v in PROMPT_INPUTS.values() if isinstance(v, str))):
        if kw not in blocks:
            add([NP.UNRECORDED], f"{kw} (not supplied)")
        elif kw == "domain_data":
            add(domain_families(_builder_for(coach_id), data, blocks[kw]), kw)
        else:
            add(RUNTIME_RESOLVERS[kw](blocks[kw]), kw)
    for kw in sorted(set(blocks) - set(RUNTIME_RESOLVERS) - {"domain_data"}):
        add([NP.UNRECORDED], f"{kw} (unregistered)")
    return {f: sorted(names) for f, names in sorted(out.items())}


def pipeline_provenance(coach_id: str, data: Optional[dict], **blocks: Any) -> dict:
    """The provenance record of one coach v2 read, from the blocks its prompt was built from."""
    return NP.stamp(pipeline_families(coach_id, data, **blocks), producer=PRODUCER_PIPELINE)


# ── transport and the state updater ──────────────────────────────────────────────────────────────────────────────
def portable(record: Any) -> Optional[dict]:
    """A JSON-safe copy of a provenance record (a DynamoDB read carries ``Decimal``), or None."""
    rec = NP.record_of(record)
    if rec is None:
        return None
    try:
        out = {"v": int(rec.get("v")), "families": [str(f) for f in rec.get("families") or []]}
    except (TypeError, ValueError):
        return {"v": -1, "families": []}  # malformed stays malformed — eligibility withholds it
    for k in ("producer", "stamped_at"):
        if rec.get(k) is not None:
            out[k] = str(rec[k])
    return out


# The rows coach_state_updater derives from the read's TEXT (its extraction). RELATIONSHIP#state is rule-based over
# graded signals, not the text, and is left as it was.
UPDATER_DERIVED_SK_PREFIXES = ("OUTPUT#", "THREAD#", "PREDICTION#", "COMMITMENT#", "TRACE#", "VOICE#")


def updater_record(event_provenance: Any) -> dict:
    """What coach_state_updater stamps on every row it derives from one read: the producer's record (``unrecorded``
    when none was sent) merged with the extractor's own input, the voice spec."""
    return NP.stamp([PERSONA], producer=PRODUCER_UPDATER, upstream=[event_provenance])


def merged(row_record: Any, run_record: dict) -> dict:
    """A row rewritten from its prior state (VOICE#, RELATIONSHIP#) keeps the prior state's families as well."""
    if NP.record_of(row_record) is None:
        return run_record
    return NP.stamp([], producer=str(run_record.get("producer") or PRODUCER_UPDATER), upstream=[run_record, row_record])


def digest_record(coach_data: Any) -> dict:
    """The ensemble digest's record: it synthesizes each coach's latest OUTPUT# and COMPRESSED#latest, so it carries
    every one of their records (``unrecorded`` for each that has none). ``None`` (not gathered) -> unrecorded."""
    if coach_data is None:
        return NP.stamp([NP.UNRECORDED], producer=PRODUCER_DIGEST)
    rows = [r for d in (coach_data or {}).values() if isinstance(d, dict) for r in (d.get("output"), d.get("compressed")) if r]
    return NP.stamp([PERSONA], producer=PRODUCER_DIGEST, upstream=rows)


def without_records(value: Any) -> Any:
    """``value`` with every provenance record removed (a copy) — family names are bookkeeping, never prompt text."""
    if isinstance(value, dict):
        return {k: without_records(v) for k, v in value.items() if k != NP.PROVENANCE_KEY}
    if isinstance(value, list):
        return [without_records(v) for v in value]
    return value
