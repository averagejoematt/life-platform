#!/usr/bin/env python3
"""
agent.py — self-healing remediation agent (runs in GitHub Actions).

Flow per run:
  1. Gate on SSM /life-platform/remediation-mode (off|shadow) + budget tier. `auto` is a
     RETIRED value (#2833, ADR-129 amendment 2026-08-30 — shadow is permanent): nothing in
     this pipeline can merge, so a stale `auto` in SSM runs as shadow and is reported.
  2. Gather the last 24h of signals deterministically (alarms, QA/freshness/cost,
     failed CI runs, DLQ) — cheap boto3/gh, no LLM.
  3. Hand the signals + docs/REMEDIATION_TAXONOMY.md to Claude (Agent SDK, on
     Bedrock) with a scoped toolset. Claude classifies each into A/B/C/D and:
       - Bucket A (auto-fix-safe): fix in a branch, open a PR labeled auto-fix-safe
         (the label is a triage class, not a merge grant — a human merges it; the
         deterministic auto-merge gate that once consumed it was retired by #2833).
       - Bucket B (fix-via-pr): open a PR labeled needs-review.
       - Bucket C (needs-human): no change — include the specific action in the report.
       - Bucket D (stale): collapse.
       - Operational remediations (clear stale alarm / drain stale DLQ msg / re-run
         gap-fill): done directly via the scoped role.
  4. Claude emits a JSON summary; we render + email it (SES) and write the audit log.

Triggered by: schedule (daily sweep) or repository_dispatch (urgent_alarm).
Auth: AWS OIDC (Bedrock + read-only diagnosis + scoped ops). Model: Sonnet 4.6.
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

import boto3

import drift_report

REGION = os.environ.get("AWS_REGION", "us-west-2")
MODE_PARAM = "/life-platform/remediation-mode"
BUDGET_PARAM = "/life-platform/budget-tier"
REPO = os.environ.get("GITHUB_REPOSITORY", "averagejoematt/life-platform")
SENDER = RECIPIENT = "awsdev@mattsusername.com"
LOG_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_ssm = boto3.client("ssm", region_name=REGION)
_cw = boto3.client("cloudwatch", region_name=REGION)
_logs = boto3.client("logs", region_name=REGION)
_sqs = boto3.client("sqs", region_name=REGION)
_ses = boto3.client("sesv2", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)


def _param(name, default):
    try:
        return _ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except Exception:
        return default


# The kill-switch's live values. `auto` was retired 2026-08-30 (#2833, ADR-129 amendment):
# the auto-merge gate and the auto-earn path are gone, so there is no mode in which this
# pipeline merges anything. A value outside this tuple is NOT honoured — gate() coerces
# it to shadow and names it, so an operator who flips the parameter learns it did nothing
# from the report rather than from silence.
_LIVE_MODES = ("off", "shadow")
_stale_mode = None  # set by gate() when SSM holds a value that is no longer live


def gate():
    """Return the active mode, or None to skip the run."""
    global _stale_mode
    mode = _param(MODE_PARAM, "shadow")
    if mode == "off":
        print("remediation-mode=off — no-op")
        return None
    if int(_param(BUDGET_PARAM, "0") or 0) >= 3:
        print("budget tier 3 — skipping remediation to protect the ceiling")
        return None
    if mode not in _LIVE_MODES:
        _stale_mode = mode
        print(f"::warning::remediation-mode={mode!r} is not a live value ({'|'.join(_LIVE_MODES)}) — running as shadow (#2833)")
        return "shadow"
    _stale_mode = None
    return mode


def stale_mode_escalation():
    """A needs-human line when SSM holds a retired/unknown mode value; None otherwise.

    Deterministic, like the alarm-aging backstop: the LLM never sees the raw parameter,
    so this is the only place a stale `auto` can be surfaced to the operator."""
    if not _stale_mode:
        return None
    return {
        "issue": f"SSM {MODE_PARAM} holds {_stale_mode!r}, which is not a live mode (live: {'|'.join(_LIVE_MODES)}). "
        "`auto` was retired 2026-08-30 (#2833) — the agent has no self-merge path in any mode, so this run proceeded as shadow.",
        "action": f"Reset it so the parameter says what the pipeline does: aws ssm put-parameter --name {MODE_PARAM} "
        "--value shadow --type String --overwrite --region us-west-2",
    }


# ── Alarm-acknowledgement ledger (#396) ─────────────────────────────────────
# Known, persistent signals must not be re-triaged from scratch every run — the
# 2026-07-03 run burned its whole turn budget re-investigating one already-known
# test failure and emitted nothing. After each run, alarms that landed in
# needs_human or stale are acked for ACK_TTL_DAYS; the next run hands the agent
# the prior conclusion so it carries it forward in one line instead of digging.

ACK_LEDGER_KEY = "remediation-log/ack_ledger.json"
ACK_TTL_DAYS = 7

# ── Ack-age ratchet (#1960) ─────────────────────────────────────────────────
# The loop above had no upper bound: every run that reached the same conclusion
# rewrote the entry with a fresh 7-day expiry, so an ack renewed FOREVER and a
# red board became normal. Worse, a WRONG ack renewed just as happily — the
# 2026-07-28 review found ingest-auth-unhealthy-24h acked "duplicate, covered by
# source-specific alarms" (false for garmin/notion/todoist, which had no
# per-source alarm at all), still being re-renewed on 2026-08-01 with 10 alarms
# simultaneously red. An ack is a "I looked, carry it forward" note, not a mute
# button: after ACK_MAX_RENEWALS consecutive renewals the alarm stops counting as
# acknowledged and escalates to needs_human WITH ITS AGE, every run, until it
# actually clears.
ACK_MAX_RENEWALS = 3

# Ledger schema version. Bumping it INVALIDATES every stored entry on the next
# load — deliberate, and the mechanism by which the wrong "duplicate" ack is
# corrected: v1 entries carry no first_acked_at/renewals, so their true age is
# unknowable and grandfathering them in at renewals=0 would hand the mislabeled
# ack another three free renewals. Dropping them forces one honest re-triage of
# every currently-acked alarm; the ones that are genuinely known get re-acked on
# that same run at renewals=1 and the ratchet starts counting from real data.
ACK_SCHEMA = 2


def load_ack_ledger():
    try:
        obj = _s3.get_object(Bucket=LOG_BUCKET, Key=ACK_LEDGER_KEY)
        ledger = json.loads(obj["Body"].read().decode())
        if not isinstance(ledger, dict):
            return {}
        return {k: v for k, v in ledger.items() if isinstance(v, dict) and v.get("schema") == ACK_SCHEMA}
    except Exception:
        return {}


def _ack_renewals(entry):
    try:
        return int(entry.get("renewals", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _ack_age_hours(entry, now):
    """Hours since the alarm was FIRST acked (not since the last renewal — that
    resets every run and is exactly what made the staleness invisible)."""
    stamp = entry.get("first_acked_at") or entry.get("acked_at")
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600.0


def ack_is_exhausted(entry):
    """True once the ack has been renewed ACK_MAX_RENEWALS times — the 3rd
    consecutive renewal is the ratchet's trip point."""
    return _ack_renewals(entry) >= ACK_MAX_RENEWALS


