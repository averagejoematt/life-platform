"""phase_plausibility.py — deterministic phase-plausibility over published API payloads (#1922).

reader_truth asked Haiku to judge whether published numbers CAN be true at the
current experiment phase. Most of that question is arithmetic, and ADR-105 says
the arithmetic comes first: deterministic computation before any LLM verdict.
On 2026-08-01 the model mis-graded `weight_delta_window_days: 5` at Day 6 six
times in a row with six different rationales, while the two findings it got
right (#1917) were exactly the ones a comparison catches trivially. This module
is that comparison, run identically every time, at zero token cost — so unlike
the LLM rubric it is NEVER budget-paused (the 26-day dark window of #1920/#1927
cannot happen to arithmetic).

THE OVERLAP, STATED (acceptance item 4 of #1922): this module now owns the
NUMERIC phase-bound claims — window-named fields (via the #1917 registry),
explicit span declarations (*_window_days / actual_days), numeric day fields,
and bare "Day N" claims inside strict payloads' strings. The LLM rubric's
`impossible_number` category is retired (see reader_truth_qa.CATEGORIES);
the LLM keeps what is genuinely semantic: duplicated_narrative,
audience_violation, and prose-level temporal_contradiction in human sentences
(word-numbers — "seven days of an experiment", #1897 — remain the LLM's, since
"seven" is not arithmetic until something parses it).

Findings are emitted in reader_truth's canonical shape
({"page", "category", "severity", "note"}) so both passes route through one
reporting path in qa_smoke's Reader Truth check (partition content_truth,
ADR-147 — a finding here never reverts a deploy).
"""

import json
import re

from web.window_registry import INTENSIVE, REGISTRY, window_days

# Keys that DECLARE an in-cycle span in days. Live payloads clamp trailing
# windows to genesis (ADR-077 "clamped, not hidden"), so a declared span can
# never legitimately exceed the days the cycle has actually run. (Time-travel
# `?date=` payloads keep full reach by contract — but qa-smoke sweeps only the
# live surfaces, and this module is only pointed at live payloads.)
_SPAN_DECL_RE = re.compile(r"(?:^|_)(?:window_days|actual_days)$")

# Numeric keys that claim the current experiment day outright.
_DAY_CLAIM_KEYS = {"day_n", "experiment_day", "cycle_day"}

# ── R6 (#2613): a dated series row may not predate the cycle start ───────────
#
# The deterministic half of the #2613 ruling, and the reason that ruling is safe.
# ADR-077 clamps every trailing window to genesis ("clamped, not hidden"), so on a
# STRICT payload a row dated before the cycle start is a clamp breach — arithmetic,
# not judgment. Existing rules did not ask this: R1-R4 read numeric fields and R5
# deliberately SKIPS a row carrying its own `date` key (a dated row inside a dated
# series is scoped by its key), so no rule looked at the date itself.
#
# It exists because #2613 widens the LLM's wake-date clause to cover the earliest
# TREND ROW, not just the scalar `night_of`. A widened prose exemption can mask the
# real defect it resembles, so the real defect is now caught by code that cannot be
# budget-paused (the #1920/#1927 dark-window lesson). The exemption covers a row
# dated exactly genesis whose NIGHT is genesis-1; this rule still reds a row whose
# own DATE is before genesis.
#
# strict=True only, and for R4's documented reason: strict surfaces are clamped
# with no legitimate prior-cycle narration, while a narrative payload (/api/coaches)
# may legitimately carry rows dated in a labeled earlier cycle.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _pre_genesis_row_findings(page, payload, start_date):
    """R6 — no row in a dated series on a strict live payload predates the cycle start.

    Scope is the row's OWN `date` key. A timestamp *inside* a genesis-dated row
    (`sleep_start`) is deliberately NOT checked: sleep rows are wake-date keyed
    (#1923), so the first row of every cycle legitimately begins on the evening
    before Day 1. That is the artefact #2613 exempts, and conflating it with a
    genuinely pre-genesis row is exactly the mistake this rule guards against.
    """
    findings = []
    for path, obj in _objects(payload):
        if not isinstance(obj, dict):
            continue
        d = obj.get("date")
        if not isinstance(d, str) or not _ISO_DATE_RE.match(d) or d >= start_date:
            continue
        findings.append(
            {
                "page": page,
                "category": "temporal_contradiction",
                "severity": "high",
                "note": (
                    f"{path or '<root>'}.date = {d} predates the cycle start {start_date} — every trailing window "
                    f"on a live surface is clamped to genesis (ADR-077), so a prior-cycle row reaching a live "
                    f"series is a clamp breach, not a short window (#2613)"
                ),
            }
        )
    return findings


