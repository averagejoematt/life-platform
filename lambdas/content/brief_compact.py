"""brief_compact.py — the compact Morning Brief: the WHOLE email, about a minute to read (#6240, owner ruling 2026-11-23).

The compact format replaces the entire email — html part, text part and subject. The legacy report is not
appended: its detail stays behind ONE link (the public day page) and the analysis that produced it keeps running
(the coach pipeline and its model calls are unchanged; this module only chooses what to SHOW).

What one email holds, in order:

  1. VERIFIED CRITICAL ALERTS, when there are any (``critical_alerts``). Exempt from the three-metric ceiling,
     counted separately, and never dropped to meet the word ceiling: a brief they push past 250 words still sends.
  2. THE LEAD. The day's one decision, or a conditional sentence. The categorical quiet line ("Nothing important
     changed, and nothing needs you today.") is used ONLY when nothing is unknown, nothing changed, no alert stands
     and no recommendation survived — a day with data still on its way says what is not known instead.
  3. WHAT CHANGED. One sentence, or "nothing changed beyond normal day-to-day variation", by the thresholds below.
  4. AT MOST THREE METRICS — recovery, weight, training — each with its source and the day it describes.
  5. AT MOST TWO RECOMMENDATIONS (ceilings, not quotas): NEW ones, or a repeat whose evidence changed. An unchanged
     repeat is suppressed and counted; nothing is manufactured to fill the slot.
  6. NOT KNOWN YET: one line per input that has not arrived or could not be read.
  7. ONE DETAIL LINK: the public day page for the data day.

One editorial voice: no coach name, no byline, no board. No sentence reads a recovery score or a load ratio as
clearance. Pure module: no AWS, no clock, no I/O except ``persona_names`` (the bundled registry file, fail-soft).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from common.digest_utils import safe_float
from common.pacific_time import day_in_words, shift_day_key

from content.brief_format import esc

FORMAT_VERSION = "compact-v1"

# ── the budget (owner ruling 2026-11-23 §1: ceilings, not quotas) ────────────────────────────────────────────────
WORD_CEILING = 250
METRIC_CEILING = 3
REC_CEILING = 2
QUIET_WORDS = (50, 100)  # a quiet day may be 50–100 words
READING_WPM = 230  # the reading speed MEASURES uses for every product, so minutes compare across emails

# ── "what changed": the thresholds (owner ruling §5 — meaningful change, never day-to-day noise) ─────────────────
# RECOVERY: this morning's Whoop recovery has changed only when it falls OUTSIDE the range of the previous seven
# mornings (the same 7-day Whoop rows the brief already reads, `data["whoop_7d"]`). A value inside the past week's own
# spread is, by construction, a size of day-to-day movement already seen this week. Fewer than this many prior
# mornings = not enough history to call anything a change.
RECOVERY_RANGE_DAYS = 7
RECOVERY_MIN_HISTORY = 4
# WEIGHT: day-over-day weigh-in differences are mostly water and food mass; the 7-day trend (with its likely range,
# `weekly_rate_ci_low/high` from daily-metrics-compute) carries real change. A weigh-in has changed only when it differs
# from the previous weigh-in by at least this much — about three times the ~0.6 lb/day the current trend implies.
WEIGHT_DAY_NOISE_LB = 2.0
# TRAINING LOAD: the platform's own ACWR band (lambdas/compute/acwr_compute_lambda._classify_acwr, Gabbett 2016 /
# Hulin 2014). The load has changed only when the ratio CROSSES out of the band (inside the day before, outside now) —
# a ratio sitting outside for days is not new each day.
LOAD_BAND = (0.8, 1.3)
REBASELINING = "re-baselining"  # health.hr_regime.REBASELINING: the ratio is not read while heart-rate numbers re-baseline

# ── verified critical alerts (owner ruling §4/§5) ─────────────────────────────────────────────────────────────────
# "Verified" = a stored platform verdict or a device record, never model text:
#   * training_load — daily-metrics/acwr compute's own `acwr_alert` with the injury-risk zones (ratio above 1.3);
#   * anomaly — the anomaly detector's own multi-source verdict (`severity` moderate/high: metrics across more than one
#     source on the data day; a single-source flag or a travel/sick-suppressed day is not one) AND at least two of its
#     flagged metrics physiological (`ANOMALY_PHYSIOLOGICAL_FIELDS`). A weigh-in below baseline is the goal's direction
#     and a habit/task/steps dip is behaviour (often computed from a food log that has not arrived), so neither can make
#     the detector's verdict a critical alert on its own;
#   * heart_rhythm — a device-recorded rhythm notification or ECG dated the data day, shown as the owner-only data
#     lines the health package's owner-only renderer already produces for this email (counts with n and window, no
#     interpretation) — handed in by emails.brief_trial, the one reviewed door (tests/test_rhythm_channel_privacy_4972.py).
LOAD_ALERT_ZONES = ("caution", "danger")
ANOMALY_ALERT_SEVERITIES = ("moderate", "high")
# lambdas/emails/anomaly_detector_lambda.METRICS' body signals (fields), as opposed to behaviour and weight
ANOMALY_PHYSIOLOGICAL_FIELDS = frozenset(
    {
        "recovery_score",
        "hrv",
        "resting_heart_rate",
        "sleep_quality_score",
        "sleep_efficiency_percentage",
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "walking_asymmetry_pct",
    }
)
ANOMALY_MIN_PHYSIOLOGICAL = 2
RHYTHM_EVENTS_PREFIX = "Events in the "  # the owner-only renderer's dated-episode line (pinned by the #6240 tests)

QUIET_LEAD = "Nothing important changed, and nothing needs you today."
NO_CHANGE = "Nothing changed beyond normal day-to-day variation."
NO_CHANGE_SO_FAR = "In the data that has arrived, no change is beyond normal day-to-day variation."  # never categorical
NOT_MEDICAL = "Personal tracking, not medical advice."

# Wording the compact brief never sends: a recovery score or load ratio read as clearance (owner ruling §5).
CLEARANCE_RE = re.compile(
    r"\b(cleared|clearance|safe to|safe zone|green light|all clear|good to go|fine to train|nothing to worry"
    r"|ready (?:for|to) (?:train|push|go hard)|hard training (?:or [a-z -]+ )?is fine)\b",
    re.I,
)
# Absence worded as behaviour — never about an input that is still pending (owner ruling §2).
MISSED_RE = re.compile(
    r"\b(missed|skipped|not logged|nothing (?:was )?logged|zero (?:nutrition|food|calories|intake)|failed to log)\b", re.I
)
# A recommendation's action class -> the metric whose meaningful change counts as new evidence for it (§6).
_LEADING_MARKS = re.compile(r"^[^\w(\"“]+")  # the guidance's leading emoji: one voice, plain sentences
EVIDENCE_OF = {"recovery_day": "recovery", "sleep": "recovery", "movement": "training"}


@dataclass
class Metric:
    key: str  # recovery | weight | training
    text: str
    source: str
    as_of: str  # the day key the value describes
    value: str  # the one number shown for this quantity (contradiction check)
    changed: Optional[str] = None  # the what-changed sentence, when this metric crossed its threshold


@dataclass
class Alert:
    kind: str  # training_load | anomaly | heart_rhythm
    lines: list


@dataclass
class CompactRec:
    key: str
    text: str
    status: str  # NEW | REPEAT
    rec_id: str
    changed_because: Optional[str] = None
    origin: Any = None  # the brief_hybrid.Rec it came from (the response token and the dark #6158 pilot read it)


@dataclass
class CompactView:
    data_day: str
    lead: str
    lead_kind: str  # quiet | decision | alert | unknown | plain
    changed: str
    has_change: bool
    metrics: list
    recs: list
    alerts: list
    unknown: list
    detail_url: str
    pending_inputs: list = field(default_factory=list)
    repeats_suppressed: int = 0
    dropped_voice: int = 0
    dropped_clearance: int = 0
    dropped_for_length: int = 0
    respond_url: Optional[str] = None
    respond_rec: Any = None
    respond_note: Optional[str] = None
    follow_up: Optional[dict] = None  # #6158 pilot (dark), duck-typed with brief_hybrid.View
    follow_up_url: Optional[str] = None

    @property
    def quiet(self) -> bool:
        return self.lead_kind == "quiet"


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _n(v, nd=0) -> str:
    return str(int(round(v))) if nd == 0 else f"{v:.{nd}f}"


def _signed(v, nd=1) -> str:
    return ("−" if v < 0 else "+" if v > 0 else "") + _n(abs(v), nd)


def range_change(value, prior) -> Optional[str]:
    """'above' / 'below' when `value` is outside the range of `prior` (n ≥ RECOVERY_MIN_HISTORY), else None."""
    vals = [x for x in (_f(p) for p in prior or []) if x is not None]
    if value is None or len(vals) < RECOVERY_MIN_HISTORY:
        return None
    return "above" if value > max(vals) else "below" if value < min(vals) else None


def persona_names() -> tuple:
    """Every persona name in the registry (config/personas.json), plus the board's — the voices the compact brief
    never carries. Fail-soft: () when the file cannot be read (the checker then records `voice_unchecked`)."""
    try:
        from common.repo_config import config_path

        with open(config_path("personas.json"), encoding="utf-8") as fh:
            personas = (json.load(fh) or {}).get("personas") or {}
        names = {str(p.get("name") or "").strip() for p in personas.values() if isinstance(p, dict)}
        # proper names only: "The Chair" is also ordinary English ("get up from the chair")
        return tuple(sorted(n for n in names if len(n) >= 4 and not n.startswith("The "))) + ("Board of Directors",)
    except Exception:  # noqa: BLE001
        return ()


def names_a_persona(text: str, persona: tuple) -> bool:
    """A persona's name as a whole phrase, any case (the legacy headers print them in capitals)."""
    return any(re.search(r"\b" + re.escape(p) + r"\b", text or "", re.I) for p in persona)