def annotate_acked(signals, ledger, now=None):
    """Mark alarms that were already triaged on a recent run (unexpired ack).

    An EXHAUSTED ack (#1960) is deliberately not annotated: the alarm goes back
    to the agent untriaged, and the deterministic aging backstop
    (aged_alarm_escalations) stops skipping it — the ack has run out of the
    benefit of the doubt."""
    now_dt = now or datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    for a in signals.get("alarms", []):
        entry = ledger.get(a.get("name", ""))
        if entry and str(entry.get("expires", "")) > now_iso and not ack_is_exhausted(entry):
            a["acked"] = {
                "acked_at": entry.get("acked_at"),
                "first_acked_at": entry.get("first_acked_at"),
                "renewals": _ack_renewals(entry),
                "bucket": entry.get("bucket"),
                "prior_conclusion": entry.get("conclusion", "")[:300],
            }


def ack_ratchet_escalations(signals, ledger, now=None):
    """Return `(alarm_name, needs_human_item)` for every still-firing alarm whose
    ack has been renewed ACK_MAX_RENEWALS times (#1960).

    Deterministic and pure, like aged_alarm_escalations — it fires even when the
    LLM turn budget burns out. The item names the alarm, the renewal count, the
    age since the FIRST ack, and the prior conclusion, so the operator is asked
    the one question a renewed ack never asks: is this conclusion still TRUE?"""
    now_dt = now or datetime.now(timezone.utc)
    out = []
    for a in signals.get("alarms", []) or []:
        name = a.get("name", "")
        entry = ledger.get(name)
        if not name or not entry or not ack_is_exhausted(entry):
            continue
        renewals = _ack_renewals(entry)
        age = _ack_age_hours(entry, now_dt)
        age_txt = _fmt_age(age) if age is not None else "unknown age"
        prior = str(entry.get("conclusion", ""))[:200] or "(no conclusion recorded)"
        out.append(
            (
                name,
                {
                    "issue": f"Alarm '{name}' has been acked and renewed {renewals}x over {age_txt} and is STILL in ALARM "
                    f"(> {ACK_MAX_RENEWALS}-renewal ratchet, #1960). The stored conclusion was: {prior!r}. An ack that "
                    "renews forever is a mute button, not an acknowledgement — and a wrong conclusion renews just as "
                    "silently as a right one (the 2026-07-28 'duplicate, covered by source-specific alarms' ack was "
                    "false for three sources and was still being renewed a week later).",
                    "action": f"Re-verify the stored conclusion for '{name}' against current reality — do not re-ack it "
                    "unchanged. Either fix the underlying condition, file/point at a tracking issue and add the alarm to "
                    "docs/alarm_citations.json, or retire the alarm. This escalation repeats every run until the alarm "
                    "clears.",
                },
            )
        )
    return out


