"""hook_liveness_qa.py — the nightly (cycle_day × hook × artifact) liveness matrix (#3615 box 1).

ONE WALK OVER hook_registry.HOOK_REGISTRY, inside qa-smoke's existing nightly invocation.
Each cell gets ONE bounded read (an HTTP GET, a `get_item`, a `Limit`-ed query, a
`get_object`) and resolves to exactly one of:

  ALIVE            the artifact was observed
  HONESTLY_ABSENT  it was absent AND the row carries a DECLARED absence contract that
                   this run could TEST (no live cycle / nothing to produce / declared dark)
  MISSING          absent with no contract that holds — a FAIL, never a shrug
  DEFERRED         the shared read budget was spent before the probe ran — reported as a
                   WARN, because an unread cell is an absence of evidence, not a pass

WHY THE ROW IS WRITTEN AND NOT JUST EMAILED
  The matrix is stored at `USER#matthew#SOURCE#qa_hook_matrix / DATE#<pt-date>` with the
  cycle day on it. A single night's verdict answers "is it alive now"; the row is what
  makes "was the ask-the-board door alive on Day 4 of the last cycle" answerable at all
  — the question #3615 opens with, which nothing in the platform could answer before.
  The write is fail-soft: a denied or throttled put must never turn a clean census red.

WHY A DOOR IS PROBED WITH A GET
  Every reader hook is a POST endpoint. Posting to it nightly would manufacture votes,
  asks and check-ins — a synthetic row in a measured partition, which the platform does
  not do. A GET on a POST-only route answers with the route's OWN method guard (405, or
  400/401/403/429 depending on the door), and a route that has been dropped answers 404.
  So the GET is a true liveness probe of the ROUTE — it proves the door is mounted, and
  it deliberately does NOT claim the handler behind it works. That distinction is in the
  cell label; nothing here is allowed to imply more than it observed.

CONTENT_TRUTH, not DEPLOY_HEALTH (#1921): a dark hook is a fact about the world as
served, and reverting the fleet does not conjure a chronicle installment or an episode.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

from boto3.dynamodb.conditions import Key

from operational import hook_registry as reg
from operational.census_probe import ProbeBudget

MATRIX_PK = "USER#matthew#SOURCE#qa_hook_matrix"

#: Status codes that prove a POST-only route is MOUNTED. A door that answers with its
#: own method guard, an auth challenge or a rate-limit is alive; 404 (route gone) and
#: 5xx (door broken) are the findings.
DOOR_ALIVE_STATUSES = (200, 400, 401, 403, 405, 409, 415, 422, 429)


def _pt_today(pt_now) -> date:
    """The sweep's own Pacific day. The fallback is PACIFIC too (#2798/#2811): a UTC day
    here would put the matrix's date axis 7-8h ahead of the day a reader is living in."""
    try:
        return pt_now().date()
    except Exception:  # noqa: BLE001 — the clock seam must never break the sweep
        from common.pacific_time import pacific_now

        return pacific_now().date()


def _cycle_day(today: date) -> Optional[int]:
    """Cycle day N for `today`, or None when there is no live cycle.

    Derived from `common.constants.day_n` — the platform's own day counter — so the
    matrix's day axis can never disagree with the day the site shows a reader.
    """
    try:
        from common.constants import day_n

        n = int(day_n(today.isoformat()))
    except Exception:  # noqa: BLE001
        return None
    return n or None


def _live_cycle(today: date) -> bool:
    return _cycle_day(today) is not None


# ── locator derivations ──────────────────────────────────────────────────────
def _newest_post(budget: ProbeBudget, site_base: str) -> tuple:
    """(post, observed) from the SAME manifest fetch the manifest cell grades (cached).

    `observed` is False when the manifest itself was never read — a deferred or failed
    manifest fetch must make its DEPENDENT cells deferred too, not missing. Reporting
    "no post to resolve a permalink from" when the manifest was simply not fetched would
    be evidence manufactured out of a transport blip.
    """
    res = budget.get(site_base + "/journal/posts.json")
    if res.deferred or res.error or res.status != 200:
        return None, False
    data = res.json()
    posts = (data or {}).get("posts") if isinstance(data, dict) else None
    posts = [p for p in (posts or []) if isinstance(p, dict)]
    if not posts:
        return None, True
    return sorted(posts, key=lambda p: (str(p.get("date") or ""), int(p.get("sequence") or 0)))[-1], True