# ── the three metrics ────────────────────────────────────────────────────────────────────────────────────────────


def recovery_metric(data: dict, status: dict) -> tuple[Optional[Metric], list]:
    """This morning's recovery when scored, else the data day's labelled with its morning. (metric, unknown lines)."""
    day = data.get("date") or ""
    today = shift_day_key(day, 1)
    unknown = []
    # the day rows only: the same partition carries per-workout rows (DATE#<day>#WORKOUT#<id>) with no recovery
    prior_rows = [
        r
        for r in (data.get("whoop_7d") or [])
        if isinstance(r, dict) and len(str(r.get("sk", ""))) == 15 and r.get("recovery_score") is not None
    ]
    today_rec = _f(status.get("today_recovery"))
    if today_rec is not None:
        value, as_of, when = today_rec, today, "this morning (" + day_in_words(today) + ")"
        prior = [safe_float(r, "recovery_score") for r in prior_rows][-RECOVERY_RANGE_DAYS:]  # day rows only (below)
        hrv = safe_float(data.get("whoop_today") or {}, "hrv")
    else:
        value, as_of, when = _f(status.get("recovery")), day, "the morning of " + day_in_words(day)
        prior = [safe_float(r, "recovery_score") for r in prior_rows if str(r.get("sk", ""))[5:15] < day][-RECOVERY_RANGE_DAYS:]
        hrv = _f(status.get("hrv"))
        unknown.append("This morning's recovery (" + day_in_words(today) + ") was not scored when this was built.")
    if value is None:
        unknown.append("Recovery: no Whoop score for " + day_in_words(day) + " or this morning.")
        return None, unknown
    text = "Recovery " + _n(value) + ", " + when + ", from Whoop."
    vals = [x for x in (_f(p) for p in prior) if x is not None]
    if len(vals) >= RECOVERY_MIN_HISTORY:
        text += " Previous " + str(len(vals)) + " mornings: " + _n(min(vals)) + " to " + _n(max(vals)) + "."
    h30 = _f(status.get("hrv_30d"))
    if hrv is not None and h30 is not None:
        text += " HRV " + _n(hrv) + " ms against a 30-day average of " + _n(h30) + "."
    m = Metric("recovery", text, "Whoop", as_of, _n(value))
    side = range_change(value, prior)
    if side:
        m.changed = "Recovery " + _n(value) + " is " + side + " the previous week's range (" + _n(min(vals)) + " to " + _n(max(vals)) + ")."
    return m, unknown


