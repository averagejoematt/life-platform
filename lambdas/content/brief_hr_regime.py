"""The daily brief's reading of the HR regime markers (#5029).

`health.hr_regime` is THE registry of dated heart-rate regime markers (#4999). Inside a marker's
re-baselining window no green / yellow / red label may be drawn from a heart-rate-derived number
(Whoop recovery, HRV, RHR, HR-weighted load). This module is where the brief's renderer
(`content.html_builder`) and its dashboard JSON (`content.output_writers`) ask that question, so
both answer it the same way. Protective flags are never withheld here: an ACWR alert keeps its red.

Pure module: no I/O, no clock — every function takes the day it reasons about.
"""

from __future__ import annotations

from common.digest_utils import safe_float
from health import hr_regime

REBASELINING_GREY = "#94a3b8"
# The scorecard tiles computed from heart rate (Whoop recovery = HRV + RHR).
HR_DERIVED_SCORE_TILES = frozenset({"Recovery"})

_R_COLORS = {"green": "#22c55e", "yellow": "#f59e0b", "red": "#ef4444", "gray": "#64748b", hr_regime.REBASELINING: REBASELINING_GREY}
_R_LABELS = {"green": "GO", "yellow": "MODERATE", "red": "EASY DAY", "gray": "NO DATA", hr_regime.REBASELINING: "RE-BASELINING"}
_R_EMOJIS = {"green": "🟢", "yellow": "🟡", "red": "🔴", "gray": "⚪", hr_regime.REBASELINING: "⚪"}
_R_RECS = {
    "green": "System is ready. Hard training or high-focus work OK.",
    "yellow": "Moderate effort day. Zone 2 or moderate strength.",
    "red": "Recovery day. Walk, stretch, or easy Zone 2 only.",
    "gray": "No readiness data available.",
    hr_regime.REBASELINING: (
        "Heart-rate numbers are re-baselining after the HR regime marker — no green/yellow/red is drawn from them. "
        "Train to the standing constraint, not to these numbers."
    ),
}


def rebaselining(data) -> bool:
    """Is the brief's data day inside an HR regime marker's re-baselining window?

    True on the registry's own reading of `data["date"]`, or when the stored computed_metrics
    row already says so (`readiness_state`, written by daily-metrics-compute, #4999)."""
    cm = (data or {}).get("computed_metrics") or {}
    return cm.get("readiness_state") == hr_regime.REBASELINING or hr_regime.is_rebaselining((data or {}).get("date"))


def score_tile(label, score, rebase) -> tuple[str, str]:
    """(colour, text) of one scorecard tile. An HR-derived tile inside the window draws no colour
    claim; every other tile keeps the 80 / 60 bands unchanged."""
    if rebase and label in HR_DERIVED_SCORE_TILES:
        return REBASELINING_GREY, "re-baselining"
    if score is None:
        return "#475569", "—"
    return ("#22c55e" if score >= 80 else "#f59e0b" if score >= 60 else "#ef4444"), str(score)


def hrv_line_suffix(rebase) -> str:
    return " · re-baselining after the HR regime marker" if rebase else ""


def acwr_colour(acwr_val, acwr_alert, data) -> str:
    """The brief's ACWR line colour. Inside the window a non-alert ratio is grey (no safe-green or
    detraining-amber claim); an alert (ACWR > 1.3) keeps its red — nothing protective is withheld."""
    av = float(acwr_val)
    if acwr_alert:
        return "#ef4444"
    if rebaselining(data):
        return REBASELINING_GREY
    return "#f59e0b" if av > 1.3 or av < 0.8 else "#22c55e"


def readiness_signal_html(data, readiness_colour) -> str:
    """The brief's READINESS SIGNAL section. Inside the window daily-metrics-compute stores no
    readiness score ("gray" + `readiness_state`): the card says RE-BASELINING, never NO DATA."""
    key = hr_regime.REBASELINING if rebaselining(data) else readiness_colour
    out = (
        "<!-- S:readiness -->"
        '<div style="background:#1e293b;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
        '<div style="display:flex;align-items:center;gap:12px;">'
        '<div style="background:rgba(0,0,0,0.3);border-radius:50%;width:48px;height:48px;'
        'display:flex;align-items:center;justify-content:center;font-size:24px;">' + _R_EMOJIS.get(key, "⚪") + "</div>"
        '<div><p style="color:#94a3b8;font-size:10px;margin:0;font-weight:700;">READINESS SIGNAL</p>'
        '<p style="color:'
        + _R_COLORS.get(key, "#64748b")
        + ';font-size:20px;font-weight:700;margin:2px 0;">'
        + _R_LABELS.get(key, "—")
        + "</p>"
        '<p style="color:#64748b;font-size:11px;margin:0;">' + _R_RECS.get(key, "") + "</p>"
        "</div></div>"
    )
    whoop = data.get("whoop") or {}
    recovery = safe_float(whoop, "recovery_score")
    strain = safe_float(whoop, "strain")
    rhr = safe_float(whoop, "resting_heart_rate")
    if recovery or strain or rhr:
        out += '<div style="margin-top:10px;display:flex;gap:16px;">'
        for r_label, r_val in [
            ("Recovery", str(round(recovery)) + "%" if recovery else "—"),
            ("Strain", str(round(strain, 1)) if strain else "—"),
            ("RHR", str(round(rhr)) + " bpm" if rhr else "—"),
        ]:
            out += (
                '<div><p style="color:#e2e8f0;font-size:14px;font-weight:600;margin:0;">' + r_val + "</p>"
                '<p style="color:#475569;font-size:9px;margin:0;">' + r_label + "</p></div>"
            )
        out += "</div>"
    return out + "</div><!-- /S:readiness -->"


def dashboard_readiness(readiness_score, readiness_colour, day) -> dict:
    """dashboard/data.json's `readiness` block. Inside the window: colour "gray", label
    "Re-baselining" (not "No Data") and no HR-derived training recommendation."""
    if hr_regime.is_rebaselining(day):
        return {"score": readiness_score, "color": "gray", "label": "Re-baselining", "training_rec": ""}
    recs = {"green": "Hard workout OK · Follow today's plan", "yellow": "Moderate effort · Zone 2 or easy strength"}
    recs["red"] = "Active recovery only · Walk, yoga, stretch"
    labels = {"green": "Go", "yellow": "Moderate", "red": "Easy", "gray": "No Data"}
    return {
        "score": readiness_score,
        "color": readiness_colour,
        "label": labels.get(readiness_colour, "—"),
        "training_rec": recs.get(readiness_colour, ""),
    }
