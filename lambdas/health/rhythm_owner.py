"""health/rhythm_owner.py — the owner-only heart-rhythm READ: event trend, episodes, ECG results (#4972 part 2,
folded from #4977 by owner ruling 2026-10-30; epic #4967).

WHAT IT IS
  The channel (`health.rhythm_channel`) stores watch ECG results, heart-rate notifications and the medication log
  as owner-only rows. This module turns them into numbers and lines for the owner and NOBODY else:

    * ``summarize``   — counts per family/kind in the current window against the window before it, the dated
                        episodes in the current window, ECG results by the device's own label;
    * ``owner_lines`` — the daily brief's owner-only section (``emails.brief_lines.rhythm_lines``);
    * ``coach_block`` — the same lines with the no-advice instruction, shaped for the owner's own Telegram coach
                        thread (the wiring into ``coach.coach_domain_facts`` is a hand-off — see #4972);
    * ``burden_change`` — the reader a later burden-rise alert consumes (the hypothesis engine, a follow-up): a
                        window-vs-window count with n, both windows' bounds, worn-day coverage when supplied and
                        the stated confounders. It decides nothing; the alert's threshold is the caller's.

  "Burden" here is the EVENT burden — how many notifications / recordings the device produced in a window. The
  watch's AFib History percentage is not ingested (no HAE mapping), so no percentage is claimed (ADR-104).

PRIVACY (owner ruling (c), 2026-10-17: heart-rhythm data is owner-only)
  The input is ``rhythm_channel.read_events`` — neutral events with no medication name or dose, no device and no
  reading. The ONLY importers are the owner surfaces in ``tests/test_rhythm_owner_4972.py::PERMITTED_IMPORTERS``;
  no public route, generated file, published prompt or log line ever carries an output of this module. Logs name
  the exception class only.

WORDING (ADR-104/105)
  Events and trends are reported as data — counts with their window, dates, the device's own result label. Never
  an interpretation, a diagnosis, a dose comment or reassurance. The one advice string is ``CLINICIAN_LINE``.

Pure core (no I/O, no clock — ``today`` is always passed in) + one fail-soft read (``read_summary``).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
MAX_EPISODES = 6

# The ONE advice string any rhythm surface may carry (#4972: "no clinical advice beyond 'discuss with your
# clinician'"). tests/test_rhythm_owner_4972.py holds every rendered line to it.
ADVICE = "discuss with your clinician"
CLINICIAN_LINE = f"Questions about these records: {ADVICE}."
HEADER = "HEART RHYTHM EVENTS (owner-only device records — never repeat them in anything that may be published)"
COACH_INSTRUCTION = (
    "Report these as data only: counts, dates and the device's own result labels. Do not interpret them, diagnose, "
    "reassure, or comment on any medication or dose. The only advice you may give about them is: "
    f"{ADVICE}."
)

KIND_LABELS = {
    "irregular": "irregular-rhythm notifications",
    "high": "high heart-rate notifications",
    "low": "low heart-rate notifications",
    "hypertension": "hypertension notifications",
    "unknown": "unclassified heart-rate notifications",
}
_KIND_ORDER = ("irregular", "high", "low", "hypertension", "unknown")

# What a burden-rise alert must state beside the number (#4972 box 2): reasons a count can move that are not the
# heart. In-channel ones are computed by ``burden_change``; the rest are named for the alert to read or disclose.
CONFOUNDERS = (
    "watch wear time (a night without the watch records no events — absence, not zero)",
    "medication-log changes between the two windows",
    "alcohol",
    "short or disrupted sleep",
    "illness or the overload triad",
    "training load",
    "a change in the watch's notification settings or software",
)


# ── pure helpers ─────────────────────────────────────────────────────────────


def _d(text: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None


def _window(end: date, window_days: int, offset: int = 0) -> tuple[date, date]:
    """(start, end) inclusive, ``offset`` whole windows before the one ending on ``end``."""
    last = end - timedelta(days=window_days * offset)
    return last - timedelta(days=window_days - 1), last


def _in(event: dict, bounds: tuple[date, date]) -> bool:
    d = _d(event.get("day"))
    return d is not None and bounds[0] <= d <= bounds[1]


def _counts(events: Iterable[dict], bounds: tuple[date, date]) -> dict:
    out: dict = {
        "start": bounds[0].isoformat(),
        "end": bounds[1].isoformat(),
        "ecg": 0,
        "ecg_results": {},
        "notifications": {},
        "inferred": 0,
        "medication_log": 0,
        "medication_status": {},
    }
    for e in events:
        if not _in(e, bounds):
            continue
        family = e.get("family")
        if family == "ecg":
            out["ecg"] += 1
            label = e.get("result") or "no result label"
            out["ecg_results"][label] = out["ecg_results"].get(label, 0) + 1
        elif family == "notification":
            kind = e.get("kind") if e.get("kind") in KIND_LABELS else "unknown"
            out["notifications"][kind] = out["notifications"].get(kind, 0) + 1
            out["inferred"] += 1 if e.get("kind_inferred") else 0
        elif family == "medication":
            out["medication_log"] += 1
            status = e.get("status")
            if status:
                out["medication_status"][status] = out["medication_status"].get(status, 0) + 1
    return out


def summarize(events: Optional[list], today: str, window_days: int = WINDOW_DAYS) -> Optional[dict]:
    """The current window (ending ``today``, inclusive) against the one before it, or None for an unread channel."""
    end = _d(today)
    if events is None or end is None or window_days < 1:
        return None
    current, prior = _window(end, window_days), _window(end, window_days, 1)
    episodes = sorted((e for e in events if _in(e, current) and e.get("family") in ("ecg", "notification")), key=lambda e: str(e.get("at")))
    return {
        "today": end.isoformat(),
        "window_days": window_days,
        "current": _counts(events, current),
        "prior": _counts(events, prior),
        "episodes": list(reversed(episodes)),
    }


def _trend(now: int, before: int) -> str:
    if now > before:
        return f"up from {before}"
    if now < before:
        return f"down from {before}"
    return f"the same as the {before} before"


def _results_text(results: dict) -> str:
    return ", ".join(f"'{label}' x{n}" for label, n in sorted(results.items(), key=lambda kv: (-kv[1], kv[0])))


def _episode_text(e: dict) -> str:
    when = str(e.get("at") or e.get("day")).replace("T", " ")[:16]
    if e.get("family") == "ecg":
        return f"{when} ECG recording, device result '{e.get('result') or 'no result label'}'"
    kind = str(e.get("kind"))
    label = KIND_LABELS.get(kind, KIND_LABELS["unknown"])[: -len("s")]  # singular
    return f"{when} {label}" + (" (kind inferred from the reading, not named by the device)" if e.get("kind_inferred") else "")


def owner_lines(summary: Optional[dict]) -> list:
    """The owner-only lines: data, n and window on every count; the clinician line only when there are events."""
    if not summary:
        return []
    cur, pri, w = summary["current"], summary["prior"], summary["window_days"]
    span = f"in the {w} days to {cur['end']}"
    n_cur = cur["ecg"] + sum(cur["notifications"].values()) + cur["medication_log"]
    n_pri = pri["ecg"] + sum(pri["notifications"].values()) + pri["medication_log"]
    if n_cur == 0 and n_pri == 0:
        return [f"No heart-rhythm records stored in the {2 * w} days to {cur['end']} — an absence of records, not a measurement."]
    lines = []
    for kind in _KIND_ORDER:
        now, before = cur["notifications"].get(kind, 0), pri["notifications"].get(kind, 0)
        if now or before:
            lines.append(f"{KIND_LABELS[kind].capitalize()}: {now} {span}, {_trend(now, before)} in the {w} days before.")
    if cur["inferred"]:
        lines.append(f"{cur['inferred']} of this window's notification kinds were inferred from the reading, not named by the device.")
    if cur["ecg"] or pri["ecg"]:
        line = f"ECG recordings: {cur['ecg']} {span}, {_trend(cur['ecg'], pri['ecg'])} in the {w} days before"
        lines.append(line + (f"; device results: {_results_text(cur['ecg_results'])}." if cur["ecg_results"] else "."))
    if cur["medication_log"] or pri["medication_log"]:
        line = f"Medication log: {cur['medication_log']} entries {span}, {_trend(cur['medication_log'], pri['medication_log'])}"
        statuses = ", ".join(f"{s} {n}" for s, n in sorted(cur["medication_status"].items()))
        lines.append(line + f" in the {w} days before" + (f" ({statuses})." if statuses else "."))
    episodes = summary.get("episodes") or []
    if episodes:
        shown = episodes[:MAX_EPISODES]
        more = f" (+{len(episodes) - len(shown)} more)" if len(episodes) > len(shown) else ""
        lines.append(f"Events {span}, newest first{more}: " + "; ".join(_episode_text(e) for e in shown) + ".")
    if n_cur:
        lines.append(CLINICIAN_LINE)
    return lines


def coach_block(summary: Optional[dict]) -> str:
    """The prompt block for the owner's own coach thread, or "" — the instruction always rides with the data."""
    lines = owner_lines(summary)
    if not lines:
        return ""
    return "\n".join([HEADER, COACH_INSTRUCTION] + [f"- {ln}" for ln in lines])