def weight_metric(data: dict, status: dict, previous: Optional[tuple]) -> tuple[Optional[Metric], list]:
    """The newest weigh-in with its date and the trend's likely range; a stale weigh-in is dropped and named.
    `previous` = (day, lb) of the weigh-in before it, or None."""
    wr = data.get("weight_recency") or {}
    w, as_of = _f(status.get("weight_lbs")), wr.get("current_weight_as_of") or status.get("weight_day")
    if w is None or not as_of:
        return None, ["Weight: no weigh-in on record for this cycle."]
    if wr.get("current_weight_is_stale"):
        return None, ["Weight: the newest weigh-in is from " + day_in_words(as_of) + ", too old to show as current."]
    text = "Weight " + _n(w, 1) + " lb on " + day_in_words(as_of) + ", from Withings."
    m = Metric("weight", "", "Withings", as_of, _n(w, 1))
    if previous and _f(previous[1]) is not None:
        delta = w - float(previous[1])
        if abs(delta) >= 0.05:
            text += (
                " "
                + _n(abs(delta), 1)
                + " lb"
                + (" up" if delta > 0 else " down")
                + " on "
                + day_in_words(previous[0], weekday=False)
                + "."
            )
        if abs(delta) >= WEIGHT_DAY_NOISE_LB:
            m.changed = (
                "Weight is "
                + _n(abs(delta), 1)
                + " lb "
                + ("up" if delta > 0 else "down")
                + " on the previous weigh-in, beyond the "
                + _n(WEIGHT_DAY_NOISE_LB, 0)
                + " lb day-to-day range."
            )
    rate, lo, hi = _f(status.get("weekly_rate_lbs")), _f(status.get("rate_ci_low")), _f(status.get("rate_ci_high"))
    if rate is not None:
        text += " Trend " + _signed(rate) + " lb a week"
        if lo is not None and hi is not None:
            text += " (likely " + _signed(lo) + " to " + _signed(hi) + ")"
        text += ", provisional." if status.get("rate_provisional") else "."
    m.text = text
    return m, []