def update_ack_ledger(ledger, report, signals, now=None):
    """Ack every alarm the run concluded needs_human or stale (the persistent
    classes) so the next runs skip the from-scratch investigation. Fail-soft.

    #1960: an ack now CARRIES ITS HISTORY — first_acked_at survives every renewal
    and `renewals` counts them, so the ratchet above can tell "triaged on Monday"
    from "renewed unchanged for a month"."""
    now_dt = now or datetime.now(timezone.utc)
    alarm_names = [a.get("name", "") for a in signals.get("alarms", []) if a.get("name")]
    changed = False
    for bucket, text_keys in (("needs_human", ("issue", "action")), ("stale", ("summary",))):
        for item in report.get(bucket, []) or []:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get(k, "")) for k in text_keys)
            for name in alarm_names:
                if name and name in text:
                    prior = ledger.get(name) if isinstance(ledger.get(name), dict) else None
                    ledger[name] = {
                        "schema": ACK_SCHEMA,
                        "acked_at": now_dt.isoformat(),
                        "first_acked_at": (prior or {}).get("first_acked_at") or now_dt.isoformat(),
                        "renewals": (_ack_renewals(prior) + 1) if prior else 0,
                        "expires": (now_dt + timedelta(days=ACK_TTL_DAYS)).isoformat(),
                        "bucket": bucket,
                        "conclusion": text[:500],
                    }
                    changed = True
    # Expire old entries so the ledger can't grow unbounded / mask a regression.
    for name in list(ledger):
        if str(ledger[name].get("expires", "")) <= now_dt.isoformat():
            ledger.pop(name)
            changed = True
    if changed:
        try:
            _s3.put_object(Bucket=LOG_BUCKET, Key=ACK_LEDGER_KEY, Body=json.dumps(ledger, indent=2), ContentType="application/json")
        except Exception as e:
            print(f"[warn] ack ledger write: {e}")
    return ledger


# ── Report-first skeleton (#396) ─────────────────────────────────────────────
# The report file is written BEFORE the agent starts, with every signal listed
# under `untriaged`. The agent moves signals into buckets as it classifies them
# (rewriting the file incrementally), so a burned turn budget can no longer
# produce the empty raw-fallback report — worst case the report honestly says
# what was and wasn't triaged.


def signal_descriptors(signals):
    out = []
    for a in signals.get("alarms", []) or []:
        out.append({"kind": "alarm", "id": a.get("name", "?"), "acked": bool(a.get("acked"))})
    for c in signals.get("ci_failures", []) or []:
        out.append({"kind": "ci_failure", "id": str(c.get("databaseId", "?")), "title": c.get("displayTitle", "")[:120]})
    if (signals.get("dlq") or {}).get("depth"):
        out.append({"kind": "dlq", "id": "ingestion-dlq", "depth": signals["dlq"]["depth"]})
    if signals.get("coherence"):
        out.append({"kind": "coherence", "id": str(signals["coherence"].get("date", "latest"))})
    if signals.get("drift"):
        out.append({"kind": "drift", "id": "weekly-drift"})
    if signals.get("urgent"):
        out.append({"kind": "urgent", "id": "repository-dispatch"})
    for s in signals.get("secrets_stale", []) or []:
        out.append({"kind": "secret_rotation", "id": s.get("name", "?"), "age_days": s.get("age_days")})
    return out


def write_skeleton_report(report_path, signals):
    skeleton = {"auto_fixed": [], "prs": [], "needs_human": [], "stale": [], "untriaged": signal_descriptors(signals), "_skeleton": True}
    try:
        with open(report_path, "w") as f:
            json.dump(skeleton, f, indent=2)
    except Exception as e:
        print(f"[warn] skeleton report write: {e}")
    return skeleton


# ── Alarm-aging escalation (#1204) ──────────────────────────────────────────
# A digest-routed CloudWatch alarm can sit in ALARM indefinitely with the daily
# digest as its only consumer — grading-stalled sat in ALARM ~10 days and the LLM
# triage produced no fix, no issue, no acted-on needs-human item, so the solo
# operator's attention silently absorbed a dead load-bearing sensor. This is a
# DETERMINISTIC backstop, independent of the LLM turn/token budget: any alarm that
# has been in ALARM past the escalation window becomes a NAMED needs-human line
# carrying its age, until it clears or is acked. The remediation role is read-only
# — this only SURFACES the aged alarm into the report; it does not act on it (no
# deploy, no IAM, no alarm mutation — #1229 owns the digest-consumer alarms).

ALARM_AGE_ESCALATION_HOURS = 72


def _alarm_age_hours(alarm, now):
    """Hours the alarm has been in its current (ALARM) state, from the
    StateUpdatedTimestamp captured in gather_signals (`updated`). None if it can't
    be parsed — an unparseable stamp must never manufacture a false escalation."""
    ts = alarm.get("updated")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600.0


def _fmt_age(hours):
    days = hours / 24.0
    if days >= 1:
        return f"{days:.1f}d ({hours:.0f}h)"
    return f"{hours:.0f}h"


def aged_alarm_escalations(signals, now=None):
    """Return `(alarm_name, needs_human_item)` tuples for every alarm that has been
    in ALARM longer than ALARM_AGE_ESCALATION_HOURS and is not already acked. Pure
    and deterministic (no LLM, no I/O) so it always fires even when the agent's turn
    budget burns out mid-triage. An already-acked alarm (annotate_acked ran a prior
    conclusion forward) is skipped — that IS the acknowledgement — and it re-escalates
    only once the ack expires and the alarm is still stuck."""
    now_dt = now or datetime.now(timezone.utc)
    out = []
    for a in signals.get("alarms", []) or []:
        if a.get("acked"):
            continue
        age = _alarm_age_hours(a, now_dt)
        if age is None or age <= ALARM_AGE_ESCALATION_HOURS:
            continue
        name = a.get("name", "?")
        out.append(
            (
                name,
                {
                    "issue": f"Alarm '{name}' has been in ALARM for {_fmt_age(age)} "
                    f"(> {ALARM_AGE_ESCALATION_HOURS}h aging threshold) — an aged, unresolved sensor whose only "
                    "consumer is the daily alert digest (#1204).",
                    "action": f"Investigate and resolve '{name}', or ack it if the state is expected. "
                    "This aging escalation repeats each run until the alarm clears or is acknowledged.",
                },
            )
        )
    return out


