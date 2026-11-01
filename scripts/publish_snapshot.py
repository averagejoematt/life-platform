#!/usr/bin/env python3
"""scripts/publish_snapshot.py — the publication snapshot: the ONE boundary between the
platform and the v9 static build (docs/design/v9/STAGE4_ENGINEERING_PLAN.md §B, §D; #5530,
epic #5529).

What it does
  * reads the platform's PUBLIC surface over HTTPS (``--mode live``) — never DynamoDB, never
    an AWS credential (owner decision 4, 2026-10-31) — or a committed fixture set
    (``--mode fixture``) so CI builds are deterministic and offline;
  * wraps every object in the publication envelope (id · type · visibility · as_of ·
    data_through · source · state · absent_text · approved · method_ids · edges · sample ·
    title · summary) and validates it against SCHEMA, the Python mirror of
    ``www/src/content.config.ts`` (the two field sets are a contract, checked by
    tests/test_web_publication_snapshot_5530.py);
  * WRITES ONLY ``visibility == "public"`` objects. A ``held`` or ``private`` object is
    counted in the manifest and never serialised — not its id, not its title (owner
    requirement: private and unpublished objects cannot enter the public build). The Astro
    schema then refuses anything that is not literally ``"public"``, so the gate has two
    independent halves;
  * refuses a dangling edge (an edge to an object that is not in the public snapshot) —
    the derivation guard for the relationship index;
  * writes byte-stable files (sorted keys, sorted ids, no timestamps) so two runs over the
    same input produce the same bytes; the only clock is ``manifest.json``'s generated_at.

Phase 0 scope (honest): live mode maps the endpoints whose shapes were verified on
2026-10-31 — /api/edition, /journal/posts.json, /panelcast/episodes.json, /api/coaches,
/api/predictions, /api/calls, /api/coach_docket, /api/source_freshness, /api/methods,
/api/experiments, /journal/blog.json. Insights have no public list endpoint yet (Phase 1);
the full paginated ledger with the grader's quality flags is Phase 3. Nothing is computed
here that a page would present as a published statistic: counts are carried, not derived.

Usage
  python3 scripts/publish_snapshot.py --mode fixture --out www/content/snapshot
  python3 scripts/publish_snapshot.py --mode live --out www/content/snapshot [--base-url URL]

Exit codes: 0 ok · 2 schema violation · 3 dangling edge · 4 fetch failure (live).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_snapshot_contract import (  # noqa: E402,F401 — re-exported: the contract is one module, reached through this one
    _ISO_IN_TEXT,
    _MONTHS,
    _ON_ATTR,
    _PROSE,
    _ROOT_LINK,
    _SCRIPT,
    _WORDED_TEXT_KEYS,
    COLLECTION_OF,
    DEFAULT_BASE_URL,
    DEFAULT_FIXTURES,
    ENVELOPE,
    EXPORTER_VERSION,
    GROUPS,
    ID_RE,
    ISO_DAY,
    KIT_LIVE,
    OBJECT_TYPES,
    QUALITY_FLAGS,
    REPO,
    SCHEMA,
    UTILITY,
    VISIBILITIES,
    SchemaError,
    _check,
    _dump,
    _words_in_text,
    _write_data_files,
    build_appendix,
    dangling_edges,
    day_in_words,
    envelope,
    extract_prose,
    load_fixture_data_files,
    load_fixtures,
    log,
    partition,
    validate,
    validate_data_files,
    word_dates,
    write_snapshot,
)


# ── live mode ────────────────────────────────────────────────────────────────────────────
def _get(base_url: str, path: str, timeout: float) -> Any:
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(
        url, headers={"User-Agent": "life-platform publish_snapshot/" + EXPORTER_VERSION, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — constant public base URL
        return json.loads(resp.read().decode("utf-8"))


def _get_text(base_url: str, path: str, timeout: float) -> str:
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform publish_snapshot/" + EXPORTER_VERSION, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — constant public base URL
        return resp.read().decode("utf-8", errors="replace")


def _slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._:-]+", "-", s).strip("-")
    return s or "x"


def _persona(short: str) -> str:
    return short if short.endswith("_coach") or short == "eli_marsh" else f"{short}_coach"


def _week_id(url: str | None) -> str | None:
    m = re.search(r"/week-(\d+)/?$", url or "")
    return f"week-{int(m.group(1)):02d}" if m else None


LIVE_ENDPOINTS = {
    "edition": "/api/edition",
    "posts": "/journal/posts.json",
    "episodes": "/panelcast/episodes.json",
    "coaches": "/api/coaches",
    "predictions": "/api/predictions",
    "docket": "/api/coach_docket",
    "freshness": "/api/source_freshness",
    "methods": "/api/methods",
    "experiments": "/api/experiments",
    "blog": "/journal/blog.json",
    "chapters": "/api/chapters",  # the program-week states (PR #5538); optional until it is live
    "series_catalogue": "/api/series",  # the publishable metric keys (PR #5538)
    "pairs": "/api/pairs",  # the precomputed pair statistics for the data room (PR #5538)
}
OPTIONAL_ENDPOINTS = ("blog", "docket", "experiments", "chapters", "series_catalogue", "pairs")


# Presentation labels for the metric keys the series catalogue serves (the key is the id; the
# label is how a page names it). A key not listed falls back to the key with spaces.
METRIC_LABELS = {
    "weight_lbs": "Body · weight",
    "sleep_duration_hours": "Sleep · duration",
    "hrv": "Recovery · HRV",
    "resting_hr": "Resting heart rate",
    "recovery_score": "Recovery score",
    "deep_pct": "Sleep · deep share",
    "rem_pct": "Sleep · REM share",
    "total_protein_g": "Fuel · protein",
    "total_calories_kcal": "Fuel · calories",
    "steps": "Movement · steps",
}
HR_REGIME_METRICS = ("hrv", "resting_hr", "recovery_score")


def _baseline_change_markers() -> list[dict]:
    """The reader-facing baseline-change date (lambdas/web/baseline_change.py is the one public
    door onto it; its vocabulary — "baseline change", never the clinical term — is the contract
    tests/test_hr_regime_surfaces_5029.py enforces). Read from the module, never typed here; an
    import failure leaves the list empty and the chart unmarked."""
    try:
        sys.path.insert(0, os.path.join(REPO, "lambdas"))
        from web.baseline_change import baseline_change_date  # type: ignore

        d = baseline_change_date()
        return [{"date": d, "label": "baseline change"}] if d and ISO_DAY.match(d) else []
    except Exception as exc:  # pragma: no cover — the module is in the repo
        log(f"  baseline-change marker unavailable ({exc})")
        return []


class LiveContext:
    """What the per-collection mappers share: the fetched payloads and the cross-references
    built as the collections are mapped (episodes by week, chapters by week, the coach ids,
    the metric keys the pending calls name)."""

    def __init__(self, base_url: str, fetched: dict[str, Any], timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.fetched = fetched
        self.timeout = timeout
        self.as_of: str = (fetched["edition"] or {}).get("as_of")
        self.objs: dict[str, list[dict]] = {t: [] for t in OBJECT_TYPES}
        self.ep_by_week: dict[int, str] = {}
        self.chapter_by_week: dict[int, str] = {}
        self.coach_ids: set[str] = set()
        self.metric_keys: set[str] = set()
        self.series: dict[str, dict] = {}  # metric key -> the series payload (written as a data file)
        self.pairs: dict | None = None

    def rows(self, key: str, field: str) -> list:
        return (self.fetched.get(key) or {}).get(field) or []


def fetch_live(base_url: str, timeout: float) -> dict[str, Any]:
    fetched: dict[str, Any] = {}
    for key, path in LIVE_ENDPOINTS.items():
        try:
            fetched[key] = _get(base_url, path, timeout)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            # HTTPError is a URLError: a 404 on an optional route (e.g. /api/chapters before PR #5538
            # is live) leaves that collection empty; anything else is fatal.
            if key in OPTIONAL_ENDPOINTS:
                log(f"  optional {path} unavailable ({exc}); collection left empty")
                fetched[key] = None
            else:
                raise RuntimeError(f"fetch failed for {path}: {exc}") from exc
    return fetched


def _live_episodes(ctx: LiveContext) -> None:
    for e in ctx.rows("episodes", "episodes"):
        m = re.search(r"wk(\d+)", e.get("url") or "")
        if not m:
            continue
        n = int(m.group(1))
        eid = f"wk{n}"
        ctx.ep_by_week[n] = eid
        audio = e.get("url")
        if audio and audio.startswith("/"):
            audio = ctx.base_url + audio
        transcript = None
        t_url = e.get("transcript_url")
        if isinstance(t_url, str) and t_url.startswith("/"):
            try:
                turns = (_get(ctx.base_url, t_url, ctx.timeout) or {}).get("turns") or []
                transcript = [
                    {"speaker": str(t.get("speaker") or ""), "line": str(t.get("line") or "")} for t in turns if t.get("line")
                ] or None
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
                log(f"  transcript {t_url} unavailable ({exc})")
        ctx.objs["episode"].append(
            envelope(
                id=eid,
                type="episode",
                as_of=ctx.as_of,
                data_through=e.get("date"),
                source=["/panelcast/episodes.json"],
                title=e.get("title") or f"Episode {n}",
                summary=e.get("excerpt"),
                number=n,
                date=e["date"],
                duration_sec=int(e["duration_sec"]) if e.get("duration_sec") is not None else None,
                audio_url=audio,
                transcript_url=(ctx.base_url + t_url) if isinstance(t_url, str) and t_url.startswith("/") else t_url,
                byline=e.get("byline"),
                chapter_id=None,
                transcript=transcript,
            )
        )


def _chapter_body(ctx: LiveContext, url: str | None) -> str | None:
    """The published permalink's prose, as published. A fetch failure is logged and leaves the
    body None (the page says the text lives on the site), never a fabricated body."""
    if not url:
        return None
    try:
        return extract_prose(_get_text(ctx.base_url, url, ctx.timeout), ctx.base_url)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log(f"  body {url} unavailable ({exc})")
        return None


def _live_week_states(ctx: LiveContext) -> None:
    """Program weeks with no published chapter: `held` (a draft awaiting approval), `skipped`
    (a later week published, this one never was) or `pending` (the current or most recent week,
    not yet written). From `/api/chapters` when it is served; otherwise derived from the
    published weeks and the edition's day count — never a title or a body for any of them."""
    published = {c["week"] for c in ctx.objs["chapter"] if isinstance(c.get("week"), int)}
    weeks_api = (ctx.fetched.get("chapters") or {}).get("weeks") or []
    states: dict[int, dict] = {}
    if weeks_api:
        for w in weeks_api:
            n, st = w.get("week"), w.get("status")
            if isinstance(n, int) and st in ("held", "skipped", "pending") and n not in published:
                states[n] = {"status": st, "start": w.get("start"), "reason": w.get("reason"), "drafted_at": w.get("drafted_at")}
    else:
        edition = ctx.fetched.get("edition") or {}
        day_n = edition.get("day_n") if isinstance(edition.get("day_n"), int) else 0
        last_week = max(day_n // 7, max(published, default=0))
        held = ((((edition.get("blocks") or {}).get("chapter") or {}).get("data") or {}) or {}).get("held")
        for n in range(1, last_week + 1):
            if n in published:
                continue
            later_published = any(m > n for m in published)
            st = "skipped" if later_published else "pending"
            if isinstance(held, dict) and held.get("week") == n:
                st = "held"
            states[n] = {
                "status": st,
                "start": None,
                "reason": None,
                "drafted_at": held.get("drafted_at") if st == "held" and isinstance(held, dict) else None,
            }
    for n, st in sorted(states.items()):
        status = st["status"]
        text = {
            "held": "Drafted and waiting for approval.",
            "skipped": "No chapter was published for this week.",
            "pending": "No chapter yet for this week.",
        }[status]
        if st.get("reason"):
            text = str(st["reason"])
        ctx.objs["chapter"].append(
            envelope(
                id=f"program-week-{n:02d}",
                type="chapter",
                as_of=ctx.as_of,
                source=["/api/chapters"] if weeks_api else ["/journal/posts.json", "/api/edition"],
                state="stale" if status == "held" else "absent",
                absent_text=text,
                title=f"Week {n}",
                summary=None,
                week=n,
                week_label=f"Week {n}",
                date=st.get("start") if ISO_DAY.match(str(st.get("start") or "")) else _program_week_start(ctx, n),
                status=status,
                excerpt=None,
                body_html=None,
                word_count=None,
                read_minutes=None,
                url_legacy=None,
                episode_id=None,
            )
        )


def _program_week_start(ctx: LiveContext, n: int) -> str:
    """The Tuesday-anchored week date used for ordering a weekless row: genesis + 7·n days,
    read from the edition's start_date; falls back to as_of."""
    import datetime as _dt

    edition = ctx.fetched.get("edition") or {}
    today = (((edition.get("blocks") or {}).get("today") or {}).get("data") or {}) or {}
    start = today.get("start_date") if ISO_DAY.match(str(today.get("start_date") or "")) else None
    if not start:
        return ctx.as_of
    d = _dt.date.fromisoformat(start) + _dt.timedelta(days=7 * n)
    return d.isoformat()


def _live_chapters(ctx: LiveContext) -> None:
    for p in ctx.rows("posts", "posts"):
        cid = _week_id(p.get("url"))
        if not cid:
            continue
        week = p.get("week") if isinstance(p.get("week"), int) else None
        if week is not None:
            ctx.chapter_by_week[week] = cid
        wc = p.get("word_count") if isinstance(p.get("word_count"), int) else None
        has_ep = week is not None and week in ctx.ep_by_week
        ctx.objs["chapter"].append(
            envelope(
                id=cid,
                type="chapter",
                as_of=ctx.as_of,
                data_through=p.get("date"),
                source=["/journal/posts.json"],
                approved={"by": "owner", "at": p["date"], "via": "chronicle-approve"},
                title=p.get("title") or cid,
                summary=p.get("excerpt"),
                week=week,
                week_label=p.get("label") or (f"Week {week}" if week is not None else cid),
                date=p["date"],
                status="published",
                excerpt=p.get("excerpt"),
                body_html=_chapter_body(ctx, p.get("url")),
                word_count=wc,
                read_minutes=max(1, round(wc / 230)) if wc else None,
                url_legacy=p.get("url"),
                episode_id=ctx.ep_by_week.get(week) if week is not None else None,
                edges=[{"type": "episode", "id": ctx.ep_by_week[week], "rel": "listen"}] if has_ep else [],
            )
        )
    for e in ctx.objs["episode"]:
        if e["number"] in ctx.chapter_by_week:
            e["chapter_id"] = ctx.chapter_by_week[e["number"]]


def _quality_counts(q: Any) -> dict | None:
    """The grader's per-coach quality counts (#5533), as served: clean + flagged + unassessed == n."""
    if not isinstance(q, dict) or not all(isinstance(q.get(k), int) for k in ("clean", "flagged", "unassessed", "n")):
        return None
    by_flag = {str(k): int(v) for k, v in (q.get("by_flag") or {}).items() if isinstance(v, int)}
    return {"clean": q["clean"], "flagged": q["flagged"], "unassessed": q["unassessed"], "n": q["n"], "by_flag": by_flag}


def _live_coaches(ctx: LiveContext) -> None:
    by_coach = (ctx.fetched.get("predictions") or {}).get("by_coach") or {}
    for c in ctx.rows("coaches", "coaches"):
        pid = c["persona_id"]
        short = pid[: -len("_coach")] if pid.endswith("_coach") else pid
        bc = by_coach.get(short) or {}
        rec = bc.get("record") or {}
        decided = bc.get("decided")
        record = {"right": bc.get("confirmed"), "n": int(decided), "through": rec.get("through")} if isinstance(decided, int) else None
        comp = (bc.get("comparison") or {}).get("sentence")
        ctx.objs["coach"].append(
            envelope(
                id=pid,
                type="coach",
                as_of=ctx.as_of,
                source=["/api/coaches", "/api/predictions"],
                title=c.get("name") or pid,
                summary=c.get("domain"),
                name=c.get("name") or pid,
                domain=c.get("domain") or "—",
                tier="lead" if c.get("tier") == "lead" else "staff",
                retired=bool(bc.get("retired")),
                retired_date=None,
                short_bio=c.get("short_bio"),
                record=record,
                comparison_text=comp if isinstance(comp, str) and comp else None,
                quality=_quality_counts(bc.get("quality")),
                instrument_absent={"absent": bool(c.get("absent")), "reason": c.get("reason")} if c.get("absent") else None,
            )
        )
    ctx.coach_ids = {c["id"] for c in ctx.objs["coach"]}


LEDGER_STATUS = {
    "observational": "observation",
    "pending": "pending",
    "confirmed": "confirmed",
    "refuted": "refuted",
    "expired": "expired",
    "inconclusive": "inconclusive",
}
LEDGER_KIND = ("number", "direction", "yes_no", "sealed", "interval", "observation")


def _ledger_pages(ctx: LiveContext) -> list[dict]:
    """Every row of `/api/ledger_export`, page by page (the route serves at most 100 a page). A page
    that cannot be fetched is a hard failure — a partial ledger would read as a smaller record."""
    out: list[dict] = []
    page = 1
    while True:
        payload = _get(ctx.base_url, f"/api/ledger_export?page={page}&size=100", ctx.timeout)
        out.extend(r for r in payload.get("items") or [] if isinstance(r, dict))
        pages = int(payload.get("pages") or 1)
        if page >= pages:
            break
        page += 1
    return out


def _correction_entry(e: dict) -> dict:
    """One correction as the ledger serves it, every key kept (owner requirement B — the original
    grade, its timestamp, the corrected grade, the correction timestamp, the reason, the evaluator
    version and the aggregate impact), with the names the page reads normalised."""
    out = dict(e)
    out.setdefault("original_grade", e.get("original") or None)
    out.setdefault(
        "original_timestamp", (e.get("original_grade") or {}).get("snapshot_at") if isinstance(e.get("original_grade"), dict) else None
    )
    out.setdefault("corrected_grade", e.get("corrected_status"))
    out.setdefault("corrected_at", None)
    out.setdefault("reason", None)
    out.setdefault("evaluator_version", None)
    out.setdefault("aggregate_impact", None)
    return out


def _live_ledger(ctx: LiveContext) -> None:
    """The whole prediction ledger from `/api/ledger_export` (Phase 3, #5537): one Prediction per
    row, id = coach · prediction_id (a prediction_id repeats across coaches). The grade, the
    simple guess, the grader's quality flags and every correction travel as served — nothing is
    re-graded here. A metric the row names becomes an edge when it is a public Metric id."""
    for r in _ledger_pages(ctx):
        coach = str(r.get("coach_id") or "")
        pred = str(r.get("prediction_id") or "")
        if not coach or not pred or not ID_RE.match(pred):
            continue
        if not str(r.get("claim") or "").strip():
            log(f"  ledger row {coach}:{pred} served with no claim text — not a publishable record, skipped")
            continue
        pid = _persona(coach)
        if pid not in ctx.coach_ids:
            continue
        rid = f"{coach}-{pred}"
        status = LEDGER_STATUS.get(str(r.get("status") or ""), "inconclusive")
        kind = r.get("kind") if r.get("kind") in LEDGER_KIND else "unknown"
        metric = r.get("metric") if isinstance(r.get("metric"), str) and ID_RE.match(r.get("metric") or "") else None
        if metric:
            ctx.metric_keys.add(metric)
        g = r.get("grading") or {}
        sg = r.get("simple_guess") or None
        flags = [f for f in (r.get("quality_flags") or []) if isinstance(f, str)]
        corrections = [_correction_entry(e) for e in (r.get("corrections") or []) if isinstance(e, dict)]
        edges = [{"type": "coach", "id": pid, "rel": "made_by"}]
        if metric:
            edges.append({"type": "metric", "id": metric, "rel": "about"})
        ctx.objs["prediction"].append(
            envelope(
                id=rid,
                type="prediction",
                as_of=ctx.as_of,
                data_through=r.get("settled_date") if ISO_DAY.match(str(r.get("settled_date") or "")) else None,
                source=["/api/ledger_export"],
                title=(r.get("claim") or rid)[:120],
                summary=(sg or {}).get("short"),
                coach_id=pid,
                coach_name=str(r.get("coach_name") or pid),
                retired=bool(r.get("retired")),
                metric_id=metric,
                metric_key=r.get("metric") if isinstance(r.get("metric"), str) else None,
                claim=str(r.get("claim") or ""),
                logged_date=r.get("logged_date"),
                due_date=r.get("due_date") if ISO_DAY.match(str(r.get("due_date") or "")) else None,
                settled_date=r.get("settled_date") if ISO_DAY.match(str(r.get("settled_date") or "")) else None,
                kind=kind,
                status=status,
                verdict_text=g.get("outcome_notes") if isinstance(g.get("outcome_notes"), str) else None,
                grading=(
                    {
                        "how": g.get("how"),
                        "actual_text": g.get("actual_text"),
                        "tolerance_text": g.get("tolerance_text"),
                        "outcome_notes": g.get("outcome_notes"),
                    }
                    if g
                    else None
                ),
                simple_guess={"state": str(sg.get("state") or "unknown"), "right": sg.get("right"), "text": sg.get("text")} if sg else None,
                quality_flags=flags,
                corrections=corrections,
                sealed=bool(r.get("sealed")),
                confidence=(
                    float(r["confidence"])
                    if isinstance(r.get("confidence"), (int, float)) and not isinstance(r.get("confidence"), bool)
                    else None
                ),
                edges=edges,
            )
        )


def _decimals_for(unit: str) -> int:
    return {"lb": 1, "hours": 2, "ms": 1, "bpm": 0, "out of 100": 0, "%": 1, "g": 0, "kcal": 0, "steps": 0}.get(unit, 1)


def _metric_series(ctx: LiveContext, key: str, start: str | None) -> dict | None:
    if not start:
        return None
    try:
        return _get(ctx.base_url, f"/api/series?metric={key}&from={start}&to={ctx.as_of}", ctx.timeout)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        log(f"  series {key} unavailable ({exc})")
        return None


def _series_payload(
    ctx: LiveContext, key: str, m: dict, src: str | None, payload: dict, days: list[dict], start: str | None, markers: list
) -> dict:
    return {
        "metric": key,
        "unit": str(m.get("unit") or ""),
        "source_id": src,
        "behavioral": bool(m.get("behavioral")),
        "window": payload.get("window") or {"from": start, "to": ctx.as_of},
        "n_present": int(payload.get("n_present") or sum(1 for d in days if d.get("present"))),
        "n_gap": int(payload.get("n_gap") or sum(1 for d in days if d.get("gap"))),
        "markers": markers if key in HR_REGIME_METRICS else [],
        "days": [
            {
                "date": d["date"],
                "value": d.get("value") if isinstance(d.get("value"), (int, float)) and not isinstance(d.get("value"), bool) else None,
                "present": bool(d.get("present")),
                "gap": bool(d.get("gap")),
            }
            for d in days
        ],
    }


def _live_metrics(ctx: LiveContext) -> None:
    """One Metric per publishable key in the series catalogue, each with its daily series fetched
    for the experiment window and kept as a data file beside the collections. A key a pending call
    names that the catalogue does not serve gets a series-less stub, so the ledger can still link it."""
    edition = ctx.fetched.get("edition") or {}
    today = (((edition.get("blocks") or {}).get("today") or {}).get("data") or {}) or {}
    start = today.get("start_date") if ISO_DAY.match(str(today.get("start_date") or "")) else None
    source_ids = {o["id"] for o in ctx.objs["source"]}
    markers = _baseline_change_markers()
    seen: set[str] = set()
    for m in ctx.rows("series_catalogue", "metrics"):
        key = m.get("metric")
        if not isinstance(key, str) or not ID_RE.match(key):
            continue
        seen.add(key)
        unit = str(m.get("unit") or "")
        src = m.get("source_id") if isinstance(m.get("source_id"), str) and m["source_id"] in source_ids else None
        payload = _metric_series(ctx, key, start) or {}
        days = [d for d in (payload.get("days") or []) if ISO_DAY.match(str(d.get("date") or ""))]
        method_ids = [x for x in (payload.get("method_ids") or []) if isinstance(x, str) and ID_RE.match(x)]
        if days:
            ctx.series[key] = _series_payload(ctx, key, m, src, payload, days, start, markers)
        instrument = next((o["label"] for o in ctx.objs["source"] if o["id"] == src), None)
        ctx.objs["metric"].append(
            envelope(
                id=key,
                type="metric",
                as_of=ctx.as_of,
                data_through=ctx.as_of if days else None,
                source=["/api/series"],
                state="ok" if days else "absent",
                absent_text=None if days else "No series is served for this measure yet.",
                method_ids=method_ids,
                title=METRIC_LABELS.get(key, key.replace("_", " ")),
                summary=None,
                label=METRIC_LABELS.get(key, key.replace("_", " ")),
                unit=unit,
                source_id=src,
                decimals=_decimals_for(unit),
                sentence=None,
                instrument=instrument,
                series_url=f"/api/series?metric={key}" if days else None,
                edges=[{"type": "source", "id": src, "rel": "measured_by"}] if src else [],
            )
        )
    for key in sorted(ctx.metric_keys - seen):
        ctx.objs["metric"].append(
            envelope(
                id=key,
                type="metric",
                as_of=ctx.as_of,
                source=["/api/predictions"],
                state="absent",
                absent_text="Named by a coach's call; no public series is served for it.",
                title=METRIC_LABELS.get(key, key.replace("_", " ")),
                label=METRIC_LABELS.get(key, key.replace("_", " ")),
                unit="",
                source_id=None,
                decimals=1,
                sentence=None,
                instrument=None,
                series_url=None,
            )
        )
    pairs = ctx.fetched.get("pairs") or None
    if isinstance(pairs, dict) and isinstance(pairs.get("pairs"), list):
        known = {o["id"] for o in ctx.objs["metric"]}
        ctx.pairs = {
            "as_of": ctx.as_of,
            "lags": pairs.get("lags") or [],
            "min_n": pairs.get("min_n"),
            "window": pairs.get("window"),
            "family": pairs.get("family"),
            "lag_meaning": pairs.get("lag_meaning"),
            "method_ids": [x for x in (pairs.get("method_ids") or []) if isinstance(x, str)],
            "pairs": [r for r in pairs["pairs"] if r.get("a") in known and r.get("b") in known],
        }


def _docket_verdict_text(d: dict) -> str | None:
    """The docket's settled verdict as one sentence. On the wire `verdict` is a dict
    ({winner, loser, holds, outcome, actual_value}) once code has settled the bet — the
    platform's verdict, carried, never recomputed here; a string is passed through."""
    v = d.get("verdict")
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        winner, loser, outcome = v.get("winner"), v.get("loser"), v.get("outcome")
        actual = v.get("actual_value")
        parts = []
        if outcome:
            parts.append(f"Settled by code ({outcome})")
        if winner:
            parts.append(f"the call that held was {winner}'s")
        if loser:
            parts.append(f"{loser}'s did not")
        if isinstance(actual, (int, float)):
            parts.append(f"the measured value was {actual:.1f}")
        return "; ".join(parts) + "." if parts else None
    for key in ("resolution_text", "resolution"):
        if isinstance(d.get(key), str) and d[key].strip():
            return d[key].strip()
    return None


def _live_disagreements(ctx: LiveContext) -> None:
    docket = ctx.fetched.get("docket") or {}
    for status_key, status in (("open", "open"), ("resolved", "resolved")):
        for d in docket.get(status_key) or []:
            a, b = d.get("coach_a"), d.get("coach_b")
            if a not in ctx.coach_ids or b not in ctx.coach_ids:
                continue
            slug = d.get("topic_slug") or _slug(d.get("topic") or "topic")
            did = f"{slug}-{(d.get('resolved_date') or d.get('opened') or ctx.as_of)}"
            claims = d.get("claims") or {}
            ctx.objs["disagreement"].append(
                envelope(
                    id=_slug(did),
                    type="disagreement",
                    as_of=ctx.as_of,
                    source=["/api/coach_docket"],
                    title=d.get("topic") or slug,
                    topic=d.get("topic") or slug,
                    coach_a=a,
                    coach_b=b,
                    claim_a=claims.get(a) if isinstance(claims.get(a), str) else None,
                    claim_b=claims.get(b) if isinstance(claims.get(b), str) else None,
                    status=status if d.get("resolution") != "void_no_data" else "void",
                    resolved_date=d.get("resolved_date") if ISO_DAY.match(str(d.get("resolved_date") or "")) else None,
                    verdict=_docket_verdict_text(d),
                    metric_id=None,
                    edges=[{"type": "coach", "id": a, "rel": "side_a"}, {"type": "coach", "id": b, "rel": "side_b"}],
                )
            )


def _live_sources(ctx: LiveContext) -> None:
    for s in ctx.rows("freshness", "sources"):
        status = (
            s.get("status")
            if s.get("status") in ("live", "stale", "paused", "behavioral-stale")
            else ("live" if s.get("status") == "fresh" else "unknown")
        )
        last = (s.get("last_update") or "")[:10]
        latest_day = last if ISO_DAY.match(last) else None
        ctx.objs["source"].append(
            envelope(
                id=s["id"],
                type="source",
                as_of=ctx.as_of,
                data_through=last if ISO_DAY.match(last) else None,
                source=["/api/source_freshness"],
                state="ok" if status in ("live", "paused") else "stale",
                title=s.get("label") or s["id"],
                summary=s.get("desc"),
                label=s.get("label") or s["id"],
                category=s.get("category"),
                since=None,
                latest=latest_day,
                status=status,
                stale_hours=int(s["stale_hours"]) if isinstance(s.get("stale_hours"), int) else None,
                instrument_for=None,
                behavioral=bool(s.get("is_behavioral")),
            )
        )


def _live_methods(ctx: LiveContext) -> None:
    for m in ctx.rows("methods", "stats"):
        ctx.objs["method"].append(
            envelope(
                id=m["id"],
                type="method",
                as_of=ctx.as_of,
                source=["/api/methods"],
                title=m.get("name") or m["id"],
                summary=m.get("category"),
                name=m.get("name") or m["id"],
                category=m.get("category"),
                formula=m.get("formula"),
                window=m.get("window"),
                limitations=m.get("limitations"),
                min_n=int(m["min_n"]) if isinstance(m.get("min_n"), int) else None,
                used_by=[str(x) for x in (m.get("used_by") or [])],
            )
        )


def _live_experiments(ctx: LiveContext) -> None:
    """The real experiments, not the library catalogue."""
    for x in ctx.rows("experiments", "experiments"):
        if x.get("status") in (None, "backlog") or x.get("origin") == "library":
            continue
        ctx.objs["experiment"].append(
            envelope(
                id=_slug(str(x["id"])),
                type="experiment",
                as_of=ctx.as_of,
                source=["/api/experiments"],
                title=x.get("name") or str(x["id"]),
                summary=x.get("result_summary"),
                name=x.get("name") or str(x["id"]),
                status=str(x.get("status")),
                hypothesis=x.get("hypothesis"),
                pillar=x.get("pillar"),
                start_date=x.get("start_date") if ISO_DAY.match(str(x.get("start_date") or "")) else None,
                end_date=x.get("end_date") if ISO_DAY.match(str(x.get("end_date") or "")) else None,
                pre_registered=bool(x.get("pre_registered") or x.get("pre_registered_at")),
                metric_id=None,
            )
        )


def _live_essays(ctx: LiveContext) -> None:
    for p in ctx.rows("blog", "posts"):
        slug = p.get("id") or _slug(p.get("title") or "essay")
        ctx.objs["essay"].append(
            envelope(
                id=_slug(slug),
                type="essay",
                as_of=ctx.as_of,
                source=["/journal/blog.json"],
                approved={"by": "owner", "at": p.get("date") or ctx.as_of, "via": "journal-interview PR"},
                title=p.get("title") or slug,
                summary=p.get("excerpt") or p.get("summary"),
                date=p["date"],
                body_html=_chapter_body(ctx, p.get("url") or f"/journal/essays/{slug}/"),
                url_legacy=p.get("url") or f"/journal/essays/{slug}/",
            )
        )


def _live_edition(ctx: LiveContext) -> None:
    edition = ctx.fetched["edition"]
    blocks = edition.get("blocks") or {}
    today_data = (blocks.get("today") or {}).get("data")
    today = today_data if isinstance(today_data, dict) else {}
    chapter_block = (blocks.get("chapter") or {}).get("data") or {}
    latest_chapter = _week_id(chapter_block.get("url")) if isinstance(chapter_block, dict) else None
    known = latest_chapter and any(c["id"] == latest_chapter for c in ctx.objs["chapter"])
    ctx.objs["edition"].append(
        envelope(
            id=ctx.as_of,
            type="edition",
            as_of=ctx.as_of,
            data_through=ctx.as_of,
            source=["/api/edition"],
            title=f"The edition of {day_in_words(ctx.as_of)}",
            day_n=edition.get("day_n") if isinstance(edition.get("day_n"), int) else None,
            start_date=today.get("start_date") if ISO_DAY.match(str(today.get("start_date") or "")) else None,
            order=[str(k) for k in (edition.get("order") or [])],
            blocks={
                k: {kk: v.get(kk) for kk in ("state", "as_of", "source", "absent_text", "data")}
                for k, v in blocks.items()
                if isinstance(v, dict)
            },
            edges=[{"type": "chapter", "id": latest_chapter, "rel": "this_week"}] if known else [],
        )
    )


def build_live(base_url: str, timeout: float) -> dict[str, list[dict]]:
    """Map the public Site API onto the content model. Only public endpoints, only GETs."""
    return build_live_with_data(base_url, timeout)[0]


def build_live_with_data(base_url: str, timeout: float) -> tuple[dict[str, list[dict]], dict]:
    ctx = _build_live_ctx(base_url, timeout)
    return ctx.objs, {"series": ctx.series, "pairs": ctx.pairs}


def _build_live_ctx(base_url: str, timeout: float) -> "LiveContext":
    ctx = LiveContext(base_url, fetch_live(base_url, timeout), timeout)
    _live_episodes(ctx)  # first, so chapters can point at them
    _live_chapters(ctx)
    _live_week_states(ctx)
    _live_coaches(ctx)
    _live_ledger(ctx)
    _live_disagreements(ctx)
    _live_sources(ctx)
    _live_methods(ctx)
    _live_metrics(ctx)  # after sources and methods: its edges point at them
    _live_experiments(ctx)
    _live_essays(ctx)
    _live_edition(ctx)
    return ctx


def run(mode: str, out_dir: str, fixtures_dir: str, base_url: str, timeout: float) -> dict:
    if mode == "fixture":
        objs = load_fixtures(fixtures_dir)
        data_files = load_fixture_data_files(fixtures_dir)
    else:
        objs, data_files = build_live_with_data(base_url, timeout)
    public, excluded = partition(objs)
    bad = dangling_edges(public)
    if bad:
        raise LookupError("dangling edge(s): " + "; ".join(bad[:12]) + (f" (+{len(bad) - 12})" if len(bad) > 12 else ""))
    validate_data_files(data_files, public)
    return write_snapshot(out_dir, public, excluded, mode, base_url, build_appendix(), data_files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=("fixture", "live"), required=True)
    ap.add_argument("--out", required=True, help="directory to write the snapshot into (www/content/snapshot)")
    ap.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args(argv)
    try:
        manifest = run(args.mode, args.out, args.fixtures, args.base_url, args.timeout)
    except SchemaError as exc:
        log(f"SNAPSHOT-SCHEMA-ERROR {exc}")
        return 2
    except LookupError as exc:
        log(f"SNAPSHOT-DANGLING-EDGE {exc}")
        return 3
    except RuntimeError as exc:
        log(f"SNAPSHOT-FETCH-FAILED {exc}")
        return 4
    counts = ", ".join(f"{k.removesuffix('.json')}={v['count']}" for k, v in manifest["files"].items())
    log(f"SNAPSHOT-OK mode={manifest['mode']} as_of={manifest['as_of']} excluded={manifest['excluded']} {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