def training_metric(data: dict, status: dict, previous_acwr: Optional[float]) -> tuple[Optional[Metric], list]:
    """The data day's sessions (the platform's one session count) and the load ratio, labelled with its day."""
    day = data.get("date") or ""
    n = status.get("sessions")
    if n is None:
        return None, ["Training: the sessions for " + day_in_words(day) + " could not be read."]
    sources = [s for s, k in (("Hevy", "hevy"), ("Strava", "strava")) if data.get(k)]
    src = " and ".join(sources) or "the training log"
    if n == 0:
        src = src if sources else "Hevy and Strava"
        text = "Training on " + day_in_words(day) + ": no session recorded in " + src + "."
    else:
        text = "Training on " + day_in_words(day) + ": " + str(n) + " session" + ("" if n == 1 else "s") + ", "
        text += _n(_f(status.get("minutes")) or 0) + " min, from " + src + "."
    cm = data.get("computed_metrics") or {}
    acwr = _f(status.get("acwr"))
    m = Metric("training", text, src, day, str(n))
    if acwr is not None and str(cm.get("acwr_zone") or "") != REBASELINING:
        m.text += " Load ratio " + _n(acwr, 2) + " (the platform's band: " + _n(LOAD_BAND[0], 1) + " to " + _n(LOAD_BAND[1], 1) + ")."
        outside = not (LOAD_BAND[0] <= acwr <= LOAD_BAND[1])
        was_inside = previous_acwr is not None and LOAD_BAND[0] <= previous_acwr <= LOAD_BAND[1]
        if outside and was_inside:
            m.changed = (
                "The load ratio moved out of the " + _n(LOAD_BAND[0], 1) + " to " + _n(LOAD_BAND[1], 1) + " band, to " + _n(acwr, 2) + "."
            )
    elif not cm:
        return m, ["Training load: not computed for " + day_in_words(day) + "."]
    return m, []


