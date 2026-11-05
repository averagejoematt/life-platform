"""character_public.py — the character sheet's PUBLIC method, ``character-public-v1`` (owner ruling 2026-11-05).

THE RULING. "Public Mind, composite, XP, Day grades and overall levels must depend only on public-eligible
inputs. Recompute affected historical public values using the corrected methodology. Preserve the original
method 1 scores privately ... Introduce clearly versioned public methodology and effective dates."

WHAT THE METHOD IS. The same engine (``character_engine.compute_character_sheet``) over public inputs only, with
its OWN state chain — the previous day's public variant, the public raw-score histories — so EMA levels, XP,
streaks, buffers, effects, the mood and the headline level never carry a private input forward:

* **Sleep, Movement, Nutrition, Metabolic** — every component reads a public source, so the public variant takes
  the day's method-1 raw score and component details VERBATIM (``VERBATIM_PILLARS``) and only re-runs the chain.
* **Mind** — scored from its public components only (``MIND_COMPONENT_SOURCES``): a component whose source the
  publication policy does not classify public (``common.activity_publication``; unknown fails closed) is held out of
  the sum AND the coverage — not scored 0, which would let a behavioral absence move the score. The journal's 14-day
  consistency, the journal-enrichment values read, How We Feel / State of Mind and the check-in's stress are out.
  ``t1_habit_compliance`` is held out unless the day's habit score came from the core-12 set: the tier-weighted share
  counted the Morning and Evening Journal habits (both tier 1). The check-in's PRESENCE inside the core set stays in —
  the owner put it in the core twelve.
* **Relationships** — every input is the journal or its enrichment, so the public method has no reading at all: the
  never-instrumented shape every day (no XP, out of the headline mean), and public routes serve it held.
* **Consistency** — its own inputs are public (data completeness, the task queue); its cross-pillar variance, its
  all-pillars streak and its weekend/weekday composite are recomputed from the public pillars and public history.
* **Challenge XP** enters only when ``challenges`` is a public source (it is unclassified today, so it does not).
* **Presence** (mood, neglect atrophy) is the presence record's public projection (``engagement_core``), or for a
  record written before that projection existed, a derivation from its stored fields over public channels only
  (``public_presence`` — it reports whether the derivation is provably exact).

STORAGE. ``compute_public_variant`` returns the block the compute stores under ``character_privacy.PUBLIC_KEY`` beside
the method-1 fields (never over them), stamped with the method version, its effective date, its history and the
record's origin (``live`` | ``recomputed``). Public readers read it through ``character_privacy.public_sheet``; the
owner's surfaces keep reading method 1. ``scripts/backfill_public_variant.py`` replays this for every stored date.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Optional

from common import activity_publication

from health import character_engine, character_privacy

PUBLIC_KEY = character_privacy.PUBLIC_KEY
METHOD_VERSION = character_privacy.PUBLIC_METHOD_VERSION
EFFECTIVE_FROM = character_privacy.PUBLIC_METHOD_EFFECTIVE_FROM

PILLARS = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
# Pillars every component of which reads a public source: method-1 raw + details are taken verbatim.
VERBATIM_PILLARS = ("sleep", "movement", "nutrition", "metabolic")
# Every Mind component and the source it reads. A component not listed here is held out (fail closed).
MIND_COMPONENT_SOURCES = {
    "t0_habit_compliance": "habit_scores",
    "t1_habit_compliance": "habit_scores",
    "vice_control": "habit_scores",
    "reading_practice": "reading",
    "journal_consistency": "notion",
    "state_of_mind_valence": "state_of_mind",
    "stress_management": "evening_checkin",
    "values_alignment": "flourishing",
}
CORE_SET_METHOD = "core_set_v1"  # health.core_habits' habit_scores.scoring_method once the core twelve are armed
CORE_SET_ONLY_COMPONENTS = ("t1_habit_compliance",)  # the tier-1 share counted the two journal habits
CHALLENGES_SOURCE = "challenges"


def mind_component_is_public(name: str) -> bool:
    src = MIND_COMPONENT_SOURCES.get(name)
    return src is not None and activity_publication.source_is_public(src)


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    """The engine config the public method runs under: a deep copy whose Mind component set is its public components.
    Leveling, weights, bands and effects are method 1's."""
    cfg = copy.deepcopy(config or {})
    mind = ((cfg.get("pillars") or {}).get("mind") or {}).get("components")
    if isinstance(mind, dict):
        cfg["pillars"]["mind"]["components"] = {k: v for k, v in mind.items() if mind_component_is_public(k)}
    return cfg


