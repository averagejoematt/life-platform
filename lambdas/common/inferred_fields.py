"""inferred_fields.py — the model-inferred psychological fields, and the ONE way a consumer reads them (#6286).

WHY THIS EXISTS
---------------
The journal enrichment pass (``ingestion/journal_enrichment_lambda.py``) and the conversation
enrichment pass (``ai/conversation_enrichment.py``) ask a language model to read Matthew's prose
and write labels onto the row: defense mechanisms, avoidance flags and CBT-style cognitive
distortions, plus 1-5 mood / energy / stress scores. Nobody reviews or corrects those labels.
Until #6286 they were then used as if established:

  * the daily brief's journal coach was told "DEFENSE PATTERNS DETECTED: … Challenge one gently."
    and "AVOIDANCE FLAGS: … Name what's being avoided.";
  * the weekly digest printed a red "Avoidance" row and handed both families to its AI section;
  * the challenge generator mined "avoidance flags, defense mechanisms" into challenges;
  * the mind coach's fact block carried the avoidance flags;
  * MCP's mood trend resolved mood as "model score, else his own rating", so a model's reading of
    a journal entry replaced the rating he gave in the same entry.

Owner rulings (2026-11-26) that this module encodes:
  * A coach is never told it has detected a psychological mechanism in him, nor told to challenge it.
  * His explicit self-report outranks a model's inference about the same thing.
  * Rich qualitative analysis and hypothesis generation stay: stored fields are NOT deleted, the
    enrichment keeps running, and no stored row is rewritten. Themes, emotions, behaviours and his
    own causal statements may still inform generation.

THE CONTRACT
------------
``INFERRED_PSYCH_LABEL_FIELDS`` names the label families. Outside this module and the two
producers (``PRODUCER_MODULES``), no module under ``lambdas/`` or ``mcp/`` may name one of those
fields (or the bare key a consumer used to re-key them under) — ``tests/test_inferred_psych_fields_guard_6286.py``
walks the tree and fails on any such read. A consumer that has a legitimate reason to show the
labels to their OWNER (not to a coach as fact) goes through :func:`unreviewed_model_reading`, which
returns them wrapped in an explicit "unreviewed model reading, may be wrong, never assert it" caveat.
No prompt builder calls it today: withholding is the default, per the ruling "when in doubt,
withhold it from the prompt".

``resolve_rating`` is the ONE self-report-first resolution of mood / energy / stress: the rating he
gave wins; the model's score is used only when he gave none, and is then marked ``model_inferred``.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

# ── The model-inferred psychological label families ──────────────────────────────────────────────
# Each value is the list of stored attribute names in the family. ``enriched_defense_context`` is
# retired from the writer (#505) but legacy rows still carry it, so it stays in the set.
INFERRED_PSYCH_LABEL_FAMILIES: dict[str, tuple[str, ...]] = {
    "defense": ("enriched_defense_patterns", "enriched_primary_defense", "enriched_defense_context"),
    "avoidance": ("enriched_avoidance_flags",),
    "cognitive_distortion": ("enriched_cognitive_patterns",),
}

INFERRED_PSYCH_LABEL_FIELDS: frozenset[str] = frozenset(f for fields in INFERRED_PSYCH_LABEL_FAMILIES.values() for f in fields)

# The bare keys the producers' model schemas use, and that consumers used to re-key the stored
# fields under (``journal_signals["defense_patterns"]``, ``ex_journal()["avoidance_flags"]``). The
# guard treats a bare key exactly like the stored name, so the labels cannot re-enter a prompt
# one hop downstream under their short name.
INFERRED_PSYCH_LABEL_KEYS: frozenset[str] = frozenset(f[len("enriched_") :] for f in INFERRED_PSYCH_LABEL_FIELDS)

# The modules that WRITE the fields. They keep running (owner ruling: enrichment stays), so they
# are the only other place the names may appear. Repo-relative paths.
PRODUCER_MODULES: tuple[str, ...] = (
    "lambdas/ingestion/journal_enrichment_lambda.py",
    "lambdas/ai/conversation_enrichment.py",
)

PROVENANCE_UNREVIEWED = "model_inferred_unreviewed"
UNREVIEWED_CAVEAT = (
    "UNREVIEWED MODEL READING. A language model labelled this from his writing; he has not reviewed "
    "or confirmed it and it may be wrong. It is an interpretation, not an observation. Never state it "
    "to him as something detected or true about him, never tell him to challenge or confront it, and "
    "prefer what he wrote in his own words."
)


def unreviewed_model_reading(entries: Any) -> Optional[dict[str, Any]]:
    """The ONE sanctioned accessor for the label families.

    Returns ``None`` when no entry carries a label. Otherwise a dict whose ``provenance`` is
    ``model_inferred_unreviewed``, whose ``caveat`` is :data:`UNREVIEWED_CAVEAT`, and whose
    ``labels`` maps each family to the de-duplicated labels found (order of first appearance).
    Accepts one row (a mapping) or an iterable of rows; non-mapping items are skipped.
    """
    if isinstance(entries, Mapping):
        rows: list[Mapping[str, Any]] = [entries]
    else:
        rows = [e for e in (entries or []) if isinstance(e, Mapping)]
    labels: dict[str, list[str]] = {}
    for family, fields in INFERRED_PSYCH_LABEL_FAMILIES.items():
        found: list[str] = []
        for row in rows:
            for field in fields:
                val = row.get(field)
                vals = val if isinstance(val, (list, tuple)) else [val]
                for v in vals:
                    if v is None or v == "":
                        continue
                    s = str(v)
                    if s not in found:
                        found.append(s)
        if found:
            labels[family] = found
    if not labels:
        return None
    return {"provenance": PROVENANCE_UNREVIEWED, "caveat": UNREVIEWED_CAVEAT, "labels": labels}


RELABEL_KEY = "_model_reading_unreviewed"


def relabel_row(row: Any) -> Any:
    """Move a row's label-family fields under one explicitly-caveated key, in place.

    For row-dumping read paths (MCP's generic data tools) that hand whole rows to a conversation:
    the stored fields are removed from the top level and, when any were present, re-attached as
    ``row["_model_reading_unreviewed"] = unreviewed_model_reading(row)``. Only the returned copy
    changes; nothing is written back. A non-mapping is returned unchanged.
    """
    if not isinstance(row, dict):
        return row
    reading = unreviewed_model_reading(row)
    for field in INFERRED_PSYCH_LABEL_FIELDS:
        row.pop(field, None)
    if reading is not None:
        row[RELABEL_KEY] = reading
    return row


# ── Self-report-first mood / energy / stress ─────────────────────────────────────────────────────
# Every field below is 1-5 (docs/SCHEMA.md, the Notion journal row), so the self-report and the
# model score are on one scale and the substitution never rescales.
SELF_REPORT_FIELDS: dict[str, tuple[str, ...]] = {
    "mood": ("morning_mood", "day_rating"),
    "energy": ("morning_energy", "energy_eod"),
    "stress": ("stress_level",),
}
MODEL_SCORE_FIELDS: dict[str, str] = {
    "mood": "enriched_mood",
    "energy": "enriched_energy",
    "stress": "enriched_stress",
}
SOURCE_SELF_REPORT = "self_report"
SOURCE_MODEL_INFERRED = "model_inferred"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN is an absence


def resolve_rating(entry: Any, metric: str) -> tuple[Optional[float], Optional[str]]:
    """``(value, source)`` for one entry's mood / energy / stress — his own rating first.

    ``source`` is ``"self_report"`` when he rated it, ``"model_inferred"`` when only the enrichment
    model's score exists, and ``None`` (with value ``None``) when neither does.
    """
    if metric not in MODEL_SCORE_FIELDS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {sorted(MODEL_SCORE_FIELDS)}")
    if not isinstance(entry, Mapping):
        return None, None
    for field in SELF_REPORT_FIELDS[metric]:
        v = _num(entry.get(field))
        if v is not None:
            return v, SOURCE_SELF_REPORT
    v = _num(entry.get(MODEL_SCORE_FIELDS[metric]))
    if v is not None:
        return v, SOURCE_MODEL_INFERRED
    return None, None


def resolved_value(entry: Any, metric: str) -> Optional[float]:
    """The value half of :func:`resolve_rating`, for callers that only aggregate a number."""
    return resolve_rating(entry, metric)[0]


def resolved_summary(entries: Any, metrics: tuple[str, ...] = ("mood", "energy", "stress")) -> dict[str, Any]:
    """``<metric>_avg`` (1 dp, or None) per metric over ``entries``, each entry resolved by :func:`resolve_rating`,
    plus ``rating_sources``: per metric, how many entries were his own rating (``self_report``) and how many
    fell back to the model's reading (``model_inferred``). A metric with no value anywhere is omitted there."""
    rows = [e for e in (entries or []) if isinstance(e, Mapping)]
    out: dict[str, Any] = {}
    sources: dict[str, dict[str, int]] = {}
    for metric in metrics:
        pairs = [resolve_rating(e, metric) for e in rows]
        vals = [v for v, _src in pairs if v is not None]
        out[f"{metric}_avg"] = round(sum(vals) / len(vals), 1) if vals else None
        counts = {src: sum(1 for _v, s in pairs if s == src) for src in (SOURCE_SELF_REPORT, SOURCE_MODEL_INFERRED)}
        if vals:
            sources[metric] = {k: n for k, n in counts.items() if n}
    out["rating_sources"] = sources
    return out
