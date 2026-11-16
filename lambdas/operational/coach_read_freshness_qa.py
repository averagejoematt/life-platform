"""coach_read_freshness_qa.py — no coach read on the door is left behind its board while regeneration runs (#5521).

THE INCIDENT. On 2026-10-31 `/api/coaching-dashboard` served two coaches' reads from day 40 beside three from day 54,
one coach with no stored analysis at all, `content_day_span {oldest 40, newest 56, mixed: true}` and
`regeneration_paused: false`. The payload disclosed the spread honestly (#3252 — `content_day_span`), but nothing
asked WHY the spread existed while regeneration was running. The daily run and its quality gate had passed for one of
the stale coaches on 2026-10-29 while the served analysis stayed at 10-15, so the reads were dropped somewhere after
the gate and no check said so for 16 days.

THE CONTRACT. While `regeneration_paused` is False, every coach the engine does not declare `absent` (#4217: an
absent coach carries the engine's own reason and no read, by design) must carry an `analysis_as_of_day_n` within
`MAX_LAG_DAYS` of the board's `content_day_span.newest_day_n`. A present coach with no read day at all is the same
failure (the issue's "Amara Patel has no analysis" member). When regeneration IS paused the drift is the disclosed,
expected state (#3252), so the leg reports green with the reason; when the pause signal is unknown (None) the contract
still applies: an unknown pause is not a pause.

WHY 7. The V2 coach narratives regenerate twice a week (`narrative_cadence.max_gap_days()` = 4 for Monday/Thursday),
so a healthy board's spread is at most ~4 days. 7 is the issue's own bound and leaves one missed run of slack, so a
red means at least two consecutive runs failed to land for that coach, not one transient miss.

Pure core (`assess`), no AWS and no clock; `checks` owns the one HTTP read. The leg lives outside qa_smoke_lambda
on the established cohesive-module shape (`recall_freshness_qa`, `weight_truth_qa`).
"""

from __future__ import annotations

import json
import urllib.request

CATEGORY = "Reader Truth"
MAX_LAG_DAYS = 7


def _day(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def assess(dashboard) -> tuple[str, str]:
    """('ok' | 'fail' | 'warn', message) for one `/api/coaching-dashboard` body.

    'warn' = the payload cannot be judged (no coaches, or no newest day anywhere), never a silent green."""
    if not isinstance(dashboard, dict) or not isinstance(dashboard.get("coaches"), list) or not dashboard["coaches"]:
        return "warn", "coaching-dashboard served no coaches — the read freshness could not be judged"
    if dashboard.get("regeneration_paused") is True:
        return "ok", "coach regeneration is paused — the board's mixed read days are the disclosed, expected state (#3252)"
    present = [c for c in dashboard["coaches"] if isinstance(c, dict) and not c.get("absent")]
    raw_span = dashboard.get("content_day_span")
    span: dict = raw_span if isinstance(raw_span, dict) else {}
    newest = _day(span.get("newest_day_n"))
    if newest is None:
        known = [d for d in (_day(c.get("analysis_as_of_day_n")) for c in present) if d is not None]
        newest = max(known) if known else None
    if newest is None:
        return "warn", f"no coach read carries a day number ({len(present)} present coaches) — freshness unjudgeable"
    behind = []
    for c in present:
        who = str(c.get("coach_id") or c.get("name") or "?")
        d = _day(c.get("analysis_as_of_day_n"))
        if d is None:
            behind.append(f"{who}: no stored read")
        elif newest - d > MAX_LAG_DAYS:
            behind.append(f"{who}: day {d}, {newest - d} behind")
    if behind:
        return "fail", (
            f"{len(behind)} of {len(present)} present coaches are more than {MAX_LAG_DAYS} days behind the board's newest read "
            f"(day {newest}) while regeneration is not paused: " + "; ".join(behind)
        )
    return "ok", f"all {len(present)} present coaches read within {MAX_LAG_DAYS} days of day {newest}"


def checks(check_cls, site_base_url, partition, timeout=15):
    """The nightly leg: one fetch of the door's payload, one Check. A fetch error is a WARN, never a green."""
    check = check_cls("coach_read_freshness", CATEGORY, partition)
    try:
        req = urllib.request.Request(site_base_url + "/api/coaching-dashboard", headers={"User-Agent": "life-platform-qa-smoke"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 — fail-soft to WARN, named
        return [check.warn(f"/api/coaching-dashboard fetch failed (fail-soft): {str(e)[:120]}")]
    verdict, msg = assess(body)
    print(f"[QA] COUNT coach_read_freshness: {msg}")
    return [{"ok": check.ok, "fail": check.fail, "warn": check.warn}[verdict](msg)]