def public_mind(method1_details: Optional[dict[str, Any]], habit_method: Optional[str], cfg_public: dict[str, Any]) -> tuple:
    """Mind's (raw, details) from the day's method-1 component scores, public components only (config order)."""
    comps = ((cfg_public.get("pillars") or {}).get("mind") or {}).get("components") or {}
    scores: dict[str, Any] = {}
    for name in comps:
        if name in CORE_SET_ONLY_COMPONENTS and habit_method != CORE_SET_METHOD:
            continue
        d = (method1_details or {}).get(name)
        if isinstance(d, dict):  # a component method 1 did not compute that day stays out, as it did there
            scores[name] = None if d.get("absent") else d.get("score")
    return character_engine._weighted_pillar_score(scores, comps)


def public_relationships(cfg_public: dict[str, Any]) -> tuple:
    """Relationships' (raw, details) under the public method: no public input exists, so no reading."""
    comps = ((cfg_public.get("pillars") or {}).get("relationships") or {}).get("components") or {}
    return character_engine._weighted_pillar_score({c: None for c in comps}, comps)


def consistency_inputs(method1_details: Optional[dict[str, Any]], public_history: list, date: str) -> dict[str, Any]:
    """The data keys ``compute_consistency_raw`` reads, from public sources: the day's data completeness and task queue
    as method 1 scored them (both public), the streak and weekend/weekday ratio from the PUBLIC history."""
    d = method1_details or {}
    out = character_engine.derive_consistency_inputs(public_history, date)
    out["data_completeness_pct"] = (d.get("data_completeness") or {}).get("score")
    tft = (d.get("task_follow_through") or {}).get("score")
    # The component is 100 - overdue * 12.5 (clamped); the inverse hands the engine the same score back.
    out["todoist"] = {"overdue_count": (100.0 - float(tft)) / 12.5} if tft is not None else None
    return out


def public_histories(public_history: list) -> dict[str, list]:
    """The 21-day raw-score histories, from the public views — the shape ``load_raw_score_histories`` builds."""
    out: dict[str, list] = {p: [] for p in PILLARS}
    for rec in public_history or []:
        for p in PILLARS:
            raw = (rec.get(f"pillar_{p}") or {}).get("raw_score")
            out[p].append(float(raw) if raw is not None else 40.0)
    return out


def public_challenge_bonus(method1: dict[str, Any]) -> dict[str, Any]:
    """The day's challenge XP when challenges are a public source, else nothing."""
    if not activity_publication.source_is_public(CHALLENGES_SOURCE):
        return {}
    return dict(method1.get("challenge_bonus_xp") or {})


def public_presence(rec: Any) -> tuple:
    """(presence, exact, reason) — the presence the public method reads.

    The stored public projection when the record carries one (``engagement_core.PUBLIC_PROJECTION_KEY``). Otherwise a
    derivation from the stored fields: the class re-judged with the private channels left out of the quiet list. The
    engine reads only ``presence_class``, ``planned_pause`` and ``gap_days``; ``exact`` is True when the derivation
    provably equals what the projection would have said (see ``_derivation_exact``)."""
    if not isinstance(rec, dict):
        return None, True, "no presence record"
    from content import engagement_core as ec

    pub = rec.get(ec.PUBLIC_PROJECTION_KEY)
    if isinstance(pub, dict):
        return pub, True, "the record's public projection"
    private_labels = {lbl for src, lbl in ec.MANUAL_CHANNELS.items() if src not in ec.PUBLIC_CHANNELS}
    quiet = [c for c in (rec.get("channels_quiet") or []) if c not in private_labels]
    gap = rec.get("gap_days")
    gap_f = float(gap) if gap is not None else None
    planned = bool(rec.get("planned_pause"))
    presence = {
        "presence_class": ec._classify(gap_f, quiet, None, planned=planned),
        "gap_days": gap,
        "planned_pause": planned,
        "derived_from": "the stored presence record, private channels left out",
    }
    exact, reason = _derivation_exact(rec, gap_f, quiet, ec)
    return presence, exact, reason


