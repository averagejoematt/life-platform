"""repeat_family.py — the same forecast filed more than once is ONE forecast, and the record says which (owner 2026-11-09).

THE RULING (owner, 2026-11-09 third message, B — verbatim intent). "Add stored family identifiers to the 14 repeated
calls. Each family supported by original wording, criteria and observation window. Distinct forecasts stay distinct.
Preserve all original rows. Deduplicate only where the approved methodology genuinely treats calls as one family.
Record the relationship + verification evidence so the denominator can be independently reproduced."

THE SHAPE. Per member call, ``mark`` writes, in this order:

  1. an append-only audit row on the call's own partition (``attribute_not_exists(sk)``)::

        pk = COACH#<coach_id>     sk = REPEATFAMILY#<prediction_id>#<marked_at ISO>
        {family_id, role, first, members, evidence, ruling_ref, marked_by, marked_at, prediction_id, ...}

     ``evidence`` is the family's whole case — every member's frozen criteria (metric, target day, condition, window,
     predicted value, tolerance), a sha256 of each member's stored words (the words stay on their rows) and why they
     are one forecast — so anyone holding the rows can re-derive the family and the denominator;
  2. ONE conditional ``SET repeat_family = :marker`` on the PREDICTION# row, only when the row has no marker yet. The
     marker is ``{family_id, role, first, members, ruling_ref, marked_at, audit_sk}``. Nothing else on the row moves:
     not the words, the criteria, the grade, the baseline or any timestamp.

``role`` is ``first`` (the earliest filed member — the one that stands in a count) or ``repeat``. Counting reads the
family off the verification record's classification (``web.verification_fields``: within a family the earliest
counted forecast stands, the rest are the same forecast, counted once); ``scripts/record_verification.py`` copies
the marker's ``family_id`` there, and refuses an entry whose family disagrees with the row's marker.

``validate_family`` is the methodology as code: members of one family share the frozen kind, metric, target day,
condition and window, and their predicted values differ by no more than ``MAX_VALUE_SPREAD`` of the smallest
tolerance. Anything else is a distinct forecast and is refused.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from common.numeric import floats_to_decimal
from experiment.phase_taxonomy import experiment_stamp_for

from coach import grade_corrections

ATTR = "repeat_family"
AUDIT_SK_PREFIX = "REPEATFAMILY#"
ROLES = ("first", "repeat")
#: The largest spread of predicted values one family may carry, as a share of the smallest member tolerance.
MAX_VALUE_SPREAD = 0.05
#: What every member of one family must share, read off the frozen evaluation spec.
SAME_FIELDS = ("type", "metric", "target_date", "condition", "evaluation_window_days")


class FamilyError(ValueError):
    """The members do not make one forecast under the methodology, or a marker would be overwritten."""


def claim_sha256(row: dict) -> str | None:
    words = str((row or {}).get("claim_natural") or "").strip()
    return hashlib.sha256(words.encode("utf-8")).hexdigest() if words else None


def key_of(row: dict) -> str:
    return f"{str(row.get('pk') or '').replace('COACH#', '', 1)}|{grade_corrections.prediction_id(row)}"


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def criteria_of(row: dict) -> dict:
    raw = row.get("evaluation")
    spec: dict = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {k: spec.get(k) for k in SAME_FIELDS}
    out["evaluation_window_days"] = _num(out["evaluation_window_days"])
    out.update(
        {
            "key": key_of(row),
            "created_at": str(row.get("created_at") or ""),
            "claim_sha256": claim_sha256(row),
            "threshold": _num(spec.get("threshold")),
            "tolerance": _num(spec.get("tolerance")),
            "status": row.get("status"),
        }
    )
    return out


def validate_family(rows: list[dict]) -> list[dict]:
    """The members' criteria, earliest filed first — or ``FamilyError`` when they are not one forecast."""
    if len(rows) < 2:
        raise FamilyError("a family has at least two members")
    crit = sorted((criteria_of(r) for r in rows), key=lambda c: (c["created_at"], c["key"]))
    for f in SAME_FIELDS:
        if len({repr(c[f]) for c in crit}) != 1:
            raise FamilyError(f"members differ on {f}: {[c[f] for c in crit]}")
    if any(c[f] in (None, "") for c in crit for f in ("type", "metric", "target_date")):
        raise FamilyError("a family is defined on a frozen kind, metric and target day")
    th = [c["threshold"] for c in crit]
    tol = [c["tolerance"] for c in crit]
    if any(v is None for v in th + tol):
        raise FamilyError("every member must carry a frozen predicted value and tolerance")
    if max(th) - min(th) > MAX_VALUE_SPREAD * min(tol):
        raise FamilyError(f"predicted values {th} differ by more than {MAX_VALUE_SPREAD:.0%} of the tolerance {min(tol)}")
    return crit