# ── verified critical alerts ─────────────────────────────────────────────────────────────────────────────────────


def critical_alerts(data: dict, owner_rhythm=None) -> list:
    """The verified critical alerts for the data day (see the module constants for the definition)."""
    day = (data or {}).get("date") or ""
    out = []
    cm = (data or {}).get("computed_metrics") or {}
    acwr = _f(cm.get("acwr"))
    if cm.get("acwr_alert") and str(cm.get("acwr_zone") or "") in LOAD_ALERT_ZONES and acwr is not None:
        word = "very high" if str(cm.get("acwr_zone")) == "danger" else "elevated"
        out.append(
            Alert(
                "training_load",
                [
                    "Training-load alert: the load ratio for "
                    + day_in_words(day)
                    + " is "
                    + _n(acwr, 2)
                    + ", above the "
                    + _n(LOAD_BAND[1], 1)
                    + " the platform's rule treats as "
                    + word
                    + " injury risk."
                ],
            )
        )
    an = (data or {}).get("anomaly") or {}
    flagged = [m for m in an.get("anomalous_metrics") or [] if isinstance(m, dict)]
    body = [m for m in flagged if str(m.get("field") or "") in ANOMALY_PHYSIOLOGICAL_FIELDS]
    if str(an.get("severity") or "") in ANOMALY_ALERT_SEVERITIES and len(body) >= ANOMALY_MIN_PHYSIOLOGICAL:
        labels = [str(m.get("label") or m.get("field") or "a metric") for m in body + [m for m in flagged if m not in body]][:4]
        n_src = len({str(m.get("source")) for m in flagged})
        out.append(
            Alert(
                "anomaly",
                [
                    "Anomaly alert from the anomaly detector: "
                    + str(len(flagged))
                    + " metrics across "
                    + str(n_src)
                    + " sources were outside their usual range on "
                    + day_in_words(day)
                    + (" (" + ", ".join(labels) + ")." if labels else ".")
                ],
            )
        )
    lines = [str(x) for x in owner_rhythm or []]
    # an event DATED the data day (the episode list after "newest first"), never just the window's end date
    if day and any(x.startswith(RHYTHM_EVENTS_PREFIX) and (day + " ") in x.split("newest first", 1)[-1] for x in lines):
        out.append(Alert("heart_rhythm", ["Heart rhythm (owner-only device records):"] + lines))
    return out


# ── recommendations ──────────────────────────────────────────────────────────────────────────────────────────────


def select_recs(recs: list, changed_metrics: dict, persona: tuple) -> tuple[list, dict]:
    """(shown, counts) from the hybrid's labelled recs (brief_hybrid.Rec). Coaching recs only (food-export housekeeping
    becomes a Not-known-yet line). A NEW rec is shown; a REPEAT only when its evidence metric changed today (§6);
    a rec naming a persona or reading a score as clearance is dropped. Capped at REC_CEILING, NEW first."""
    shown, counts = [], {"repeats_suppressed": 0, "dropped_voice": 0, "dropped_clearance": 0}
    for r in recs:
        if getattr(r, "kind", "") != "coaching" or getattr(r, "source", "") == "readiness":
            continue
        if names_a_persona(r.text, persona):
            counts["dropped_voice"] += 1
            continue
        if CLEARANCE_RE.search(r.text):
            counts["dropped_clearance"] += 1
            continue
        because = None
        if r.status == "REPEAT":
            metric = EVIDENCE_OF.get(r.key)
            if metric and changed_metrics.get(metric):
                because = changed_metrics[metric]
            else:
                counts["repeats_suppressed"] += 1
                continue
        shown.append(CompactRec(r.key, _LEADING_MARKS.sub("", r.text), r.status, r.rec_id, because))
    shown.sort(key=lambda c: c.status != "NEW")
    return shown[:REC_CEILING], counts


# ── the view ─────────────────────────────────────────────────────────────────────────────────────────────────────