# ── Manual-rotation secret staleness escalation (#1329) ─────────────────────
# freshness-checker's manual-rotation staleness check (MANUAL_ROTATION_SECRETS /
# MANUAL_ROTATION_STALE_DAYS in lambdas/emails/freshness_checker_lambda.py) used to
# SNS-publish this RAW to the daily alert digest every single run once a secret
# crossed its threshold — life-platform/ai-keys crossed 120 days ~2026-07-06 and
# re-fired daily for 12+ consecutive days with zero action (#1329 evidence:
# LastChangedDate 2026-03-08, 132 days at filing). A channel that pages daily for
# an unactionable-same-message alert trains the operator to ignore it. #1329's
# fix: freshness-checker no longer SNS-publishes that alert (still emits the
# ManualRotationStaleCount CloudWatch metric for dashboards); this agent picks up
# the same Secrets Manager DescribeSecret read (read-only, zero new cadence — the
# agent already runs Mon/Wed/Fri) and surfaces any manual-rotation secret past its
# stale threshold as a NAMED needs-human line, deterministic and independent of the
# LLM turn budget — mirroring the alarm-aging backstop (#1204) above. Secrets are a
# denylisted path for the LLM (remediation/prompt.md "Hard rules" — never auto-fix,
# never edit secret/auth files), so this is surfacing-only; rotation stays human
# (gate:owner).
#
# Regression guard (#1329's defined recurrence condition): a stale-secret alert is
# "recurring" once its ACTIVE age — how long it's been past the rotation SLA, i.e.
# age_days - MANUAL_ROTATION_STALE_DAYS, not how long since the secret was set —
# exceeds STALE_SECRET_NO_ISSUE_DAYS with no linked tracking issue. The platform has
# no issue-linking mechanism for secrets (the curated needs-human email IS the
# tracking surface, by design — no new machinery), so "no linked issue" is
# structural: every stale secret past the recurrence window keeps recurring here,
# every curated run, until its LastChangedDate advances (rotated).

MANUAL_ROTATION_SECRETS = [
    "life-platform/ai-keys",
    "life-platform/site-api-ai-key",
    "life-platform/eightsleep-client",
    "life-platform/notion",
    "life-platform/todoist",
    "life-platform/ingestion-keys",
]
MANUAL_ROTATION_STALE_DAYS = int(os.environ.get("MANUAL_ROTATION_STALE_DAYS", "120"))
STALE_SECRET_NO_ISSUE_DAYS = 7  # #1329: active-age threshold that defines "recurrence"

_sm = boto3.client("secretsmanager", region_name=REGION)


def stale_secret_signals(now=None, sm_client=None):
    """Deterministic Secrets Manager read (no LLM, DescribeSecret only — never
    GetSecretValue, this agent never sees key material): which
    MANUAL_ROTATION_SECRETS are past MANUAL_ROTATION_STALE_DAYS since
    LastChangedDate. Fail-soft per secret (a describe_secret hiccup or a missing
    IAM grant on one secret must not blank the whole list — logs and continues)."""
    now_dt = now or datetime.now(timezone.utc)
    sm = sm_client or _sm
    out = []
    for name in MANUAL_ROTATION_SECRETS:
        try:
            meta = sm.describe_secret(SecretId=name)
            last_changed = meta.get("LastChangedDate")
            if not last_changed:
                continue
            age_days = (now_dt - last_changed.replace(tzinfo=timezone.utc)).days
            if age_days > MANUAL_ROTATION_STALE_DAYS:
                out.append({"name": name, "age_days": age_days})
        except Exception as e:
            print(f"[warn] describe_secret {name}: {e}")
    return out


def stale_secret_escalations(signals, now=None):
    """Return `(secret_name, needs_human_item)` tuples for every manual-rotation
    secret whose active age (days past the rotation SLA) exceeds
    STALE_SECRET_NO_ISSUE_DAYS — the #1329 defined recurrence condition. Pure and
    deterministic: fires every run off `signals["secrets_stale"]`, regardless of
    what the LLM triage concluded, so the reminder can never go silently missing
    the way the raw daily SNS both over-fired AND (once someone muted the topic)
    could under-fire."""
    out = []
    for s in signals.get("secrets_stale", []) or []:
        name = s.get("name", "?")
        age_days = s.get("age_days", 0)
        active_age = age_days - MANUAL_ROTATION_STALE_DAYS
        if active_age <= STALE_SECRET_NO_ISSUE_DAYS:
            continue  # freshly crossed the threshold — let the LLM triage see it first
        rotate_hint = " — one-command prep: `bash deploy/rotate_ai_keys.sh`" if name == "life-platform/ai-keys" else ""
        out.append(
            (
                name,
                {
                    "issue": f"Secret '{name}' is {age_days}d since last rotation ({active_age}d past the "
                    f"{MANUAL_ROTATION_STALE_DAYS}d manual-rotation SLA) — active >{STALE_SECRET_NO_ISSUE_DAYS}d "
                    "with no linked tracking issue, the #1329 defined recurrence condition. Previously this paged "
                    "raw daily SNS (#1329 evidence: 12+ consecutive unactioned days); now routed here as a "
                    "persistent tracked item instead.",
                    "action": f"Rotate {name} per docs/SECRETS_ROTATION.md{rotate_hint}. Rotation is human-only "
                    "(gate:owner) — this line recurs every curated Mon/Wed/Fri run until the secret's "
                    "LastChangedDate advances.",
                },
            )
        )
    return out


