"""public_brief.py — the public-safe coaching brief, one per coach per weekly cycle (owner ruling 2026-11-09, third, E).

WHAT IT IS. A structured record, written once at the start of each cycle (a Monday-to-Sunday week), from publishable
inputs ONLY, with six sections kept apart by construction:

  1. ``observations`` — deterministic: each eligible metric's last-7-day, previous-7-day and 28-day means with their n
     (code computes; the model never does arithmetic) — and ``interpretations``, the coach's reading of them, each
     citing the observation ids it rests on;
  2. ``predictions`` — specific, falsifiable, prospective: one metric, a direction or a level, a window. The claim text
     is RENDERED from that structure (never the model's sentence), passes ``coach.filing_rules`` and is filed in THE
     prediction ledger (``COACH#<id> / PREDICTION#``, ``source = public_brief``) where the existing evaluator grades it;
  3. ``evaluation_criteria`` — the filed spec of each call (metric, test, window, tolerance and its rule), frozen at
     filing and copied here so the test is on the brief before the window opens;
  4. ``recommendations`` — proposed actions, each optionally with an action check (a behaviour metric, a comparison, a
     threshold) over the cycle;
  5. ``what he did`` — EVIDENCE rows (``PUBLIC_BRIEF#<cycle>#EVIDENCE#<rec>``), written by a later run once the
     recommendation's window has closed, from the recorded readings only, with their source and day; a recommendation
     with no action check has no evidence, and nothing is inferred from timing or correlation;
  6. ``revisions`` — REVISION rows (``PUBLIC_BRIEF#<cycle>#REVISION#<ts>``), append-only, each naming the item of the
     earlier brief it revises: the next cycle's coach may change position on its own previous brief.

THE INPUT SET. The model is shown exactly: the coach's name and title (``persona``), the observation table for the
coach's ``public_brief_metrics`` (``config/personas.json``) intersected with ``public_brief_policy.eligible_metrics()``
(derived from the source classification — see that module), and the coach's previous brief with its calls' ledger
statuses when that brief is itself publishable, and (CR3, ``coach.public_brief_disputes``) the earlier coaches'
current-cycle calls on metrics this coach also reads — their RENDERED claims, from publishable briefs, which the coach may
dispute. Nothing else: no coach state, stance, thread, conversation, check-in, journal or mood read, no other coach's
own words. The provenance stamp is computed from that same set, so
``narrative_provenance`` decides publication from what the brief was actually made from.

THE ORDER (cost first, then honesty), per run:
  1. budget — ``budget_guard.allow("coach_narrative")`` before any read or call (band 2);
  2. the cycle — only the cycle containing today, never before ``FIRST_CYCLE`` (no backfill, ever);
  3. evidence for earlier briefs whose recommendation windows have closed (deterministic, no model);
  4. an existing brief for this cycle is never rewritten (conditional put);
  5. observations (deterministic) — too few readings, no call; a required input with no observation holds the coach
     (``required_inputs_absent``), and so does one whose newest reading is older than the coach's
     ``public_brief_fresh_within_days`` (``inputs_stale``) — never a brief from inputs that stopped before the run;
  6. ONE Haiku call through ``bedrock_client.invoke`` (one regeneration if the reply is unusable);
  7. item checks, fail closed: every number in the coach's words appears in the facts or the item's own structure; no
     private-activity words (``prediction_publication.words_name_private_activity``), no relationship words, nothing
     the deterministic sensitivity spine flags; a call must file GRADEABLE. A failing item is dropped; a brief with no
     surviving item is held (nothing written);
  8. write: the ledger calls, then the brief, then any revisions — each stamped with its provenance.

The private coaching process is not touched: no private reader or writer changes, and nothing here reads its output.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional

from ai.model_routing import model_for  # #4770: the one model registry
from common import narrative_provenance as NP, public_brief_policy as POL
from experiment.phase_filter import singleton_visible, with_phase_filter

from coach import public_brief_disputes as DISP

logger = logging.getLogger(__name__)

PRODUCER = "coach.public_brief"
BUDGET_FEATURE = "coach_narrative"
MODEL = model_for("coach_narrative.public_brief")
USER_ID = "matthew"
MAX_TOKENS = 1400

LAST_DAYS = 7
BASELINE_DAYS = 28
MIN_READINGS = 3  # an observation needs at least this many readings in its last 7 days to be shown
MAX_ITEMS = 3  # per section
WINDOW_MIN, WINDOW_MAX = 7, 28
CONF_MIN, CONF_MAX = 0.5, 0.95
MAX_WORDS = 45
EVIDENCE_SETTLE_DAYS = 1  # a recommendation's evidence is read the day after its window closes, at the earliest
POINT_LOOKBACK_DAYS = 30

# Plain words, unit and display precision for each measured metric. The label names the metric the way
# coach.filing_rules recognises it, so a rendered claim files against the metric it is about.
METRIC_WORDS: dict = {
    "blood_glucose_avg": ("average blood glucose", "mg/dL", 1),
    "blood_glucose_std_dev": ("glucose variability", "mg/dL", 1),
    "body_fat_pct": ("body fat", "%", 1),
    "deep_pct": ("deep sleep share", "%", 1),
    "hrv": ("heart rate variability", "ms", 1),
    "recovery_score": ("recovery score", "%", 0),
    "rem_pct": ("REM sleep share", "%", 1),
    "resting_heart_rate": ("resting heart rate", "bpm", 1),
    "sleep_duration_hours": ("sleep duration", "hours", 2),
    "sleep_score": ("sleep score", "points", 0),
    "steps": ("daily steps", "steps", 0),
    "total_calories_kcal": ("daily calories", "kcal", 0),
    "total_protein_g": ("daily protein", "g", 0),
    # Hevy: one reading per performed session that logged load (measurable_metrics.row_is_reading) — never a day total,
    # never a plan. "lifting volume" is the name filing_rules binds the call to (bare "volume" binds nothing).
    "total_volume_kg": ("per-session lifting volume", "kg", 0),
    "weight_lbs": ("weight", "lb", 1),
}
# A recommendation's action check measures what HE does, not an outcome: the metrics whose ledger subdomain is a
# behaviour (experiment.measurable_metrics.METRIC_SUBDOMAIN).
ACTION_SUBDOMAINS = frozenset({"calories", "protein", "training"})
CONDITIONS = {"at_least": ">=", "at_most": "<="}
REQUIRED_KEY = "public_brief_required_metrics"  # config/personas.json: the inputs a coach's brief cannot do without
#: config/personas.json: an explicit per-coach switch. A coach is in the brief when this is true, or — when it is absent —
#: when the coach is operational. ``false`` takes an operational coach out without touching anything else.
ENABLED_KEY = "public_brief_enabled"
HELD_FOR_INPUTS = "required_inputs_absent"  # run_coach's reason when one of them has no observation for the cycle
#: config/personas.json: a coach whose required inputs must have a reading in the last N days before the run (a manual
#: export such as MacroFactor's can leave a week with enough readings to observe that all stop days before the run).
FRESH_KEY = "public_brief_fresh_within_days"
HELD_STALE = "inputs_stale"  # run_coach's reason when a required input's newest reading is older than that floor

#: Words that would point at a partner, a relationship or another person — never in a brief (fail closed).
RELATIONSHIP_WORDS = re.compile(
    r"\b(?:partner|girlfriend|boyfriend|wife|husband|spouse|fianc\w*|dating|date night|relationship\w*|"
    r"family|friends?|kids?|children|son|daughter|mother|father|mom|dad|parents?|brother|sister|colleague\w*|boss)\b",
    re.I,
)
#: Training claims no brief input can evidence: the inputs are Hevy's recorded loads and reps (and the other coaches'
#: measured metrics), so effort, RPE, intensity, technique, pain, injury, soreness, fatigue and strength or muscle gain
#: are never stated — whichever coach writes them (fail closed: the item is dropped).
UNEVIDENCED_TRAINING_WORDS = re.compile(
    r"\b(?:rpe|perceived exertion|exertion|effort\w*|intensity|technique|form cues?|injur\w*|pain\w*|sore\w*|"
    r"strain(?:ed|s)?|tendon\w*|fatigu\w*|stronger|weaker|strength gains?|1rm|one[- ]rep max|personal (?:best|record)s?|"
    r"prs?|hypertroph\w*|muscle (?:growth|gain)s?)\b",
    re.I,
)
_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


# ── the input set ───────────────────────────────────────────────────────────────────────────
def _personas(personas: Optional[dict] = None) -> dict:
    if personas is not None:
        return personas
    from coach import persona_registry

    return persona_registry.personas() or {}


def coach_metrics(coach_id: str, personas: Optional[dict] = None) -> list:
    """The coach's brief inputs: its registry list, kept only where the policy derives the metric as eligible."""
    p = _personas(personas).get(coach_id) or {}
    eligible = set(POL.eligible_metrics())
    return [m for m in (p.get("public_brief_metrics") or []) if m in eligible and m in METRIC_WORDS]


