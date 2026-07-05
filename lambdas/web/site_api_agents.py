"""
lambdas/web/site_api_agents.py — the Agents Showcase feed (#399, PG-13).

A read-only "meet the agents" roster plus a dated weekly Agent Activity readout,
sourced PURELY from artifacts the platform ALREADY writes. No new inference and
no new agents — phase 1 renders existing artifacts only.

The watchdog agents each persist dated, durable records to S3:

  • Coherence Sentinel  → coherence-log/{YYYY-MM-DD}.json
        (lambdas/operational/coherence_sentinel_lambda.py) — "does the
        intelligence layer still make sense?" invariant checks vs live state.
  • AI Quality Canary   → ai-canary-log/{YYYY-MM-DD}.json
        (lambdas/operational/ai_quality_canary_lambda.py) — probes the served
        public AI and grades it deterministically (grounded / on-character /
        no-blocked). This is where a served answer citing a number that isn't
        in the canonical facts gets caught — the honesty machinery made visible.
  • Remediation Agent   → remediation-log/{YYYY}/{MM}/{DD}/{HHMMSS}.json
        (.github/workflows/remediation-agent.yml, remediation/agent.py) —
        triages CloudWatch alarms, failed CI, DLQ depth; auto-fixes the safe
        class, opens PRs for the rest, escalates needs-human.
  • Auto-merge Gate     → remediation-log/automerge/{YYYY}/{MM}/{DD}/pr{N}-*.json
        (remediation/automerge.py) — the deterministic merge gate for
        auto-fix-safe PRs (ADR-065).

Every free-text fragment lifted from an artifact (finding detail, PR title,
triage reason, agent narrative) can quote model output, so it passes the same
privacy + content filters the public Q&A uses before it is returned:
privacy_guard.scrub() for real-name/vice redaction, then _scrub_blocked_terms()
for the blocked-vice fail-safe. When a fragment trips the fail-safe or is fully
redacted, the fragment is DROPPED (when in doubt, exclude) rather than shown.

Read-only: GETs S3 objects. Never writes platform data. Honest empty state — a
week with no activity says so plainly rather than padding the feed.
"""

from datetime import datetime, timedelta, timezone

import boto3

from web.site_api_common import (
    S3_REGION,
    _error,
    _ok,
    _scrub_blocked_terms,
    logger,
)

try:  # layer module; import defensively so a missing layer can't 500 the route
    import privacy_guard
except Exception:  # noqa: BLE001
    privacy_guard = None

import os

S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

# The blocked-vice fail-safe returns this sentinel when an obfuscated term
# survives the literal scrub. Any fragment that reduces to it is dropped.
_BLOCKED_SENTINEL = "I can't share that."

# ── the roster (describes agents that ALREADY exist — no new agents) ───────────
# Purely descriptive metadata; the live evidence is the events, built from the
# artifacts below. Kept here (not fetched) because it's editorial, not data.
ROSTER = [
    {
        "id": "coherence_sentinel",
        "name": "Coherence Sentinel",
        "role": "Does the intelligence layer still make sense?",
        "detail": (
            "Runs pure invariants against the live intelligence layer every "
            "morning — do the served narratives agree with the canonical facts, "
            "do computed metrics agree with their components, do the cross-surface "
            "counts line up. Deterministic first; an advisory AI read on top."
        ),
        "cadence": "daily",
        "source": "coherence-log/",
    },
    {
        "id": "ai_quality_canary",
        "name": "AI Quality Canary",
        "role": "Is the served AI grounded and on-character?",
        "detail": (
            "Probes the public AI endpoints and grades each answer against the "
            "canonical facts — flags any number it cites that isn't in the data, "
            "any out-of-character voice, any blocked content. This is the guard "
            "that catches an AI coach citing a vital that doesn't exist."
        ),
        "cadence": "daily",
        "source": "ai-canary-log/",
    },
    {
        "id": "remediation_agent",
        "name": "Remediation Agent",
        "role": "Triages what broke overnight.",
        "detail": (
            "Reads CloudWatch alarms, failed CI runs, and dead-letter-queue depth, "
            "then auto-fixes the safe class, opens PRs for the rest, and escalates "
            "what needs a human — one curated report a day. Read-only role; it can "
            "propose but never deploy."
        ),
        "cadence": "daily",
        "source": "remediation-log/",
    },
    {
        "id": "automerge_gate",
        "name": "Auto-merge Gate",
        "role": "Merges only the provably safe fixes.",
        "detail": (
            "A deterministic gate — not the agent — that merges an auto-fix-safe PR "
            "only if every file is on a narrow allowlist, the diff is small, and lint "
            "plus the offline test subset pass. It never auto-deploys; CI's production "
            "approval stays intact."
        ),
        "cadence": "as needed",
        "source": "remediation-log/automerge/",
    },
]

# How many detail lines to surface per event (keep the feed scannable).
_MAX_DETAILS = 4


def _s3_client():
    """Isolated so tests can monkeypatch the client without touching AWS."""
    return boto3.client("s3", region_name=S3_REGION)