# ── Signal gathering (deterministic, no LLM) ────────────────────────────────


def _coherence_findings():
    """The Coherence Sentinel's latest durable findings (coherence-log/latest.json).

    The agent already ingests the `coherence-overall` CloudWatch alarm for free,
    but that alarm only says "OverallAlarm >= 1" — it doesn't say WHICH invariant
    failed. This is WHAT: the same findings record the Sentinel persisted. Cheap S3
    GET; fail-soft. Only surfaced when it's actually flagging (an OK record is noise)."""
    try:
        obj = _s3.get_object(Bucket=LOG_BUCKET, Key="coherence-log/latest.json")
        rec = json.loads(obj["Body"].read().decode())
    except Exception as e:
        print(f"[warn] coherence findings: {e}")
        return None
    if not (isinstance(rec, dict) and rec.get("status") in ("warn", "alarm")):
        return None
    return {
        "status": rec.get("status"),
        "date": rec.get("date"),
        "alarms": rec.get("alarms", []),
        # Only the findings that are actually flagging — drop the OK ones.
        "findings": [f for f in rec.get("findings", []) if f.get("status") in ("warn", "alarm")],
        "semantic": rec.get("semantic"),
        "digest": rec.get("digest"),
    }


def gather_signals(event_payload):
    """Collect the last 24h of technical signals into a structured dict."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    signals = {"alarms": [], "ci_failures": [], "dlq": [], "coherence": None, "drift": None, "urgent": None, "secrets_stale": []}

    # CloudWatch alarms currently in ALARM + recent transitions
    try:
        alarms = _cw.describe_alarms(StateValue="ALARM", MaxRecords=100).get("MetricAlarms", [])
        for a in alarms:
            signals["alarms"].append(
                {
                    "name": a["AlarmName"],
                    "reason": a.get("StateReason", "")[:300],
                    "metric": a.get("MetricName"),
                    "namespace": a.get("Namespace"),
                    "updated": str(a.get("StateUpdatedTimestamp", "")),
                }
            )
    except Exception as e:
        print(f"[warn] describe-alarms: {e}")

    # Recent failed CI runs
    try:
        out = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--branch",
                "main",
                "--status",
                "failure",
                "--limit",
                "5",
                "--json",
                "databaseId,headSha,displayTitle,conclusion,createdAt",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=60,
        )
        if out.returncode == 0:
            signals["ci_failures"] = json.loads(out.stdout or "[]")
    except Exception as e:
        print(f"[warn] gh run list: {e}")

    # Ingestion DLQ depth (peek count only; the agent inspects details if non-zero)
    try:
        url = f"https://sqs.{REGION}.amazonaws.com/{os.environ.get('CDK_ACCOUNT','205930651321')}/life-platform-ingestion-dlq"
        attrs = _sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])
        signals["dlq"] = {"depth": int(attrs["Attributes"]["ApproximateNumberOfMessages"]), "url": url}
    except Exception as e:
        print(f"[warn] dlq depth: {e}")

    # Coherence Sentinel findings (content/correctness — the "alive but not right"
    # class). Adds WHAT failed to the bare coherence-overall alarm above.
    signals["coherence"] = _coherence_findings()

    # Weekly drift sentinel findings (live infra vs. code — the "console-edited / orphan /
    # loosened-policy" class). Only surfaces as actionable when there is real drift; the
    # clean/degraded status still renders on the report via drift_report.status_html.
    signals["drift"] = drift_report.as_signal(drift_report.read_latest(_s3, LOG_BUCKET))

    # Manual-rotation secret staleness (#1329) — replaces the raw daily SNS the
    # freshness-checker used to publish; deterministic backstop below (main()) turns
    # any hit into a NAMED needs-human line, zero new cadence (agent already Mon/Wed/Fri).
    try:
        signals["secrets_stale"] = stale_secret_signals(now=datetime.now(timezone.utc))
    except Exception as e:
        print(f"[warn] stale_secret_signals: {e}")

    # Event-driven urgent payload (from repository_dispatch)
    if event_payload:
        signals["urgent"] = event_payload
    return signals


# ── The agent run (Agent SDK on Bedrock) ────────────────────────────────────


def build_prompt(mode, signals):
    taxonomy = open(os.path.join(ROOT, "docs", "REMEDIATION_TAXONOMY.md")).read()
    base = open(os.path.join(os.path.dirname(__file__), "prompt.md")).read()
    return (
        base
        + f"\n\n## Mode: {mode}\n"
        + "\n## Taxonomy (authoritative classification rubric)\n"
        + taxonomy
        + "\n\n## Signals to triage (last 24h)\n```json\n"
        + json.dumps(signals, indent=2, default=str)
        + "\n```\n"
        + "\nProduce your work, then end with a single ```json fenced block matching "
        + "the REPORT schema in the instructions."
    )


async def run_agent(prompt):
    """Invoke Claude via the Agent SDK on Bedrock and return its captured text.

    Headless safety: `bypassPermissions` (no interactive prompts — `acceptEdits`
    hangs/errors on Bash/gh tools headlessly). The REAL blast-radius guard is the
    IAM role (read-only AWS + SES + scoped S3-log) and the GITHUB_TOKEN scope
    (contents + pull-requests write only) — the agent literally cannot deploy or
    mutate AWS. `disallowed_tools` is best-effort defense-in-depth. We accumulate
    text across all messages and tolerate the SDK's ResultMessage protocol /
    end-of-stream exceptions so a partial run still produces a report."""
    from claude_agent_sdk import query, ClaudeAgentOptions  # installed in the workflow

    options = ClaudeAgentOptions(
        permission_mode="bypassPermissions",
        disallowed_tools=[
            "Bash(git merge *)",
            "Bash(git push --force*)",
            "Bash(gh pr merge *)",
            "Bash(aws lambda update*)",
            "Bash(aws iam *)",
            "Bash(cdk deploy*)",
            "Bash(npx cdk deploy*)",
        ],
        cwd=ROOT,
        max_turns=int(os.environ.get("REMEDIATION_MAX_TURNS", "16")),
    )
    # Hold the async generator explicitly so we can aclose() it on break/exit.
    # Without this, the `break` below leaves the generator in a yielding state
    # and GC finalization raises `RuntimeError: aclose(): asynchronous generator
    # is already running` at process exit — benign but noisy in the logs.
    agen = query(prompt=prompt, options=options)
    chunks = []
    cost_usd = None
    usage = None
    try:
        async for message in agen:
            # Final ResultMessage carries is_error + result; capture, don't crash.
            if hasattr(message, "is_error"):
                res = getattr(message, "result", None)
                if isinstance(res, str):
                    chunks.append(res)
                if getattr(message, "is_error", False):
                    print(f"[warn] agent result flagged error " f"(subtype={getattr(message, 'subtype', None)})")
                # #2883: the ResultMessage is the ONLY place this run's real spend is
                # ever visible — see _emit_cost_telemetry below for why that matters.
                cost_usd = getattr(message, "total_cost_usd", None)
                usage = getattr(message, "usage", None)
                break
            # AssistantMessage: pull text from content blocks.
            content = getattr(message, "content", None)
            if isinstance(content, list):
                for blk in content:
                    t = getattr(blk, "text", None)
                    if isinstance(t, str):
                        chunks.append(t)
    except Exception as e:
        print(f"[warn] agent stream ended with: {e} — using captured output")
    finally:
        try:
            await agen.aclose()
        except Exception:
            pass
    _emit_cost_telemetry(cost_usd, usage)
    return "\n".join(chunks)


# #2883: this agent's Bedrock spend runs entirely inside the Agent SDK (the `claude`
# CLI on Bedrock, CLAUDE_CODE_USE_BEDROCK=1) — it never touches
# lambdas/ai/bedrock_client.py's ADR-062 chokepoint, so it billed AWS/Bedrock (and
# counted in CostMetricDriftRatio's native AWS/Bedrock-metric numerator, `_ai_cost`
# in cost_governor_lambda.py) while contributing NOTHING to the self-reported
# `LifePlatform/AI::EstimatedCostUSD` denominator. That's one of the two out-of-repo
# residual candidates named when the ratio stalled at ~1.4x — the other is
# interactive dev-session Bedrock usage, which stays out of scope here on purpose
# (it isn't a platform cost the #2836 base decision should attribute to a caller).
# `ResultMessage.total_cost_usd`/`.usage` are the Agent SDK's own per-run figures
# (same attributes the `logfire` claude_agent_sdk integration reads — verified
# against that library's source, not guessed). Mirrors
# bedrock_client._emit_usage_metrics's metric shape (dimensionless +
# LambdaFunction-dimensioned) so this feeds the SAME CloudWatch series the drift
# ratio already sums — no new query needed anywhere downstream. Fail-open, and
# ERROR (not WARN) on failure — a fail-open channel that silently drops every
# emission is invisible at WARN, the exact #2974 lesson for the visual-qa CI role.
_REMEDIATION_CALLER = "remediation-agent"

# #2883: the `CallerClass` value this agent's spend belongs to. Pinned as a literal
# rather than imported because `remediation/` runs on a GitHub Actions runner from a
# bare checkout and must not take an import dependency on the Lambda bundle tree;
# tests/test_remediation_cost_telemetry_2883.py asserts it equals
# `ai.bedrock_client.CALLER_CLASS_REMEDIATION`, so the two literals cannot drift.
#
# WHY IT WAS MISSING AND WHAT IT COST: #3070 gave this emitter the dimensionless and
# `LambdaFunction`-dimensioned copies (the two the drift ratio's denominator reads) but
# not the third, `CallerClass`-dimensioned copy that `bedrock_client._emit_usage_metrics`
# has emitted since #2892. `cost_governor_lambda._self_reported_cost_by_class()` queries
# exactly four series by class name, so this agent's spend was invisible to the split BY
# CONSTRUCTION — and `remediation` is one of PROJECTED_CALLER_CLASSES, i.e. a class the
# month-end projection is supposed to extrapolate. Measured live 2026-08-30:
# `LambdaFunction=remediation-agent` = $1.60 MTD while `CallerClass=remediation` had
# **no dimension set at all** in `list-metrics` and summed $0.00. That is the whole of
# the residual class-coverage gap: over the trailing 5 days the CallerClass split covers
# 96.4% of the dimensionless total, and this emitter is what the other 3.6% is.
_REMEDIATION_CALLER_CLASS = "remediation"


def _emit_cost_telemetry(cost_usd, usage) -> None:
    if not cost_usd:
        return
    try:
        fn_dim = [{"Name": "LambdaFunction", "Value": _REMEDIATION_CALLER}]
        class_dim = [{"Name": "CallerClass", "Value": _REMEDIATION_CALLER_CLASS}]
        data = [
            {"MetricName": "EstimatedCostUSD", "Dimensions": fn_dim, "Value": float(cost_usd), "Unit": "None"},
            {"MetricName": "EstimatedCostUSD", "Value": float(cost_usd), "Unit": "None"},
            # ADDITIVE, exactly like #2892's copy at the chokepoint: the two series above
            # are untouched, so nothing the drift ratio or the G2 alarm reads changes value.
            {"MetricName": "EstimatedCostUSD", "Dimensions": class_dim, "Value": float(cost_usd), "Unit": "None"},
        ]

        def _tok(key):
            v = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
            return int(v or 0)

        if usage:
            in_tok, out_tok = _tok("input_tokens"), _tok("output_tokens")
            cache_read, cache_write = _tok("cache_read_input_tokens"), _tok("cache_creation_input_tokens")
            if in_tok:
                data.append({"MetricName": "AnthropicInputTokens", "Dimensions": fn_dim, "Value": in_tok, "Unit": "Count"})
            if out_tok:
                data.append({"MetricName": "AnthropicOutputTokens", "Dimensions": fn_dim, "Value": out_tok, "Unit": "Count"})
                data.append({"MetricName": "AnthropicOutputTokens", "Value": out_tok, "Unit": "Count"})
            if cache_read:
                data.append({"MetricName": "AnthropicCacheReadTokens", "Dimensions": fn_dim, "Value": cache_read, "Unit": "Count"})
                # #2883: the dimensionless twin, same as bedrock_client now emits. This
                # agent is 4.49M of the platform's 5.66M self-reported cache-read tokens
                # MTD (2026-08-30), so a bare series without it would under-report the
                # very quantity box 4 reconciles against Cost Explorer.
                data.append({"MetricName": "AnthropicCacheReadTokens", "Value": cache_read, "Unit": "Count"})
            if cache_write:
                data.append({"MetricName": "AnthropicCacheWriteTokens", "Dimensions": fn_dim, "Value": cache_write, "Unit": "Count"})
                data.append({"MetricName": "AnthropicCacheWriteTokens", "Value": cache_write, "Unit": "Count"})
        _cw.put_metric_data(Namespace="LifePlatform/AI", MetricData=data)
    except Exception as e:
        print(f"[error] remediation cost telemetry emit failed (dropped ${cost_usd:.4f}, #2883): {e}")


def parse_report(text):
    """Extract the trailing ```json REPORT block; tolerate prose around it."""
    if "```json" in text:
        seg = text.rsplit("```json", 1)[1].split("```", 1)[0]
        try:
            return json.loads(seg.strip())
        except Exception:
            pass
    return {"auto_fixed": [], "prs": [], "needs_human": [], "stale": [], "_raw": text[-1500:]}