def required_metrics(coach_id: str, personas: Optional[dict] = None) -> list:
    """The inputs a coach's brief cannot be written without (``public_brief_required_metrics``, config/personas.json).

    Each must have an observation for the cycle; when one is absent the coach is HELD with the missing names, never
    briefed from the metrics that remain (a glucose coach with no glucose readings is not a calories brief). A listed
    metric that is not one of the coach's eligible inputs can never be observed, so it holds the coach (fail closed)."""
    p = _personas(personas).get(coach_id) or {}
    return [str(m) for m in (p.get(REQUIRED_KEY) or [])]


def brief_enabled(p: Any) -> bool:
    """The coach's ``public_brief_enabled`` when it is a bool; otherwise (absent) its ``operational`` flag."""
    if not isinstance(p, dict):
        return False
    flag = p.get(ENABLED_KEY)
    return flag if isinstance(flag, bool) else bool(p.get("operational")) and ENABLED_KEY not in p


def fresh_within_days(coach_id: str, personas: Optional[dict] = None) -> Optional[int]:
    """The coach's freshness requirement in days (``public_brief_fresh_within_days``), None when it declares none.
    A declared value that is not a whole number of days >= 1 is returned as 0, which no reading can meet (fail closed)."""
    p = _personas(personas).get(coach_id) or {}
    if FRESH_KEY not in p:
        return None
    v = p.get(FRESH_KEY)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 0


def fresh_floor(cycle: str, days: int) -> str:
    """The oldest day a required input's newest reading may be for a run on ``cycle``'s Monday (``days`` before it)."""
    return _day(cycle, -days)


def stale_inputs(coach_id: str, obs: list, cycle: str, personas: Optional[dict] = None) -> list:
    """The required inputs whose newest reading is older than the coach's freshness floor ([] when none, or when the
    coach declares no requirement). Read from the observations' own ``latest`` day, so the hold judges exactly the
    readings the brief would have been written from; never a value, only a day."""
    days = fresh_within_days(coach_id, personas)
    if days is None:
        return []
    floor = fresh_floor(cycle, days) if days else "9999-12-31"
    latest = {o["metric"]: o["latest"]["date"] for o in obs}
    return [m for m in required_metrics(coach_id, personas) if str(latest.get(m) or "") < floor]


def brief_coaches(personas: Optional[dict] = None) -> list:
    """Coaches the brief is enabled for (``brief_enabled``) with at least one eligible input, in registry order."""
    ps = _personas(personas)
    return [cid for cid, p in ps.items() if brief_enabled(p) and coach_metrics(cid, ps)]


def action_metrics(metrics: Iterable[str]) -> list:
    from experiment.measurable_metrics import METRIC_SUBDOMAIN

    return [m for m in metrics if METRIC_SUBDOMAIN.get(m) in ACTION_SUBDOMAINS]


# ── 1. observations (deterministic) ──────────────────────────────────────────────────────────
def _day(s: str, delta: int = 0) -> str:
    return (datetime.strptime(s[:10], "%Y-%m-%d") + timedelta(days=delta)).strftime("%Y-%m-%d")


def _mean(vals: list, places: int) -> Optional[float]:
    if not vals:
        return None
    m = round(sum(vals) / len(vals), places)
    return int(m) if places == 0 else m


def observe(metrics: Iterable[str], cycle: str, readings: Callable) -> list:
    """One observation per metric with enough readings: means over the 7 days before the cycle, the 7 before that and
    the 28 before the cycle, each with its n, plus the latest reading. ``readings(metric, start, end)`` ->
    ``[(day, value)]`` or None (a read error: the metric is left out, never guessed)."""
    out: list = []
    end = _day(cycle, -1)
    last_start, prior_start, prior_end, base_start = (
        _day(cycle, -LAST_DAYS),
        _day(cycle, -2 * LAST_DAYS),
        _day(cycle, -LAST_DAYS - 1),
        _day(cycle, -BASELINE_DAYS),
    )
    for metric in metrics:
        label, unit, places = METRIC_WORDS[metric]
        rows = readings(metric, base_start, end)
        if not rows:
            continue
        rows = sorted((str(d)[:10], float(v)) for d, v in rows if base_start <= str(d)[:10] <= end)
        last = [v for d, v in rows if d >= last_start]
        prior = [v for d, v in rows if prior_start <= d <= prior_end]
        if len(last) < MIN_READINGS:
            continue
        latest_day, latest_val = rows[-1]
        out.append(
            {
                "id": f"o{len(out) + 1}",
                "metric": metric,
                "label": label,
                "unit": unit,
                "last7": {"start": last_start, "end": end, "mean": _mean(last, places), "n": len(last)},
                "prior7": {"start": prior_start, "end": prior_end, "mean": _mean(prior, places), "n": len(prior)},
                "last28": {"start": base_start, "end": end, "mean": _mean([v for _d, v in rows], places), "n": len(rows)},
                "latest": {"date": latest_day, "value": _mean([latest_val], places)},
                "source_refs": [{"source": s, "start": base_start, "end": end} for s in (POL.metric_sources(metric) or [])],
            }
        )
    return out


