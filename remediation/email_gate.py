"""remediation/email_gate.py — send the remediation email only when the hand-off changed (#5821).

The agent runs Mon/Wed/Fri plus every urgent `repository_dispatch`, and until #5821 every run
sent one email. #4034 already stopped a line whose state had not moved from being re-sent as
NEW (it moves to the "still open" list), but the email itself still went out, carrying the
same eleven needs-human items and nine carried signals the digest, the CI history and the
open issues already showed. Owner ruling 2026-11-11: send it only when the needs-human list
CHANGED since the last send.

THE FINGERPRINT is the set of signal ids the email hands the owner — `needs_human` (new
lines) plus `carried` (still-open lines), both stamped with `signal_id` by
`signal_identity.observations_for` — and the PRs awaiting review (a PR is a hand-off too).
A new alarm transition is a new id, so it changes the fingerprint; an item clearing removes
its id, so "all clear" after a non-empty send also changes it and is sent once. A line with
no id (the ledger-failure line) is keyed on a hash of its text.

STATE lives where the agent already keeps it: one small JSON object under the
`remediation-log/` prefix of the bucket it already writes (`LAST_SENT_KEY`) — the remediation
role's existing `remediation-log/*` grant, no new infra. It is written only AFTER a successful
send, so a failed send is retried by the next run.

FAIL-OPEN TOWARDS SENDING: an unreadable record means "send". Losing a hand-off is worse than
one repeated email. A manual `workflow_dispatch` always sends (the owner asked for it).

Pure except `load_last_sent`/`save_last_sent`, which take the S3 client as a parameter.
"""

from __future__ import annotations

import hashlib
import json

LAST_SENT_KEY = "remediation-log/last_email_fingerprint.json"
SCHEMA = 1


def _line_key(item) -> str:
    if isinstance(item, dict) and item.get("signal_id"):
        return f"id:{item['signal_id']}"
    text = item.get("issue", "") if isinstance(item, dict) else str(item)
    return "text:" + hashlib.sha256(" ".join(str(text).split()).encode()).hexdigest()[:16]


def handoff_keys(report: dict) -> list[str]:
    """The sorted, de-duplicated hand-off the email carries."""
    keys = {_line_key(i) for i in (report.get("needs_human") or [])}
    keys |= {_line_key(i) for i in (report.get("carried") or [])}
    keys |= {f"pr:{i.get('pr', '')}" if isinstance(i, dict) else f"pr:{i}" for i in (report.get("prs") or [])}
    return sorted(keys)


def fingerprint(report: dict) -> str:
    return hashlib.sha256("\n".join(handoff_keys(report)).encode()).hexdigest()


def should_send(report: dict, last: dict | None, event_name: str = "") -> tuple[bool, str]:
    """(send?, reason). `last` is the stored record, or None when there is none/unreadable."""
    if event_name == "workflow_dispatch":
        return True, "manual dispatch always sends"
    if not last or last.get("schema") != SCHEMA or not last.get("fingerprint"):
        return True, "no prior send on record"
    if last["fingerprint"] != fingerprint(report):
        return True, "the needs-human hand-off changed since the last send"
    return False, f"needs-human hand-off unchanged since the send at {last.get('sent_at', '?')}"


def load_last_sent(s3, bucket, key=LAST_SENT_KEY) -> dict | None:
    """The stored record, or None (missing OR unreadable — both mean send)."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read().decode())
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001 — fail-open towards sending, by design
        print(f"[info] last-email record unreadable ({type(e).__name__}) — sending")
        return None


def save_last_sent(s3, bucket, report: dict, sent_at: str, key=LAST_SENT_KEY) -> None:
    record = {"schema": SCHEMA, "fingerprint": fingerprint(report), "keys": handoff_keys(report), "sent_at": sent_at}
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(record, indent=2).encode(), ContentType="application/json")
    except Exception as e:  # noqa: BLE001 — a write failure means the next run sends again; never block
        print(f"[warn] last-email record write: {e}")