# "Day N" claims inside string values (e.g. window_disclosure prose). Only
# applied to payloads swept with strict=True: on a strict surface (vitals) no
# prior-cycle narration exists, so a Day number beyond today's is impossible
# arithmetic, not a judgment call. Narrative surfaces (coaches) may legitimately
# narrate a labeled prior cycle's Day 45 — prose day-claims there stay with the
# LLM's temporal_contradiction category.
_DAY_PROSE_RE = re.compile(r"\bDay\s+(\d+)\b")


# ── R5 (#1968): a night-scoped figure must name its night ────────────────────
#
# Measured on the live 2026-08-06 payload: `/api/sleep_detail`'s summary published
# `total_sleep_hours: 8.4` while the `sleep_trend` row for the same `as_of_date` read
# `hours: null` (Eight Sleep vs Whoop, mid auth-outage). Both numbers were true and the
# payload said so nowhere — the summary named no night and no device, so the two
# surfaces simply contradicted each other in public. reader_truth raised it HIGH on
# 2026-08-05 and the LLM had to guess at the cause; this is the same finding, computed.
#
# The rule is a LABEL rule, not an arithmetic one, so unlike R1–R4 it does not depend on
# the experiment day and runs at every phase: a figure with no scope is unreconcilable
# on Day 1 and on Day 400 alike.
_NIGHT_SCOPED_FIELDS = {
    "total_sleep_hours",
    "sleep_hours",
    "whoop_hours",
    "sleep_efficiency",
    "sleep_efficiency_pct",
    "sleep_score",
    "whoop_quality",
    "deep_sleep_hours",
    "rem_sleep_hours",
    "deep_pct",
    "rem_pct",
    "light_pct",
    "recovery_score",
    "recovery_pct",
    "hrv",
    "rhr",
}
# What counts as naming the night. `night_of` is the explicit answer. `frame` alongside a
# wake date is the other legitimate one — it declares the convention (#1923's "last_night"
# = as_of - 1) that converts the date the object DOES carry, which is exactly what
# site_api_common.night_of_for exists to publish. A bare `as_of_date` is neither: it is a
# morning, and the whole #1923 doc block exists because that ambiguity got re-litigated.
_NIGHT_LABEL_KEYS = ("night_of", "frame")


def _night_label_findings(page, payload):
    """R5 — every object publishing a night-scoped vitals figure names its night.

    Scope: dict objects that publish at least one non-null field from
    `_NIGHT_SCOPED_FIELDS`. A row carrying its OWN `date` key is skipped — a dated row
    inside a dated series is scoped by its key, and flagging all thirty of them would
    bury the one summary object that genuinely floats free.
    """
    findings = []
    for path, obj in _objects(payload):
        if not isinstance(obj, dict) or "date" in obj:
            continue
        figures = sorted(k for k in _NIGHT_SCOPED_FIELDS if obj.get(k) is not None)
        if not figures:
            continue
        if any(obj.get(k) for k in _NIGHT_LABEL_KEYS):
            continue
        findings.append(
            {
                "page": page,
                "category": "temporal_contradiction",
                "severity": "medium",
                "note": (
                    f"{path or '<root>'} publishes {len(figures)} night-scoped figure(s) "
                    f"({', '.join(figures[:6])}{', …' if len(figures) > 6 else ''}) "
                    f"with no night label (no `night_of`, no `frame`) — a reader cannot tell which "
                    f"night they describe, so a sibling surface reporting that night differently "
                    f"is indistinguishable from a contradiction (#1968)"
                ),
            }
        )
    return findings


