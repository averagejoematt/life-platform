"""tests/test_web_publication_snapshot_5530.py — the publication snapshot contract (#5530,
epic #5529; docs/design/v9/STAGE4_ENGINEERING_PLAN.md §B, §D).

What is pinned, and why each is a test rather than a convention:
  * the Python SCHEMA mirror and the Astro zod schema (www/src/content.config.ts) declare
    the same field set per collection — the two halves of the contract cannot drift apart
    silently (CHARTER primitive 4, "every must-agree pair gets a contract test");
  * a ``held`` or ``private`` object never reaches the public snapshot: not its id, not its
    title — the owner's exit criterion 3;
  * a dangling edge fails the export (the derivation guard for the relationship index);
  * a malformed object fails the export with the field named;
  * two exports over the same fixtures are byte-identical (exit criterion 1 — the build is
    reproducible because its input is);
  * the appendix derives from the page registry, never a hand list.

No network: fixture mode only. The live mapper is exercised against captured shapes in
``test_live_mapper_against_captured_shapes``.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "scripts", "publish_snapshot.py")
FIXTURES = os.path.join(REPO, "www", "content", "fixtures")
CONFIG_TS = os.path.join(REPO, "www", "src", "content.config.ts")


def _load():
    spec = importlib.util.spec_from_file_location("publish_snapshot", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ps = _load()


def _run(tmp_path, fixtures=FIXTURES):
    out = tmp_path / "snapshot"
    return ps.run("fixture", str(out), str(fixtures), ps.DEFAULT_BASE_URL, 5.0), out


# ── 1. the two schema halves agree ───────────────────────────────────────────────────────
def _ts_fields():
    """Parse the per-collection field names out of content.config.ts (envelope + extension)."""
    src = open(CONFIG_TS, encoding="utf-8").read()
    env_block = re.search(r"const envelope = [\s\S]*?z\s*\.object\(\{([\s\S]*?)\}\)\s*\.extend", src).group(1)
    envelope = set(re.findall(r"^\s*([a-z_]+):", env_block, re.M))
    fields = {}
    for m in re.finditer(r'schema: envelope\("([a-z]+)", \{([\s\S]*?)\n  \}\),', src):
        type_, body = m.group(1), m.group(2)
        # top-level keys only: indentation of exactly four spaces
        fields[type_] = set(re.findall(r"^    ([a-z_]+):", body, re.M))
    return envelope, fields


def test_python_schema_mirrors_the_astro_schema_field_for_field():
    envelope, fields = _ts_fields()
    assert envelope == set(ps.ENVELOPE), sorted(envelope ^ set(ps.ENVELOPE))
    assert set(fields) == set(ps.SCHEMA), sorted(set(fields) ^ set(ps.SCHEMA))
    for type_, names in fields.items():
        assert names == set(ps.SCHEMA[type_]), f"{type_}: {sorted(names ^ set(ps.SCHEMA[type_]))}"


def test_object_types_and_collections_agree_with_the_ts_side():
    src = open(CONFIG_TS, encoding="utf-8").read()
    types = re.search(r"OBJECT_TYPES = \[([\s\S]*?)\] as const", src).group(1)
    ts_types = re.findall(r'"([a-z]+)"', types)
    assert tuple(ts_types) == ps.OBJECT_TYPES
    exported = re.search(r"export const collections = \{([\s\S]*?)\};", src).group(1)
    assert set(re.findall(r"\b([a-z]+)\b", exported)) == set(ps.COLLECTION_OF.values())


# ── 2. the visibility gate ───────────────────────────────────────────────────────────────
def test_fixtures_carry_poison_so_the_gate_is_measured_not_assumed():
    raw = ps.load_fixtures(FIXTURES)
    vis = [o["visibility"] for items in raw.values() for o in items]
    assert vis.count("held") >= 1 and vis.count("private") >= 1, "the fixtures must include a held AND a private object"


def test_held_and_private_objects_never_reach_the_snapshot(tmp_path):
    manifest, out = _run(tmp_path)
    assert manifest["excluded"] == {"held": 2, "private": 1}
    blob = b"".join(open(os.path.join(root, f), "rb").read() for root, _, fs in os.walk(out) for f in fs)
    assert b"SENTINEL" not in blob, "a held/private object's content leaked into the public snapshot"
    assert b"week-10" not in blob and b"private-20261030" not in blob, "even the ID of a held/private object must not be written"
    for coll in os.listdir(out):
        if coll in ("manifest.json", "appendix.json", "pairs.json", "series"):
            continue
        for o in json.load(open(out / coll)):
            assert o["visibility"] == "public"


def test_unknown_visibility_is_refused_not_defaulted(tmp_path):
    raw = ps.load_fixtures(FIXTURES)
    raw["coach"][0]["visibility"] = "publik"
    with pytest.raises(ps.SchemaError, match="visibility"):
        ps.partition(raw)


# ── 3. dangling edges and malformed objects ──────────────────────────────────────────────
def test_a_dangling_edge_fails_the_export_naming_the_edge(tmp_path):
    fx = tmp_path / "fx"
    fx.mkdir()
    for name in os.listdir(FIXTURES):
        if not name.endswith(".json"):
            shutil.copytree(os.path.join(FIXTURES, name), fx / name)
            continue
        data = json.load(open(os.path.join(FIXTURES, name)))
        if name == "predictions.json":
            data[0]["edges"].append({"type": "metric", "id": "no_such_metric"})
        json.dump(data, open(fx / name, "w"))
    with pytest.raises(LookupError, match=r"prediction:.* -> metric:no_such_metric"):
        _run(tmp_path, fx)


def test_an_edge_to_a_held_object_is_dangling_in_the_public_snapshot(tmp_path):
    # a public chapter that points at the held chapter: the held one is not public, so the
    # edge has nowhere to land — the export must refuse rather than leak the held id
    fx = tmp_path / "fx"
    fx.mkdir()
    for name in os.listdir(FIXTURES):
        if not name.endswith(".json"):
            shutil.copytree(os.path.join(FIXTURES, name), fx / name)
            continue
        data = json.load(open(os.path.join(FIXTURES, name)))
        if name == "chapters.json":
            pub = next(c for c in data if c["visibility"] == "public")
            pub["edges"].append({"type": "chapter", "id": "week-10"})
        json.dump(data, open(fx / name, "w"))
    with pytest.raises(LookupError, match="chapter:week-10"):
        _run(tmp_path, fx)


@pytest.mark.parametrize(
    "mutation, needle",
    [
        (lambda o: o.__setitem__("as_of", "31/10/2026"), "as_of"),
        (lambda o: o.__setitem__("extra_field", 1), "unknown field"),
        (lambda o: o.pop("title"), "missing field title"),
        (lambda o: o.__setitem__("edges", [{"type": "planet", "id": "x"}]), "bad edge"),
        (lambda o: o.__setitem__("quality_flags", ["vibes"]), "quality flag"),
        (lambda o: o.__setitem__("status", "maybe"), "status"),
    ],
)
def test_malformed_prediction_is_refused_with_the_field_named(mutation, needle):
    raw = ps.load_fixtures(FIXTURES)
    o = copy.deepcopy(next(p for p in raw["prediction"] if p["visibility"] == "public"))
    mutation(o)
    with pytest.raises(ps.SchemaError, match=needle):
        ps.validate(o, "prediction")


def test_every_public_fixture_validates():
    raw = ps.load_fixtures(FIXTURES)
    for type_, items in raw.items():
        for o in items:
            if o["visibility"] == "public":
                ps.validate(o, type_)


# ── 4. reproducibility ───────────────────────────────────────────────────────────────────
def test_two_exports_are_byte_identical_except_the_manifest_clock(tmp_path):
    _, a = _run(tmp_path / "a")
    _, b = _run(tmp_path / "b")
    for name in os.listdir(a):
        if name == "series":
            for f in os.listdir(a / name):
                assert open(a / name / f, "rb").read() == open(b / name / f, "rb").read(), f
            continue
        if name == "manifest.json":
            ma, mb = json.load(open(a / name)), json.load(open(b / name))
            ma.pop("generated_at")
            mb.pop("generated_at")
            assert ma == mb
            continue
        assert open(a / name, "rb").read() == open(b / name, "rb").read(), name


def test_manifest_hashes_match_the_files(tmp_path):
    manifest, out = _run(tmp_path)
    for name, meta in manifest["files"].items():
        assert hashlib.sha256(open(out / name, "rb").read()).hexdigest() == meta["sha256"]
        data = json.load(open(out / name))
        rows = (
            data
            if isinstance(data, list)
            else (data.get("items") if "items" in data else data.get("days") if "days" in data else data["pairs"])
        )
        assert meta["count"] == len(rows), name


def test_ids_are_unique_and_sorted(tmp_path):
    _, out = _run(tmp_path)
    for coll in ps.COLLECTION_OF.values():
        ids = [o["id"] for o in json.load(open(out / f"{coll}.json"))]
        assert ids == sorted(ids) and len(ids) == len(set(ids)), coll


# ── 5. the appendix derives from the page registry ───────────────────────────────────────
def test_appendix_derives_from_qa_manifest_and_excludes_the_kit_doors():
    sys.path.insert(0, REPO)
    from qa.qa_manifest import MANIFEST

    app = ps.build_appendix()
    paths = {it["path"] for it in app["items"]}
    assert paths <= {m["path"] for m in MANIFEST}
    assert not (paths & ps.KIT_LIVE) and not (paths & ps.UTILITY)
    assert len(paths) >= 50, "the appendix lost most of the registry"
    assert all(it["group"] for it in app["items"])


# ── 6. the live mapper, on captured shapes (no network) ─────────────────────────────────
def test_live_mapper_against_captured_shapes(monkeypatch, tmp_path):
    captured = {
        "/api/edition": {
            "as_of": "2026-10-31",
            "day_n": 56,
            "order": ["today", "chapter"],
            "blocks": {
                "today": {
                    "state": "ok",
                    "as_of": "2026-10-31",
                    "source": "/api/journey",
                    "absent_text": None,
                    "data": {"start_date": "2026-09-06", "weight_lbs": 296.6},
                },
                "chapter": {
                    "state": "stale",
                    "as_of": "2026-10-13",
                    "source": ["/journal/posts.json"],
                    "absent_text": "x",
                    "data": {"url": "/journal/posts/week-09/"},
                },
            },
        },
        "/journal/posts.json": {
            "posts": [
                {
                    "date": "2026-10-13",
                    "title": "The Quiet Accumulation",
                    "url": "/journal/posts/week-09/",
                    "week": 6,
                    "label": "Week 6",
                    "word_count": 1700,
                    "excerpt": "e",
                }
            ]
        },
        "/panelcast/episodes.json": {
            "episodes": [
                {
                    "title": "EP6 · x",
                    "date": "2026-10-15",
                    "duration_sec": 1400,
                    "url": "/panelcast/wk6.mp3",
                    "byline": "The Panel",
                    "transcript_url": None,
                }
            ]
        },
        "/api/coaches": {
            "coaches": [
                {
                    "persona_id": "sleep_coach",
                    "name": "Lisa Park",
                    "domain": "Sleep",
                    "tier": "staff",
                    "absent": False,
                    "reason": None,
                    "short_bio": "b",
                },
                {"persona_id": "eli_marsh", "name": "Eli Marsh", "domain": "Lead", "tier": "lead", "absent": False},
            ]
        },
        "/api/predictions": {
            "by_coach": {
                "sleep": {
                    "decided": 48,
                    "confirmed": 19,
                    "retired": False,
                    "record": {"through": "2026-10-31"},
                    "comparison": {"sentence": "level"},
                }
            },
            "predictions": [
                {
                    "coach_id": "sleep",
                    "text": "Recovery will stabilise.",
                    "confidence": 0.5,
                    "status": "pending",
                    "date": "2026-10-19",
                    "due_date": "2026-11-02",
                    "metric": "recovery_score",
                    "eval_type": "directional",
                    "pre_registered": False,
                }
            ],
        },
        "/api/calls": {
            "calls": [
                {
                    "id": "sleep-20261005-abc1234567",
                    "kind": "direction",
                    "coach_id": "sleep",
                    "claim": "Deep sleep will rise.",
                    "logged_date": "2026-10-05",
                    "sealed": False,
                    "settled_date": "2026-10-26",
                    "verdict": "wrong",
                    "verdict_text": "Lisa Park was wrong.",
                    "actual": {"text": "17%"},
                    "tolerance": {"text": "2 points", "statistic": "the median day-to-day change"},
                    "simple_guess": {"state": "scored", "right": True, "text": "also right"},
                    "title": "Lisa called deep sleep up",
                    "happened": "flat",
                    "happened_short": "flat",
                }
            ]
        },
        "/api/coach_docket": {
            "open": [],
            # the real wire shape (2026-11-01): `verdict` is a dict once code settled the bet
            "resolved": [
                {
                    "topic": "Deep sleep spike interpretation: signal vs. noise",
                    "topic_slug": "deep-sleep-spike-interpretation-signal-vs-noise",
                    "coach_a": "sleep_coach",
                    "coach_b": "eli_marsh",
                    "claims": {"sleep_coach": "Regression to the mean.", "eli_marsh": "A real shift."},
                    "resolved_date": "2026-10-16",
                    "verdict": {
                        "actual_value": 16.357142857142858,
                        "holds": False,
                        "loser": "eli_marsh",
                        "outcome": "graded",
                        "winner": "sleep_coach",
                    },
                }
            ],
        },
        "/api/source_freshness": {
            "sources": [
                {
                    "id": "whoop",
                    "label": "WHOOP",
                    "desc": "d",
                    "category": "wearable",
                    "last_update": "2026-10-31",
                    "stale_hours": 36,
                    "status": "fresh",
                    "is_behavioral": False,
                }
            ]
        },
        "/api/methods": {
            "stats": [
                {
                    "id": "pearson_r",
                    "name": "Pearson",
                    "category": "Correlation",
                    "formula": "r",
                    "window": "w",
                    "limitations": "l",
                    "min_n": 3,
                    "used_by": ["x"],
                }
            ]
        },
        "/api/experiments": {
            "experiments": [
                {"id": "lib", "name": "Library item", "status": "backlog", "origin": "library"},
                {
                    "id": "real_2026-10-01",
                    "name": "Real",
                    "status": "active",
                    "origin": "owner",
                    "hypothesis": "h",
                    "pillar": "sleep",
                    "start_date": "2026-10-01",
                },
            ]
        },
        "/journal/blog.json": {
            "posts": [{"id": "org-chart-of-one", "title": "Org chart", "date": "2026-09-20", "url": "/journal/essays/org-chart-of-one/"}]
        },
    }
    import urllib.error

    def fake_get(base, path, timeout):
        if path not in captured:  # /api/chapters before it is live, the transcript file, …
            raise urllib.error.HTTPError(base + path, 404, "not found", None, None)
        return copy.deepcopy(captured[path])

    page = (
        '<html><body><article class="post-body"><div class="prose"><p>Week six, <a href="/data/sleep/">as published</a>.</p>'
        '<script>alert(1)</script><p onclick="x()">Kept text.</p></div><div class="signature">— E.V.</div></article></body></html>'
    )
    monkeypatch.setattr(ps, "_get", fake_get)
    monkeypatch.setattr(ps, "_get_text", lambda base, path, timeout: page)
    objs = ps.build_live("https://example.test", 1.0)
    public, excluded = ps.partition(objs)
    assert excluded == {"held": 0, "private": 0}
    assert ps.dangling_edges(public) == []
    chapters = {o["id"]: o for o in public["chapter"]}
    # the published chapter carries its body as published: scripts and inline handlers gone, links absolute
    body = chapters["week-09"]["body_html"]
    assert "Week six" in body and 'href="https://example.test/data/sleep/"' in body
    assert "<script" not in body and "onclick" not in body and "signature" not in body
    assert chapters["week-09"]["episode_id"] == "wk6" and public["episode"][0]["chapter_id"] == "week-09"
    assert public["episode"][0]["transcript"] is None  # the transcript file 404s in this capture
    # week states derived without /api/chapters: day 56 = week 8; week 6 published → 1–5 skipped, 7–8 pending
    states = {o["week"]: o["status"] for o in public["chapter"] if o["id"].startswith("program-week-")}
    assert states == {1: "skipped", 2: "skipped", 3: "skipped", 4: "skipped", 5: "skipped", 7: "pending", 8: "pending"}
    assert all(o["body_html"] is None and o["title"].startswith("Week ") for o in public["chapter"] if o["id"].startswith("program-week-"))
    assert public["coach"][0]["record"] is None  # the lead has no by_coach row
    lisa = next(c for c in public["coach"] if c["id"] == "sleep_coach")
    assert lisa["record"] == {"right": 19, "n": 48, "through": "2026-10-31"}
    kinds = {p["id"]: (p["status"], p["kind"]) for p in public["prediction"]}
    assert kinds["sleep-20261005-abc1234567"] == ("refuted", "direction")
    pending = [p for p in public["prediction"] if p["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["metric_id"] == "recovery_score"
    assert {m["id"] for m in public["metric"]} == {"recovery_score"}
    assert [x["id"] for x in public["experiment"]] == ["real_2026-10-01"], "the library catalogue is not an experiment"
    assert public["source"][0]["status"] == "live"
    assert public["edition"][0]["edges"] == [{"type": "chapter", "id": "week-09", "rel": "this_week"}]
    dis = public["disagreement"]
    assert len(dis) == 1 and dis[0]["status"] == "resolved" and dis[0]["resolved_date"] == "2026-10-16"
    assert isinstance(dis[0]["verdict"], str) and "sleep_coach" in dis[0]["verdict"] and "16.4" in dis[0]["verdict"]
    for type_, items in public.items():
        for o in items:
            ps.validate(o, type_)


# ── 7. the CLI ───────────────────────────────────────────────────────────────────────────
def test_cli_exit_codes(tmp_path):
    ok = subprocess.run(
        [sys.executable, SCRIPT, "--mode", "fixture", "--out", str(tmp_path / "s")], capture_output=True, text=True, cwd=REPO
    )
    assert ok.returncode == 0, ok.stderr
    assert "SNAPSHOT-OK" in ok.stderr and "excluded={'held': 2, 'private': 1}" in ok.stderr
    fx = tmp_path / "fx"
    fx.mkdir()
    for name in os.listdir(FIXTURES):
        if not name.endswith(".json"):
            shutil.copytree(os.path.join(FIXTURES, name), fx / name)
            continue
        data = json.load(open(os.path.join(FIXTURES, name)))
        if name == "coaches.json":
            data[0].pop("domain")
        json.dump(data, open(fx / name, "w"))
    bad = subprocess.run(
        [sys.executable, SCRIPT, "--mode", "fixture", "--out", str(tmp_path / "t"), "--fixtures", str(fx)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert bad.returncode == 2 and "SNAPSHOT-SCHEMA-ERROR" in bad.stderr
    assert not (tmp_path / "t").exists(), "a failed export must write nothing"


def test_extract_prose_keeps_the_text_and_drops_what_a_different_host_must_not_run():
    html = (
        '<article class="post-body"><div class="prose"><p>Hello <em>there</em>.</p><script src="/x.js"></script>'
        '<img src="/assets/a.png" onerror="evil()"><p>Bye.</p></div><div class="signature">sig</div></article>'
    )
    out = ps.extract_prose(html, "https://averagejoematt.com")
    assert out.startswith("<p>Hello <em>there</em>.</p>") and out.endswith("<p>Bye.</p>")
    assert "<script" not in out and "onerror" not in out and "sig" not in out
    spaced = ps.extract_prose(
        '<article class="post-body"><div class="prose"><p>a</p><script>x()</script ><p>b</p></div></article>', "https://x"
    )
    assert spaced == "<p>a</p><p>b</p>"
    attr = ps.extract_prose(
        '<article class="post-body"><div class="prose"><p>a</p><script>x()</script\t\n bar><p>b</p></div></article>', "https://x"
    )
    assert attr == "<p>a</p><p>b</p>"
    assert 'src="https://averagejoematt.com/assets/a.png"' in out
    assert ps.extract_prose("<main>no prose block</main>", "https://x") is None


def test_live_metrics_write_series_files_and_filter_pairs_to_public_metrics(monkeypatch):
    """Phase 2: the series catalogue becomes Metrics with a series file each; the pairs file keeps
    only rows whose both sides are public Metrics; the chart marker is the baseline-change date."""
    catalogue = {
        "metrics": [
            {"metric": "hrv", "unit": "ms", "source_id": "whoop", "behavioral": False},
            {"metric": "ghost", "unit": "x", "source_id": None},
        ]
    }
    pairs = {
        "lags": [-1, 0, 1],
        "min_n": 10,
        "window": {"from": "2026-09-06", "to": "2026-10-31"},
        "family": {"offered": 2, "tested": 2},
        "method_ids": ["pearson_r"],
        "pairs": [
            {"a": "hrv", "b": "ghost", "lag": 0, "n": 40, "r": 0.1},
            {"a": "hrv", "b": "secret_metric", "lag": 0, "n": 40, "r": 0.9},
        ],
    }
    series = {
        "hrv": {
            "window": {"from": "2026-09-06", "to": "2026-10-31"},
            "method_ids": [],
            "n_present": 2,
            "n_gap": 1,
            "days": [
                {"date": "2026-09-06", "value": 31.3, "present": True, "gap": False},
                {"date": "2026-09-07", "value": None, "present": False, "gap": True},
            ],
        },
    }

    def fake_get(base, path, timeout):
        if path.startswith("/api/series?metric="):
            key = path.split("metric=")[1].split("&")[0]
            if key in series:
                return series[key]
            raise urllib.error.HTTPError(path, 404, "nf", None, None)
        raise AssertionError(path)

    monkeypatch.setattr(ps, "_get", fake_get)
    monkeypatch.setattr(ps, "_baseline_change_markers", lambda: [{"date": "2026-10-10", "label": "baseline change"}])
    fetched = {
        "edition": {"as_of": "2026-10-31", "blocks": {"today": {"data": {"start_date": "2026-09-06"}}}},
        "series_catalogue": catalogue,
        "pairs": pairs,
    }
    ctx = ps.LiveContext("https://x", fetched, 5.0)
    ctx.objs["source"] = (
        [
            ps.envelope(
                id="whoop",
                type="source",
                as_of="2026-10-31",
                source=["/api/sources"],
                title="Whoop",
                label="Whoop",
                kind="wearable",
                cadence="daily",
                latest=None,
                fields=[],
                paused=False,
            )
        ]
        if "kind" in ps.SCHEMA["source"]
        else [{"id": "whoop", "label": "Whoop"}]
    )
    ps._live_metrics(ctx)
    ids = {o["id"]: o for o in ctx.objs["metric"]}
    assert ids["hrv"]["state"] == "ok" and ids["hrv"]["series_url"] == "/api/series?metric=hrv" and ids["hrv"]["source_id"] == "whoop"
    assert ids["ghost"]["state"] == "absent" and ids["ghost"]["series_url"] is None
    assert ctx.series["hrv"]["markers"] == [{"date": "2026-10-10", "label": "baseline change"}]
    assert ctx.series["hrv"]["days"][1] == {"date": "2026-09-07", "value": None, "present": False, "gap": True}
    assert "ghost" not in ctx.series
    assert [r["b"] for r in ctx.pairs["pairs"]] == ["ghost"], "a pairing naming a non-public metric is dropped"
    # the validator refuses a series or a pairing that names a metric outside the public set
    public = {"metric": [ids["hrv"]]}
    with pytest.raises(LookupError):
        ps.validate_data_files({"series": {"ghost": ctx.series["hrv"]}, "pairs": None}, public)
    with pytest.raises(LookupError):
        ps.validate_data_files({"series": {}, "pairs": {"pairs": [{"a": "hrv", "b": "ghost"}]}}, public)
    with pytest.raises(ps.SchemaError):
        ps.validate_data_files({"series": {}, "pairs": {"pairs": [{"a": "hrv", "b": "hrv", "note": "Significant!"}]}}, public)