def _num(v: Any) -> str:
    return "none" if v is None else f"{v:g}" if isinstance(v, float) else str(v)


def facts_text(obs: list) -> str:
    lines = []
    for o in obs:
        u = o["unit"]
        lines.append(
            f"{o['id']} | {o['label']} ({u}) | last 7 days {o['last7']['start']} to {o['last7']['end']}: mean "
            f"{_num(o['last7']['mean'])}, {o['last7']['n']} readings | previous 7 days: mean {_num(o['prior7']['mean'])}, "
            f"{o['prior7']['n']} readings | last 28 days: mean {_num(o['last28']['mean'])}, {o['last28']['n']} readings | "
            f"latest {_num(o['latest']['value'])} on {o['latest']['date']}"
        )
    return "\n".join(lines)


# ── the previous brief (only when it is itself publishable) ──────────────────────────────────
def prior_block(prior: Optional[dict], ledger: dict) -> str:
    if not prior:
        return ""
    lines = [f"Your previous brief (cycle {prior.get('brief_cycle')}). Each item has an id you may revise:"]
    for it in prior.get("interpretations") or []:
        lines.append(f"{it['id']} (reading): {it.get('text', '')}")
    for p in prior.get("predictions") or []:
        st = (ledger.get(p.get("prediction_id")) or {}).get("status") or "unknown"
        lines.append(f"{p['id']} (prediction): {p.get('claim', '')} — ledger status: {st}")
    for r in prior.get("recommendations") or []:
        lines.append(f"{r['id']} (recommendation): {r.get('text', '')}")
    return "\n".join(lines)


# ── 6. the model ──────────────────────────────────────────────────────────────────────────────
def system_prompt(persona: dict, metrics: list, actions: list, targets: Optional[list] = None) -> str:
    name, title = persona.get("name") or "The coach", persona.get("title") or "coach"
    return (
        f"You are {name}, {title}, writing this week's PUBLIC coaching brief for a public health-experiment site. "
        'You write ABOUT Matthew in the third person ("he"), for readers who will check your record later.\n'
        "Rules you must obey:\n"
        "- Use ONLY the measured facts you are given. Every number you write must appear in them exactly. Do no "
        "arithmetic: never add, subtract, average, convert or re-round a number.\n"
        "- Never mention or guess at his feelings, mood, motivation, journal, diary, videos, check-ins, conversations, "
        "symptoms or private life, and never mention any other person. No medical diagnosis. Correlative only: never "
        "claim one thing caused another.\n"
        "- Training facts are what Hevy recorded for sessions he performed (load and reps). Never mention effort, RPE, "
        "intensity, technique, pain, injury, soreness, fatigue, strength or muscle gain, and never describe a planned or "
        "recommended session as one he did.\n"
        f"- Plain words; at most {MAX_WORDS} words per text field.\n"
        "Return ONE JSON object and nothing else, with these keys:\n"
        f'- "interpretations": up to {MAX_ITEMS} of {{"text", "cites": [observation ids]}} — what the numbers say.\n'
        f'- "predictions": up to {MAX_ITEMS} of {{"metric", "kind": "direction"|"level", "direction": "up"|"down" '
        f'(direction only), "target": number (level only), "window_days": {WINDOW_MIN}-{WINDOW_MAX}, "confidence": '
        f'{CONF_MIN}-{CONF_MAX}, "rationale", "cites": [observation ids]}}. "metric" must be one of: '
        f"{', '.join(metrics)}. The platform writes the claim from these fields and grades it later, so make it a "
        "real forecast that could turn out wrong.\n"
        f'- "recommendations": up to {MAX_ITEMS} of {{"text", "rationale", "check": null or {{"metric", "condition": '
        f'"at_least"|"at_most", "threshold": number}}}} for this week. A check\'s metric must be one of: '
        f"{', '.join(actions) or '(none — use null)'}.\n"
        '- "position_changes": only if a previous brief is shown: up to 3 of {"target": its item id, "text": what you '
        'now think, "reason"} where your position has changed. Otherwise [].\n' + DISP.prompt_rules(targets or [])
    )


def generate(invoke: Callable, system: str, user: str, correction: str = "") -> tuple:
    """(parsed dict or None, usage) from ONE model call. ``invoke`` is ``bedrock_client.invoke`` in production."""
    msg = user + ("\n\nYour previous reply was refused: " + correction if correction else "")
    resp = invoke(
        {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system, "messages": [{"role": "user", "content": msg}]},
        model_name=MODEL,
    )
    text = ""
    for block in (resp or {}).get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            text = block["text"]
            break
    return parse_reply(text), dict((resp or {}).get("usage") or {})


def parse_reply(text: str) -> Optional[dict]:
    from ai.structured_json import parse_json_span  # #4276: the one parse door for model text

    out = parse_json_span(text, "{")
    return out if isinstance(out, dict) else None


# ── 7. item checks (fail closed) ──────────────────────────────────────────────────────────────
def _numbers(text: str) -> set:
    from ai.grounded_generation import numbers_in_text

    return numbers_in_text(_ISO.sub(" ", text or ""))


def _grounding_findings(text: str, shown: str, today: Optional[str]) -> list:
    """The registered grounding surface (tests/grounding_wiring.py): numbers, dates, freshness — against an allow-list
    built from exactly what the model was shown (the facts, the previous brief, the item's own structured numbers)."""
    from ai import grounded_generation as gg
    from common.constants import EXPERIMENT_START_DATE

    return gg.grounding_findings(
        text,
        allowed=gg.allowed_numbers(shown),
        allowed_dates=gg.allowed_dates(shown),
        generation_date_iso=today,
        start_date_iso=EXPERIMENT_START_DATE,
    )


