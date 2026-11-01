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
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

EXPORTER_VERSION = "0.1.0"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FIXTURES = os.path.join(REPO, "www", "content", "fixtures")
DEFAULT_BASE_URL = "https://averagejoematt.com"
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_ISO_IN_TEXT = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
# Free-text fields a page prints verbatim. Dates on a reader surface are written in words
# (the kit's standing rule, held by tests/web_preview_gate.py), so an ISO date inside served
# prose is rewritten here — presentation only; ids, urls, formulas and the dated fields the
# templates format themselves are left exactly as served.
_WORDED_TEXT_KEYS = frozenset(
    {
        "title",
        "summary",
        "claim",
        "verdict_text",
        "reason",
        "short_bio",
        "comparison_text",
        "limitations",
        "window",
        "sentence",
        "instrument",
        "hypothesis",
        "topic",
        "claim_a",
        "claim_b",
        "verdict",
        "text",
        "excerpt",
        "absent_text",
        "label",
        "name",
        "outcome_notes",
        "how",
        "actual_text",
        "tolerance_text",
        "byline",
    }
)


def day_in_words(iso: str) -> str:
    """'2026-10-31' -> '31 October 2026'; anything else is returned unchanged."""
    m = _ISO_IN_TEXT.fullmatch(iso or "")
    if not m:
        return iso
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 1 <= mo <= 12:
        return iso
    return f"{d} {_MONTHS[mo - 1]} {y}"


def _words_in_text(value: str) -> str:
    return _ISO_IN_TEXT.sub(lambda m: day_in_words(m.group(0)), value)


