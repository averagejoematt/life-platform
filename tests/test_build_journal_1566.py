"""#1566 — the journal essay generator: kill the hand-HTML step.

Pins the contract that lets an essay be TWO edits (a blog.json entry + a body
fragment) instead of a hand-authored static page:
  - the generator renders a valid, design-system-correct permalink page;
  - it is dry-run by DEFAULT (publishing stays a manual deploy step — the #1563
    "Voice" scope guard) and idempotent after --write;
  - every rendered body passes the same fail-closed privacy gate as the rest of
    the platform;
  - the lightweight markdown authoring path renders the supported subset;
  - the QA registry DERIVES the essay page from blog.json (essays register once);
  - the deploy path runs the generator the way it runs v4_build_dispatches.py.
"""

import importlib
import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import v4_build_journal as j  # noqa: E402

BLOG_PATH = os.path.join(_REPO, "site", "journal", "blog.json")


def _blog():
    with open(BLOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _first_post():
    return _blog()["posts"][0]


# ── The rendered page is valid + design-system correct ────────────────────────
def test_render_produces_a_complete_v5_page():
    html = j.render(_first_post())
    assert html.startswith("<!DOCTYPE html>")
    assert '<html lang="en" data-door="story">' in html
    assert 'property="og:type" content="article"' in html
    assert '"@type": "BlogPosting"' in html
    assert 'class="post-header__title"' in html  # the structural marker qa_manifest asserts
    assert 'class="prose"' in html  # v5 .prose body
    assert 'class="reading-progress"' in html
    # chrome comes from the single source (v4_chrome), so the page is born normalized
    assert 'class="doors"' in html and 'aria-current="page"' in html
    assert 'class="loop-forward"' in html
    assert 'class="site-foot"' in html


def test_canonical_and_title_track_the_entry():
    p = _first_post()
    html = j.render(p)
    assert f'<link rel="canonical" href="https://averagejoematt.com{p["url"]}">' in html
    assert f"<title>{p['title']} — averagejoematt</title>" in html


def test_read_minutes_derives_from_word_count_when_absent():
    p = dict(_first_post())
    p.pop("read_minutes", None)
    p["word_count"] = 2100
    assert j.read_minutes(p) == 10  # 2100 / 210 wpm
    assert j.read_minutes({"word_count": 0}) == 1  # floor


def test_slug_resolves_from_url_then_id():
    assert j.slug_for({"url": "/journal/essays/foo-bar/"}) == "foo-bar"
    assert j.slug_for({"id": "baz", "url": ""}) == "baz"


# ── Dry-run is the default; --write is idempotent ─────────────────────────────
def test_dry_run_is_the_default_and_writes_nothing(tmp_path, monkeypatch):
    target = os.path.join(_REPO, "site", "journal", "essays", "org-chart-of-one", "index.html")
    before = open(target, encoding="utf-8").read()
    # bare build() with write=False must not touch the tree
    rc = j.build(write=False, check=False)
    assert rc == 0
    assert open(target, encoding="utf-8").read() == before


def test_write_then_check_is_clean():
    assert j.build(write=True, check=False) == 0
    # a second pass in --check mode must find nothing stale (idempotent generator)
    assert j.build(write=False, check=True) == 0


# ── The fail-closed privacy gate is enforced on every body ────────────────────
def test_privacy_gate_blocks_a_leaking_body(monkeypatch):
    def boom(text, context=""):
        raise j.privacy_guard.PrivacyViolation([("vice", "<synthetic>"), ("context", context)])

    monkeypatch.setattr(j.privacy_guard, "assert_clean", boom)
    with pytest.raises(j.privacy_guard.PrivacyViolation):
        j.render(_first_post())


def test_real_essay_body_passes_the_privacy_gate():
    # The shipped org-chart essay is clean — render() (which calls assert_clean on
    # title/excerpt/body) must not raise.
    j.render(_first_post())


# ── The lightweight markdown authoring path ───────────────────────────────────
def test_markdown_subset_renders():
    md = (
        "## Heading\n\n"
        "Para with **bold**, _em_, `code`, [link](/cockpit/).\n\n"
        "> quoted line\n> and more\n\n"
        "- a\n- b\n\n"
        "1. one\n2. two\n\n"
        "---\n\n"
        "End."
    )
    out = j.markdown_to_html(md)
    assert "<h2>Heading</h2>" in out
    assert "<strong>bold</strong>" in out and "<em>em</em>" in out
    assert "<code>code</code>" in out and '<a href="/cockpit/">link</a>' in out
    assert "<blockquote><p>quoted line and more</p></blockquote>" in out
    assert "<ul><li>a</li><li>b</li></ul>" in out
    assert "<ol><li>one</li><li>two</li></ol>" in out  # markers stripped
    assert "<hr>" in out
    assert "<p>End.</p>" in out


def test_markdown_escapes_raw_html():
    # a markdown source can't inject markup — angle brackets are escaped
    assert "&lt;script&gt;" in j.markdown_to_html("a <script> tag")


def test_load_body_prefers_html_then_md(tmp_path, monkeypatch):
    d = tmp_path / "essays" / "slugx"
    d.mkdir(parents=True)
    monkeypatch.setattr(j, "ESSAYS_DIR", tmp_path / "essays")
    (d / "body.md").write_text("## md heading\n\nbody", encoding="utf-8")
    assert "<h2>md heading</h2>" in j.load_body("slugx")
    (d / "body.html").write_text("<p>verbatim</p>", encoding="utf-8")
    assert j.load_body("slugx") == "<p>verbatim</p>"  # html wins


def test_load_body_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(j, "ESSAYS_DIR", tmp_path / "essays")
    with pytest.raises(FileNotFoundError):
        j.load_body("nope")


# ── The QA registry derives the essay from blog.json (register once) ──────────
def test_qa_manifest_derives_essays_from_blog_json():
    qa = importlib.import_module("qa_manifest") if "qa_manifest" not in sys.modules else sys.modules["qa_manifest"]
    sys.path.insert(0, os.path.join(_REPO, "tests"))
    qa = importlib.import_module("qa_manifest")
    rows = qa._essay_rows()
    paths = {r["path"] for r in rows}
    for p in _blog()["posts"]:
        assert p["url"] in paths, f"essay {p['url']} not derived into the QA manifest"
    # each derived essay carries the structural marker + is in the structural sweep
    structural = [r for r in qa.structural_rows() if r.split("|")[0].startswith("/journal/essays/")]
    assert structural, "no essay in the structural sweep"


def test_body_fragment_not_counted_as_a_page():
    sys.path.insert(0, os.path.join(_REPO, "tests"))
    qa = importlib.import_module("qa_manifest")
    unregistered, ghosts = qa.self_check()
    assert not any("body.html" in u or "body.md" in u for u in unregistered), unregistered


# ── The deploy path wires the generator in (AC #4) ────────────────────────────
def test_deploy_path_runs_the_generator():
    sync = open(os.path.join(_REPO, "deploy", "sync_site_to_s3.sh"), encoding="utf-8").read()
    assert "v4_build_journal.py" in sync
    assert "--write" in sync.split("v4_build_journal.py")[1].split("\n")[0], "deploy must pass --write (default is dry-run)"