def text_problems(text: Any, allowed: set, shown: str = "", today: Optional[str] = None) -> list:
    """Why a piece of the coach's words cannot be published ([] = it can). ``shown`` arms the grounding surface."""
    if not isinstance(text, str) or not text.strip():
        return ["empty"]
    reasons = []
    if len(text.split()) > MAX_WORDS:
        reasons.append("too_long")
    if _numbers(text) - allowed:  # exact: every number is one the facts (or the item's own fields) carry
        reasons.append("uncited_number")
    if shown and _grounding_findings(text, shown, today):
        reasons.append("grounding")
    from common import prediction_publication as PP

    if PP.words_name_private_activity(text):
        reasons.append("private_activity_words")
    if RELATIONSHIP_WORDS.search(text):
        reasons.append("relationship_words")
    if UNEVIDENCED_TRAINING_WORDS.search(text):
        reasons.append("unevidenced_training_claim")
    try:
        from privacy.broadcast_sensitivity_gate import deterministic_findings

        if deterministic_findings(text):
            reasons.append("sensitivity")
    except Exception:  # noqa: BLE001 — the screen could not run: fail closed
        reasons.append("sensitivity_unavailable")
    return reasons


def _cites(raw: Any, obs_ids: set) -> Optional[list]:
    cites = [str(c) for c in raw or [] if str(c) in obs_ids] if isinstance(raw, list) else []
    return sorted(set(cites)) or None


def _float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) < 1e7 else None


def check_draft(
    draft: dict,
    obs: list,
    metrics: list,
    actions: list,
    allowed: set,
    prior: Optional[dict],
    shown: str = "",
    today: Optional[str] = None,
    targets: Optional[list] = None,
) -> tuple:
    """(sections, dropped) — the items that pass, per section, and a count of dropped items (no text kept)."""

    def bad(text: Any, own: set = frozenset()) -> list:
        extra = " ".join(f"{x:g}" for x in sorted(own))
        return text_problems(text, allowed | set(own), (shown + "\n" + extra) if shown else "", today)

    obs_ids = {o["id"] for o in obs}
    dropped = {"interpretations": 0, "predictions": 0, "recommendations": 0, "position_changes": 0, "disputes": 0}
    out: dict = {"interpretations": [], "predictions": [], "recommendations": [], "position_changes": [], "disputes": []}
    for it in (draft.get("interpretations") or [])[:MAX_ITEMS]:
        cites = _cites((it or {}).get("cites"), obs_ids) if isinstance(it, dict) else None
        if not cites or bad(it.get("text")):
            dropped["interpretations"] += 1
            continue
        out["interpretations"].append({"id": f"i{len(out['interpretations']) + 1}", "text": it["text"].strip(), "cites": cites})
    for p in (draft.get("predictions") or [])[:MAX_ITEMS]:
        ok = isinstance(p, dict) and p.get("metric") in metrics and p.get("kind") in ("direction", "level")
        window = int(_float(p.get("window_days")) or 0) if ok else 0
        conf = _float(p.get("confidence")) if ok else None
        cites = _cites(p.get("cites"), obs_ids) if ok else None
        if ok and p["kind"] == "direction":
            ok = p.get("direction") in ("up", "down")
        if ok and p["kind"] == "level":
            ok = _float(p.get("target")) is not None
        own = {round(w, 4) for w in (window, _float(p.get("target")) or 0.0)} if ok else set()
        if not ok or not (WINDOW_MIN <= window <= WINDOW_MAX) or conf is None or not (CONF_MIN <= conf <= CONF_MAX) or not cites:
            dropped["predictions"] += 1
            continue
        if bad(p.get("rationale"), own):
            dropped["predictions"] += 1
            continue
        out["predictions"].append(
            {
                "metric": p["metric"],
                "kind": p["kind"],
                "direction": p.get("direction") if p["kind"] == "direction" else None,
                "target": _float(p.get("target")) if p["kind"] == "level" else None,
                "window_days": window,
                "confidence": round(conf, 2),
                "rationale": p["rationale"].strip(),
                "cites": cites,
            }
        )
    for r in (draft.get("recommendations") or [])[:MAX_ITEMS]:
        if not isinstance(r, dict):
            dropped["recommendations"] += 1
            continue
        chk = r.get("check")
        check = None
        if isinstance(chk, dict):
            thr = _float(chk.get("threshold"))
            if chk.get("metric") in actions and chk.get("condition") in CONDITIONS and thr is not None:
                check = {"metric": chk["metric"], "condition": chk["condition"], "threshold": thr}
            else:
                dropped["recommendations"] += 1
                continue
        own = {round(check["threshold"], 4)} if check else set()
        if bad(r.get("text"), own) or bad(r.get("rationale"), own):
            dropped["recommendations"] += 1
            continue
        out["recommendations"].append(
            {"id": f"r{len(out['recommendations']) + 1}", "text": r["text"].strip(), "rationale": r["rationale"].strip(), "check": check}
        )
    prior_ids = _item_ids(prior)
    for c in (draft.get("position_changes") or [])[:MAX_ITEMS] if prior else []:
        if not isinstance(c, dict) or str(c.get("target")) not in prior_ids:
            dropped["position_changes"] += 1
            continue
        if bad(c.get("text")) or bad(c.get("reason")):
            dropped["position_changes"] += 1
            continue
        out["position_changes"].append({"target": str(c["target"]), "text": c["text"].strip(), "reason": c["reason"].strip()})
    by_ref = {t["ref"]: t for t in targets or []}
    means = {o["metric"]: o["last7"]["mean"] for o in obs}
    seen: set = set()
    for d in (draft.get("disputes") or [])[: DISP.MAX_DISPUTES] if by_ref else []:
        pred = _check_dispute(d, by_ref, means, obs_ids, seen, bad)
        if pred is None:
            dropped["disputes"] += 1
            continue
        seen.add((pred["against"]["coach_id"], pred["metric"]))
        out["disputes"].append(pred)
    return out, dropped


def _check_dispute(d: Any, by_ref: dict, means: dict, obs_ids: set, seen: set, bad: Callable) -> Optional[dict]:
    """A dispute the opposition rule accepts, as a call structure over its target's window — or None."""
    theirs = by_ref.get(str(d.get("against"))) if isinstance(d, dict) else None
    if theirs is None or (d.get("metric") not in (None, theirs["metric"])) or (theirs["coach_id"], theirs["metric"]) in seen:
        return None
    mine = {
        "metric": theirs["metric"],
        "kind": d.get("kind"),
        "direction": d.get("direction") if d.get("kind") == "direction" else None,
        "target": _float(d.get("target")) if d.get("kind") == "level" else None,
    }
    rule = DISP.opposition(theirs, mine, means.get(theirs["metric"]))
    conf, cites = _float(d.get("confidence")), _cites(d.get("cites"), obs_ids)
    if rule is None or conf is None or not (CONF_MIN <= conf <= CONF_MAX) or not cites:
        return None
    own = {round(float(theirs["window_days"]), 4)} | ({round(mine["target"], 4)} if mine["target"] is not None else set())
    if bad(d.get("rationale"), own):
        return None
    against = {k: theirs[k] for k in ("coach_id", "item", "prediction_id", "claim")}
    return {
        **mine,
        "window_days": int(theirs["window_days"]),
        "confidence": round(conf, 2),
        "rationale": d["rationale"].strip(),
        "cites": cites,
        "against": against,
        "rule": rule,
        "mean": means.get(theirs["metric"]),
    }