def word_dates(obj: Any, key: str | None = None) -> Any:
    """Rewrite ISO dates to words inside the free-text keys, recursively (grading, simple_guess, instrument_absent)."""
    if isinstance(obj, dict):
        return {k: word_dates(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [word_dates(v, key) for v in obj]
    if isinstance(obj, str) and key in _WORDED_TEXT_KEYS:
        return _words_in_text(obj)
    return obj


OBJECT_TYPES = (
    "chapter",
    "episode",
    "essay",
    "metric",
    "insight",
    "experiment",
    "prediction",
    "disagreement",
    "coach",
    "source",
    "method",
    "edition",
)
COLLECTION_OF = {
    "chapter": "chapters",
    "episode": "episodes",
    "essay": "essays",
    "metric": "metrics",
    "insight": "insights",
    "experiment": "experiments",
    "prediction": "predictions",
    "disagreement": "disagreements",
    "coach": "coaches",
    "source": "sources",
    "method": "methods",
    "edition": "editions",
}
VISIBILITIES = ("public", "held", "private")

# ── the schema mirror ────────────────────────────────────────────────────────────────────
# Each field: (kind, nullable). kinds: str (non-empty), text (may be empty), int, num, bool, day, id, list[str], list[id],
# edges, approval, enum:<a|b|c>, obj (unchecked structure), list[obj].
ENVELOPE: dict[str, tuple[str, bool]] = {
    "id": ("id", False),
    "type": ("str", False),
    "visibility": ("enum:public|held|private", False),
    "as_of": ("day", False),
    "data_through": ("day", True),
    "source": ("list[str]", False),
    "state": ("enum:ok|stale|absent", False),
    "absent_text": ("str", True),
    "approved": ("approval", True),
    "method_ids": ("list[id]", False),
    "edges": ("edges", False),
    "sample": ("bool", False),
    "title": ("str", False),
    "summary": ("str", True),
}
SCHEMA: dict[str, dict[str, tuple[str, bool]]] = {
    "chapter": {
        "week": ("int", True),
        "week_label": ("str", False),
        "date": ("day", False),
        "status": ("enum:published|held|skipped", False),
        "excerpt": ("str", True),
        "body_html": ("str", True),
        "word_count": ("int", True),
        "read_minutes": ("int", True),
        "url_legacy": ("str", True),
        "episode_id": ("id", True),
    },
    "episode": {
        "number": ("int", False),
        "date": ("day", False),
        "duration_sec": ("int", True),
        "audio_url": ("str", True),
        "transcript_url": ("str", True),
        "byline": ("str", True),
        "chapter_id": ("id", True),
    },
    "essay": {"date": ("day", False), "body_html": ("str", True), "url_legacy": ("str", True)},
    "metric": {
        "label": ("str", False),
        "unit": ("text", False),
        "source_id": ("id", True),
        "decimals": ("int", False),
        "sentence": ("str", True),
        "instrument": ("str", True),
        "series_url": ("str", True),
    },
    "insight": {
        "date": ("day", False),
        "kind": ("enum:insight|hypothesis", False),
        "status": ("str", False),
        "text": ("str", False),
        "metric_id": ("id", True),
    },
    "experiment": {
        "name": ("str", False),
        "status": ("str", False),
        "hypothesis": ("str", True),
        "pillar": ("str", True),
        "start_date": ("day", True),
        "end_date": ("day", True),
        "pre_registered": ("bool", False),
        "metric_id": ("id", True),
    },
    "prediction": {
        "coach_id": ("id", False),
        "metric_id": ("id", True),
        "claim": ("str", False),
        "logged_date": ("day", False),
        "due_date": ("day", True),
        "settled_date": ("day", True),
        "kind": ("enum:number|direction|yes_no|sealed|interval|observation|unknown", False),
        "status": ("enum:pending|confirmed|refuted|expired|inconclusive|observation", False),
        "verdict_text": ("str", True),
        "grading": ("obj", True),
        "simple_guess": ("obj", True),
        "quality_flags": ("list[str]", False),
        "sealed": ("bool", False),
        "confidence": ("num", True),
    },
    "disagreement": {
        "topic": ("str", False),
        "coach_a": ("id", False),
        "coach_b": ("id", False),
        "claim_a": ("str", True),
        "claim_b": ("str", True),
        "status": ("enum:open|resolved|void", False),
        "resolved_date": ("day", True),
        "verdict": ("str", True),
        "metric_id": ("id", True),
    },
    "coach": {
        "name": ("str", False),
        "domain": ("str", False),
        "tier": ("enum:lead|staff", False),
        "retired": ("bool", False),
        "retired_date": ("day", True),
        "short_bio": ("str", True),
        "record": ("obj", True),
        "comparison_text": ("str", True),
        "instrument_absent": ("obj", True),
    },
    "source": {
        "label": ("str", False),
        "category": ("str", True),
        "since": ("str", True),
        "latest": ("str", True),
        "status": ("enum:live|stale|paused|behavioral-stale|unknown", False),
        "stale_hours": ("int", True),
        "instrument_for": ("id", True),
        "behavioral": ("bool", False),
    },
    "method": {
        "name": ("str", False),
        "category": ("str", True),
        "formula": ("str", True),
        "window": ("str", True),
        "limitations": ("str", True),
        "min_n": ("int", True),
        "used_by": ("list[str]", False),
    },
    "edition": {
        "day_n": ("int", True),
        "start_date": ("day", True),
        "order": ("list[str]", False),
        "blocks": ("obj", False),
    },
}
QUALITY_FLAGS = ("logging_gap", "low_power", "proxy_metric")


class SchemaError(ValueError):
    pass


def _check(kind: str, nullable: bool, value: Any, where: str) -> None:
    if value is None:
        if nullable:
            return
        raise SchemaError(f"{where}: null not allowed")
    if kind.startswith("enum:"):
        allowed = kind[5:].split("|")
        if value not in allowed:
            raise SchemaError(f"{where}: {value!r} not in {allowed}")
        return
    if kind == "str":
        if not isinstance(value, str) or not value.strip():
            raise SchemaError(f"{where}: expected non-empty string, got {value!r}")
    elif kind == "text":
        if not isinstance(value, str):
            raise SchemaError(f"{where}: expected string, got {value!r}")
    elif kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaError(f"{where}: expected int, got {value!r}")
    elif kind == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaError(f"{where}: expected number, got {value!r}")
    elif kind == "bool":
        if not isinstance(value, bool):
            raise SchemaError(f"{where}: expected bool, got {value!r}")
    elif kind == "day":
        if not isinstance(value, str) or not ISO_DAY.match(value):
            raise SchemaError(f"{where}: expected YYYY-MM-DD, got {value!r}")
    elif kind == "id":
        if not isinstance(value, str) or not ID_RE.match(value):
            raise SchemaError(f"{where}: bad id {value!r}")
    elif kind == "list[str]":
        if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
            raise SchemaError(f"{where}: expected list of non-empty strings")
    elif kind == "list[id]":
        if not isinstance(value, list) or not all(isinstance(x, str) and ID_RE.match(x) for x in value):
            raise SchemaError(f"{where}: expected list of ids")
    elif kind == "edges":
        if not isinstance(value, list):
            raise SchemaError(f"{where}: expected list")
        for i, e in enumerate(value):
            if not isinstance(e, dict) or e.get("type") not in OBJECT_TYPES or not isinstance(e.get("id"), str) or not ID_RE.match(e["id"]):
                raise SchemaError(f"{where}[{i}]: bad edge {e!r}")
            extra = set(e) - {"type", "id", "rel"}
            if extra:
                raise SchemaError(f"{where}[{i}]: unknown edge keys {sorted(extra)}")
    elif kind == "approval":
        if (
            not isinstance(value, dict)
            or set(value) != {"by", "at", "via"}
            or not all(isinstance(value[k], str) and value[k] for k in value)
        ):
            raise SchemaError(f"{where}: approval needs by/at/via strings")
    elif kind == "obj":
        if not isinstance(value, dict):
            raise SchemaError(f"{where}: expected object")
    else:  # pragma: no cover — a typo in SCHEMA
        raise SchemaError(f"{where}: unknown kind {kind}")


def validate(obj: dict, type_: str) -> None:
    """Raise SchemaError unless ``obj`` is a well-formed object of ``type_`` (strict keys)."""
    if obj.get("type") != type_:
        raise SchemaError(f"{obj.get('id')}: type {obj.get('type')!r} != {type_!r}")
    fields = {**ENVELOPE, **SCHEMA[type_]}
    unknown = set(obj) - set(fields)
    if unknown:
        raise SchemaError(f"{type_} {obj.get('id')}: unknown field(s) {sorted(unknown)}")
    for name, (kind, nullable) in fields.items():
        if name not in obj:
            raise SchemaError(f"{type_} {obj.get('id')}: missing field {name}")
        _check(kind, nullable, obj[name], f"{type_} {obj.get('id')}.{name}")
    if type_ == "prediction":
        bad = [f for f in obj["quality_flags"] if f not in QUALITY_FLAGS]
        if bad:
            raise SchemaError(f"prediction {obj['id']}: unknown quality flag(s) {bad}")
    if "decimals" in obj and not 0 <= obj["decimals"] <= 3:
        raise SchemaError(f"metric {obj['id']}: decimals out of range")


def envelope(**kw: Any) -> dict:
    """The publication envelope with Phase 0 defaults; callers override what they know."""
    base = {
        "visibility": "public",
        "data_through": None,
        "source": [],
        "state": "ok",
        "absent_text": None,
        "approved": None,
        "method_ids": [],
        "edges": [],
        "sample": False,
        "summary": None,
    }
    base.update(kw)
    return base


# ── fixture mode ─────────────────────────────────────────────────────────────────────────
def load_fixtures(fixtures_dir: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for type_, coll in COLLECTION_OF.items():
        path = os.path.join(fixtures_dir, f"{coll}.json")
        if not os.path.exists(path):
            out[type_] = []
            continue
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise SchemaError(f"{path}: expected a JSON array")
        out[type_] = data
    return out


# ── live mode ────────────────────────────────────────────────────────────────────────────
def _get(base_url: str, path: str, timeout: float) -> Any:
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(
        url, headers={"User-Agent": "life-platform publish_snapshot/" + EXPORTER_VERSION, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — constant public base URL
        return json.loads(resp.read().decode("utf-8"))


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
    "calls": "/api/calls",
    "docket": "/api/coach_docket",
    "freshness": "/api/source_freshness",
    "methods": "/api/methods",
    "experiments": "/api/experiments",
    "blog": "/journal/blog.json",
}
OPTIONAL_ENDPOINTS = ("blog", "docket", "experiments")


class LiveContext:
    """What the per-collection mappers share: the fetched payloads and the cross-references
    built as the collections are mapped (episodes by week, chapters by week, the coach ids,
    the metric keys the pending calls name)."""

    def __init__(self, base_url: str, fetched: dict[str, Any]):
        self.base_url = base_url.rstrip("/")
        self.fetched = fetched
        self.as_of: str = (fetched["edition"] or {}).get("as_of")
        self.objs: dict[str, list[dict]] = {t: [] for t in OBJECT_TYPES}
        self.ep_by_week: dict[int, str] = {}
        self.chapter_by_week: dict[int, str] = {}
        self.coach_ids: set[str] = set()
        self.metric_keys: set[str] = set()

    def rows(self, key: str, field: str) -> list:
        return (self.fetched.get(key) or {}).get(field) or []


def fetch_live(base_url: str, timeout: float) -> dict[str, Any]:
    fetched: dict[str, Any] = {}
    for key, path in LIVE_ENDPOINTS.items():
        try:
            fetched[key] = _get(base_url, path, timeout)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
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
                transcript_url=e.get("transcript_url"),
                byline=e.get("byline"),
                chapter_id=None,
            )
        )


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
                body_html=None,  # Phase 1 carries the published body across, as published
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
                instrument_absent={"absent": bool(c.get("absent")), "reason": c.get("reason")} if c.get("absent") else None,
            )
        )
    ctx.coach_ids = {c["id"] for c in ctx.objs["coach"]}