def _share_kit_key(url_path: str) -> str:
    """The kit's S3 key from the PRODUCER's own key function — never restated here."""
    from content.chronicle_share_kit import kit_s3_key

    return kit_s3_key(url_path)


# ── predicates ───────────────────────────────────────────────────────────────
def _path(data: Any, dotted: str) -> Any:
    cur = data
    for part in str(dotted).split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _predicate_holds(data: Any, expect: dict) -> bool:
    if "truthy_path" in expect:
        return bool(_path(data, expect["truthy_path"]))
    if "nonempty_path" in expect:
        value = _path(data, expect["nonempty_path"])
        return bool(value) and (not isinstance(value, (list, dict, str)) or len(value) > 0)
    return data is not None


def _row_is_fresh(item: dict, expect: dict, today: date) -> tuple:
    """(fresh, note) for a DDB_ROW cell: present, not tombstoned, dated inside the window."""
    if item.get("tombstone"):
        return False, "row is tombstoned"
    max_age = int(expect.get("max_age_days") or 0)
    if not max_age:
        return True, "present"
    for field_name in expect.get("date_fields") or ("date",):
        raw = str(item.get(field_name) or "")[:10]
        try:
            stamped = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            continue
        age = (today - stamped).days
        if age <= max_age:
            return True, f"{field_name}={raw} ({age}d old)"
        return False, f"{field_name}={raw} is {age}d old, past the {max_age}d window"
    return True, "present (no parseable date field — presence only)"


