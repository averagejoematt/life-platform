"""emails/sunday_what_changed.py — the Sunday "what changed and what matters" owner email (#6176, item 1).

THE RULING (owner, 2026-11-22, section 9): one Sunday communication replaces the Sunday Weekly Report and the Monday
Compass. It carries AT MOST one decision, what changed this week against last, and an advice-status section that
reads honestly. One direct analytical voice — no board, no named coaches, no model call: every sentence below is
built by code from numbers already read by the weekly digest's ``gather_all``.

RULES THE RENDER KEEPS
  * at most one decision; when there is none it says "Nothing new needs you this week";
  * a metric with no reading in a week says so — it is listed under UNKNOWN, never shown as 0;
  * "changed" means the week-on-week move is at least the metric's stated threshold (``METRICS``); everything else is
    "did not change", with both numbers shown, so the reader can disagree with the threshold;
  * advice status comes ONLY from ``emails.advice_status`` (what he recorded); nothing is inferred from sensor,
    training or food data, and an empty record reads "not recorded";
  * no calorie target is stated: the owner has that question open (ruling 2026-11-22 section 10), so the food line
    reports what was logged and nothing about a target.

PURE: no table, no clock, no AWS. ``build(data, advice)`` returns ``{"subject", "text", "html"}``.
"""

from __future__ import annotations

import html as _html
from typing import Any, Callable, Optional

#: (key, label, getter, unit, decimals, threshold, source) — one row per metric. A getter reads one week's block.
Getter = Callable[[dict], Optional[float]]


def _g(*path: str) -> Getter:
    def get(week: dict) -> Optional[float]:
        cur: Any = week
        for p in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        try:
            return None if cur is None else float(cur)
        except (TypeError, ValueError):
            return None

    return get


def _workouts(week: dict) -> Optional[float]:
    w = week.get("mf_workouts")
    if not isinstance(w, dict):
        return None
    return float(w.get("workout_count") or 0)


METRICS: tuple = (
    ("weight", "Weight (weekly mean)", _g("withings", "weight_avg"), " lb", 1, 1.0, "Withings"),
    ("recovery", "Recovery (mean)", _g("whoop", "recovery_avg"), "%", 0, 5.0, "Whoop"),
    ("hrv", "HRV (mean)", _g("whoop", "hrv_avg"), " ms", 1, 3.0, "Whoop"),
    ("rhr", "Resting heart rate (mean)", _g("whoop", "rhr_avg"), " bpm", 0, 2.0, "Whoop"),
    ("sleep", "Sleep (mean)", _g("sleep", "duration_avg_hrs"), " h", 1, 0.3, "Whoop"),
    ("lifting", "Lifting sessions", _workouts, "", 0, 1.0, "Hevy"),
    ("steps", "Steps (daily mean)", _g("apple", "steps_avg"), "", 0, 1000.0, "Apple Health"),
    ("calories", "Food logged (daily mean)", _g("macrofactor", "calories_avg"), " kcal", 0, 100.0, "MacroFactor"),
    ("protein", "Protein logged (daily mean)", _g("macrofactor", "protein_avg_g"), " g", 0, 10.0, "MacroFactor"),
    ("habits", "Essential habits (daily mean)", _g("habitify", "mvp_avg_pct"), "%", 0, 5.0, "Habitify"),
)


def _fmt(v: Optional[float], unit: str, dec: int) -> str:
    if v is None:
        return "no reading"
    s = f"{v:,.{dec}f}" if dec else f"{round(v):,}"
    return f"{s}{unit}"


def _delta(cur: float, prev: float, unit: str, dec: int) -> str:
    # The move between the two numbers AS PRINTED, so the line never reads "52 → 53 (+0)".
    d = round(round(cur, dec) - round(prev, dec), dec)
    if d == 0:
        return "no change"
    sign = "+" if d > 0 else "−"
    mag = f"{abs(d):,.{dec}f}" if dec else f"{round(abs(d)):,}"
    return f"{sign}{mag}{unit}"


def compare(this: dict, prior: dict) -> dict:
    """Pure: split METRICS into changed / unchanged / unknown lines for this week vs last."""
    changed, unchanged, unknown = [], [], []
    for key, label, get, unit, dec, threshold, source in METRICS:
        cur, prev = get(this or {}), get(prior or {})
        if cur is None:
            unknown.append(f"{label}: no {source} reading this week" + ("" if prev is None else f" (last week {_fmt(prev, unit, dec)})"))
            continue
        if prev is None:
            unknown.append(f"{label}: {_fmt(cur, unit, dec)} this week; no {source} reading last week to compare")
            continue
        line = f"{label}: {_fmt(prev, unit, dec)} → {_fmt(cur, unit, dec)} ({_delta(cur, prev, unit, dec)})"
        (changed if abs(cur - prev) >= threshold else unchanged).append(line)
    return {"changed": changed, "unchanged": unchanged, "unknown": unknown}


def food_log_note(this: dict) -> Optional[str]:
    """How many days carry a food log — the honest limit on every food number above."""
    mf = (this or {}).get("macrofactor")
    if not isinstance(mf, dict):
        return None
    n = mf.get("days_logged")
    if n is None:
        return None
    return f"Food was logged on {int(n)} of 7 days. Whether everything eaten was logged is not known."