def _live_checked_calls(ctx: LiveContext) -> set[str]:
    """The checked calls (`/api/calls`): real ids, grading, the simple guess. Returns the ids seen."""
    seen: set[str] = set()
    for k in ctx.rows("calls", "calls"):
        pid = _persona(k["coach_id"])
        if pid not in ctx.coach_ids:
            continue
        status = {"right": "confirmed", "wrong": "refuted"}.get(k.get("verdict"), "inconclusive")
        tol = k.get("tolerance") or {}
        act = k.get("actual") or {}
        sg = k.get("simple_guess") or None
        kind = k.get("kind") if k.get("kind") in ("number", "direction", "yes_no", "sealed", "interval") else "unknown"
        ctx.objs["prediction"].append(
            envelope(
                id=k["id"],
                type="prediction",
                as_of=ctx.as_of,
                data_through=k.get("settled_date"),
                source=["/api/calls"],
                title=k.get("title") or k.get("called_short") or k["claim"],
                summary=k.get("happened_short"),
                coach_id=pid,
                metric_id=None,
                claim=k["claim"],
                logged_date=k["logged_date"],
                due_date=None,
                settled_date=k.get("settled_date"),
                kind=kind,
                status=status,
                verdict_text=k.get("verdict_text"),
                grading={
                    "how": tol.get("statistic"),
                    "actual_text": act.get("text"),
                    "tolerance_text": tol.get("text"),
                    "outcome_notes": k.get("happened"),
                },
                simple_guess={"state": sg.get("state", "unknown"), "right": sg.get("right"), "text": sg.get("text")} if sg else None,
                quality_flags=[],
                sealed=bool(k.get("sealed")),
                confidence=None,
                edges=[{"type": "coach", "id": pid, "rel": "made_by"}],
            )
        )
        seen.add(k["id"])
    return seen