def build(
    *,
    data: dict,
    status: dict,
    recs: list,
    alerts: list,
    food_pending: bool,
    food_unknown: bool,
    previous_weight: Optional[tuple],
    previous_acwr: Optional[float],
    site_url: str,
    persona: tuple,
) -> CompactView:
    """Pure assembly from already-read inputs (the tests drive this directly)."""
    day = data.get("date") or ""
    unknown, pending = [], []
    metrics = []
    for m, u in (recovery_metric(data, status), weight_metric(data, status, previous_weight), training_metric(data, status, previous_acwr)):
        unknown += u
        if m is not None:
            metrics.append(m)
    if food_pending:
        pending.append("food")
        last = status.get("last_arrival_day")
        unknown.insert(
            0,
            "Food for "
            + day_in_words(day)
            + ": the MacroFactor export has not arrived"
            + (" (the last one landed " + day_in_words(last, weekday=False) + ")" if last else "")
            + ". This is data on its way, so the day grade stays provisional. If you logged that day, export when convenient.",
        )
    elif food_unknown:
        pending.append("food")
        unknown.insert(0, "Food for " + day_in_words(day) + ": whether its export has arrived could not be read.")
    changed_by = {m.key: m.changed for m in metrics if m.changed}
    shown, counts = select_recs(recs, changed_by, persona)
    first_change = next((m.changed for m in metrics if m.changed), None)
    decision = next((r for r in shown if r.status == "NEW"), None) or (shown[0] if shown else None)
    if alerts:
        lead, kind = (
            "The alert above is the one thing to look at today." if len(alerts) == 1 else "The alerts above come first today."
        ), "alert"
    elif decision is not None:
        lead, kind = decision.text, "decision"
        shown = [decision] + [r for r in shown if r is not decision]  # the decision leads; it is not repeated below
    elif unknown:
        lead, kind = "No decision is needed from the data in hand; some of it is not known yet.", "unknown"
    elif first_change:
        lead, kind = "No decision is needed today.", "plain"
    else:
        lead, kind = QUIET_LEAD, "quiet"
    changed = first_change or (NO_CHANGE if not unknown else NO_CHANGE_SO_FAR)
    return CompactView(
        data_day=day,
        lead=lead,
        lead_kind=kind,
        changed=changed,
        has_change=bool(first_change),
        metrics=metrics[:METRIC_CEILING],
        recs=shown,
        alerts=alerts,
        unknown=unknown,
        detail_url=site_url.rstrip("/") + "/data/day/" + day + "/",
        pending_inputs=pending,
        **counts,
    )


# ── render ───────────────────────────────────────────────────────────────────────────────────────────────────────


def subject(view: CompactView, today_short: str) -> str:
    """Keeps the `Morning Brief | <day>` prefix (filters and the send ledger key on nothing else)."""
    if view.alerts:
        tail = str(len(view.alerts)) + " alert" + ("" if len(view.alerts) == 1 else "s")
    elif view.lead_kind == "decision":
        tail = "1 decision"
    elif view.quiet:
        tail = "Nothing changed, nothing needed"
    elif view.unknown:
        tail = "No decision · some data not in yet"
    else:
        tail = "No decision needed"
    return "Morning Brief | " + today_short + " | " + tail


def render_text(view: CompactView, today_short: str) -> str:
    """The plain-text part. Alert lines start with 'ALERT ' (the checker counts them apart from the word ceiling)."""
    out = ["Morning Brief · " + today_short, ""]
    for a in view.alerts:
        out += ["ALERT " + x for x in a.lines] + [""]
    lead_rec = view.recs[0] if view.lead_kind == "decision" and view.recs else None
    out += [view.lead] + (["Shown again because: " + lead_rec.changed_because] if lead_rec and lead_rec.changed_because else [])
    out += [""] if view.quiet else ["", "What changed: " + view.changed, ""]
    out += ["• " + m.text for m in view.metrics]
    for r in [x for x in view.recs if x is not lead_rec]:
        out += ["", "Recommendation: " + r.text] + (["Shown again because: " + r.changed_because] if r.changed_because else [])
    if view.follow_up:
        out += ["", "Follow-up due: " + str(view.follow_up.get("text") or "")]
    if view.respond_url and view.respond_rec is not None:
        out += ["Your answer (optional): " + view.respond_url]
    if view.unknown:
        out += ["", "Not known yet:"] + ["• " + u for u in view.unknown]
    out += ["", "The day in full: " + view.detail_url, NOT_MEDICAL]
    return "\n".join(out)