def _clean(text):
    """Run an artifact fragment through the SAME public content gates the Q&A
    uses. Returns cleaned text, or None if it must be excluded.

    privacy_guard.scrub() redacts real names / vices inline; _scrub_blocked_terms
    drops the whole fragment (→ sentinel) when an obfuscated blocked term survives.
    A fragment that reduces to the sentinel or to empty is excluded entirely.
    """
    if not text:
        return None
    out = str(text)
    if privacy_guard is not None:
        try:
            out = privacy_guard.scrub(out)[0]
        except Exception:  # noqa: BLE001 — never let the gate itself 500 the route
            pass
    try:
        out = _scrub_blocked_terms(out)
    except Exception:  # noqa: BLE001
        pass
    out = (out or "").strip()
    if not out or out == _BLOCKED_SENTINEL:
        return None
    return out


def _get_json(key):
    """GET + parse a single S3 JSON object. Returns dict or None (fail-soft)."""
    import json

    try:
        resp = _s3_client().get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read())
    except Exception as e:  # noqa: BLE001 — a missing day is normal, not an error
        logger.info("[agents] no artifact at %s (%s)", key, e.__class__.__name__)
        return None


def _list_keys(prefix):
    """List object keys under a prefix (paginated). Returns [] on any failure."""
    keys = []
    try:
        client = _s3_client()
        token = None
        while True:
            kw = {"Bucket": S3_BUCKET, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            keys.extend(o["Key"] for o in resp.get("Contents", []))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
    except Exception as e:  # noqa: BLE001
        logger.info("[agents] list %s failed (%s)", prefix, e.__class__.__name__)
    return keys


# ── week math ─────────────────────────────────────────────────────────────────
def _monday_of(d):
    """The Monday (date) of the ISO week containing date `d`."""
    return d - timedelta(days=d.weekday())


def _parse_week(qs):
    """Resolve the requested week to (monday_date, [7 date objs]). Defaults to the
    current week. A ?week=YYYY-MM-DD param anchors to that day's Monday."""
    anchor = datetime.now(timezone.utc).date()
    raw = (qs or {}).get("week")
    if raw:
        try:
            anchor = datetime.strptime(raw.strip(), "%Y-%m-%d").date()
        except (ValueError, AttributeError):
            pass  # bad param → default to current week
    monday = _monday_of(anchor)
    return monday, [monday + timedelta(days=i) for i in range(7)]


# ── per-source event builders (each returns a list of event dicts) ────────────
def _status_norm(s):
    """Normalize the mixed-case statuses across artifacts to ok/warn/alarm/info."""
    s = (s or "").strip().lower()
    if s in ("alarm", "fail", "failed", "error"):
        return "alarm"
    if s in ("warn", "warning"):
        return "warn"
    if s in ("ok", "pass", "passed", "clean"):
        return "ok"
    return "info"


def _coherence_events(week_dates):
    events = []
    for d in week_dates:
        iso = d.isoformat()
        rec = _get_json(f"coherence-log/{iso}.json")
        if not rec:
            continue
        status = _status_norm(rec.get("status"))
        findings = rec.get("findings") or []
        flagged = [f for f in findings if _status_norm(f.get("status")) in ("alarm", "warn")]
        details = []
        for f in flagged[:_MAX_DETAILS]:
            line = _clean(f"{f.get('name')}: {f.get('detail')}")
            if line:
                details.append(line)
        if status == "alarm":
            headline = f"Flagged {len(flagged)} coherence break(s) in the live intelligence layer."
        elif status == "warn":
            headline = f"Noted {len(flagged)} soft coherence warning(s)."
        else:
            headline = "Ran the coherence invariants — everything agreed."
        events.append(
            {
                "date": iso,
                "agent_id": "coherence_sentinel",
                "agent": "Coherence Sentinel",
                "status": status,
                "headline": headline,
                "details": details,
            }
        )
    return events


def _canary_events(week_dates):
    events = []
    for d in week_dates:
        iso = d.isoformat()
        rec = _get_json(f"ai-canary-log/{iso}.json")
        if not rec:
            continue
        if rec.get("skipped"):
            events.append(
                {
                    "date": iso,
                    "agent_id": "ai_quality_canary",
                    "agent": "AI Quality Canary",
                    "status": "info",
                    "headline": "Probes skipped — website AI was budget-paused.",
                    "details": [],
                }
            )
            continue
        status = _status_norm(rec.get("status"))
        findings = rec.get("findings") or []
        flagged = [f for f in findings if _status_norm(f.get("status")) in ("alarm", "warn")]
        # The showpiece: a grounding failure means the served AI cited a number
        # that isn't in the canonical facts.
        grounding_hit = any("grounded" in (f.get("name") or "") for f in flagged if _status_norm(f.get("status")) == "alarm")
        details = []
        for f in flagged[:_MAX_DETAILS]:
            line = _clean(f"{f.get('name')}: {f.get('detail')}")
            if line:
                details.append(line)
        if grounding_hit:
            headline = "Caught a served AI answer citing a figure that isn't in the data — flagged as ungrounded."
        elif status == "alarm":
            headline = f"Flagged {len(flagged)} quality failure(s) in the served AI."
        elif status == "warn":
            headline = f"Noted {len(flagged)} quality warning(s) in the served AI."
        else:
            headline = "Probed the public AI — grounded, on-character, and clean."
        events.append(
            {
                "date": iso,
                "agent_id": "ai_quality_canary",
                "agent": "AI Quality Canary",
                "status": status,
                "headline": headline,
                "details": details,
            }
        )
    return events


def _remediation_events(week_dates):
    events = []
    for d in week_dates:
        prefix = f"remediation-log/{d.year:04d}/{d.month:02d}/{d.day:02d}/"
        for key in _list_keys(prefix):
            if not key.endswith(".json"):
                continue
            rec = _get_json(key)
            if not rec:
                continue
            signals = rec.get("signals") or {}
            report = rec.get("report") or {}
            n_alarms = len(signals.get("alarms") or [])
            n_ci = len(signals.get("ci_failures") or [])
            dlq = (signals.get("dlq") or {}).get("depth", 0)
            n_fixed = len(report.get("auto_fixed") or [])
            n_prs = len(report.get("prs") or [])
            n_human = len(report.get("needs_human") or [])
            # NB: report["_raw"] is the model's scratch narrative — never surfaced.
            details = []
            for a in (signals.get("alarms") or [])[:_MAX_DETAILS]:
                line = _clean(a.get("name") if isinstance(a, dict) else a)
                if line:
                    details.append(f"alarm · {line}")
            status = "alarm" if (n_human or n_alarms or n_ci or dlq) else "ok"
            if n_fixed or n_prs or n_human:
                headline = (
                    f"Triaged {n_alarms} alarm(s) and {n_ci} CI failure(s) — "
                    f"auto-fixed {n_fixed}, opened {n_prs} PR(s), escalated {n_human}."
                )
            elif n_alarms or n_ci or dlq:
                headline = f"Triaged {n_alarms} alarm(s), {n_ci} CI failure(s), DLQ depth {dlq} — nothing auto-fixable."
            else:
                headline = "Swept the alarms, CI, and DLQ — nothing to do."
                status = "ok"
            events.append(
                {
                    "date": d.isoformat(),
                    "agent_id": "remediation_agent",
                    "agent": "Remediation Agent",
                    "status": status,
                    "headline": headline,
                    "details": details,
                }
            )
    return events


def _automerge_events(week_dates):
    events = []
    for d in week_dates:
        prefix = f"remediation-log/automerge/{d.year:04d}/{d.month:02d}/{d.day:02d}/"
        for key in _list_keys(prefix):
            if not key.endswith(".json"):
                continue
            rec = _get_json(key)
            if not rec:
                continue
            action = (rec.get("action") or "").strip().lower()
            pr = rec.get("pr")
            title = _clean(rec.get("title")) or ""
            reason = _clean(rec.get("reason"))
            if action == "merged":
                status = "ok"
                headline = f"Auto-merged PR #{pr}" + (f": {title}" if title else "")
            else:
                status = "info"
                headline = f"Held PR #{pr} for human review" + (f": {title}" if title else "")
            details = [reason] if reason else []
            events.append(
                {
                    "date": d.isoformat(),
                    "agent_id": "automerge_gate",
                    "agent": "Auto-merge Gate",
                    "status": status,
                    "headline": headline,
                    "details": details,
                }
            )
    return events


# ── route ─────────────────────────────────────────────────────────────────────
def handle_agent_activity(event):
    """GET /api/agent_activity[?week=YYYY-MM-DD] — the agent roster plus a dated
    weekly readout of what the watchdog agents actually did, sourced purely from
    existing artifacts. Read-only, content-filtered, honest empty state."""
    qs = (event or {}).get("queryStringParameters") or {}
    try:
        monday, week_dates = _parse_week(qs)
        events = []
        events += _coherence_events(week_dates)
        events += _canary_events(week_dates)
        events += _remediation_events(week_dates)
        events += _automerge_events(week_dates)

        # newest first; stable secondary sort by agent for a deterministic order
        events.sort(key=lambda e: (e["date"], e["agent_id"]), reverse=True)

        # per-agent tallies for the roster cards
        summary = {r["id"]: {"runs": 0, "flags": 0} for r in ROSTER}
        for e in events:
            s = summary.setdefault(e["agent_id"], {"runs": 0, "flags": 0})
            s["runs"] += 1
            if e["status"] in ("alarm", "warn"):
                s["flags"] += 1

        return _ok(
            {
                "week_start": monday.isoformat(),
                "week_end": (monday + timedelta(days=6)).isoformat(),
                "has_activity": bool(events),
                "roster": ROSTER,
                "events": events,
                "summary": summary,
            },
            cache_seconds=1800,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[agents] handler failed: %s", e)
        return _error(500, "agent activity unavailable")