def _live_pending_calls(ctx: LiveContext, seen: set[str]) -> None:
    """The pending rows (`/api/predictions`): served without an id, so a stable one is minted
    from coach · date · claim until Phase 3 exports prediction_id."""
    for r in ctx.rows("predictions", "predictions"):
        if r.get("status") != "pending":
            continue
        pid = _persona(r["coach_id"])
        if pid not in ctx.coach_ids:
            continue
        digest = hashlib.sha1((r.get("text") or "").encode("utf-8")).hexdigest()[:10]  # noqa: S324 — id minting, not security
        rid = f"{r['coach_id']}-{r['date'].replace('-', '')}-{digest}"
        if rid in seen:
            continue
        seen.add(rid)
        metric = r.get("metric") if isinstance(r.get("metric"), str) and ID_RE.match(r.get("metric") or "") else None
        if metric:
            ctx.metric_keys.add(metric)
        edges = [{"type": "coach", "id": pid, "rel": "made_by"}]
        if metric:
            edges.append({"type": "metric", "id": metric, "rel": "about"})
        ctx.objs["prediction"].append(
            envelope(
                id=rid,
                type="prediction",
                as_of=ctx.as_of,
                source=["/api/predictions"],
                title=(r.get("text") or rid)[:120],
                coach_id=pid,
                metric_id=metric,
                claim=r["text"],
                logged_date=r["date"],
                due_date=r.get("due_date"),
                settled_date=None,
                kind={"directional": "direction", "point": "number", "machine": "number"}.get(r.get("eval_type") or "", "unknown"),
                status="pending",
                verdict_text=None,
                grading=None,
                simple_guess=None,
                quality_flags=[],
                sealed=bool(r.get("pre_registered")),
                confidence=float(r["confidence"]) if isinstance(r.get("confidence"), (int, float)) else None,
                edges=edges,
            )
        )