def _derivation_exact(rec: dict, gap: Optional[float], quiet: list, ec: Any) -> tuple:
    """Whether the derived class is provably the public projection's. The class is fixed by the food gap (a public
    channel) except (a) on a two-day gap, where three quiet channels make it 'quiet' — the public habits channel can
    only ADD itself to the list, so fewer than two other quiet channels proves 'light' — and (b) through the planned
    pause, whose window starts at the latest manual log: provably unchanged when a public channel other than habits
    (whose public predicate is stricter) logged on that same latest day."""
    if gap is not None and gap <= 1:
        return True, "food logged within a day: present whatever else"
    habits_label = ec.MANUAL_CHANNELS.get("habitify")
    if gap == 2 and len([c for c in quiet if c != habits_label]) + 1 >= 3:
        return False, "two-day gap with enough quiet public channels that the public habits predicate could tip it"
    if gap == 2:  # a planned pause holds the class at 'light' too, so the pause window cannot move it
        return True, "two-day gap with too few quiet public channels to make it quiet: light, planned or not"
    last = rec.get("last_manual_log_date")
    detail = rec.get("channel_detail") or {}
    same_window = any((detail.get(src) or {}).get("last_log_date") == last for src in ec.PUBLIC_CHANNELS if src != "habitify" and last)
    if same_window:
        return True, "the latest manual log was on a public channel, so the pause window is the same"
    return False, "the latest manual log may have been private or habits-only: the pause window is not provably the same"


def public_view_for_chain(record: Any) -> Optional[dict[str, Any]]:
    """A stored record's public variant as the NEXT day's chain reads it (top-level date, unmasked pillars)."""
    return character_privacy.public_view(record)


def compute_public_variant(
    method1: dict[str, Any],
    prev_public: Optional[dict[str, Any]],
    public_history: list,
    config: dict[str, Any],
    *,
    engagement: Optional[dict[str, Any]] = None,
    habit_method: Optional[str] = None,
    vice_streaks: Optional[dict[str, Any]] = None,
    origin: str = "live",
    computed_at: Optional[str] = None,
) -> tuple:
    """(public block, public progression transitions) for one day.

    ``method1``        the day's method-1 record (as computed, or as stored — Decimals are converted)
    ``prev_public``    the previous record's public view (``public_view_for_chain``), None on the first day
    ``public_history`` the public views of the records in the 21-day window, oldest first — the SAME dates method 1's
                       history held (the caller fails closed when any of them has no public variant)
    ``engagement``     the public presence (``public_presence``)
    ``habit_method``   the day's habit_scores.scoring_method as the compute saw it (None: no habit score)
    """
    m1 = character_engine._from_decimal(method1)
    date = m1["date"]
    cfg = public_config(config)
    pre: dict[str, Any] = {}
    for p in VERBATIM_PILLARS:
        pd = m1.get(f"pillar_{p}") or {}
        pre[p] = (pd.get("raw_score"), copy.deepcopy(pd.get("components") or {}))
    pre["mind"] = public_mind((m1.get("pillar_mind") or {}).get("components"), habit_method, cfg)
    pre["relationships"] = public_relationships(cfg)
    hist = [character_engine._from_decimal(h) for h in public_history or []]
    prev_cs = (m1.get("pillar_consistency") or {}).get("components")
    data: dict[str, Any] = {"date": date, "precomputed_pillars": pre, "engagement_state": engagement, "vice_streaks": vice_streaks}
    data.update(consistency_inputs(prev_cs, hist, date))
    bonus = public_challenge_bonus(m1)
    if bonus:
        data["challenge_bonus_xp"] = bonus
    prev = character_engine._from_decimal(prev_public) if prev_public else None
    rec = character_engine.compute_character_sheet(data, prev, public_histories(hist), cfg)
    transitions = rec.pop("progression_transitions", None)
    rec.update(
        {
            "public_method_version": METHOD_VERSION,
            "effective_from": EFFECTIVE_FROM,
            "method_history": [dict(m) for m in character_privacy.PUBLIC_METHOD_HISTORY],
            "origin": origin,
            "computed_at": computed_at or datetime.now(timezone.utc).isoformat(),
        }
    )
    return rec, transitions


