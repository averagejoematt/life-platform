"""emails/panelcast_hold.py — #6112: the owner's explicit HOLD on a Panel week, and the one refusal every publisher calls.

WHY THIS EXISTS (owner ruling 2026-11-16). Week 10's chronicle was approved and delivered on 2026-11-14 and its Panel
episode was deliberately NOT published, because the Story Desk's script for it retained two blocking audit findings.
That decision was never recorded anywhere a reader of publication state looks: not under ``panelcast-holds/`` (the
Panel's private hold store, read by the lambda and its sweep), not in ``episodes.json``'s ``pending`` marker (the
public face qa-smoke reads); the Panel was simply never invoked for the week. qa-smoke's
``story_season:episode_or_hold`` therefore read week 10 as silently skipped. And the decision had no force of its
own: what kept the script off air was only the desk's findings still sitting on the chronicle row (a manual invoke or
a DLQ redrive would have turned them into an AUTOMATED safety hold) — a row edit or desk re-run that cleared them would
have let the next run publish, and a season promote or re-cut reads no hold at all.

THE SHAPE — the existing hold store, one class wider. A hold is ``panelcast-holds/wk{N}.json`` (private) — the record
``_hold_and_alert`` already writes for an automated safety/quality hold. An owner hold is the same object with
``hold_class: "owner"`` and the fields that make it a decision rather than a gate result (``record_problems``): who
decided, when, why, the findings it preserves (ids + hashes + where their text lives; the text itself only in this
private object), and what lifts it. Its public face is one line in ``episodes.json``'s ``held`` list
(``public_entry``: week, date, decider, a reason with no private detail). The script that records the hold writes
that line, and every later index write (``panelcast_retire.index_doc``) RE-DERIVES it from the private records, so a
later week's publish can neither drop nor invent one. The private record is the authority; the public line is its
projection, read by qa-smoke, whose role cannot read ``panelcast-holds/``.

HOW IT DIFFERS FROM THE OTHER TWO MARKERS.
  * an automated hold (``safety``/``quality``) is a gate result: a later run that passes every gate publishes over
    it (``{"owner_approved": true}`` answers the legacy writer's audit), and qa-smoke escalates it at 7 days.
  * a retired week (``wk{N}.retired.json``) will never air.
  * an OWNER hold is neither: nothing automatic publishes over it (``force`` and ``owner_approved`` included), it is
    lifted only by an explicit owner release (``panel_owner_hold.py --release``), and the week can be revisited.

FAIL CLOSED. ``refuse`` raises when the hold store cannot be listed or a hold object cannot be read or parsed — a
publisher that cannot prove a week is not held does not publish it. The cost is that a broken hold store stops every
Panel publish until it is readable; that is the direction the owner asked for.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from common.pacific_time import parse_iso_utc  # #3609: THE ISO-8601 parser

OWNER_CLASS = "owner"
STATUS_HELD = "held"  # neither "delivered" nor "missing" — the third state qa-smoke reads
PUBLIC_KEY = "held"  # episodes.json's list of owner-held weeks
REFUSED_TOKEN = "PANELCAST-OWNER-HOLD-REFUSED"  # noqa: S105 — a log token, not a credential
_HOLD_KEY_RE = re.compile(r"(?:^|/)wk(\d+)\.json$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HeldWeekRefused(RuntimeError):
    """A publisher was asked to publish a week the owner holds."""


class HoldStateUnreadable(RuntimeError):
    """The hold store could not be read — no publisher may assume a week is not held."""


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _iso_day(v: Any) -> Optional[datetime]:
    """The day a hold was decided, as midnight UTC — through THE ISO parser (#3609), never a hand-rolled one."""
    return parse_iso_utc(str(v)[:10]) if v else None


def _text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


# ── the record ──────────────────────────────────────────────────────────────


def finding_problems(f: Any) -> List[str]:
    if not isinstance(f, dict):
        return ["a finding is not an object"]
    out = [f"finding is missing {k}" for k in ("id", "category", "source") if not _text(f.get(k))]
    if not _SHA256_RE.match(str(f.get("sha256") or "")):
        out.append("finding sha256 is not a 64-hex digest")
    return out


def record_problems(rec: Any) -> List[str]:
    """Why ``rec`` is not a complete owner hold (empty = complete). Used by the writer before it writes and by the
    read-back after; a publisher refuses on ANY owner-class record, complete or not (fail closed)."""
    if not isinstance(rec, dict):
        return ["the hold record is not a JSON object"]
    out: List[str] = []
    wk = _int(rec.get("week"))
    if wk is None or wk < 0:
        out.append("week is not a non-negative integer")
    if rec.get("hold_class") != OWNER_CLASS:
        out.append(f"hold_class is {rec.get('hold_class')!r}, not {OWNER_CLASS!r}")
    if rec.get("status") != STATUS_HELD:
        out.append(f"status is {rec.get('status')!r}, not {STATUS_HELD!r}")
    if _iso_day(rec.get("decided_at")) is None:
        out.append("decided_at is not an ISO date")
    for k in ("decided_by", "reason", "lift"):
        if not _text(rec.get(k)):
            out.append(f"{k} is empty")
    findings = rec.get("findings")
    if not isinstance(findings, list):
        out.append("findings is not a list (an empty list is a hold with no findings)")
    else:
        out += [p for f in findings for p in finding_problems(f)]
    return out


def is_owner_hold(rec: Any) -> bool:
    return isinstance(rec, dict) and rec.get("hold_class") == OWNER_CLASS


def public_entry(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The line episodes.json carries for an owner hold — no finding text, no script text."""
    n = len(rec.get("findings") or [])
    reason = str(rec.get("public_reason") or "").strip() or (
        f"held by the owner: the script retained {n} blocking audit finding{'s' if n != 1 else ''}" if n else "held by the owner"
    )
    return {
        "week": _int(rec.get("week")),
        "status": STATUS_HELD,
        "held_at": str(rec.get("decided_at"))[:10],
        "decided_by": str(rec.get("decided_by")),
        "reason": reason,
    }


def public_problems(entry: Any) -> List[str]:
    """Why a public ``held`` line is not a hold qa-smoke can accept (empty = valid). An empty or malformed marker is
    NOT a hold: the week then reads as missing."""
    if not isinstance(entry, dict):
        return ["not an object"]
    out: List[str] = []
    wk = _int(entry.get("week"))
    if wk is None or wk < 0:
        out.append("no week")
    if _iso_day(entry.get("held_at")) is None:
        out.append("no held_at date")
    for k in ("decided_by", "reason"):
        if not _text(entry.get(k)):
            out.append(f"no {k}")
    return out


# ── the store ───────────────────────────────────────────────────────────────


def owner_held_weeks(s3: Any, bucket: str, prefix: str) -> Dict[int, Dict[str, Any]]:
    """``{week: record}`` for every owner hold under ``prefix``. Raises ``HoldStateUnreadable`` on any list, read or
    parse failure — one prefix list (the role's PanelcastHoldsList grant) plus a GetObject per ``wk{N}.json``."""
    out: Dict[int, Dict[str, Any]] = {}
    try:
        token = None
        keys: List[str] = []
        while True:
            kw: Dict[str, Any] = {"Bucket": bucket, "Prefix": f"{prefix}/"}
            if token:
                kw["ContinuationToken"] = token
            resp = s3.list_objects_v2(**kw)
            keys += [str(o.get("Key", "")) for o in resp.get("Contents") or [] if _HOLD_KEY_RE.search(str(o.get("Key", "")))]
            token = resp.get("NextContinuationToken") if resp.get("IsTruncated") else None
            if not token:
                break
        for key in keys:
            rec = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
            if is_owner_hold(rec):
                wk = _int(rec.get("week"))
                out[int(_HOLD_KEY_RE.search(key).group(1)) if wk is None else wk] = rec  # type: ignore[union-attr]
    except Exception as e:  # noqa: BLE001 — every failure is the same answer: cannot prove a week is not held
        raise HoldStateUnreadable(f"the Panel hold store s3://{bucket}/{prefix}/ could not be read: {e}") from e
    return out


def refuse(weeks: Any, *, _g: Dict[str, Any]) -> None:
    """THE refusal. Raises ``HeldWeekRefused`` when any of ``weeks`` is owner-held, ``HoldStateUnreadable`` when the
    store cannot be read. Called at the Panel's two publish chokepoints (``_publish_episode_audio`` and
    ``_write_indexes``), so the lambda, ``scripts/season_promote.py`` and ``scripts/panel_recut.py`` all pass through it."""
    wanted = {w for w in (_int(x) for x in weeks) if w is not None}
    try:
        held = owner_held_weeks(_g["s3"], _g["S3_BUCKET"], _g["HOLD_PREFIX"])
    except HoldStateUnreadable as e:
        _g["logger"].error("%s weeks %s: hold state UNREADABLE — refusing to publish (fail closed): %s", REFUSED_TOKEN, sorted(wanted), e)
        raise
    hit = sorted(wanted & set(held))
    if hit:
        _g["logger"].error(
            "%s weeks %s are held by the owner (%s) — refusing to publish; only an explicit owner release lifts it",
            REFUSED_TOKEN,
            hit,
            "; ".join(f"wk{w}: {held[w].get('reason')}" for w in hit),
        )
        raise HeldWeekRefused(f"Panel week(s) {hit} are held by the owner — release the hold first (scripts/panel_owner_hold.py --release)")


def run_skip(week: Any, dry_run: bool, _g: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The weekly run's answer for an owner-held week (None when it is not held) — checked before any generation, so a
    held week spends no inference and ``force``/``owner_approved`` never reach a writer."""
    try:
        refuse([week], _g=_g)
        return None
    except HeldWeekRefused:
        if dry_run:
            return _g["_dry"](week, "SKIP", stage="owner-hold")
        return {"statusCode": 200, "body": json.dumps({"week": week, "held": OWNER_CLASS})}
    except HoldStateUnreadable as e:
        return {"statusCode": 503, "body": json.dumps({"week": week, "refused": "hold state unreadable", "error": str(e)[:200]})}


def build_record(
    week: int,
    *,
    decided_at: str,
    decided_by: str,
    ruling: str,
    reason: str,
    findings: List[Dict[str, Any]],
    lift: str,
    refs: str = "",
    bound_to: Optional[Dict[str, Any]] = None,
    prior: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An owner hold record. ``prior`` (an automated hold already on the key) is kept whole under ``superseded_hold``."""
    rec: Dict[str, Any] = {
        "week": int(week),
        "hold_class": OWNER_CLASS,
        "status": STATUS_HELD,
        "decided_at": decided_at,
        "decided_by": decided_by,
        "ruling": ruling,
        "reason": reason,
        "findings": findings,
        "lift": lift,
        # the fields the lambda's own hold readers already use (_hold_age_days, the SS-02 sweep)
        "held_at": decided_at,
        "first_held_at": (prior or {}).get("first_held_at") or decided_at,
        "retry_count": 0,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    if refs:
        rec["refs"] = refs
    if bound_to:
        rec["bound_to"] = bound_to
    if prior:
        rec["superseded_hold"] = prior
    return rec