def _live_metrics(ctx: LiveContext) -> None:
    """The metric keys the pending calls name (Phase 2 exports the registry proper)."""
    for key in sorted(ctx.metric_keys):
        ctx.objs["metric"].append(
            envelope(
                id=key,
                type="metric",
                as_of=ctx.as_of,
                source=["/api/predictions"],
                title=key.replace("_", " "),
                label=key.replace("_", " "),
                unit="",
                source_id=None,
                decimals=1,
                sentence=None,
                instrument=None,
                series_url=None,
            )
        )


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
                body_html=None,
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
    ctx = LiveContext(base_url, fetch_live(base_url, timeout))
    _live_episodes(ctx)  # first, so chapters can point at them
    _live_chapters(ctx)
    _live_coaches(ctx)
    seen = _live_checked_calls(ctx)
    _live_pending_calls(ctx, seen)
    _live_metrics(ctx)
    _live_disagreements(ctx)
    _live_sources(ctx)
    _live_methods(ctx)
    _live_experiments(ctx)
    _live_essays(ctx)
    _live_edition(ctx)
    return ctx.objs


# ── the appendix (the kept pages, from the page registry) ───────────────────────────────
KIT_LIVE = {"/", "/start/", "/story/", "/coaches/"}
UTILITY = {"/subscribe/", "/privacy/", "/404.html"}
GROUPS = [
    ("/cockpit/", "Today's slice"),
    ("/data/", "Detailed data pages"),
    ("/protocols/", "What he tries"),
    ("/coaching/", "The coaches, in detail"),
    ("/story/", "The story, in detail"),
    ("/journal/", "The story, in detail"),
    ("/method/", "How it's built, in detail"),
    ("/gear/", "How it's built, in detail"),
]