# ── the per-cell evaluator ───────────────────────────────────────────────────
def _evaluate(hook, artifact, ctx: dict) -> tuple:
    """(verdict, note, nothing_to_produce) for ONE cell. Never raises."""
    kind = artifact.kind
    budget: ProbeBudget = ctx["budget"]
    site_base: str = ctx["site_base"]

    if kind in (reg.HTTP_DOOR, reg.HTTP_JSON, reg.HTTP_TEXT, reg.HTTP_PAGE):
        locator = artifact.locator
        if locator.startswith("derive:"):
            name = locator.split(":", 1)[1]
            if name == "newest_post_url":
                post, observed = _newest_post(budget, site_base)
                if not observed:
                    return reg.DEFERRED, "the served manifest was not read this run — permalink not observed", False
                if not post or not post.get("url"):
                    return reg.MISSING, "no post in the served manifest to resolve a permalink from", False
                locator = str(post["url"])
            else:  # pragma: no cover — guarded by the registry test
                return reg.MISSING, f"unknown derivation {name!r}", False
        res = budget.get(site_base + locator)
        if res.deferred:
            return reg.DEFERRED, res.error, False
        if res.error:
            return reg.DEFERRED, f"fetch failed ({res.error}) — not observed, so no verdict", False
        if kind == reg.HTTP_DOOR:
            allowed = tuple(artifact.expect.get("status_in") or DOOR_ALIVE_STATUSES)
            if res.status in allowed:
                return reg.ALIVE, f"HTTP {res.status} — route mounted (the door's own method guard)", False
            return reg.MISSING, f"HTTP {res.status} — the POST door is not mounted", False
        if kind == reg.HTTP_PAGE:
            allowed = tuple(artifact.expect.get("status_in") or (200,))
            if res.status in allowed:
                return reg.ALIVE, f"{locator} → HTTP {res.status}", False
            return reg.MISSING, f"{locator} → HTTP {res.status}", False
        if kind == reg.HTTP_TEXT:
            if res.status != 200:
                return reg.MISSING, f"HTTP {res.status}", False
            needle = str(artifact.expect.get("needle") or "")
            count = res.body.count(needle) if needle else 0
            if count >= int(artifact.expect.get("min_count") or 1):
                return reg.ALIVE, f"{count} × {needle!r}", False
            return reg.MISSING, f"{count} × {needle!r} (want ≥ {artifact.expect.get('min_count', 1)})", False
        # HTTP_JSON
        if res.status != 200:
            return reg.MISSING, f"HTTP {res.status}", False
        data = res.json()
        if data is None:
            return reg.MISSING, "response is not JSON", False
        if _predicate_holds(data, artifact.expect):
            return reg.ALIVE, "predicate holds on the served payload", False
        return reg.MISSING, f"served payload fails {artifact.expect}", False

    if kind == reg.S3_JSON:
        key = artifact.locator
        if key.startswith("derive:"):
            name = key.split(":", 1)[1]
            if name == "newest_post_share_kit_key":
                post, observed = _newest_post(budget, site_base)
                if not observed:
                    return reg.DEFERRED, "the served manifest was not read this run — share kit not observed", False
                if not post or not post.get("url"):
                    return reg.MISSING, "no post in the served manifest to resolve a share kit from", False
                key = _share_kit_key(str(post["url"]))
            else:  # pragma: no cover — guarded by the registry test
                return reg.MISSING, f"unknown derivation {name!r}", False
        try:
            body = ctx["s3"].get_object(Bucket=ctx["bucket"], Key=key)["Body"].read()
            data = json.loads(body)
        except Exception as exc:  # noqa: BLE001 — a missing kit IS the finding
            return reg.MISSING, f"s3://{ctx['bucket']}/{key} unreadable: {str(exc)[:90]}", False
        if _predicate_holds(data, artifact.expect):
            return reg.ALIVE, f"s3://{ctx['bucket']}/{key}", False
        return reg.MISSING, f"s3://{ctx['bucket']}/{key} fails {artifact.expect}", False

    if kind == reg.DDB_ROW:
        pk, sk = artifact.locator.split("|", 1)
        try:
            item = ctx["table"].get_item(Key={"pk": pk, "sk": sk}).get("Item")
        except Exception as exc:  # noqa: BLE001
            return reg.DEFERRED, f"get_item failed ({str(exc)[:90]}) — not observed", False
        if not item:
            return reg.MISSING, f"{pk} / {sk} does not exist", False
        fresh, note = _row_is_fresh(item, artifact.expect, ctx["today"])
        return (reg.ALIVE if fresh else reg.MISSING), f"{sk}: {note}", False

    if kind == reg.DDB_WINDOW:
        pk, sk_prefix = artifact.locator.split("|", 1)
        window = int(artifact.expect.get("window_days") or 30)
        floor = (ctx["today"] - timedelta(days=window)).isoformat()
        created_field = str(artifact.expect.get("created_field") or "created_at")
        produced_field = str(artifact.expect.get("produced_field") or "")
        try:
            resp = ctx["table"].query(
                KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
                ProjectionExpression="sk, " + ", ".join(sorted({created_field, produced_field} - {""})),
            )
            items = resp.get("Items") or []
        except Exception as exc:  # noqa: BLE001
            return reg.DEFERRED, f"query failed ({str(exc)[:90]}) — not observed", False
        in_window = [i for i in items if str(i.get(created_field) or "")[:10] >= floor]
        produced = [i for i in in_window if str(i.get(produced_field) or "")]
        if produced:
            return reg.ALIVE, f"{len(produced)} of {len(in_window)} in-window row(s) carry {produced_field}", False
        if not in_window:
            return reg.MISSING, f"no row with {created_field} ≥ {floor}", True
        return reg.MISSING, f"{len(in_window)} in-window row(s) and none carries {produced_field}", False

    return reg.MISSING, f"unknown probe kind {kind!r}", False  # pragma: no cover — registry-guarded


def _absence_is_honest(artifact, ctx: dict, nothing_to_produce: bool) -> tuple:
    """(honest, why) — can this cell's DECLARED absence contract be shown to hold tonight?"""
    absence = artifact.absence
    if absence is None:
        return False, ""
    if absence.contract == "no_live_cycle":
        if not ctx["live_cycle"]:
            return True, f"no live cycle on {ctx['today'].isoformat()} — {absence.reason} ({absence.issue})"
        return False, ""
    if absence.contract == "nothing_to_produce":
        if nothing_to_produce:
            return True, f"{absence.reason} ({absence.issue})"
        return False, ""
    if absence.contract == "declared_dark":
        return True, f"declared dark {absence.declared_on} — {absence.reason} ({absence.issue})"
    return False, ""  # pragma: no cover — registry-guarded vocabulary