_STATE_WORDS = {
    "acted_on": "acted on",
    "declined": "declined",
    "partially_followed": "partly followed",
    "unknown": "no state recorded",
}


def _states(counts: dict) -> str:
    parts = [f"{_STATE_WORDS.get(k, k)} {v}" for k, v in sorted(counts.items()) if v]
    return ", ".join(parts)


def advice_lines(advice: dict) -> list[str]:
    """Pure: the ADVICE STATUS section, from ``emails.advice_status.read``'s dict. Never inferred."""
    if not advice or not advice.get("readable"):
        return ["Advice status could not be read this week, so none is shown. Nothing here is a zero."]
    lines = [
        "Morning Brief recommendations: not recorded. No store links a brief item to your answer yet.",
        f"Decisions you logged: {advice.get('decisions_this_week', 0)} this week, {advice.get('decisions_last_week', 0)} last week.",
    ]
    linked = advice.get("linked_decisions") or 0
    if linked:
        lines.append(f"Linked by you to a coach recommendation: {_states(advice.get('linked_states') or {})}. The rest: not recorded.")
    else:
        lines.append("Linked by you to a coach recommendation: none recorded.")
    answered = advice.get("ask_answers_this_week") or {}
    if answered:
        lines.append(f"Coach asks you answered this week: {_states(answered)}.")
    else:
        lines.append("Coach asks you answered this week: none recorded.")
    lines.append("Only what you recorded counts here; nothing is inferred from sensor, training or food data.")
    return lines


def decision_lines(advice: dict) -> list[str]:
    od = (advice or {}).get("open_decision") if (advice or {}).get("readable") else None
    if not od:
        return ["Nothing new needs you this week."]
    return [
        f"You marked a {od.get('coach_id')} ask ({od.get('ask_id')}) 'not yet decided' on {od.get('since')}.",
        "The call: act on it or decline it, and record which (log_advice_link in a Claude session). "
        "It stays here until you do. This is the only decision in this email.",
    ]


def build(data: dict, advice: dict, *, week_number: Optional[int] = None) -> dict:
    """Pure: the Sunday email from ``gather_all``'s data dict and ``advice_status.read``'s dict."""
    dates = data.get("dates") or {}
    cmp_ = compare(data.get("this") or {}, data.get("prior") or {})
    decision = decision_lines(advice)
    food = food_log_note(data.get("this") or {})
    unknown = list(cmp_["unknown"]) + ([food] if food else [])

    week = f"Week {week_number}: " if week_number else ""
    if (advice or {}).get("readable") and (advice or {}).get("open_decision"):
        lead = "one decision"
    else:
        lead = "nothing new needs you"
    n_changed = len(cmp_["changed"])
    subject = f"{week}{lead}; {n_changed} measure{'s' if n_changed != 1 else ''} changed this week"

    period = f"{dates.get('this_start', '?')} → {dates.get('this_end', '?')}, against {dates.get('prior_start', '?')} → {dates.get('prior_end', '?')}"
    sections = [
        ("ONE DECISION", decision),
        ("WHAT CHANGED (this week vs last)", cmp_["changed"] or ["Nothing moved past its threshold this week."]),
        ("WHAT DID NOT CHANGE", cmp_["unchanged"] or ["Nothing: every measure with two weeks of readings moved."]),
        ("ADVICE STATUS", advice_lines(advice)),
        ("UNKNOWN", unknown or ["Nothing: every measure has a reading in both weeks."]),
    ]
    footer = (
        f"Weeks: {period}. Sources: Withings, Whoop, Hevy, Apple Health, MacroFactor, Habitify and your decisions record, "
        "read-only. A measure counts as changed when it moved at least: weight 1 lb, recovery 5 points, HRV 3 ms, "
        "resting heart rate 2 bpm, sleep 0.3 h, lifting 1 session, steps 1,000, food 100 kcal, protein 10 g, habits 5 points. "
        "This email replaces the Sunday Weekly Report and the Monday Compass for a two-week trial (#6176)."
    )

    text_parts = []
    for title, lines in sections:
        text_parts.append(title)
        text_parts.extend(f"• {ln}" for ln in lines)
        text_parts.append("")
    text_parts.append("———")
    text_parts.append(footer)
    text = "\n".join(text_parts)

    esc = _html.escape
    blocks = []
    for title, lines in sections:
        items = "".join(f'<li style="margin:0 0 6px 0;">{esc(ln)}</li>' for ln in lines)
        blocks.append(
            f'<h2 style="font-size:13px;letter-spacing:.06em;color:#374151;margin:22px 0 8px 0;">{esc(title)}</h2>'
            f'<ul style="margin:0;padding-left:18px;color:#111827;font-size:15px;line-height:1.5;">{items}</ul>'
        )
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="color-scheme" content="light">'
        '</head><body style="margin:0;padding:24px;background:#ffffff;font-family:-apple-system,Arial,sans-serif;">'
        f'<div style="max-width:640px;margin:0 auto;">'
        f'<p style="color:#6b7280;font-size:12px;margin:0 0 4px 0;">{esc(period)}</p>'
        + "".join(blocks)
        + f'<p style="color:#6b7280;font-size:12px;margin:28px 0 0 0;border-top:1px solid #e5e7eb;padding-top:12px;">{esc(footer)}</p>'
        "</div></body></html>"
    )
    return {"subject": subject, "text": text, "html": html, "sections": {t: list(ls) for t, ls in sections}}