def family_id(crit: list[dict]) -> str:
    """Deterministic: the first member's filing day + a digest of the sorted member keys."""
    day = crit[0]["created_at"][:10].replace("-", "")
    digest = hashlib.sha256("\n".join(sorted(c["key"] for c in crit)).encode("utf-8")).hexdigest()[:8]
    return f"F{day}-{digest}"


def plan_family(
    rows: list[dict], *, why_same: str, ruling_ref: str, marked_by: str, marked_at: str, references: dict | None = None
) -> list[dict]:
    """``[{row, marker, audit}]`` for every member — pure. Refuses a row that already carries a marker."""
    if not (why_same and ruling_ref and marked_by):
        raise FamilyError("a family names why its members are the same, the ruling and who marked it")
    crit = validate_family(rows)
    fid = family_id(crit)
    first = crit[0]["key"]
    members = [c["key"] for c in crit]
    evidence = {"criteria": crit, "why_same": why_same, "same_fields": list(SAME_FIELDS), "max_value_spread": MAX_VALUE_SPREAD}
    if references:
        evidence["references"] = dict(references)
    out = []
    for row in sorted(rows, key=lambda r: members.index(key_of(r))):
        if row.get(ATTR):
            raise FamilyError(f"{key_of(row)} already carries {ATTR}: a marker is never overwritten")
        pk, pid = str(row["pk"]), grade_corrections.prediction_id(row)
        audit_sk = f"{AUDIT_SK_PREFIX}{pid}#{marked_at}"
        role = "first" if key_of(row) == first else "repeat"
        marker = {
            "family_id": fid,
            "role": role,
            "first": first,
            "members": members,
            "ruling_ref": ruling_ref,
            "marked_at": marked_at,
            "audit_sk": audit_sk,
        }
        audit = {
            **experiment_stamp_for(pk, audit_sk),
            "pk": pk,
            "sk": audit_sk,
            "record_type": "repeat_family",
            "prediction_id": pid,
            "prediction_sk": row.get("sk"),
            "coach_id": row.get("coach_id") or pk.replace("COACH#", "", 1),
            "family_id": fid,
            "role": role,
            "first": first,
            "members": members,
            "evidence": evidence,
            "ruling_ref": ruling_ref,
            "marked_by": marked_by,
            "marked_at": marked_at,
        }
        out.append({"row": row, "marker": marker, "audit": audit})
    return out


def write_marker(table: Any, row: dict, marker: dict, audit: dict) -> dict:
    """THE ONE WRITER of ``repeat_family``: the audit row first, then the marker — only onto an unmarked row whose grade
    is still the one the plan read. A failure between the two leaves a visible audit row and an unmarked call."""
    if audit.get("pk") != row.get("pk") or not str(audit.get("sk") or "").startswith(AUDIT_SK_PREFIX) or marker.get("role") not in ROLES:
        raise FamilyError("a family audit row lives on its call's own partition under REPEATFAMILY#")
    table.put_item(Item=floats_to_decimal(audit), ConditionExpression="attribute_not_exists(sk)")
    table.update_item(
        Key={"pk": row["pk"], "sk": row["sk"]},
        UpdateExpression=f"SET {ATTR} = :m",
        ConditionExpression=f"attribute_exists(sk) AND attribute_not_exists({ATTR}) AND #s = :st",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=floats_to_decimal({":m": marker, ":st": row.get("status")}),
    )
    return marker


def now_iso(now: datetime | None = None) -> str:
    return grade_corrections.now_iso(now)