def chain_inputs_ready(previous_state: Optional[dict[str, Any]], history_records: list) -> tuple:
    """(prev_public, public_history, reason) — None for both when a record the chain needs has no public variant (the
    live compute then writes NO public variant: a chain restarted from nothing would publish a reset level)."""
    prev_public = None
    if previous_state:
        prev_public = public_view_for_chain(previous_state)
        if prev_public is None:
            return None, None, f"previous record {previous_state.get('date')} has no public variant"
    hist = []
    for rec in history_records or []:
        v = public_view_for_chain(rec)
        if v is None:
            return None, None, f"history record {rec.get('date')} has no public variant"
        hist.append(v)
    return prev_public, hist, None


def attach_public_variant(
    record: dict[str, Any], data: dict[str, Any], previous_state: Any, history_records: list, config: dict
) -> Optional[str]:
    """The live compute's step: compute the day's public variant from the method-1 ``record`` just computed and attach
    it (``PUBLIC_KEY`` + the transitions the receipt stores). Returns None on success, else the reason no variant was
    attached — the record is then stored without one and every public surface fails closed for that date."""
    prev_public, hist, reason = chain_inputs_ready(previous_state, history_records)
    if reason:
        return reason
    engagement, _exact, _why = public_presence(data.get("engagement_state"))
    hs = data.get("habit_scores") or {}
    block, transitions = compute_public_variant(
        record,
        prev_public,
        hist or [],
        config,
        engagement=engagement,
        habit_method=hs.get("scoring_method") if isinstance(hs, dict) else None,
        vice_streaks=data.get("vice_streaks"),
        origin="live",
    )
    record[PUBLIC_KEY] = block
    record["public_progression_transitions"] = transitions
    return None


def public_input_rows(input_rows: Any) -> list:
    """A receipt's input-row groups restricted to public sources (the ``/api/character_receipt`` filter, applied
    BEFORE the public receipt is digested, so its digest covers exactly the rows it names)."""
    out = []
    for r in input_rows or []:
        src = str((r or {}).get("pk") or "").split("#SOURCE#")[-1] if isinstance(r, dict) else ""
        if src and activity_publication.source_is_public(src):
            out.append(r)
    return out


def public_receipt(record: dict[str, Any], config: dict[str, Any], input_rows: Any) -> Optional[dict[str, Any]]:
    """The public variant's progression receipt (#1373 shape, digested + self-replayed against the PUBLIC config), or
    None when the record carries no public variant. Stored inside the day's receipt item under ``PUBLIC_KEY``."""
    transitions = record.get("public_progression_transitions")
    block = record.get(PUBLIC_KEY)
    if not transitions or not isinstance(block, dict):
        return None
    from health import progression_receipts as pr

    cfg = public_config(config)
    shaped = {
        "date": record.get("date"),
        "engine_version": block.get("engine_version"),
        "computed_at": block.get("computed_at"),
        "progression_transitions": transitions,
    }
    receipt = pr.build_receipt(shaped, cfg, input_rows=public_input_rows(input_rows))
    if receipt is None:
        return None
    receipt["replay_verified"] = bool(pr.replay(receipt, cfg).get("verified"))
    receipt["public_method_version"] = METHOD_VERSION
    return receipt