_C = {
    "outer": "margin:0;padding:0;background:#f4f4f6;",
    "card": "max-width:560px;width:100%;background:#ffffff;border-radius:10px;",
    "pad": "padding:20px 22px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f2933;",
    "head": "font-size:12px;color:#6b7280;margin:0 0 12px;letter-spacing:0.3px;",
    "lead": "font-size:17px;font-weight:700;line-height:1.4;margin:0 0 12px;color:#111827;",
    "p": "font-size:15px;line-height:1.5;margin:0 0 10px;",
    "h": "font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:0.6px;margin:16px 0 6px;",
    "alert": "font-size:15px;line-height:1.5;margin:0 0 12px;padding:10px 12px;background:#fef2f2;border-left:3px solid #dc2626;color:#7f1d1d;",
    "small": "font-size:13px;line-height:1.45;color:#4b5563;margin:0 0 6px;",
    "link": "color:#1d4ed8;text-decoration:underline;word-break:break-all;",
}


def render_html(view: CompactView, today_short: str) -> str:
    """The whole email: a centred single-column table, inline styles only (what mail clients keep)."""
    body = '<p style="' + _C["head"] + '">Morning Brief · ' + esc(today_short) + "</p>"
    for a in view.alerts:
        body += '<div data-alert="' + esc(a.kind) + '" style="' + _C["alert"] + '">' + "<br>".join(esc(x) for x in a.lines) + "</div>"
    lead_rec = view.recs[0] if view.lead_kind == "decision" and view.recs else None
    body += '<p data-lead="' + view.lead_kind + '"' + (_rec_attrs(lead_rec) if lead_rec else "") + ' style="' + _C["lead"] + '">'
    body += esc(view.lead) + (_because(lead_rec) if lead_rec else "") + "</p>"
    if not view.quiet:  # on a quiet day the lead already says nothing changed; once is enough
        changed_attr = ' data-changed="1"' if view.has_change else ""
        body += '<p data-what-changed=""' + changed_attr + ' style="' + _C["p"] + '"><b>What changed.</b> ' + esc(view.changed) + "</p>"
    if view.metrics:
        body += '<p style="' + _C["h"] + '">The numbers</p>'
    for m in view.metrics:
        body += (
            '<p data-metric="'
            + m.key
            + '" data-source="'
            + esc(m.source)
            + '" data-as-of="'
            + esc(m.as_of)
            + '" data-q="'
            + m.key
            + '" data-v="'
            + esc(m.value)
            + '"'
            + (' data-changed="1"' if m.changed else "")
            + ' style="'
            + _C["p"]
            + '">'
            + esc(m.text)
            + "</p>"
        )
    rest = [r for r in view.recs if r is not lead_rec]
    if rest:
        body += '<p style="' + _C["h"] + '">' + ("Also worth doing" if lead_rec else "Recommendation") + "</p>"
    for r in rest:
        body += "<p" + _rec_attrs(r) + ' style="' + _C["p"] + '">' + esc(r.text) + _because(r) + "</p>"
    if view.follow_up:
        body += (
            '<p data-rec="follow_up" data-status="FOLLOW_UP" style="'
            + _C["p"]
            + '">Follow-up due: '
            + esc(str(view.follow_up.get("text") or ""))
            + "</p>"
        )
    if view.respond_note:
        body += '<p style="' + _C["small"] + '">' + esc(view.respond_note) + "</p>"
    if view.respond_url and view.respond_rec is not None:
        body += '<p style="' + _C["small"] + '"><a data-respond="" style="' + _C["link"] + '" href="' + esc(view.respond_url) + '">'
        body += "Answer (optional): done / not doing it / still deciding</a></p>"
    if view.unknown:
        body += '<p style="' + _C["h"] + '">Not known yet</p>'
        for u in view.unknown:
            body += '<p data-unknown="" style="' + _C["small"] + '">' + esc(u) + "</p>"
    body += (
        '<p style="'
        + _C["p"]
        + 'margin-top:14px;">The day in full: <a data-detail-link="" style="'
        + _C["link"]
        + '" href="'
        + esc(view.detail_url)
        + '">'
        + esc(view.detail_url.split("://", 1)[-1])
        + "</a></p>"
    )
    body += '<p style="' + _C["small"] + 'margin-top:10px;">' + NOT_MEDICAL + "</p>"
    return _frame(body)


