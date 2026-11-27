"""character_public.py — the character sheet's PUBLIC method, ``character-public-v3`` (owner rulings 2026-11-05, 2026-11-26).

THE RULING. "Public Mind, composite, XP, Day grades and overall levels must depend only on public-eligible
inputs. Recompute affected historical public values using the corrected methodology. Preserve the original
method 1 scores privately ... Introduce clearly versioned public methodology and effective dates."

WHAT THE METHOD IS. The same engine (``character_engine.compute_character_sheet``) over public inputs only, with
its OWN state chain — the previous day's public variant, the public raw-score histories — so EMA levels, XP,
streaks, buffers, effects, the mood and the headline level never carry a private input forward:

* **Sleep, Movement, Nutrition, Metabolic** — every component reads a public source, so the public variant takes
  the day's method-1 raw score and component details VERBATIM (``VERBATIM_PILLARS``) and only re-runs the chain — less
  any raw-score modifier whose source is not public (#6224: the food-delivery multiplier on Nutrition, owner ruling
  2026-11-26), restored from the values the engine recorded before applying it (``without_private_modifiers``).
* **Mind — NOT SCORED (v2, #6224, owner rulings 2026-11-26: "Keep Mind unscored publicly"; "Do not replace private
  inputs with inferred or renamed equivalents").** The engine runs with Mind in ``unscored_pillars``: no raw score,
  level, tier, XP, driver or event, and no place in the consistency variance, the effects, the mood or the headline
  mean. The variant stores ``character_privacy.not_scored_pillar("mind")`` — the reason, and no number. Under v1 (below,
  kept for the backfill report's analysis) Mind was scored from its "public" components, but its habit shares still
  counted restraint habits (the core-12 share and the tier-weighted share), so v1 published a Mind derived from private
  inputs; recounting those shares over public habits would be the renamed equivalent the ruling forbids.
* **Mind (v1, retired)** — scored from its public components only (``MIND_COMPONENT_SOURCES``): a component whose source the
  publication policy does not classify public (``common.activity_publication``; unknown fails closed) is held out of
  the sum AND the coverage — not scored 0, which would let a behavioral absence move the score. The journal's 14-day
  consistency, the journal-enrichment values read, How We Feel / State of Mind and the check-in's stress are out.
  ``t1_habit_compliance`` is held out unless the day's habit score came from the core-12 set: the tier-weighted share
  counted the Morning and Evening Journal habits (both tier 1). The check-in's PRESENCE inside the core set stays in —
  the owner put it in the core twelve.
* **Restraint habits** (#6224, owner ruling 2026-11-24) — private: Mind's ``vice_control`` is held out of the sum and
  the coverage (the journal components' treatment, so the public Mind is a function of public inputs only and moves by
  nothing when a restraint streak does), and no cross-pillar effect whose condition reads a restraint streak is
  evaluated. The engine receives no restraint streaks at all. Both reopen only with ``RESTRAINT_DATA_PUBLISHED``.
* **Relationships — NOT INSTRUMENTED (#6293 amendment, owner ruling 2026-11-26: "Amend the calculation so uninstrumented
  Relationships is excluded entirely from consistency, variance and related aggregate calculations. Do not substitute a
  neutral value of 50 for missing evidence.")** — in ``UNSCORED_PUBLIC_PILLARS`` with its own reason: out of the whole
  chain like Mind (the engine's ``UNINSTRUMENTED_PILLARS`` does the same in method 1). It used to run as the engine's
  never-instrumented shape, whose neutral 50 sat in the consistency variance, the Alignment Bonus's all-pillars
  condition and the mood's composite.
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
from common.pacific_time import PACIFIC, parse_iso_utc

from health import character_engine, character_privacy

PUBLIC_KEY = character_privacy.PUBLIC_KEY
METHOD_VERSION = character_privacy.PUBLIC_METHOD_VERSION
EFFECTIVE_FROM = character_privacy.PUBLIC_METHOD_EFFECTIVE_FROM
# #6224: the pillars the public method does not score (``character_privacy.UNSCORED_PUBLIC_PILLARS``).
UNSCORED_PILLARS = tuple(
    p
    for p in ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
    if not character_privacy.pillar_scored_in_public(p)
)

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
    if name in character_privacy.RESTRAINT_COMPONENTS and not character_privacy.restraint_published():
        return False  # #6224: restraint streaks are private (owner ruling 2026-11-24) — out of the sum AND the coverage
    src = MIND_COMPONENT_SOURCES.get(name)
    return src is not None and activity_publication.source_is_public(src)


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    """The engine config the public method runs under: a deep copy whose Mind component set is its public components
    and whose cross-pillar effects are those that read no restraint input (#6224). Leveling, weights and bands are
    method 1's."""
    cfg = copy.deepcopy(config or {})
    if isinstance(cfg.get("cross_pillar_effects"), list) and not character_privacy.restraint_published():
        cfg["cross_pillar_effects"] = [e for e in cfg["cross_pillar_effects"] if not character_privacy.effect_reads_restraint(e)]
    mind = ((cfg.get("pillars") or {}).get("mind") or {}).get("components")
    if isinstance(mind, dict):
        cfg["pillars"]["mind"]["components"] = {k: v for k, v in mind.items() if mind_component_is_public(k)}
        cfg["pillars"]["mind"]["not_instrumented_note"] = UNAVAILABLE_NOTE
    return cfg


def public_contract(config: dict[str, Any]) -> dict[str, Any]:
    """#6224: the engine config as the PUBLIC "how the engine works" contract (``/api/character_config``) may describe
    it: ``public_config`` (no restraint component, no restraint-conditioned effect) with every pillar the public method
    does not score emptied of components, and no cross-pillar effect whose condition reads such a pillar (it is never
    evaluated publicly) — and that pillar's key taken out of every effect's targets."""
    cfg = public_config(config)
    for name in UNSCORED_PILLARS:
        pillar = (cfg.get("pillars") or {}).get(name)
        if isinstance(pillar, dict):
            cfg["pillars"][name] = dict(pillar, components={})
    effects = []
    for e in cfg.get("cross_pillar_effects") or []:
        cond = str((e or {}).get("condition") or "").lower().split()
        if any(name in cond for name in UNSCORED_PILLARS):
            continue
        if isinstance(e.get("targets"), dict):
            e = dict(e, targets={k: v for k, v in e["targets"].items() if k not in UNSCORED_PILLARS})
        effects.append(e)
    if isinstance(cfg.get("cross_pillar_effects"), list):
        cfg["cross_pillar_effects"] = effects
    return cfg


# Owner ruling 2026-11-06: "Missing data must not be represented as a genuine zero score. If no public-eligible Mind
# measurements are available, use an explicit unavailable/insufficient-data state rather than reporting a misleading
# 0.0." The unavailable state is the engine's existing no-signal state (`not_instrumented`): no XP judgment, levels
# frozen, out of the route composite, and out of the headline mean while the pillar has never earned a level.
UNAVAILABLE_NOTE = "Insufficient public data: no public-eligible Mind measurement was recorded for this day."
# Habit components whose `absent` flag means their INPUT RECORD was missing (no habit_scores record, or no known
# core habit) — missing data, never a behavioral zero, in the public method.
RECORD_BACKED_COMPONENTS = ("t0_habit_compliance", "t1_habit_compliance")
# A component whose zero is an EMPTY LOG (no reading session in the window): counted inside a measured day, but on
# its own it is no measurement.
EMPTY_LOG_COMPONENTS = ("reading_practice",)


def habit_components_public(habit_method: Optional[str]) -> bool:
    """Habit compliance may enter a public score only when the day's habit score came from the core-12 set and every
    core basis reads a public family (owner ruling 2026-11-06: the evening check-in's PRESENCE is classified
    `evening_checkin_presence`, public) — fail closed otherwise."""
    from health import core_habits

    return habit_method == CORE_SET_METHOD and all(activity_publication.core_basis_is_public(b) for b in core_habits.BASES)


def _is_measurement(name: str, score: Any) -> bool:
    return score is not None and (name not in EMPTY_LOG_COMPONENTS or float(score) > 0)


def public_mind(method1_details: Optional[dict[str, Any]], habit_method: Optional[str], cfg_public: dict[str, Any]) -> tuple:
    """Mind's (raw, details) from the day's component scores, public components only (config order). A habit
    component whose input record was missing is missing data (out of the sum, still in the coverage denominator),
    not a zero; with no public measurement at all the pillar is UNAVAILABLE (the engine's no-signal shape)."""
    comps = dict(((cfg_public.get("pillars") or {}).get("mind") or {}).get("components") or {})
    scores: dict[str, Any] = {}
    for name in list(comps):
        if name in CORE_SET_ONLY_COMPONENTS and not habit_components_public(habit_method):
            continue
        if name in RECORD_BACKED_COMPONENTS and habit_method == CORE_SET_METHOD and not habit_components_public(habit_method):
            continue  # a core-set day whose bases are not all public: no habit share in a public score
        d = (method1_details or {}).get(name)
        if not isinstance(d, dict):  # a component method 1 did not compute that day stays out, as it did there
            continue
        if d.get("absent") and name in RECORD_BACKED_COMPONENTS:
            scores[name] = None
            comps[name] = dict(comps[name], behavioral=False) if isinstance(comps[name], dict) else comps[name]
        else:
            scores[name] = None if d.get("absent") else d.get("score")
    if not any(_is_measurement(n, s) for n, s in scores.items()):
        comps = {n: (dict(c, behavioral=False) if isinstance(c, dict) else c) for n, c in comps.items()}
        raw, details = character_engine._weighted_pillar_score({n: None for n in scores}, comps)
        details["_insufficient_data"] = True
        return raw, details
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
    """The 21-day raw-score histories, from the public views — the shape ``load_raw_score_histories`` builds, by the same
    rule (#6293 amendment): a held pillar-day (not instrumented, below the coverage floor, absent) is left out, never
    filled with a stand-in value."""
    out: dict[str, list] = {p: [] for p in PILLARS}
    for rec in public_history or []:
        for p in PILLARS:
            pd = rec.get(f"pillar_{p}") or {}
            raw = pd.get("raw_score")
            if raw is None or character_engine.day_is_held(pd):
                continue
            out[p].append(float(raw))
    return out


def public_challenge_bonus(challenge_bonus: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The day's PUBLIC challenge XP ({pillar: xp} of the challenges ``activity_publication.challenge_is_public``
    passed — owner ruling 2026-11-06), when challenges are a public source. The stored method-1 aggregate is never
    used: it does not say which challenges it came from (fail closed)."""
    if not activity_publication.source_is_public(CHALLENGES_SOURCE):
        return {}
    return {k: v for k, v in (challenge_bonus or {}).items() if v}


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


def without_private_modifiers(raw: Any, details: Any) -> tuple:
    """#6224: a verbatim pillar's (raw, details) without any raw-score modifier whose source the publication policy does
    not classify public (``activity_publication``; unclassified fails closed) — the food-delivery multiplier on Nutrition
    (owner ruling 2026-11-26: the source's dates are private, and its multiplier must not reach the public variant). The
    pre-modifier values are the ones the engine recorded before it applied the multiplier; a record that carries a
    modifier without them cannot be restored exactly and raises (fail closed — never divided back out)."""
    d = copy.deepcopy(details or {})
    mod = d.get("_modifier")
    if not isinstance(mod, dict) or activity_publication.source_is_public(mod.get("source")):
        return raw, d
    del d["_modifier"]
    if d.get("_raw_unblended") is not None:
        if "pre_modifier_raw_unblended" not in mod:
            raise ValueError("a non-public modifier without its pre-modifier unblended raw: the public day cannot be restored")
        d["_raw_unblended"] = mod["pre_modifier_raw_unblended"]
    return mod.get("pre_modifier_raw", raw), d


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
    challenge_bonus: Optional[dict[str, Any]] = None,
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
        pre[p] = without_private_modifiers(pd.get("raw_score"), pd.get("components") or {})
    if "mind" not in UNSCORED_PILLARS:  # pragma: no cover — v1's arithmetic, kept for an owner ruling that reopens it
        pre["mind"] = public_mind((m1.get("pillar_mind") or {}).get("components"), habit_method, cfg)
    if "relationships" not in UNSCORED_PILLARS:  # pragma: no cover — #6293: not instrumented, so never scored
        pre["relationships"] = public_relationships(cfg)
    hist = [character_engine._from_decimal(h) for h in public_history or []]
    # #6224: an unscored pillar's history (a v1 variant's Mind) never reaches the consistency streak or its ratio.
    hist = [{k: v for k, v in h.items() if k not in {f"pillar_{u}" for u in UNSCORED_PILLARS}} for h in hist]
    prev_cs = (m1.get("pillar_consistency") or {}).get("components")
    # #6224: the restraint streaks never reach the public engine (no effect, no component reads them) while no restraint
    # figure is published — the parameter stays so the live compute and the backfill keep one call shape.
    restraint_in = vice_streaks if character_privacy.restraint_published() else None
    data: dict[str, Any] = {
        "date": date,
        "precomputed_pillars": pre,
        "engagement_state": engagement,
        "vice_streaks": restraint_in,
        "unscored_pillars": list(UNSCORED_PILLARS),
    }
    data.update(consistency_inputs(prev_cs, hist, date))
    bonus = public_challenge_bonus(challenge_bonus)
    if bonus:
        data["challenge_bonus_xp"] = bonus
    prev = character_engine._from_decimal(prev_public) if prev_public else None
    rec = character_engine.compute_character_sheet(data, prev, public_histories(hist), cfg)
    transitions = rec.pop("progression_transitions", None)
    for name in UNSCORED_PILLARS:  # #6224: the reason, and no number
        rec[f"pillar_{name}"] = character_privacy.not_scored_pillar(name)
    rec["unscored_pillars"] = list(UNSCORED_PILLARS)
    rec["headline_excluded_pillars"] = [p for p in rec.get("headline_excluded_pillars") or [] if p not in UNSCORED_PILLARS] + list(
        UNSCORED_PILLARS
    )
    if prev and prev.get("public_method_version") not in (None, METHOD_VERSION):
        # A level computed under an earlier method is not the level this one would have reached: a move from it is the
        # method changing, never an event (owner ruling 2026-11-06: a recalculation is not an achievement).
        rec["level_events"] = [
            e for e in rec.get("level_events") or [] if e.get("type") not in ("character_level_up", "character_level_down")
        ]
    rec.update(
        {
            "public_method_version": METHOD_VERSION,
            "effective_from": EFFECTIVE_FROM,
            "method_history": [dict(m) for m in character_privacy.PUBLIC_METHOD_HISTORY],
            "origin": origin,
            "basis": character_privacy.PUBLIC_METHOD_BASIS.get(origin),
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
    ready = data.get("habit_scores_status", habit_scores_readiness(hs, str(record.get("date")))) == READY
    block, transitions = compute_public_variant(
        record if ready else without_habit_inputs(record),
        prev_public,
        hist or [],
        config,
        engagement=engagement,
        habit_method=hs.get("scoring_method") if ready else None,
        vice_streaks=data.get("vice_streaks") if ready else None,
        challenge_bonus=data.get("public_challenge_bonus_xp"),
        origin="live",
    )
    record[PUBLIC_KEY] = block
    record["public_progression_transitions"] = transitions
    return None


READY = "ready"


def habit_scores_readiness(hs: Any, date: str) -> str:
    """Owner ruling 2026-11-06: an explicit dependency check, not a timing assumption. ``ready`` only when the record is
    for this day, was written after the day closed (a record written during the day is not the day), and its own input
    manifest says the Habitify data reached this day. Only the PUBLIC input is consulted: the manifest's journal rows
    are always degraded and must not gate a public score."""
    if not isinstance(hs, dict) or not hs:
        return "missing"
    if str(hs.get("date") or str(hs.get("sk", "")).replace("DATE#", ""))[:10] != date:
        return "wrong_day"
    stamp = parse_iso_utc(hs.get("computed_at"))  # the canonical parser (#1964): naive == UTC, never runner-local
    if stamp is None:
        return "unverified"
    if stamp.astimezone(PACIFIC).date().isoformat() <= date:
        return "before_day_closed"
    latest = (((hs.get("input_manifest") or {}).get("sources") or {}).get("habitify") or {}).get("latest_day")
    if not latest:
        return "unverified"
    return READY if str(latest) >= date else "habitify_behind"


def without_habit_inputs(method1: dict[str, Any]) -> dict[str, Any]:
    """The record with Mind's habit-backed components as missing data: a day whose habit scores were not ready is
    never scored from a stale or partial record, and never carries the previous day's forward."""
    out = copy.deepcopy(method1)
    comps = (out.get("pillar_mind") or {}).get("components")
    if isinstance(comps, dict):
        for name in RECORD_BACKED_COMPONENTS:
            if name in comps:
                comps[name] = {"score": 0.0, "absent": True}
        if "vice_control" in comps:
            comps["vice_control"] = {"score": None}
    return out


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