# ── the leg ──────────────────────────────────────────────────────────────────
def walk(table, s3, bucket: str, pt_now, *, site_base_url: str, budget: Optional[ProbeBudget] = None) -> dict:
    """Probe every cell. Returns the matrix dict that is stored and reported."""
    today = _pt_today(pt_now)
    ctx = {
        "table": table,
        "s3": s3,
        "bucket": bucket,
        "today": today,
        "site_base": site_base_url.rstrip("/"),
        "budget": budget if budget is not None else ProbeBudget(),
        "cycle_day": _cycle_day(today),
    }
    ctx["live_cycle"] = ctx["cycle_day"] is not None
    rows = []
    for hook, artifact in reg.cells():
        try:
            verdict, note, nothing_to_produce = _evaluate(hook, artifact, ctx)
        except Exception as exc:  # noqa: BLE001 — one bad cell costs one cell, never the leg
            verdict, note, nothing_to_produce = reg.DEFERRED, f"probe raised: {str(exc)[:110]}", False
        if verdict == reg.MISSING:
            honest, why = _absence_is_honest(artifact, ctx, nothing_to_produce)
            if honest:
                verdict, note = reg.HONESTLY_ABSENT, why
        rows.append(
            {
                "hook": hook.id,
                "artifact": artifact.id,
                "label": artifact.label,
                "verdict": verdict,
                "note": note,
            }
        )
    return {
        "date": today.isoformat(),
        "cycle_day": ctx["cycle_day"],
        "cells": rows,
        "counts": {v: sum(1 for r in rows if r["verdict"] == v) for v in reg.VERDICTS},
        "reads": ctx["budget"].requests,
    }


def _store(table, matrix: dict) -> None:
    """Fail-soft write of tonight's row — a denied put must never red a clean census."""
    try:
        table.put_item(
            Item={
                "pk": MATRIX_PK,
                "sk": f"DATE#{matrix['date']}",
                "date": matrix["date"],
                "cycle_day": matrix.get("cycle_day"),
                "counts": matrix["counts"],
                # Stored as one JSON string: the cell list is display data, and a nested
                # DDB map of 20+ entries would have to be Decimal-sanitised on every write.
                "cells_json": json.dumps(matrix["cells"], separators=(",", ":"))[:38000],
                "source": "qa_smoke/hook_liveness (#3615)",
            }
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[QA] hook-matrix row write failed (fail-soft): {str(exc)[:140]}")


def check_hook_liveness(table, s3, bucket: str, Check, tier, pt_now, *, site_base_url: str, budget=None) -> list:
    """The qa-smoke leg. One Check; MISSING cells are the FAIL, deferred cells a WARN."""
    check = Check("hooks:liveness_matrix", "Hook Liveness", tier)
    try:
        matrix = walk(table, s3, bucket, pt_now, site_base_url=site_base_url, budget=budget)
    except Exception as exc:  # noqa: BLE001
        return [check.warn(f"hook liveness matrix errored (no verdict was reached): {str(exc)[:160]}")]
    _store(table, matrix)

    counts = matrix["counts"]
    day = matrix.get("cycle_day")
    day_label = f"cycle day {day}" if day else "no live cycle"
    missing = [r for r in matrix["cells"] if r["verdict"] == reg.MISSING]
    deferred = [r for r in matrix["cells"] if r["verdict"] == reg.DEFERRED]
    absent = [r for r in matrix["cells"] if r["verdict"] == reg.HONESTLY_ABSENT]
    details = [f"{r['hook']}/{r['artifact']}: {r['verdict']} — {r['note']}" for r in matrix["cells"]]

    if missing:
        named = "; ".join(f"{r['hook']}/{r['artifact']} ({r['note']})" for r in missing[:6])
        more = f" (+{len(missing) - 6} more)" if len(missing) > 6 else ""
        return [
            check.fail(
                f"{len(missing)} of {len(matrix['cells'])} hook×artifact cell(s) MISSING on {day_label} "
                f"with no absence contract that holds: {named}{more} (#3615)"
            ).with_details(details)
        ]
    if deferred:
        named = "; ".join(f"{r['hook']}/{r['artifact']}" for r in deferred[:6])
        return [
            check.warn(
                f"{len(deferred)} cell(s) NOT OBSERVED on {day_label} (read budget or transport): {named} — "
                f"{counts[reg.ALIVE]} alive, {len(absent)} honestly absent (#3615)"
            ).with_details(details)
        ]
    honest = "; ".join(f"{r['hook']}/{r['artifact']}" for r in absent)
    tail = f"; honestly absent: {honest}" if absent else ""
    return [
        check.ok(
            f"{counts[reg.ALIVE]} of {len(matrix['cells'])} hook×artifact cells alive on {day_label} " f"({matrix['reads']} reads){tail}"
        ).with_details(details)
    ]
