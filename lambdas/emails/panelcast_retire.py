"""panelcast_retire.py — #4536: retire a held Panel week BY NAME (owner ruling 2026-10-18, "retire weeks 5 and 6").

A safety hold is human-review only, and the owner may rule that a held week never airs. Retiring is a MARKER beside
the hold, never a release:

  * `{"week": N, "retire": true}` writes `panelcast-holds/wk{N}.retired.json` next to the hold record and removes
    nothing under panelcast-holds/. The hold record, its `hold_class` and the safety gates are not changed — the
    marker copies the hold's reasons for the audit trail only.
  * A retired week is skipped by `_select_week_post` (the newest NON-retired week is the current one), the hold
    sweep (SKIP "retired") and the weekly run (`{"week": N}` on a retired week returns `{"week": N, "retired": true}`
    without generating, `force` and `owner_approved` included).
  * `{"week": N, "unretire": true}` is the reversal: the marker goes, and the week is held exactly as before.
  * `dry_run` reports what it would do and writes nothing.

Public face: episodes.json carries `retired: [{week, retired_at}]` (no reasons — they can name sensitive content
and stay in the private marker), kept across every publish, so qa-smoke's story_season:episode_or_hold and the site
read the week as accounted for, never as a missing episode. The "held for review" `pending` line that named the
retired week is dropped; unretire restores it while the hold record stands.

Functions take `_g` (the Panel lambda's globals) like panelcast_desk, so the lambda's `s3` client, bucket and hold
helpers stay the one source.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

RETIRED_BY = "owner ruling 2026-10-18"
_RETIRED_KEY_RE = re.compile(r"/wk(\d+)\.retired\.json$")


def retired_key(_g: dict, week) -> str:
    return f"{_g['HOLD_PREFIX']}/wk{week}.retired.json"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def retired_weeks(_g: dict) -> set:
    """Every week with a retire marker, from ONE prefix list (the role's `PanelcastHoldsList` grant is conditioned
    on `s3:prefix` = panelcast-holds/*, which a prefix list matches). A failed list is logged and reads as none
    retired: the week then runs every gate, the safety class included — the failure direction is a fresh hold,
    never an unsafe publish."""
    weeks: set = set()
    try:
        token = None
        while True:
            kw = {"Bucket": _g["S3_BUCKET"], "Prefix": f"{_g['HOLD_PREFIX']}/"}
            if token:
                kw["ContinuationToken"] = token
            resp = _g["s3"].list_objects_v2(**kw)
            for obj in resp.get("Contents") or []:
                m = _RETIRED_KEY_RE.search(str(obj.get("Key", "")))
                if m:
                    weeks.add(int(m.group(1)))
            token = resp.get("NextContinuationToken") if resp.get("IsTruncated") else None
            if not token:
                return weeks
    except Exception as e:  # noqa: BLE001
        _g["logger"].warning("[panel] retired-week list FAILED — %s; no week reads as retired this run", e)
        return set()


def is_retired(_g: dict, week) -> bool:
    return _int(week) in retired_weeks(_g)


def choose(weekly: list, _g: dict) -> dict:
    """The newest current-cycle week that is NOT retired. The weeks retired above it ride on the post as
    `skipped_retired`; when every week is retired the newest is returned flagged `retired` (nothing is chosen)."""
    retired = retired_weeks(_g)
    live = [p for p in weekly if _int(p.get("week")) not in retired]
    newest = max(weekly, key=lambda p: p["date"])
    if not live:
        return {**newest, "retired": True, "skipped_retired": sorted({_int(p["week"]) for p in weekly}, reverse=True)}
    chosen = max(live, key=lambda p: p["date"])
    newer = sorted({_int(p["week"]) for p in weekly if _int(p.get("week")) in retired and p["date"] > chosen["date"]}, reverse=True)
    return {**chosen, "skipped_retired": newer} if newer else chosen


def run_skip(post: dict, week, dry_run: bool, _g: dict):
    """The weekly run's answer for a retired week (None when it is not retired) — checked before the
    already-published short-circuit, so `force` never generates a retired week."""
    if not (post.get("retired") or is_retired(_g, week)):
        return None
    _g["logger"].info("[panel] wk%s retired by name — not generating (outcome=retired)", week)
    if dry_run:
        return _g["_dry"](week, "SKIP", stage="retired")
    return {"statusCode": 200, "body": json.dumps({"week": week, "retired": True})}


def sweep_skip(post: dict, _g: dict):
    """The hold sweep's SKIP for a retired current week (None when the current week is live). A week retired
    ABOVE the selected one is still the current week, so the sweep retries nothing that run."""
    week = post.get("week")
    newer = list(post.get("skipped_retired") or [])
    if not newer and not is_retired(_g, week):
        return None
    for w in newer or [week]:
        _g["logger"].info("[panel] hold sweep wk%s SKIP — retired (by name; the hold record stands, untouched)", w)
    return {"swept": [], "week": newer[0] if newer else week, "skipped": "retired"}


def episodes_doc(_g: dict) -> dict:
    try:
        doc = json.loads(_g["s3"].get_object(Bucket=_g["S3_BUCKET"], Key=f"{_g['PREFIX']}/episodes.json")["Body"].read())
        return doc if isinstance(doc, dict) else {"episodes": []}
    except Exception:  # noqa: BLE001
        return {"episodes": []}


def index_doc(episodes: list, _g: dict) -> dict:
    """episodes.json as a publish writes it: the episodes, plus the weeks retired by name that never aired."""
    aired = {str(e.get("week")) for e in episodes}
    kept = [r for r in episodes_doc(_g).get("retired") or [] if isinstance(r, dict) and str(r.get("week")) not in aired]
    return {"episodes": episodes, "retired": kept} if kept else {"episodes": episodes}


def _write_doc(doc: dict, _g: dict) -> None:
    _g["s3"].put_object(
        Bucket=_g["S3_BUCKET"],
        Key=f"{_g['PREFIX']}/episodes.json",
        Body=json.dumps(doc, indent=1),
        ContentType="application/json",
        CacheControl="max-age=3600, public",
    )
    _g["_invalidate_cdn"]()


def retire(week: int, dry_run: bool, _g: dict) -> dict:
    """Write the retire marker beside week N's hold; remove nothing in panelcast-holds/. A week with a published
    episode is refused — retire is for a week that never aired."""
    if _g["_episode_published"](week):
        return {"week": week, "retire": "refused", "reason": "the week has a published episode — retire is for a week that never aired"}
    hold = _g["_read_hold"](week)
    marker = {
        "week": week,
        "retired_at": datetime.now(timezone.utc).isoformat(),
        "reason": "retired by name — the held episode will not air; the next episode is the next week's",
        "retired_by": RETIRED_BY,
        "hold_found": bool(hold),
        "hold_class": hold.get("hold_class"),
        "hold_reasons": list(hold.get("reasons") or []),
        "first_held_at": hold.get("first_held_at"),
        "hold_key": f"{_g['HOLD_PREFIX']}/wk{week}.json",
    }
    key = retired_key(_g, week)
    doc = episodes_doc(_g)
    pending = doc.get("pending") if isinstance(doc.get("pending"), dict) else None
    drops_pending = bool(pending and str(pending.get("week")) == str(week))
    if dry_run:
        return {"dry_run": True, "week": week, "would": "RETIRE", "marker_key": key, "marker": marker, "drops_pending": drops_pending}
    _g["s3"].put_object(Bucket=_g["S3_BUCKET"], Key=key, Body=json.dumps(marker, indent=1).encode("utf-8"), ContentType="application/json")
    others = [r for r in doc.get("retired") or [] if isinstance(r, dict) and str(r.get("week")) != str(week)]
    doc["retired"] = sorted(others + [{"week": week, "retired_at": marker["retired_at"]}], key=lambda r: _int(r.get("week")) or 0)
    if drops_pending:
        doc.pop("pending", None)
    try:
        _write_doc(doc, _g)
    except Exception as e:  # noqa: BLE001 — the private marker is the decision; the public line is its face
        _g["logger"].error("[panel] wk%s retired, but the episodes.json write failed — %s", week, e)
    _g["logger"].warning("[panel] wk%s RETIRED by name (%s) — marker %s; hold record untouched", week, RETIRED_BY, key)
    return {"week": week, "retired": True, "marker_key": key, "hold_found": bool(hold), "dropped_pending": drops_pending}


def unretire(week: int, dry_run: bool, _g: dict) -> dict:
    """The reversal: delete the marker, take the week off the public `retired` list, and restore the "held for
    review" line while the hold record is still there."""
    key = retired_key(_g, week)
    if dry_run:
        return {"dry_run": True, "week": week, "would": "UNRETIRE", "marker_key": key, "was_retired": is_retired(_g, week)}
    hold = _g["_read_hold"](week)
    _g["s3"].delete_object(Bucket=_g["S3_BUCKET"], Key=key)
    doc = episodes_doc(_g)
    doc["retired"] = [r for r in doc.get("retired") or [] if isinstance(r, dict) and str(r.get("week")) != str(week)]
    if not doc["retired"]:
        doc.pop("retired")
    try:
        _write_doc(doc, _g)
    except Exception as e:  # noqa: BLE001
        _g["logger"].error("[panel] wk%s unretired, but the episodes.json write failed — %s", week, e)
    if hold:
        _g["_set_pending"](week, "held_for_review", _g["HELD_DISPLAY"])
    _g["logger"].warning("[panel] wk%s UNRETIRED — marker removed; the hold (%s) stands", week, hold.get("hold_class") or "none")
    return {"week": week, "unretired": True, "hold_found": bool(hold)}


def route(event: dict, dry_run: bool, _g: dict) -> dict:
    """`{"week": N, "retire": true}` / `{"week": N, "unretire": true}` — no AI, so the handler routes it before the
    budget gate."""
    week = _int(event.get("week"))
    if week is None or week < 1 or (event.get("retire") and event.get("unretire")):
        return {"statusCode": 400, "body": json.dumps({"error": 'one of retire/unretire, with {"week": N} and N >= 1'})}
    try:
        out = unretire(week, dry_run, _g) if event.get("unretire") else retire(week, dry_run, _g)
        return {"statusCode": 200, "body": json.dumps(out, default=str)}
    except Exception as e:  # noqa: BLE001
        _g["logger"].error("[panel] retire/unretire wk%s failed — %s", week, e)
        return {"statusCode": 500, "body": json.dumps({"retire": "failed", "error": str(e)[:200]})}