def burden_change(
    events: Optional[list],
    end_day: str,
    *,
    family: str = "notification",
    kind: Optional[str] = "irregular",
    window_days: int = WINDOW_DAYS,
    worn_days: Optional[Iterable[str]] = None,
) -> Optional[dict]:
    """The count of one event kind in the window ending ``end_day`` against the window before — the reader a
    burden-rise alert consumes. None for an unread channel. Decides nothing: ``rose`` is a bare comparison and
    any threshold, minimum n or alert wording is the caller's.

    ``worn_days`` (the days the watch recorded anything, from the caller's own read) adds per-window coverage, so
    a quiet window that was simply not worn is visible as such. The medication-log count per window is computed
    here because it is in-channel; ``confounders`` lists every stated confounder the alert must show."""
    s = summarize(events, end_day, window_days)
    if s is None:
        return None

    def n_of(c: dict) -> int:
        if family == "notification":
            return sum(c["notifications"].values()) if kind is None else c["notifications"].get(kind, 0)
        if family == "ecg":
            return c["ecg"]
        return c["medication_log"]

    out: dict = {"family": family, "kind": kind, "window_days": window_days}
    worn = {str(d)[:10] for d in worn_days} if worn_days is not None else None
    for name in ("current", "prior"):
        c = s[name]
        entry = {"start": c["start"], "end": c["end"], "n": n_of(c), "medication_log": c["medication_log"]}
        if worn is not None:
            entry["worn_days"] = sum(1 for d in worn if c["start"] <= d <= c["end"])
        out[name] = entry
    out["n"] = out["current"]["n"] + out["prior"]["n"]
    out["delta"] = out["current"]["n"] - out["prior"]["n"]
    out["rose"] = out["delta"] > 0
    out["medication_log_changed"] = out["current"]["medication_log"] != out["prior"]["medication_log"]
    out["confounders"] = list(CONFOUNDERS)
    return out


# ── the one read (fail-soft) ─────────────────────────────────────────────────


def read_events(table, *, user_id: str = "matthew") -> Optional[list]:
    """The channel's neutral events (`rhythm_channel.read_events`), or None on any trouble."""
    try:
        from health import rhythm_channel  # noqa: PLC0415 — lazy: the producer's webhook imports stay out of a cold start

        return rhythm_channel.read_events(table, user_id=user_id)
    except Exception as e:  # noqa: BLE001 — owner surfaces run without the channel
        logger.warning("rhythm_owner read failed: %s", type(e).__name__)
        return None


def read_summary(table, today: str, *, window_days: int = WINDOW_DAYS, user_id: str = "matthew") -> Optional[dict]:
    """THE entry point for an owner surface: the summary for the window ending ``today``, or None (render nothing)."""
    if table is None:
        return None
    return summarize(read_events(table, user_id=user_id), today, window_days)