def _objects(obj, path=""):
    """Yield (json_path, dict) for the payload and every nested dict, depth-first."""
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _objects(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _objects(v, f"{path}[{i}]")


def _walk(obj, path=""):
    """Yield (json_path, key, value) for every dict entry, depth-first."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            yield p, k, v
            yield from _walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_payload(page, payload, day_n, strict=False, start_date=None):
    """Deterministic phase-plausibility findings for one live JSON payload.

    Args:
        page: the surface path, used verbatim in findings (reader_truth shape).
        payload: the parsed JSON object.
        day_n: 1-indexed current experiment day (reader_truth_qa.phase_context).
        strict: also apply the bare "Day N" prose rule to string values, and R6.
        start_date: the cycle start (phase_context's `start_date`), for R6. Omitted
            => R6 is skipped: a rule with no genesis to compare against must not
            guess one (the same fail-soft posture as the rest of this module).

    Returns a list of {"page", "category", "severity", "note"} findings.
    Pre-start (day_n == 0) returns only R5 — the phase rules R1–R4 have nothing to
    compare against (the countdown state has its own honest copy and the LLM rubric
    already knows the pre-start phase line), while R5's night-label question is
    phase-independent (#1968).
    """
    # R5 runs FIRST and outside the pre-start guard: it asks whether a figure names its
    # night, which is not a question about the experiment day (see the block above).
    findings = _night_label_findings(page, payload)
    # R6 (#2613) is likewise phase-independent — "before genesis" is a date comparison,
    # not a day count — so it runs outside the pre-start guard too. A FUTURE genesis
    # (#931/#939) is precisely when a stale prior-cycle row is most likely to leak.
    if strict and start_date:
        findings.extend(_pre_genesis_row_findings(page, payload, start_date))
    if not day_n or day_n < 1:
        return findings
    for path, key, value in _walk(payload):
        # R1 — a gated INTENSIVE window-named field carrying a value before its
        # window can exist. The registry (one source of truth, #1917) decides
        # which fields make full-window claims; gap-declared debt (#1919) is
        # deliberately exempt here because the registry already tracks it.
        if _is_number(value) and key in REGISTRY:
            kind, gap = REGISTRY[key]
            n = window_days(key)
            if kind == INTENSIVE and gap is None and n is not None and n > day_n:
                findings.append(
                    {
                        "page": page,
                        "category": "impossible_number",
                        "severity": "high",
                        "note": f"{path} = {value}: a full {n}-day intensive claim cannot exist on Day {day_n} "
                        f"(#1917 gates this field to null until its window is genuinely full)",
                    }
                )
            continue
        # R2 — an explicit span declaration longer than the cycle has run.
        if _is_number(value) and _SPAN_DECL_RE.search(key):
            if value > day_n:
                findings.append(
                    {
                        "page": page,
                        "category": "impossible_number",
                        "severity": "high",
                        "note": f"{path} = {value}: a live in-cycle window cannot span more than the {day_n} day(s) elapsed",
                    }
                )
            continue
        # R3 — a numeric field claiming a later experiment day than today's.
        if _is_number(value) and key in _DAY_CLAIM_KEYS:
            if value > day_n:
                findings.append(
                    {
                        "page": page,
                        "category": "temporal_contradiction",
                        "severity": "high",
                        "note": f"{path} = {value}: today is Day {day_n} — the payload claims a day that has not happened",
                    }
                )
            continue
        # R4 — bare "Day N" in strict payloads' prose (e.g. window_disclosure).
        if strict and isinstance(value, str):
            for m in _DAY_PROSE_RE.finditer(value):
                n = int(m.group(1))
                if n > day_n:
                    findings.append(
                        {
                            "page": page,
                            "category": "temporal_contradiction",
                            "severity": "high",
                            "note": f'{path} says "Day {n}" but today is Day {day_n} — a frame/staleness leak',
                        }
                    )
    return findings


def sweep_payloads(payloads, today_iso=None):
    """Run check_payload over [{"path", "body", "strict"?}, ...] raw JSON texts.

    Returns (findings, warnings). A body that does not parse as JSON is a
    warning, never a crash (fail-soft, same posture as the LLM pass) — but it
    is REPORTED, because a payload this module could not read is a page it did
    not check (#1931's lesson).
    """
    from operational.reader_truth_qa import phase_context

    phase = phase_context(today_iso)
    day_n = phase["day_n"]
    findings, warnings = [], []
    for p in payloads:
        try:
            payload = json.loads(p["body"])
        except (ValueError, KeyError) as e:
            warnings.append(f"{p.get('path', '?')} — not checkable ({str(e)[:80]})")
            continue
        findings.extend(
            check_payload(
                p.get("path", "?"),
                payload,
                day_n,
                strict=bool(p.get("strict")),
                start_date=phase["start_date"],  # R6 (#2613)
            )
        )
    return findings, warnings
