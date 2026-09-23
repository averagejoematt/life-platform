"""remediation/signal_identity.py — hand-offs with identity (#4034 box 5).

Every needs-human line the remediation agent sends now carries a STABLE SIGNAL ID keyed on
(alarm-or-check, StateTransitionedTimestamp), recorded in one ledger on the existing audit
trail — `s3://<bucket>/remediation-log/signal_ledger.json` — with `first_seen` and a
`renewals` count. A line whose underlying state timestamp has not moved is NOT re-emitted:
it is carried in a one-line "still open" list with its renewal count. The same alarm going
red AGAIN (a new transition) is a new id and a new line.

Before this, the only identity a hand-off had was the alarm NAME inside prose. The aged
escalation (#1204) re-sent the same paragraph every Mon/Wed/Fri run for as long as the alarm
stayed red, so a line that had been read and acted on looked identical to one nobody had
seen, and "how many pages did we send, and how many did anyone act on?" was unanswerable.
`scripts/monthly_close.py` now answers it from this ledger (pages-sent / pages-acted-on /
ratio, and the DEMOTE-candidate list for alarms with zero true pages in 90 days).

THE #3443 CO-OWNED-RECORD TRAP, and what this module does about it
  #3443: a from-scratch re-put by one writer silently erased fields another writer had
  merged onto the same record, nightly, for nine days, with nothing watching. The ledger
  here has the same shape of risk — a scheduled run and a repository_dispatch run can
  overlap, each read-modify-writing the same object. So:
    * the write is a MERGE, never a replace: `merge()` keeps every entry it did not touch,
      and `save()` writes with an S3 conditional put (IfMatch on the ETag it read,
      IfNoneMatch for a first write) and on a precondition failure RE-READS and re-merges —
      contract-tested in tests/test_signal_identity_4034.py against a concurrent writer;
    * `_meta.merged_at` is written ONLY by the merger, and its age is the dead-man: the next
      agent run emits a needs-human line when it is older than MERGER_STALE_HOURS, and the
      monthly close fails on it. (An S3 LastModified would be bumped by any writer — the
      co-owned-timestamp version of the same trap.)

Pure except `load()`/`save()`, which take the S3 client as a parameter — no boto3 at import,
so `scripts/monthly_close.py` reads the ledger through the SAME module that writes it.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

SIGNAL_LEDGER_KEY = "remediation-log/signal_ledger.json"
SIGNAL_LEDGER_SCHEMA = 1
META = "_meta"

# The agent runs Mon/Wed/Fri: the longest designed gap is Fri -> Mon, 72h. 96h means one
# missed run is named by the next run that does happen.
MERGER_STALE_HOURS = 96
_SAVE_ATTEMPTS = 3


def _iso(dt) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalize_state_ts(ts) -> str:
    """One spelling per instant, so the same transition always yields the same id."""
    dt = _parse(ts)
    return _iso(dt) if dt else str(ts or "")


def signal_id(check: str, state_ts) -> str:
    return f"{check}@{normalize_state_ts(state_ts)}"


# ── keying a needs-human item ───────────────────────────────────────────────


def key_item(item: dict, signals: dict) -> tuple[str, str, str]:
    """(check, state_ts, kind) for one needs-human item.

    Deterministic items carry `item["signal"] = {"check", "state_ts"}` (set where they are
    built). An LLM-written line is keyed on the ONE alarm or stale secret it names, taking
    that signal's transition / LastChangedDate; a line naming none (or several) is keyed on
    a hash of its text — `kind="unkeyed"`, reported as such, never passed off as stable."""
    sig = item.get("signal") if isinstance(item.get("signal"), dict) else None
    if sig and sig.get("check"):
        return sig["check"], normalize_state_ts(sig.get("state_ts")), sig.get("kind", "alarm")
    text = f"{item.get('issue', '')} {item.get('action', '')}"
    alarms = [
        a for a in signals.get("alarms", []) or [] if a.get("name") and re.search(rf"(?<![\w-]){re.escape(a['name'])}(?![\w-])", text)
    ]
    if len(alarms) == 1:
        a = alarms[0]
        return a["name"], normalize_state_ts(a.get("transitioned") or a.get("updated")), "alarm"
    secrets = [s for s in signals.get("secrets_stale", []) or [] if s.get("name") and s["name"] in text]
    if len(secrets) == 1:
        s = secrets[0]
        return f"secret:{s['name']}", normalize_state_ts(s.get("last_changed")), "secret"
    digest = hashlib.sha256(str(item.get("issue", "")).strip().encode()).hexdigest()[:12]
    return f"agent-note:{digest}", "", "unkeyed"


# ── the ledger ──────────────────────────────────────────────────────────────


def empty_ledger() -> dict:
    return {META: {"schema": SIGNAL_LEDGER_SCHEMA}}


def load(s3, bucket, key=SIGNAL_LEDGER_KEY):
    """(ledger, etag). A missing object is an empty ledger with etag None; any other read
    failure RAISES — writing over a ledger we could not read is the #3443 erasure."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except Exception as e:  # noqa: BLE001
        code = ((getattr(e, "response", None) or {}).get("Error") or {}).get("Code")
        if code in ("NoSuchKey", "404") or type(e).__name__ == "NoSuchKey":
            return empty_ledger(), None
        raise
    data = json.loads(obj["Body"].read().decode())
    if not isinstance(data, dict) or (data.get(META) or {}).get("schema") != SIGNAL_LEDGER_SCHEMA:
        raise ValueError(f"{key}: unrecognised schema — refusing to merge over it")
    return data, obj.get("ETag")


