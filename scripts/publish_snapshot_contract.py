#!/usr/bin/env python3
"""scripts/publish_snapshot_contract.py — the publication snapshot's CONTRACT: the schema mirror
(pinned equal to www/src/content.config.ts), the envelope, validation, the public/held/private
partition, the dangling-edge check, the date-to-words rule, the prose sanitiser, the appendix and
the writer. Pure: no network, no clock. `scripts/publish_snapshot.py` (the live mappers and the
CLI) imports everything here and re-exports it, so `publish_snapshot.<name>` keeps working for
every caller and test. Split out of the exporter when it crossed the 1000-line module ceiling
(tests/test_module_size_guard.py) in the v9 Phase 1/2 build (#5535, #5536).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
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
        "how",
        "actual_text",
        "tolerance_text",
        "outcome_notes",
        "short",
        "aggregate_impact",
        "absent_text",
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
# Each field: (kind, nullable). kinds: str (non-empty), text (may be empty), int, num, bool, day, id, list[str], list[id], list[obj],
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
        "status": ("enum:published|held|skipped|pending", False),
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
        "transcript": ("list[obj]", True),
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
        "coach_name": ("str", False),
        "retired": ("bool", False),
        "metric_key": ("str", True),
        "corrections": ("list[obj]", False),
        "claim_withheld": ("enum:unsourced|privacy", True),
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
        "quality": ("obj", True),
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
    elif kind == "list[obj]":
        if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            raise SchemaError(f"{where}: expected list of objects")
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


_PROSE = re.compile(
    r'<article class="post-body">\s*<div class="prose">([\s\S]*?)</div>\s*(?:<div class="signature">[\s\S]*?</div>\s*)?</article>'
)
_SCRIPT = re.compile(r"<script\b[\s\S]*?</script\b[^>]*>|<script\b[^>]*/>", re.IGNORECASE)  # an end tag with whitespace or attributes too
_ON_ATTR = re.compile(r'\s+on[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE)
_ROOT_LINK = re.compile(r'(href|src)="(/[^"]*)"')


def extract_prose(html: str, base_url: str) -> str | None:
    """The published body as published: the `.prose` block of a permalink page, with any script,
    inline handler or root-relative link made safe for a different host. None when the page has no
    prose block (the permalink changed shape) — the chapter then says the text lives on the site."""
    m = _PROSE.search(html or "")
    if not m:
        return None
    body = _SCRIPT.sub("", m.group(1))
    body = _ON_ATTR.sub("", body)
    body = _ROOT_LINK.sub(lambda mm: f'{mm.group(1)}="{base_url.rstrip("/")}{mm.group(2)}"', body)
    return body.strip() or None


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


REFERENCE_GROUP = "Earlier front pages"
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def reference_copies(site: str = os.path.join(REPO, "site")) -> list[dict]:
    """The kept copies of replaced layouts under site/reference/<date>-<slug>/ (owner ruling 2026-10-18).

    Derived from the tree, never hand-listed: each copy is a served, noindex page whose head comment
    names the last live sha (scripts/v9_reference_copies.py writes them; the #4588 v5 copies are the
    precedent). They are EXEMPT from the page registry, so the appendix reads them here (#5534). The
    date in the name is rendered in words — the site never shows an ISO date (tests/web_preview_gate.py).
    """
    root = os.path.join(site, "reference")
    if not os.path.isdir(root):
        return []
    items = []
    for name in sorted(os.listdir(root)):
        index = os.path.join(root, name, "index.html")
        if not os.path.isfile(index):
            continue
        with open(index, encoding="utf-8") as fh:
            head = fh.read(8000)
        m = _TITLE_RE.search(head)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else name
        items.append(
            {
                "path": f"/reference/{name}/",
                "name": f"{title} — as served until {day_in_words(name[:10])}",
                "group": REFERENCE_GROUP,
                "unlisted": True,
            }
        )
    return items


def build_appendix() -> dict:
    """Every registered page that keeps an earlier design, grouped — read from qa/qa_manifest.py,
    plus the reference copies of replaced layouts (from the site/reference/ tree, #5534)."""
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
        if m.get("owner") == "www":
            continue  # #5534: a v9 page is the site, not something the site keeps from an earlier design
        group = next((g for prefix, g in GROUPS if path.startswith(prefix)), "Other pages")
        items.append({"path": path, "name": m.get("name") or path, "group": group, "unlisted": bool(m.get("unlisted"))})
    items.extend(reference_copies())
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


def _write_data_files(out_dir: str, data_files: dict, files: dict) -> None:
    """series/<metric>.json and pairs.json — data files beside the collections, hashed into the manifest."""
    series_dir = os.path.join(out_dir, "series")
    os.makedirs(series_dir, exist_ok=True)
    for old in os.listdir(series_dir):
        os.remove(os.path.join(series_dir, old))
    for key, payload in sorted((data_files.get("series") or {}).items()):
        text = _dump(payload)
        with open(os.path.join(series_dir, f"{key}.json"), "w", encoding="utf-8") as fh:
            fh.write(text)
        files[f"series/{key}.json"] = {"count": len(payload.get("days", [])), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    pairs = data_files.get("pairs") or {
        "as_of": None,
        "lags": [],
        "min_n": None,
        "window": None,
        "family": None,
        "lag_meaning": None,
        "method_ids": [],
        "pairs": [],
    }
    text = _dump(pairs)
    with open(os.path.join(out_dir, "pairs.json"), "w", encoding="utf-8") as fh:
        fh.write(text)
    files["pairs.json"] = {"count": len(pairs.get("pairs", [])), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def write_snapshot(
    out_dir: str,
    public: dict[str, list[dict]],
    excluded: dict[str, int],
    mode: str,
    base_url: str | None,
    appendix: dict,
    data_files: dict | None = None,
) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    data_files = data_files or {}
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
    _write_data_files(out_dir, data_files, files)
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


def load_fixture_data_files(fixtures_dir: str) -> dict:
    """The series/ files and pairs.json beside the fixture collections."""
    out: dict = {"series": {}, "pairs": None}
    sdir = os.path.join(fixtures_dir, "series")
    if os.path.isdir(sdir):
        for name in sorted(os.listdir(sdir)):
            if name.endswith(".json"):
                with open(os.path.join(sdir, name), encoding="utf-8") as fh:
                    out["series"][name[:-5]] = json.load(fh)
    ppath = os.path.join(fixtures_dir, "pairs.json")
    if os.path.exists(ppath):
        with open(ppath, encoding="utf-8") as fh:
            out["pairs"] = json.load(fh)
    return out


def validate_data_files(data_files: dict, public: dict[str, list[dict]]) -> None:
    """Series and pairs are data files, not collections — a light shape check, plus every metric
    they name must be a public Metric (the derivation guard for the data room)."""
    metrics = {o["id"] for o in public["metric"]}
    for key, payload in (data_files.get("series") or {}).items():
        if key not in metrics:
            raise LookupError(f"series/{key}.json names a metric that is not public")
        days = payload.get("days")
        if not isinstance(days, list) or not days:
            raise SchemaError(f"series/{key}.json: days must be a non-empty list")
        for d in days:
            ok = (
                isinstance(d, dict)
                and ISO_DAY.match(str(d.get("date") or ""))
                and isinstance(d.get("present"), bool)
                and isinstance(d.get("gap"), bool)
            )
            if not ok:
                raise SchemaError(f"series/{key}.json: bad day row {d!r}")
            v = d.get("value")
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise SchemaError(f"series/{key}.json: value must be a number or null")
    pairs = data_files.get("pairs") or {}
    for r in pairs.get("pairs") or []:
        for side in ("a", "b"):
            if r.get(side) not in metrics:
                raise LookupError(f"pairs.json names a metric that is not public: {r.get(side)}")
        if "significant" in json.dumps(r).lower():
            raise SchemaError("pairs.json: the word 'significant' is not served")