def _rec_attrs(r: CompactRec) -> str:
    return (
        ' data-rec="'
        + esc(r.rec_id)
        + '" data-rec-key="'
        + esc(r.key)
        + '" data-status="'
        + r.status
        + '"'
        + (' data-changed-because="1"' if r.changed_because else "")
    )


def _because(r: CompactRec) -> str:
    return (" <i>Shown again because: " + esc(r.changed_because) + "</i>") if r.changed_because else ""


def _frame(body: str) -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Morning Brief</title></head>"
        '<body style="' + _C["outer"] + '">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="' + _C["outer"] + '"><tr>'
        '<td align="center" style="padding:12px 8px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="' + _C["card"] + '"><tr>'
        '<td style="' + _C["pad"] + '">' + body + "</td></tr></table></td></tr></table></body></html>"
    )


# ── the failure notice (owner ruling §4) ─────────────────────────────────────────────────────────────────────────

FALLBACK_LEAD = "Today's Morning Brief could not be prepared."


def fallback_subject(today_short: str) -> str:
    return "Morning Brief | " + today_short + " | Not prepared today"


def fallback_text(data_day: str, alerts: Optional[list], detail_url: str, today_short: str) -> str:
    out = ["Morning Brief · " + today_short, "", FALLBACK_LEAD, "This is a failure notice, not a brief: nothing here summarises your day."]
    if alerts is None:
        out += ["", "The alert check could not run either."]
    elif alerts:
        out += ["", "Verified alerts for " + day_in_words(data_day) + ":"]
        for a in alerts:
            out += ["ALERT " + x for x in a.lines]
    else:
        out += ["", "No verified alert was found for " + day_in_words(data_day) + "."]
    out += ["", "The day's data: " + detail_url, "The failure is recorded for the platform to fix."]
    return "\n".join(out)


def fallback_html(data_day: str, alerts: Optional[list], detail_url: str, today_short: str) -> str:
    """Short, factual, unmistakably not a brief: no metric, no recommendation, no lead that reads as a normal day."""
    body = '<p style="' + _C["head"] + '">Morning Brief · ' + esc(today_short) + "</p>"
    body += '<p data-fallback="" style="' + _C["lead"] + '">' + esc(FALLBACK_LEAD) + "</p>"
    body += '<p style="' + _C["p"] + '">This is a failure notice, not a brief: nothing here summarises your day.</p>'
    if alerts is None:
        body += '<p style="' + _C["p"] + '">The alert check could not run either.</p>'
    elif alerts:
        body += '<p style="' + _C["p"] + '">Verified alerts for ' + esc(day_in_words(data_day)) + ":</p>"
        for a in alerts:
            body += '<div data-alert="' + esc(a.kind) + '" style="' + _C["alert"] + '">' + "<br>".join(esc(x) for x in a.lines) + "</div>"
    else:
        body += '<p style="' + _C["p"] + '">No verified alert was found for ' + esc(day_in_words(data_day)) + ".</p>"
    body += (
        '<p style="'
        + _C["p"]
        + '">The day\'s data: <a data-detail-link="" style="'
        + _C["link"]
        + '" href="'
        + esc(detail_url)
        + '">'
        + esc(detail_url.split("://", 1)[-1])
        + "</a></p>"
    )
    body += '<p style="' + _C["small"] + '">The failure is recorded for the platform to fix.</p>'
    return _frame(body)