def _item_ids(brief: Optional[dict]) -> set:
    if not brief:
        return set()
    return {
        str(i.get("id")) for k in ("interpretations", "predictions", "recommendations") for i in brief.get(k) or [] if isinstance(i, dict)
    }


# ── 2/3. the ledger calls ───────────────────────────────────────────────────────────────────
def render_claim(pred: dict, target_date: str) -> str:
    label, unit, places = METRIC_WORDS[pred["metric"]]
    if pred["kind"] == "direction":
        verb = "rise" if pred["direction"] == "up" else "fall"
        return f"{label[0].upper()}{label[1:]} will {verb} over the next {pred['window_days']} days."
    target = round(pred["target"], places)
    target = int(target) if places == 0 else target
    return f"{label[0].upper()}{label[1:]} will be about {target:g} {unit} on {target_date}."


def criteria_rule(spec: dict) -> str:
    """The engine's sentence for how a filed call is graded (deterministic copy, never the coach's words)."""
    if spec.get("type") == "point":
        return (
            f"Graded on the reading on {spec.get('target_date')}: confirmed if it is within ±{spec.get('tolerance'):g} of "
            f"{spec.get('threshold'):g} ({spec.get('tolerance_rule')}); refuted if not; inconclusive with no reading."
        )
    return (
        f"Graded on the first and last readings between {spec.get('window_start')} and {spec.get('window_end')}: confirmed "
        "if the change is in the called direction and larger than the window's own day-to-day noise; refuted if not; "
        "inconclusive without readings."
    )


def file_call(coach_id: str, cycle: str, item_id: str, pred: dict, tolerance_for: Callable, provenance: dict) -> Optional[dict]:
    """The PREDICTION# row for one brief call, or None when it cannot be filed GRADEABLE (it is then dropped)."""
    from coach import prediction_emission as PE, prediction_windows
    from coach.filing_rules import validate_filing

    metric, window = pred["metric"], int(pred["window_days"])
    subdomain = PE.infer_subdomain(metric)
    if pred["kind"] == "direction":
        spec = PE.build_prediction_eval_spec(metric, pred["direction"], window)
    else:
        tol = tolerance_for(metric)
        if not tol:
            return None
        tolerance, rule, _n = tol
        spec = PE.build_point_eval_spec(metric, pred["target"], tolerance, rule, window, cycle)
    window = prediction_windows.effective_window_days(spec, subdomain)  # the domain clamp, applied before the words
    spec["evaluation_window_days"] = window
    if spec.get("type") == "point":
        spec["target_date"] = _day(cycle, window)
    claim = render_claim({**pred, "window_days": window}, _day(cycle, window))
    verdict = validate_filing(claim, spec, cycle, stated_days=window)
    if not verdict["gradeable"]:
        logger.info("[public_brief] %s call on %s not filed: %s", coach_id, metric, verdict["filing"].get("reason"))
        return None
    row = PE.build_prediction_record(
        coach_id, cycle, claim, verdict["eval_spec"], Decimal(str(pred["confidence"])), "observational", filing=verdict["filing"]
    )
    if row.get("status") != "pending":
        return None
    row["source"] = POL.BRIEF_CALL_SOURCE
    row["brief_ref"] = {"coach_id": coach_id, "brief_cycle": cycle, "item": item_id}
    row[NP.PROVENANCE_KEY] = provenance
    return row


# ── 5. evidence (deterministic, after the window closes) ─────────────────────────────────────
def evidence_row(coach_id: str, cycle: str, rec: dict, readings: Callable, today: str, places: int) -> Optional[dict]:
    chk = rec.get("check") or {}
    metric = chk.get("metric")
    if not metric or not POL.metric_is_eligible(metric):
        return None
    start, end = cycle, POL.cycle_end(cycle)
    rows = readings(metric, start, end)
    if rows is None:
        return None  # a read error is not evidence; a later run tries again
    rows = sorted((str(d)[:10], float(v)) for d, v in rows if start <= str(d)[:10] <= end)
    op = CONDITIONS[chk["condition"]]
    met = [d for d, v in rows if (v >= chk["threshold"] if op == ">=" else v <= chk["threshold"])]
    sk = POL.evidence_sk(cycle, rec["id"])
    return {
        "pk": f"COACH#{coach_id}",
        "sk": sk,
        "coach_id": coach_id,
        "brief_cycle": cycle,
        "recommendation_id": rec["id"],
        "metric": metric,
        "condition": chk["condition"],
        "threshold": Decimal(str(chk["threshold"])),
        "window_start": start,
        "window_end": end,
        "days_in_window": POL.CYCLE_DAYS,
        "days_with_data": len(rows),
        "days_meeting": len(met),
        "readings": [{"date": d, "value": Decimal(str(round(v, places)))} for d, v in rows],
        "source_refs": [{"source": s, "start": start, "end": end} for s in (POL.metric_sources(metric) or [])],
        "state": "recorded" if rows else "no_record",
        "as_of": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        NP.PROVENANCE_KEY: NP.stamp(POL.families_for([metric]), producer=PRODUCER + ".evidence"),
    }


def _query_briefs(table: Any, coach_id: str) -> list:
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :p)",
        "ExpressionAttributeValues": {":pk": f"COACH#{coach_id}", ":p": POL.BRIEF_SK_PREFIX},
    }
    items: list = []
    while True:
        resp = table.query(**with_phase_filter(kwargs))  # a reset's tombstoned briefs never feed the next one
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def write_evidence(table: Any, coach_id: str, rows: list, readings: Callable, today: str, persist: bool) -> int:
    """Evidence for every recommendation (with a check) of an earlier brief whose window has settled and has none yet."""
    have = {r["sk"] for r in rows if POL.EVIDENCE_TAG in str(r.get("sk"))}
    n = 0
    for b in rows:
        sk = str(b.get("sk"))
        if not POL.is_brief_sk(sk) or not b.get("brief_cycle"):
            continue
        if _day(POL.cycle_end(b["brief_cycle"]), EVIDENCE_SETTLE_DAYS) > today:
            continue
        for rec in b.get("recommendations") or []:
            if not rec.get("check") or POL.evidence_sk(b["brief_cycle"], rec["id"]) in have:
                continue
            places = METRIC_WORDS.get(rec["check"]["metric"], ("", "", 1))[2]
            row = evidence_row(coach_id, b["brief_cycle"], _plain(rec), readings, today, places)
            if row and persist:
                _put_new(table, row)
            n += 1 if row else 0
    return n