# ── Loop-close guard (#1201) ────────────────────────────────────────────────
# The self-healing loop only "closes" if the agent actually classifies each
# signal into a bucket. When the Bedrock turn/token budget burns out
# mid-investigation, the report keeps every signal under `untriaged` AND carries
# a truncated `_raw` reasoning tail (the tell that the structured output never
# parsed). #396 made that partial state HONEST in the report/email, but the
# workflow step still exited 0 — so 3 of 4 runs (Jul 8/13/15) concluded
# 'success' with zero triage and the recurrence went untracked. This guard makes
# an incomplete run LOUD: the step reds instead of reporting a deceptive green.


def triage_incomplete(report):
    """True when the run failed to close the loop: signals remain `untriaged`
    AND the agent's structured output never parsed (a truncated `_raw` tail is
    present). A clean run (all signals bucketed) or one that at least produced a
    parseable REPORT with no `_raw` returns False."""
    if not isinstance(report, dict):
        return True
    return bool(report.get("untriaged")) and bool(report.get("_raw"))


# ── Reporting ────────────────────────────────────────────────────────────────


def email_report(report, mode):
    def block(title, items, fmt):
        if not items:
            return ""
        return f"<h3>{title}</h3><ul>" + "".join(f"<li>{fmt(i)}</li>" for i in items) + "</ul>"

    af = report.get("auto_fixed", [])
    prs = report.get("prs", [])
    nh = report.get("needs_human", [])
    stale = report.get("stale", [])
    unt = report.get("untriaged", [])
    subj = f"🤖 Remediation [{mode}]: {len(af)} fixed, {len(prs)} PRs, {len(nh)} need you"
    if unt:
        subj += f", {len(unt)} untriaged"
    _drift_record = drift_report.read_latest(_s3, LOG_BUCKET)
    html = (
        f"<p><b>Mode:</b> {mode} · {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}</p>"
        + block("✅ Auto-fixed", af, lambda i: f"{i.get('summary','')} — {i.get('pr','')}")
        + block("🔀 PRs awaiting you", prs, lambda i: f"{i.get('summary','')} — {i.get('pr','')}")
        + block("👤 Needs you", nh, lambda i: f"<b>{i.get('issue','')}</b>: {i.get('action','')}")
        + block("· Stale / ignored", stale, lambda i: str(i.get("summary", i)))
        # #396: honest partial-run accounting — signals the turn budget didn't reach.
        + block("⏳ Not triaged this run", unt, lambda i: f"{i.get('kind','')}: {i.get('id','')}")
        + ("<p><i>No actionable signals.</i></p>" if not (af or prs or nh or unt) else "")
        # Weekly drift sentinel status — always rendered when a record exists so a clean
        # week reports explicitly clean (never silent about infra drift). AC4 of #394.
        + drift_report.status_html(_drift_record)
        # GitHub Actions quota/billing glance — always rendered alongside it (#1334, #1453).
        + drift_report.quota_html(_drift_record)
    )
    try:
        _ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={"Simple": {"Subject": {"Data": subj[:99]}, "Body": {"Html": {"Data": html}}}},
        )
        print(f"report emailed: {subj}")
    except Exception as e:
        print(f"[warn] SES send: {e}")


