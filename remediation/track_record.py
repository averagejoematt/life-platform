#!/usr/bin/env python3
"""
track_record.py — compute the Remediation Agent's PUBLIC track record from the
EXISTING S3 audit log (#1399, epic #1367). There is NO new logging path: every
number here is DERIVED from records the agent and the auto-merge gate already
write.

Source records (schema observed on the live log, not invented):

  • agent runs      remediation-log/{YYYY}/{MM}/{DD}/{HHMMSS}.json
        {mode, signals:{alarms:[{name,reason,metric,namespace,updated}],
         ci_failures:[…], dlq:{depth}, urgent:[…]},
         report:{auto_fixed:[{summary,pr}], prs:[{summary,…}],
                 needs_human:[{issue,action}], stale:[{summary}], _raw}}
        (.github/workflows/remediation-agent.yml, remediation/agent.py)

  • gate decisions  remediation-log/automerge/{YYYY}/{MM}/{DD}/pr{N}-{HHMMSS}.{merged|held}.json
        {pr, title, url, action:"merged"|"held", reason, infra}
        (remediation/automerge.py::_decision / audit)

This module is PURE — it operates on already-parsed record dicts, does no I/O,
imports no boto3 — so the build script (scripts/v4_build_agent_review.py) and the
tests (tests/test_agent_track_record.py) exercise exactly one code path. Callers
attach an ISO date to each record as `_date` (the {YYYY}/{MM}/{DD} from its S3
key) and, on gate records, `_key` for provenance.

Two invariants this module exists to hold:

  1. R22 PRIVACY — the load-bearing control. A case file is rendered publicly
     ONLY when its alarm class is on a positive, default-DENY allowlist of
     operational classes AND no field trips a security/exploit marker. A novel
     security-shaped alarm we have never classified defaults to EXCLUDED, never
     INCLUDED. Proven by test_security_alarm_never_published.

  2. ADR-104 HONEST GRADING — fix-survival-at-14-days is graded held / regressed
     / not-yet-gradeable. A fix younger than the window is not-yet-gradeable and
     is NEVER counted as a success; the held-rate is over the gradeable n only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# ── Fix-survival window ───────────────────────────────────────────────────────
SURVIVAL_WINDOW_DAYS = 14

GRADE_HELD = "held"
GRADE_REGRESSED = "regressed"
GRADE_NOT_YET = "not_yet_gradeable"

# ── R22 privacy: the alarm-type ALLOWLIST (positive, default-deny) ────────────
# Operational alarm CLASSES that are safe to render publicly. classify_alarm_type
# maps a raw alarm name to one of these slugs; anything that does not map — or
# that trips a SECURITY marker below — is excluded from every published case
# file. Keeping this a positive allowlist (not a denylist of bad classes) is the
# whole R22 posture: an alarm class we have never seen defaults to EXCLUDED.
PUBLIC_ALARM_CLASSES = {
    "source-freshness",  # slo-source-freshness, *-stale
    "dlq-depth",  # *-dlq-*, dead-letter depth
    "ingest-liveness",  # ingest-liveness-*, UnhealthySourceCount
    "ingest-error",  # ingestion-error-*, ingest-consecutive-failures-*
    "oauth-health",  # *-auth-unhealthy-* (OAuth TOKEN HEALTH — operational, not a breach)
    "reconciliation",  # ingest-reconciliation-* (ADR-092 backfill)
    "ai-quality",  # ai-canary-*, coherence-*, grading-stalled
    "content-cadence",  # panelcast-no-episode-*, compute-pipeline-stale
    "budget",  # *budget*, ai-tokens-*, qa-paused-by-budget
    "qa-smoke",  # qa-smoke-*
    "ci",  # CI-run failures
    "iam-grant",  # role_policies missing-grant template (Bucket A auto-fix)
    "lambda-map",  # ci/lambda_map.json drift (Bucket A auto-fix)
    "alarm-threshold",  # monitoring_stack threshold recalibration (Bucket A auto-fix)
}

# Substrings that mark an alarm/PR/reason as SECURITY / EXPLOIT-adjacent (the R22
# kill-list posture, e.g. the #893 MCP /token exposure class). Matched against the
# RAW text of every field BEFORE classification — the first and hardest gate.
# NB: plain "auth" is deliberately NOT here (OAuth-token-HEALTH alarms such as
# `ingest-auth-unhealthy-24h` are operational and already public on /story/agents/);
# only exploit-shaped auth phrasings ("auth-bypass", "authz-…") trip the gate.
SECURITY_MARKERS = (
    "waf",
    "sqli",
    "xss",
    "csrf",
    "injection",
    "exploit",
    "breach",
    "unauthorized",
    "intrusion",
    "token-expos",
    "token_expos",
    "tokenexpos",
    "/token",
    "credential",
    "secret-expos",
    "secret-access",
    "secret-leak",
    "leak",
    "privilege",
    "privesc",
    "brute-force",
    "bruteforce",
    "ddos",
    "denial-of-service",
    "attack",
    "cve-",
    "vuln",
    "backdoor",
    "malware",
    "exfil",
    "r22",
    "rate-limit-bypass",
    "auth-bypass",
    "authz",
    "pentest",
    "0day",
    "zero-day",
)


def _norm(s) -> str:
    return (s or "").strip().lower() if isinstance(s, str) else ("" if s is None else str(s).strip().lower())


def is_security_shaped(*texts) -> bool:
    """True if ANY provided text (alarm name, PR title, gate reason, fix summary)
    trips a security/exploit marker. This runs BEFORE classification, so a
    security-shaped item is excluded no matter how else it might classify."""
    blob = " ".join(_norm(t) for t in texts if t)
    return any(m in blob for m in SECURITY_MARKERS)


# name-substring → class slug, most specific patterns first.
_CLASS_PATTERNS = (
    ("oauth-health", ("auth-unhealthy", "oauth", "reauth", "auth-health", "token-refresh")),
    ("reconciliation", ("reconciliation", "reconcile", "missing-activity")),
    ("ingest-liveness", ("ingest-liveness", "liveness", "unhealthysource", "unhealthy-source")),
    ("ingest-error", ("ingestion-error", "consecutive-failures", "ingest-error", "ingestion-failure")),
    ("source-freshness", ("source-freshness", "freshness", "slo-source", "-stale", "stale-source")),
    ("dlq-depth", ("dlq", "dead-letter", "deadletter")),
    ("ai-quality", ("ai-canary", "canary", "coherence", "grading-stalled", "grading", "grounded", "ungrounded")),
    ("content-cadence", ("panelcast", "no-episode", "compute-pipeline", "pipeline-stale", "compute-stale")),
    ("budget", ("budget", "ai-tokens", "tokens-platform", "ceiling", "cost-spike")),
    ("qa-smoke", ("qa-smoke", "qa-paused", "smoke")),
    ("ci", ("ci-fail", "ci_fail", "ci-run", "workflow-fail", "build-fail")),
    ("iam-grant", ("iam-grant", "missing-grant", "role-policy", "role_policies", "accessdenied", "not-authorized")),
    ("lambda-map", ("lambda-map", "lambda_map", "unmapped-lambda", "lambda-drift")),
    ("alarm-threshold", ("alarm-threshold", "threshold-miscalibration", "false-fire", "recalibrat")),
)


def classify_alarm_type(name) -> str | None:
    """Map an alarm NAME (or PR title / gate-reason fragment) to an operational
    alarm-class slug, or None when it matches no known public class."""
    n = _norm(name)
    if not n:
        return None
    for slug, pats in _CLASS_PATTERNS:
        if any(p in n for p in pats):
            return slug
    return None


def public_alarm_class(name, *extra_texts) -> str | None:
    """THE single public-safety decision for one alarm/case (the R22 control).

    Returns the class slug if the item may be rendered publicly, or None to
    EXCLUDE it. Excludes when (1) any text is security/exploit-shaped, or (2) the
    name does not classify to a known operational class (default-deny). Proven by
    test_security_alarm_never_published and test_unknown_alarm_class_excluded."""
    if is_security_shaped(name, *extra_texts):
        return None
    slug = classify_alarm_type(name)
    if slug is None or slug not in PUBLIC_ALARM_CLASSES:
        return None
    return slug


# ── date helpers ──────────────────────────────────────────────────────────────
def _to_date(x) -> date | None:
    """Coerce a date / datetime / ISO-ish string to a date; None if unparseable."""
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    s = str(x).strip()
    if not s:
        return None
    # tolerate full ISO timestamps and bare YYYY-MM-DD
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt) + 6] if "%H" in fmt else s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


# ── fix-survival grading (ADR-104 honest) ─────────────────────────────────────
def grade_survival(merged_at, refire_dates, now, window_days: int = SURVIVAL_WINDOW_DAYS) -> str:
    """Grade a LANDED fix's survival at `window_days`.

    merged_at     when the fix landed (date / datetime / ISO string)
    refire_dates  iterable of dates the SAME alarm class fired AFTER the fix
    now           the evaluation instant
    window_days   the survival horizon (default 14)

    → GRADE_REGRESSED  a matching alarm re-fired within (merged_at, +window]
      GRADE_HELD       the full window elapsed with no re-fire
      GRADE_NOT_YET    the window has not yet elapsed and nothing has re-fired
                       (never counted as a success — ADR-104)

    A re-fire is a definitive regression even before the window closes, so it is
    checked first; only then does age decide held vs. not-yet-gradeable."""
    m = _to_date(merged_at)
    n = _to_date(now)
    if m is None or n is None:
        return GRADE_NOT_YET
    window_end = m + timedelta(days=window_days)
    for r in refire_dates or ():
        rd = _to_date(r)
        if rd is None:
            continue
        if m < rd <= window_end:
            return GRADE_REGRESSED
    if n >= window_end:
        return GRADE_HELD
    return GRADE_NOT_YET


# ── flatten the agent runs into an alarm-fire timeline ────────────────────────
def alarm_fire_events(agent_records):
    """Every classifiable alarm fire across the agent runs, as (date, class, name).

    Only alarms that pass the public-safety gate are kept — a security-shaped or
    unknown-class alarm can neither be published nor match a published case's
    re-fire, so it never enters the timeline."""
    events = []
    for r in agent_records or ():
        d = _to_date(r.get("_date"))
        if d is None:
            continue
        sig = r.get("signals") or {}
        for a in sig.get("alarms") or ():
            name = a.get("name") if isinstance(a, dict) else a
            reason = a.get("reason") if isinstance(a, dict) else None
            cls = public_alarm_class(name, reason)
            if cls is None:
                continue
            events.append((d, cls, name))
    return events


def _refires_for(cls, merged_on, events):
    """Dates on which alarm class `cls` fired strictly AFTER `merged_on`."""
    m = _to_date(merged_on)
    out = []
    for d, ecls, _name in events:
        if ecls == cls and m is not None and d > m:
            out.append(d)
    return out


# ── case files (survival-graded, public-safe only) ────────────────────────────
def build_cases(agent_records, automerge_records, now, window_days: int = SURVIVAL_WINDOW_DAYS):
    """Build the public case-file list plus the count of items EXCLUDED by the R22
    gate. A case is one of:

      kind="auto-merge"  a gate MERGED record OR an agent report.auto_fixed item —
                         a landed fix, survival-graded.
      kind="gate-hold"   a gate HELD record — a decision the gate made, no landed
                         fix, so no survival grade.
      kind="proposed-pr" an agent report.prs item — a PR opened for a human, not
                         yet landed by the agent, so no survival grade.

    Only public-safe cases (public_alarm_class is not None) are emitted; every
    excluded item is counted so the page can state an honest "N withheld"."""
    events = alarm_fire_events(agent_records)
    cases = []
    excluded = 0

    def _emit(kind, name_text, extra_text, fields):
        nonlocal excluded
        cls = public_alarm_class(name_text, extra_text)
        if cls is None:
            excluded += 1
            return
        entry = {"kind": kind, "alarm_class": cls}
        entry.update(fields)
        cases.append(entry)

    # 1) gate decisions (the named audit source) — merged (graded) + held (decision only)
    for a in automerge_records or ():
        action = _norm(a.get("action"))
        title = a.get("title") or ""
        reason = a.get("reason") or ""
        landed = _to_date(a.get("_date"))
        base = {
            "pr": a.get("pr"),
            "url": a.get("url") or "",
            "title": title,
            "reason": reason,
            "infra": bool(a.get("infra")),
            "decided_on": landed.isoformat() if landed else None,
            "provenance": {"log": "automerge", "source": a.get("_key") or ""},
        }
        if action == "merged":
            grade = grade_survival(landed, _refires_for(public_alarm_class(title, reason), landed, events), now, window_days)
            _emit("auto-merge", title, reason, {**base, "landed_on": base["decided_on"], "survival": grade})
        else:
            _emit("gate-hold", title, reason, {**base, "landed_on": None, "survival": None})

    # 2) agent-side fixes / proposals (report.auto_fixed = landed, report.prs = proposed)
    for r in agent_records or ():
        d = _to_date(r.get("_date"))
        key = r.get("_key") or ""
        rep = r.get("report") or {}
        for item in rep.get("auto_fixed") or ():
            summary = (item.get("summary") if isinstance(item, dict) else str(item)) or ""
            pr = item.get("pr") if isinstance(item, dict) else None
            grade = grade_survival(d, _refires_for(public_alarm_class(summary, summary), d, events), now, window_days)
            _emit(
                "auto-merge",
                summary,
                summary,
                {
                    "pr": None,
                    "url": pr or "",
                    "title": summary,
                    "reason": "",
                    "infra": False,
                    "landed_on": d.isoformat() if d else None,
                    "decided_on": d.isoformat() if d else None,
                    "survival": grade,
                    "provenance": {"log": "agent-run", "source": key},
                },
            )
        for item in rep.get("prs") or ():
            summary = (item.get("summary") if isinstance(item, dict) else str(item)) or ""
            pr = item.get("pr") if isinstance(item, dict) else None
            _emit(
                "proposed-pr",
                summary,
                summary,
                {
                    "pr": None,
                    "url": pr or "",
                    "title": summary,
                    "reason": "",
                    "infra": False,
                    "landed_on": None,
                    "decided_on": d.isoformat() if d else None,
                    "survival": None,
                    "provenance": {"log": "agent-run", "source": key},
                },
            )

    # newest decision first; stable
    cases.sort(key=lambda c: (c.get("decided_on") or "", str(c.get("pr") or "")), reverse=True)
    return cases, excluded


# ── computed counts ───────────────────────────────────────────────────────────
def compute_counts(agent_records, automerge_records) -> dict:
    """The headline tallies — all DERIVED, never hand-maintained (AC1)."""
    runs = len(agent_records or ())
    signals_triaged = prs_opened = auto_fixed = needs_human = 0
    for r in agent_records or ():
        sig = r.get("signals") or {}
        rep = r.get("report") or {}
        signals_triaged += len(sig.get("alarms") or ()) + len(sig.get("ci_failures") or ())
        prs_opened += len(rep.get("prs") or ()) + len(rep.get("auto_fixed") or ())
        auto_fixed += len(rep.get("auto_fixed") or ())
        needs_human += len(rep.get("needs_human") or ())
    gate_merges = sum(1 for a in (automerge_records or ()) if _norm(a.get("action")) == "merged")
    gate_holds = sum(1 for a in (automerge_records or ()) if _norm(a.get("action")) == "held")
    return {
        "agent_runs": runs,
        "signals_triaged": signals_triaged,
        "prs_opened": prs_opened,
        "auto_fixed": auto_fixed,
        "gate_merges": gate_merges,
        "gate_holds": gate_holds,
        "needs_human": needs_human,
    }


def _survival_summary(cases) -> dict:
    """Roll the graded landed-fix cases into an honest held/regressed/not-yet split
    with an n over gradeable fixes only (ADR-104)."""
    graded = [c for c in cases if c.get("survival") is not None]
    held = sum(1 for c in graded if c["survival"] == GRADE_HELD)
    regressed = sum(1 for c in graded if c["survival"] == GRADE_REGRESSED)
    not_yet = sum(1 for c in graded if c["survival"] == GRADE_NOT_YET)
    n_gradeable = held + regressed  # not-yet is NOT in the denominator
    return {
        "held": held,
        "regressed": regressed,
        "not_yet_gradeable": not_yet,
        "n_gradeable": n_gradeable,
        "held_rate": (round(held / n_gradeable, 3) if n_gradeable else None),
        "window_days": SURVIVAL_WINDOW_DAYS,
    }


def build_track_record(agent_records, automerge_records, now=None, window_days: int = SURVIVAL_WINDOW_DAYS) -> dict:
    """The full public track record: computed counts, honest survival roll-up, the
    public-safe case list, and the count of items the R22 gate withheld."""
    if now is None:
        now = datetime.now(timezone.utc)
    agent_records = list(agent_records or ())
    automerge_records = list(automerge_records or ())
    cases, excluded = build_cases(agent_records, automerge_records, now, window_days)
    dates = [d for d in (_to_date(r.get("_date")) for r in agent_records) if d is not None]
    mode = None
    if agent_records:
        # latest run's mode, by date then key
        latest = max(agent_records, key=lambda r: (r.get("_date") or "", r.get("_key") or ""))
        mode = latest.get("mode")
    return {
        "generated_at": (now.isoformat() if isinstance(now, datetime) else str(now)),
        "window_days": window_days,
        "mode": mode,
        "first_run": min(dates).isoformat() if dates else None,
        "last_run": max(dates).isoformat() if dates else None,
        "counts": compute_counts(agent_records, automerge_records),
        "survival": _survival_summary(cases),
        "cases": cases,
        "excluded_case_count": excluded,
    }