def _plain(v: Any) -> Any:
    """DynamoDB Decimals back to floats (for a stored brief read as input)."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _ddb(v: Any) -> Any:
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _ddb(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_ddb(x) for x in v]
    return v


def _put_new(table: Any, item: dict) -> bool:
    """Append-only: a row is written once and never overwritten."""
    try:
        table.put_item(Item=_ddb(item), ConditionExpression="attribute_not_exists(sk)")
        return True
    except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed (already written) or a transport error
        logger.info("[public_brief] not written %s/%s: %s", item.get("pk"), item.get("sk"), e)
        return False


# ── the brief row ────────────────────────────────────────────────────────────────────────────
def build_brief(
    coach_id: str, cycle: str, today: str, obs: list, sections: dict, calls: list, dropped: dict, cost: dict, provenance: dict
) -> dict:
    preds, criteria = [], []
    for item_id, pred, row in calls:
        spec = row["evaluation"]
        preds.append(
            {
                "id": item_id,
                "prediction_id": row["prediction_id"],
                "claim": row["claim_natural"],
                "metric": pred["metric"],
                "kind": pred["kind"],
                "direction": pred.get("direction"),
                "target": pred.get("target"),
                "window_days": pred.get("window_days"),
                "confidence": pred["confidence"],
                "rationale": pred["rationale"],
                "cites": pred["cites"],
                **({"against": pred["against"]} if pred.get("against") else {}),
            }
        )
        criteria.append(
            {
                "prediction": item_id,
                "prediction_id": row["prediction_id"],
                "type": spec.get("type"),
                "metric": spec.get("metric"),
                "condition": spec.get("condition"),
                "threshold": spec.get("threshold"),
                "tolerance": spec.get("tolerance"),
                "tolerance_rule": spec.get("tolerance_rule"),
                "target_date": spec.get("target_date"),
                "window_start": spec.get("window_start"),
                "window_end": spec.get("window_end"),
                "evaluation_window_days": spec.get("evaluation_window_days"),
                "filing_rules_version": (row.get("filing") or {}).get("filing_rules_version"),
                "rule_sentence": criteria_rule(spec),
            }
        )
    sk = POL.brief_sk(cycle)
    row = {
        "pk": f"COACH#{coach_id}",
        "sk": sk,
        "coach_id": coach_id,
        "brief_cycle": cycle,
        "cycle_end": POL.cycle_end(cycle),
        "data_through": _day(cycle, -1),
        "policy_version": POL.POLICY_VERSION,
        "observations": obs,
        "interpretations": sections["interpretations"],
        "predictions": preds,
        "evaluation_criteria": criteria,
        "recommendations": sections["recommendations"],
        "dropped_items": dropped,
        "model": MODEL,
        "calls": int(cost.get("calls", 0)),
        "input_tokens": int(cost.get("input_tokens", 0)),
        "output_tokens": int(cost.get("output_tokens", 0)),
        "cost_usd": cost.get("cost_usd", 0.0),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_on": today,
        NP.PROVENANCE_KEY: provenance,
    }
    try:
        from experiment.phase_taxonomy import experiment_stamp_for

        row.update(experiment_stamp_for(row["pk"], sk))
    except Exception as e:  # noqa: BLE001 — a stamp is metadata, never a reason to drop the row
        logger.info("[public_brief] no experiment stamp: %s", e)
    return row


def revision_row(coach_id: str, prior_cycle: str, cycle: str, change: dict, provenance: dict, n: int) -> dict:
    at = datetime.now(timezone.utc).isoformat()
    return {
        "pk": f"COACH#{coach_id}",
        "sk": POL.revision_sk(prior_cycle, f"{at}#{n}"),
        "coach_id": coach_id,
        "brief_cycle": prior_cycle,
        "revised_in_cycle": cycle,
        "target": change["target"],
        "kind": "position_change",
        "text": change["text"],
        "reason": change["reason"],
        "generated_at": at,
        NP.PROVENANCE_KEY: provenance,
    }


def _cost(usages: list) -> dict:
    try:
        from ai import bedrock_client

        model_id = bedrock_client.resolve_model_id(MODEL)
        usd = sum(bedrock_client.estimate_cost_usd(u, model_id) for u in usages)
    except Exception:  # noqa: BLE001 — cost is metadata
        usd = 0.0
    return {
        "calls": len(usages),
        "input_tokens": sum(int(u.get("input_tokens", 0) or 0) for u in usages),
        "output_tokens": sum(int(u.get("output_tokens", 0) or 0) for u in usages),
        "cost_usd": round(usd, 6),
    }


# ── the run ────────────────────────────────────────────────────────────────────────────────────
def run_coach(
    table: Any,
    coach_id: str,
    cycle: str,
    today: str,
    *,
    invoke: Callable,
    readings: Callable,
    tolerance_for: Callable,
    persist: bool = True,
    personas: Optional[dict] = None,
    others: Optional[list] = None,
) -> dict:
    """One coach's brief. ``others``: the earlier coaches' shareable calls this cycle (registry order); the result's
    ``_shared`` carries this coach's for the coaches after it (``run`` strips it)."""
    rows = _query_briefs(table, coach_id)
    evidence_n = write_evidence(table, coach_id, rows, readings, today, persist)
    have = next((r for r in rows if POL.is_brief_sk(r.get("sk"), cycle)), None)
    if have is not None:
        return {"status": "exists", "evidence_written": evidence_n, "_shared": DISP.shared_calls(coach_id, _plain(have))}
    persona = _personas(personas).get(coach_id) or {}
    metrics = coach_metrics(coach_id, personas)
    obs = observe(metrics, cycle, readings)
    missing = [m for m in required_metrics(coach_id, personas) if m not in {o["metric"] for o in obs}]
    if missing:  # before any model call: no brief from substitute metrics under this coach's name
        return {"status": "held", "reason": HELD_FOR_INPUTS, "missing": missing, "evidence_written": evidence_n}
    stale = stale_inputs(coach_id, obs, cycle, personas)
    if stale:  # before any model call: a brief is never written from inputs that stopped days before the run
        days = fresh_within_days(coach_id, personas) or 0
        return {
            "status": "held",
            "reason": HELD_STALE,
            "stale": stale,
            "fresh_from": fresh_floor(cycle, days) if days else None,
            "evidence_written": evidence_n,
        }
    if not obs:
        return {"status": "insufficient_data", "evidence_written": evidence_n}
    prev = next((r for r in rows if str(r.get("sk")) == POL.brief_sk(_day(cycle, -POL.CYCLE_DAYS))), None)
    prior = _plain({k: v for k, v in prev.items() if k != NP.PROVENANCE_KEY}) if prev and NP.is_publishable(prev) else None
    ledger: dict = {}
    for p in (prior or {}).get("predictions") or []:
        got = table.get_item(Key={"pk": f"COACH#{coach_id}", "sk": f"PREDICTION#{p.get('prediction_id')}"}).get("Item") or {}
        ledger[p.get("prediction_id")] = {
            "status": got.get("status") if singleton_visible(got) else None
        }  # #946: a wiped call reads absent
    actions = action_metrics(metrics)
    families = POL.families_for(metrics) + [POL.PERSONA_FAMILY] + ([POL.LEDGER_FAMILY] if prior else [])
    provenance = NP.stamp(families, producer=PRODUCER, upstream=[prev] if prior else [])
    if not NP.is_publishable(provenance):  # belt: the input set must be publishable before any call is made
        return {"status": "refused", "reason": "inputs_not_publishable", "evidence_written": evidence_n}
    targets = DISP.offered(others or [], [o["metric"] for o in obs])
    if targets:  # the later coach reads earlier briefs' rendered calls: its provenance carries theirs
        families.append(POL.LEDGER_FAMILY)
        provenance = NP.stamp(families, producer=PRODUCER, upstream=([prev] if prior else []) + [t["brief"] for t in targets])
        if not NP.is_publishable(provenance):
            return {"status": "refused", "reason": "inputs_not_publishable", "evidence_written": evidence_n}
    system = system_prompt(persona, [o["metric"] for o in obs], [m for m in actions if m in {o["metric"] for o in obs}], targets)
    pblock = "\n\n".join(b for b in (prior_block(prior, ledger), DISP.others_block(targets, _personas(personas))) if b)
    user = "Measured facts (data through " + _day(cycle, -1) + "):\n" + facts_text(obs) + ("\n\n" + pblock if pblock else "")
    allowed = _numbers(facts_text(obs) + "\n" + pblock) | {float(LAST_DAYS), float(BASELINE_DAYS)}
    usages: list = []
    draft, usage = generate(invoke, system, user)
    usages.append(usage)
    if draft is None:
        draft, usage = generate(invoke, system, user, "it was not one JSON object with the keys asked for.")
        usages.append(usage)
    if draft is None:
        return {"status": "held", "reason": "unparseable", **_cost(usages), "evidence_written": evidence_n}
    obs_metrics = [o["metric"] for o in obs]
    shown = facts_text(obs) + ("\n" + pblock if pblock else "")
    sections, dropped = check_draft(
        draft, obs, obs_metrics, [m for m in actions if m in obs_metrics], allowed, prior, shown, today, targets
    )
    calls: list = []
    for pred in sections["predictions"]:
        item_id = f"p{len(calls) + 1}"
        row = file_call(coach_id, cycle, item_id, pred, tolerance_for, provenance)
        if row is None:
            dropped["predictions"] += 1
            continue
        calls.append((item_id, pred, row))
    disputes: list = []  # (call, target, dispute provenance) — each side a ledger call graded by the existing evaluator
    for n, pred in enumerate(sections["disputes"], 1):
        theirs = next(t for t in targets if t["prediction_id"] == pred["against"]["prediction_id"])
        prov = DISP.provenance(provenance, theirs["brief"], pred["metric"], PRODUCER)
        row = file_call(coach_id, cycle, f"d{n}", pred, tolerance_for, provenance) if NP.is_publishable(prov) else None
        if row is None:
            dropped["disputes"] += 1
            continue
        row["dispute_ref"] = {"coach_id": theirs["coach_id"], "prediction_id": theirs["prediction_id"], "rule": pred["rule"]}
        calls.append((f"d{n}", pred, row))
        disputes.append(((f"d{n}", pred, row), theirs, prov))
    if not (sections["interpretations"] or calls or sections["recommendations"]):
        return {"status": "held", "reason": "no_item_passed", "dropped": dropped, **_cost(usages), "evidence_written": evidence_n}
    cost = _cost(usages)
    brief = build_brief(coach_id, cycle, today, obs, sections, calls, dropped, cost, provenance)
    if persist:
        filed = [c for c in calls if _put_new(table, c[2])]
        if len(filed) != len(calls):  # a call that could not be filed is not on the brief
            brief = build_brief(coach_id, cycle, today, obs, sections, filed, dropped, cost, provenance)
        if not _put_new(table, brief):
            return {"status": "exists", "evidence_written": evidence_n}
        for n, change in enumerate(sections["position_changes"]):
            _put_new(table, revision_row(coach_id, (prior or {})["brief_cycle"], cycle, change, provenance, n))
        filed_ids = {c[2]["prediction_id"] for c in filed}
        disputes = [d for d in disputes if d[0][2]["prediction_id"] in filed_ids]
        write_disputes(table, coach_id, cycle, disputes)
    out = {
        "status": "written" if persist else "dry_run",
        "sk": brief["sk"],
        "interpretations": len(sections["interpretations"]),
        "predictions": len(brief["predictions"]),
        "recommendations": len(sections["recommendations"]),
        "position_changes": len(sections["position_changes"]),
        "disputes": len(disputes),
        "dropped": dropped,
        "evidence_written": evidence_n,
        **cost,
        "_shared": DISP.shared_calls(coach_id, brief),
    }
    if not persist:  # the rehearsal reports what each check decided — counts and classes only, never the words
        out["checks"] = dry_run_checks(coach_id, brief, calls)
        out["checks"]["dispute_provenance_publishable"] = [NP.is_publishable(d[2]) for d in disputes]
    return out