def merge(ledger: dict, observations: list[dict], now) -> tuple[dict, list[str], list[str]]:
    """Merge one run's observations into `ledger` (mutated and returned).

    observations: [{"id", "check", "state_ts", "kind", "summary", "acted_on": bool}]
    Returns (ledger, new_ids, renewed_ids). Entries not observed this run are untouched —
    the merge never drops a record it did not write."""
    now_iso = _iso(now)
    new_ids, renewed = [], []
    for ob in observations:
        sid = ob["id"]
        entry = ledger.get(sid)
        if entry is None:
            ledger[sid] = {
                "check": ob["check"],
                "state_ts": ob["state_ts"],
                "kind": ob.get("kind", "alarm"),
                "first_seen": now_iso,
                "last_seen": now_iso,
                "renewals": 0,
                "summary": str(ob.get("summary", ""))[:300],
                "acted_on_at": now_iso if ob.get("acted_on") else None,
            }
            new_ids.append(sid)
        else:
            if entry.get("last_seen") != now_iso:  # idempotent within one run's merge
                entry["renewals"] = int(entry.get("renewals", 0) or 0) + 1
                entry["last_seen"] = now_iso
            if ob.get("acted_on") and not entry.get("acted_on_at"):
                entry["acted_on_at"] = now_iso
            renewed.append(sid)
    meta = ledger.setdefault(META, {"schema": SIGNAL_LEDGER_SCHEMA})
    meta["schema"] = SIGNAL_LEDGER_SCHEMA
    meta.setdefault("created_at", now_iso)
    meta["merged_at"] = now_iso  # written by the merger ONLY — the dead-man reads this field
    meta["merges"] = int(meta.get("merges", 0) or 0) + 1
    return ledger, new_ids, renewed


def _is_precondition_failure(e) -> bool:
    resp = getattr(e, "response", None) or {}
    code = (resp.get("Error") or {}).get("Code")
    return code in ("PreconditionFailed", "412", "ConditionalRequestConflict")


def save(s3, bucket, observations, now, key=SIGNAL_LEDGER_KEY):
    """Read-merge-write with an S3 conditional put; on a lost race, re-read and re-merge.
    Returns (ledger, new_ids, renewed_ids) from the merge that actually landed."""
    last_err = None
    for _ in range(_SAVE_ATTEMPTS):
        ledger, etag = load(s3, bucket, key)
        ledger, new_ids, renewed = merge(ledger, observations, now)
        body = json.dumps(ledger, indent=2, sort_keys=True).encode()
        cond = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json", **cond)
            return ledger, new_ids, renewed
        except Exception as e:  # noqa: BLE001
            if not _is_precondition_failure(e):
                raise
            last_err = e
    raise RuntimeError(f"signal ledger: lost the write race {_SAVE_ATTEMPTS} times ({last_err})")


# ── the merger's own dead-man ───────────────────────────────────────────────


def merger_age_hours(ledger: dict, now) -> float | None:
    merged = _parse((ledger.get(META) or {}).get("merged_at"))
    return None if merged is None else (now - merged).total_seconds() / 3600.0