def build_appendix() -> dict:
    """Every registered page that keeps an earlier design, grouped — read from qa/qa_manifest.py."""
    sys.path.insert(0, REPO)
    try:
        from qa.qa_manifest import MANIFEST  # type: ignore
    except Exception as exc:  # pragma: no cover — the registry is in the repo
        log(f"  qa_manifest unavailable ({exc}); appendix left empty")
        return {"items": []}
    items = []
    for m in MANIFEST:
        path = m.get("path")
        if not path or path in KIT_LIVE or path in UTILITY:
            continue
        group = next((g for prefix, g in GROUPS if path.startswith(prefix)), "Other pages")
        items.append({"path": path, "name": m.get("name") or path, "group": group, "unlisted": bool(m.get("unlisted"))})
    items.sort(key=lambda it: (it["group"], it["path"]))
    return {"items": items}


# ── the gate: validate · partition · dangling edges · write ─────────────────────────────
def partition(objs: dict[str, list[dict]]) -> tuple[dict[str, list[dict]], dict[str, int]]:
    public: dict[str, list[dict]] = {t: [] for t in OBJECT_TYPES}
    excluded = {"held": 0, "private": 0}
    for type_, items in objs.items():
        for o in items:
            vis = o.get("visibility")
            if vis not in VISIBILITIES:
                raise SchemaError(f"{type_} {o.get('id')}: visibility {vis!r} is not one of {VISIBILITIES}")
            if vis == "public":
                o = word_dates(o)
                validate(o, type_)
                public[type_].append(o)
            else:
                excluded[vis] += 1
    for type_, items in public.items():
        ids = [o["id"] for o in items]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise SchemaError(f"{type_}: duplicate id(s) {dupes}")
        items.sort(key=lambda o: o["id"])
    return public, excluded


def dangling_edges(public: dict[str, list[dict]]) -> list[str]:
    known = {(t, o["id"]) for t, items in public.items() for o in items}
    bad = []
    for t, items in public.items():
        for o in items:
            for e in o["edges"]:
                if (e["type"], e["id"]) not in known:
                    bad.append(f"{t}:{o['id']} -> {e['type']}:{e['id']}")
            for mid in o["method_ids"]:
                if ("method", mid) not in known:
                    bad.append(f"{t}:{o['id']} -> method:{mid} (method_ids)")
            for ref in ("coach_id", "coach_a", "coach_b"):
                if ref in o and ("coach", o[ref]) not in known:
                    bad.append(f"{t}:{o['id']} -> coach:{o[ref]} ({ref})")
    return bad


def _dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def write_snapshot(
    out_dir: str, public: dict[str, list[dict]], excluded: dict[str, int], mode: str, base_url: str | None, appendix: dict
) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    files: dict[str, dict] = {}
    for type_, coll in COLLECTION_OF.items():
        text = _dump(public[type_])
        path = os.path.join(out_dir, f"{coll}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        files[f"{coll}.json"] = {"count": len(public[type_]), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    text = _dump(appendix)
    with open(os.path.join(out_dir, "appendix.json"), "w", encoding="utf-8") as fh:
        fh.write(text)
    files["appendix.json"] = {"count": len(appendix.get("items", [])), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    as_of = max((o["as_of"] for items in public.values() for o in items), default=None)
    manifest = {
        "exporter_version": EXPORTER_VERSION,
        "mode": mode,
        "base_url": base_url if mode == "live" else None,
        "as_of": as_of,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "files": files,
        "excluded": excluded,
        "note": "Only visibility=public objects are written. held/private are counted here and never serialised.",
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(_dump(manifest))
    return manifest


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def run(mode: str, out_dir: str, fixtures_dir: str, base_url: str, timeout: float) -> dict:
    objs = load_fixtures(fixtures_dir) if mode == "fixture" else build_live(base_url, timeout)
    public, excluded = partition(objs)
    bad = dangling_edges(public)
    if bad:
        raise LookupError("dangling edge(s): " + "; ".join(bad[:12]) + (f" (+{len(bad) - 12})" if len(bad) > 12 else ""))
    return write_snapshot(out_dir, public, excluded, mode, base_url, build_appendix())


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