def write_disputes(table: Any, coach_id: str, cycle: str, disputes: list) -> int:
    """Each ``(call, target, provenance)`` as its DISPUTE row — written once (conditional put): the frozen criterion
    is never rewritten, not by a re-run and not by a later dispute on the same pair and metric."""
    rows = [DISP.dispute_row(coach_id, cycle, mine, theirs, mine[1]["rule"], mine[1]["mean"], prov) for mine, theirs, prov in disputes]
    return sum(1 for r in rows if _put_new(table, r))


def dry_run_checks(coach_id: str, brief: dict, calls: list) -> dict:
    """What the publication and provenance checks decided for a brief that was NOT written (dry run): the brief's
    provenance verdict, and each call's class now (dark) and by its structure once the switch is on."""
    from common import prediction_publication as PP

    pk = f"COACH#{coach_id}"
    return {
        "brief_provenance_publishable": NP.is_publishable(brief),
        "call_provenance_publishable": [NP.is_publishable(c[2]) for c in calls],
        "calls_gradeable": [str((c[2].get("filing") or {}).get("verdict")) == "gradeable" for c in calls],
        "call_class_now": [list(PP.classify_call(pk, c[2])) for c in calls],
        "call_class_when_live": [list(PP.classify_call(pk, {**c[2], "source": None})) for c in calls],
    }