def audit_log(report, signals, mode):
    try:
        key = f"remediation-log/{datetime.now(timezone.utc):%Y/%m/%d/%H%M%S}.json"
        _s3.put_object(
            Bucket=LOG_BUCKET,
            Key=key,
            Body=json.dumps({"mode": mode, "signals": signals, "report": report}, indent=2, default=str),
            ContentType="application/json",
        )
    except Exception as e:
        print(f"[warn] audit log: {e}")


def main():
    mode = gate()
    if not mode:
        return 0
    event_payload = json.loads(os.environ.get("DISPATCH_PAYLOAD", "null") or "null")
    signals = gather_signals(event_payload)
    if not (
        signals["alarms"]
        or signals["ci_failures"]
        or (signals["dlq"] or {}).get("depth")
        or signals["coherence"]
        or signals["drift"]
        or signals["urgent"]
        or signals.get("secrets_stale")  # .get: older test doubles/fixtures predate this key (#1329)
    ):
        print("no actionable signals — clean run")
        report = {}
        stale = stale_mode_escalation()
        if stale:
            report = {"needs_human": [stale]}
        email_report(report, mode)
        return 0
    # #396: annotate signals already triaged on a recent run before prompting.
    ledger = load_ack_ledger()
    annotate_acked(signals, ledger)
    prompt = build_prompt(mode, signals)
    # #396: report-first — the file exists (with every signal untriaged) BEFORE
    # a single agent turn is spent, so a burned budget still yields a valid
    # report of what was and wasn't triaged.
    report_path = os.environ.get("REMEDIATION_REPORT_PATH", "/tmp/remediation_report.json")
    write_skeleton_report(report_path, signals)
    text = asyncio.run(run_agent(prompt))
    # Prefer the file the agent maintained; if it never touched the skeleton,
    # try the stream's fenced JSON; failing that the skeleton IS the honest
    # report (everything untriaged) with the raw tail attached for diagnosis.
    report = None
    try:
        with open(report_path) as f:
            report = json.load(f)
    except Exception:
        pass
    if not isinstance(report, dict):
        report = parse_report(text)
    elif report.get("_skeleton"):
        parsed = parse_report(text)
        if "_raw" not in parsed:
            report = parsed
        else:
            report["_raw"] = text[-1500:]
    report.pop("_skeleton", None)
    # #2833: a retired/unknown SSM mode value is a needs-human line, never a grant.
    stale = stale_mode_escalation()
    if stale:
        report.setdefault("needs_human", []).append(stale)
    # #1204: deterministic alarm-aging backstop — surface any alarm stuck in ALARM
    # past the escalation window as a NAMED needs-human line, whether or not the LLM
    # triage reached it, so a burned turn budget can never silently absorb a dead
    # load-bearing sensor. Dedup by name against what the agent already reported.
    existing_nh = report.get("needs_human", []) or []
    existing_text = " ".join(str(i.get("issue", "")) + " " + str(i.get("action", "")) for i in existing_nh if isinstance(i, dict))
    # #1960: ack-age ratchet — an ack renewed past ACK_MAX_RENEWALS is no longer an
    # acknowledgement. Runs BEFORE the aging backstop so the more specific
    # "your conclusion may be wrong" item wins the name dedup.
    for name, item in ack_ratchet_escalations(signals, ledger):
        if name not in existing_text:
            report.setdefault("needs_human", []).append(item)
            existing_text += " " + name
    for name, item in aged_alarm_escalations(signals):
        if name not in existing_text:
            report.setdefault("needs_human", []).append(item)
            existing_text += " " + name
    # #1329: same deterministic-backstop shape, for manual-rotation secret staleness —
    # replaces the raw daily SNS with a persistent tracked item in this curated email.
    for name, item in stale_secret_escalations(signals):
        if name not in existing_text:
            report.setdefault("needs_human", []).append(item)
            existing_text += " " + name
    # Keep the file consistent with what we report/audit.
    try:
        with open(report_path, "w") as f:
            json.dump(report, f)
    except Exception as e:
        print(f"[warn] write report file: {e}")
    update_ack_ledger(ledger, report, signals)
    audit_log(report, signals, mode)
    # One curated email per run, always from here — the merge-gate step that used to
    # send it in `auto` was retired with the mode (#2833).
    email_report(report, mode)
    # #1201: after the report/email/audit are written (operator is never left
    # blind), red the step if the loop didn't close — signals left untriaged with
    # a truncated `_raw` tail means the turn/token budget burned out mid-triage.
    # This must be the LAST thing so the run reports failure, not a false 'success'.
    if triage_incomplete(report):
        n = len(report.get("untriaged") or [])
        print(
            f"::error::Remediation triage did not complete — {n} signal(s) left untriaged with a "
            "truncated agent transcript (_raw present). The Bedrock turn/token budget likely burned "
            "out mid-investigation; see REMEDIATION_MAX_TURNS in remediation-agent.yml. Failing the "
            "step so the run reds instead of concluding a deceptive 'success' (#1201)."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