def merger_deadman_item(ledger: dict, now) -> dict | None:
    """A needs-human line when the ledger's merger has not run within MERGER_STALE_HOURS.
    A never-merged (empty) ledger is not stale — it is the first run."""
    age = merger_age_hours(ledger, now)
    if age is None or age <= MERGER_STALE_HOURS:
        return None
    merged_at = ledger[META]["merged_at"]
    return {
        "issue": f"The needs-human signal ledger ({SIGNAL_LEDGER_KEY}) was last merged {age / 24:.1f}d ago "
        f"({merged_at}), past the {MERGER_STALE_HOURS}h bar (#4034) — runs in between sent hand-offs with no identity record.",
        "action": "Find the remediation-agent runs since then (gh run list -w remediation-agent.yml) and read why the "
        "merge step did not land; pages sent in the gap are missing from the monthly close's pages-sent count.",
        "signal": {"check": "signal-ledger-merger", "state_ts": merged_at, "kind": "deadman"},
    }


# ── applying identity to a report ───────────────────────────────────────────


def observations_for(report: dict, signals: dict, acted_on_checks=frozenset()) -> list[dict]:
    """One observation per needs-human item (first item wins per id), each item stamped
    in place with its `signal_id`."""
    seen, out = set(), []
    for item in report.get("needs_human", []) or []:
        if not isinstance(item, dict):
            continue
        check, state_ts, kind = key_item(item, signals)
        sid = signal_id(check, state_ts)
        item["signal_id"] = sid
        if sid in seen:
            continue
        seen.add(sid)
        out.append(
            {
                "id": sid,
                "check": check,
                "state_ts": state_ts,
                "kind": kind,
                "summary": item.get("issue", ""),
                "acted_on": check in acted_on_checks,
            }
        )
    return out


def partition(report: dict, ledger: dict, new_ids) -> dict:
    """Keep first emissions in `needs_human`; move lines whose state has not moved to
    `carried` (id + renewals + first_seen) — the refusal to re-emit."""
    new = set(new_ids)
    keep, carried, carried_ids = [], [], set()
    for item in report.get("needs_human", []) or []:
        sid = item.get("signal_id") if isinstance(item, dict) else None
        if sid is None or sid in new:
            keep.append(item)
            continue
        if sid in carried_ids:
            continue
        carried_ids.add(sid)
        entry = ledger.get(sid, {})
        carried.append(
            {"signal_id": sid, "first_seen": entry.get("first_seen"), "renewals": entry.get("renewals", 0), "issue": item.get("issue", "")}
        )
    report["needs_human"] = keep
    if carried:
        report["carried"] = carried
    return report


def acted_on_checks(signals: dict, citations: dict, post_dates) -> set:
    """Alarms whose CURRENT episode has a citation stamped after it began — the operator
    provably looked. `post_dates` is scripts/alarm_citation_age.post_dates (one predicate
    for "looked after it went red", shared with the #4034 AGE gate)."""
    out = set()
    for a in signals.get("alarms", []) or []:
        name = a.get("name")
        entry = citations.get(name) if name else None
        if not entry:
            continue
        stamp = str(entry.get("cause_observed") or entry.get("added") or "")
        if post_dates(stamp, _parse(a.get("transitioned") or a.get("updated"))):
            out.add(name)
    return out


# ── the monthly close's read (scripts/monthly_close.py) ─────────────────────


def page_accounting(ledger: dict, month_start, month_end_exclusive, alarm_inventory, now, window_days=90) -> dict:
    """pages-sent / pages-acted-on / ratio for the month, and the DEMOTE candidates:
    every alarm in the inventory with zero ACTED-ON pages in the trailing `window_days`.

    `coverage_days` is how much of that window the ledger has actually observed; below
    `window_days` the demote list is PROVISIONAL (an alarm cannot be judged on history the
    ledger never saw), and the close says so rather than presenting it as a finding."""
    start = datetime.combine(month_start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(month_end_exclusive, datetime.min.time(), tzinfo=timezone.utc)
    horizon = now - timedelta(days=window_days)
    sent = acted = 0
    true_paged: set = set()
    for sid, e in ledger.items():
        if sid == META or not isinstance(e, dict):
            continue
        first = _parse(e.get("first_seen"))
        if first is None:
            continue
        if start <= first < end:
            sent += 1
            if e.get("acted_on_at"):
                acted += 1
        if first >= horizon and e.get("acted_on_at") and e.get("kind") == "alarm":
            true_paged.add(e.get("check"))
    created = _parse((ledger.get(META) or {}).get("created_at"))
    coverage = 0.0 if created is None else max(0.0, (now - max(created, horizon)).total_seconds() / 86400.0)
    return {
        "pages_sent": sent,
        "pages_acted_on": acted,
        "ratio": (acted / sent) if sent else None,
        "demote_candidates": sorted(set(alarm_inventory) - true_paged),
        "coverage_days": round(coverage, 1),
        "window_days": window_days,
        "provisional": coverage < window_days,
    }