def run(
    table: Any,
    *,
    today: Optional[str] = None,
    coach_ids: Optional[list] = None,
    persist: bool = True,
    invoke: Optional[Callable] = None,
    allow: Optional[Callable] = None,
    readings: Optional[Callable] = None,
    tolerance_for: Optional[Callable] = None,
    personas: Optional[dict] = None,
) -> dict:
    """The weekly run. Never raises; returns ``{status, cycle, results}`` for the caller's log line."""
    try:
        if allow is None:
            from ai import budget_guard

            allow = budget_guard.allow
        if not allow(BUDGET_FEATURE):  # 1. budget FIRST — before any read or call
            return {"status": "paused", "feature": BUDGET_FEATURE}
        if today is None:
            from common.pacific_time import pacific_today

            today = pacific_today()
        cycle = POL.cycle_of(today)
        ok, why = POL.cycle_allowed(cycle, today)  # 2. never a past cycle, never before FIRST_CYCLE
        if not ok:
            return {"status": "refused", "reason": why, "cycle": cycle}
        if invoke is None:
            from ai import bedrock_client

            invoke = bedrock_client.invoke
        if readings is None or tolerance_for is None:
            from coach import metric_trailing_series as MTS

            cache: dict = {}
            readings = readings or (lambda m, s, e: MTS.window_readings(table, USER_ID, m, s, e))
            tolerance_for = tolerance_for or (lambda m: MTS.point_tolerance(table, USER_ID, m, cache, POINT_LOOKBACK_DAYS))
        results: dict = {}
        shared: list = []  # registry order: each coach sees the calls of the coaches before it
        for coach_id in brief_coaches(personas):
            if coach_ids and coach_id not in coach_ids:  # not re-run: its stored brief still sets the coaches after it
                have = next((r for r in _query_briefs(table, coach_id) if POL.is_brief_sk(r.get("sk"), cycle)), None)
                shared.extend(DISP.shared_calls(coach_id, _plain(have)) if have else [])
                continue
            try:
                results[coach_id] = run_coach(
                    table,
                    coach_id,
                    cycle,
                    today,
                    invoke=invoke,
                    readings=readings,
                    tolerance_for=tolerance_for,
                    persist=persist,
                    personas=personas,
                    others=list(shared),
                )
                shared.extend(results[coach_id].pop("_shared", None) or [])
            except Exception as e:  # noqa: BLE001 — one coach never stops the others
                logger.warning("[public_brief] %s failed: %s", coach_id, e, exc_info=True)
                results[coach_id] = {"status": "error", "error": str(e)}
        logger.info("[public_brief] cycle %s: %s", cycle, {k: v.get("status") for k, v in results.items()})
        return {"status": "ok", "cycle": cycle, "results": results}
    except Exception as e:  # noqa: BLE001
        logger.warning("[public_brief] run failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


# ── the Lambda door and the run stamp (the dead-man's input) ──────────────────────────────────
#: ``COACH#public_brief / RUN#<cycle>``: one row per scheduled cycle, overwritten by a later re-run of the same cycle, with
#: each coach's outcome. ``operational.public_brief_qa`` (nightly qa-smoke) reds when the row is missing after the
#: Monday deadline or when a coach's outcome is not a sanctioned one. A dry run never stamps.
RUN_PK = "COACH#public_brief"
RUN_SK_PREFIX = "RUN#"
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def run_sk(cycle: str) -> str:
    return f"{RUN_SK_PREFIX}{cycle}"


def _outcome(res: Any) -> dict:
    res = res if isinstance(res, dict) else {}
    out = {"status": str(res.get("status") or "unknown")}
    for k in ("reason", "missing", "stale", "fresh_from"):
        if res.get(k):
            out[k] = res[k] if k in ("missing", "stale") else str(res[k])
    return out


def stamp_run(table: Any, today: str, result: dict, merge: bool = False) -> bool:
    """Write the cycle's run stamp (fail-soft: a stamp that cannot be written leaves the dead-man to report the gap).
    ``merge``: a re-run of named coaches replaces only their outcomes in the cycle's existing stamp."""
    cycle = result.get("cycle") or POL.cycle_of(today)
    if cycle < POL.FIRST_CYCLE:
        return False  # no cycle is due before the first; nothing for the dead-man to read
    results = {cid: _outcome(r) for cid, r in (result.get("results") or {}).items()}
    if merge:
        try:
            prev = table.get_item(Key={"pk": RUN_PK, "sk": run_sk(cycle)}).get("Item") or {}
        except Exception as e:  # noqa: BLE001
            logger.warning("[public_brief] run stamp unreadable for %s: %s", cycle, e)
            return False
        if not singleton_visible(prev):  # absent, or tombstoned by a reset: a partial re-run never stands in for the cycle's run
            return False
        results = {**_plain(prev.get("results") or {}), **results}
    row = {
        "pk": RUN_PK,
        "sk": run_sk(cycle),
        "brief_cycle": cycle,
        "run_on": today,
        "status": str(result.get("status") or "unknown"),
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    for k in ("reason", "feature", "error"):
        if result.get(k):
            row[k] = str(result[k])[:300]
    try:
        table.put_item(Item=_ddb(row))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[public_brief] run stamp not written for %s: %s", cycle, e)
        return False


def handle_event(table: Any, event: dict) -> dict:
    """The Lambda's ``{"mode": "public_brief"}`` door.

    ``today`` (ISO day) is accepted ONLY with ``dry_run: true`` — it rehearses a future cycle through the real Lambda
    (real reads, one real model call per coach) without writing anything; a ``today`` without ``dry_run`` is refused
    before any read or call, so the override can never write a brief, a call or a stamp for a cycle that is not today's.
    """
    dry_run = bool(event.get("dry_run"))
    today = event.get("today")
    if today is not None:
        if not dry_run:
            return {"status": "refused", "reason": "today_override_requires_dry_run"}
        if not isinstance(today, str) or not _ISO_DAY.match(today):
            return {"status": "refused", "reason": "malformed_today"}
    if dry_run:
        return run(table, today=today, coach_ids=event.get("coach_ids"), persist=False)
    from common.pacific_time import pacific_today

    today = pacific_today()
    result = run(table, today=today, coach_ids=event.get("coach_ids"), persist=True)
    stamp_run(table, today, result, merge=bool(event.get("coach_ids")))
    return result
