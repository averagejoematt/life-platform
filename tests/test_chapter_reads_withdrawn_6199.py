"""tests/test_chapter_reads_withdrawn_6199.py — #6199 G1: a withdrawn chapter is never a writer's input.

Two halves:
  1. each writer-side reader, fed a synthetic chapter partition with a ``withdrawn`` row (status still ``published``),
     skips it as if absent — and keeps a clean published row exactly as before;
  2. GUARD THE SET: every module under ``lambdas/`` and ``scripts/`` that reads a chapter's ``content_markdown`` either
     calls ``content.chapter_reads`` or is registered in ``NOT_A_WRITER_READ`` with the reason it is not a writer-side
     read. A sixth reader fails here until it does one or the other.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
for _k, _v in {"TABLE_NAME": "life-platform", "S3_BUCKET": "matthew-life-platform", "AWS_REGION": "us-west-2"}.items():
    os.environ.setdefault(_k, _v)

from content import chapter_reads  # noqa: E402

PK = "USER#matthew#SOURCE#chronicle"
CLEAN_MD = '"An Ordinary Week"\n\nHe walked every day.'
WITHDRAWN_MD = '"A Withdrawn Chapter"\n\nSYNTHETIC-WITHDRAWN-TEXT'


def _rows():
    return [
        {"pk": PK, "sk": "DATE#2026-12-08", "date": "2026-12-08", "status": "published", "title": "Ordinary", "content_markdown": CLEAN_MD},
        {
            "pk": PK,
            "sk": "DATE#2026-12-01",
            "date": "2026-12-01",
            "status": "published",
            "title": "Withdrawn",
            "content_markdown": WITHDRAWN_MD,
            "withdrawn": "privacy",
            "withdrawn_at": "2026-12-02T00:00:00Z",
        },
    ]


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        return {"Items": list(self.rows)}

    def get_item(self, Key, **kw):
        return {"Item": next((dict(r) for r in self.rows if r["sk"] == Key["sk"]), None)}


def test_the_predicate():
    ok = {"status": "published"}
    assert chapter_reads.writer_may_read(ok)
    for flag in ("withdrawn", "tombstone", "hidden", "unlisted"):
        assert not chapter_reads.writer_may_read({**ok, flag: True}), flag
    for status in ("draft", "changes_requested", "retired"):
        assert not chapter_reads.writer_may_read({"status": status}), status
    assert chapter_reads.writer_may_read({}) and not chapter_reads.writer_may_read({"tombstone": True}), "no status = published"
    assert not chapter_reads.writer_may_read(None) and not chapter_reads.writer_may_read("published")
    assert chapter_reads.is_withdrawn({"withdrawn": "privacy"}) and not chapter_reads.is_withdrawn({"status": "published"})


def test_the_desk_and_legacy_audit_previous_installments():
    from content import story_pipeline

    prev = story_pipeline._published_before(_Table(_rows()), PK, "2026-12-15", 3)
    assert list(prev.values()) == [CLEAN_MD]


def test_the_whole_life_archive():
    from health import whole_life_context

    items = whole_life_context.fetch_full_installment_archive(_Table(_rows()), PK)
    assert [i["content_markdown"] for i in items] == [CLEAN_MD]


def test_the_previously_on_recap():
    from emails import chronicle_recap

    got = chronicle_recap._published_installments({"prev_installments": _rows()})
    assert [i["content_markdown"] for i in got] == [CLEAN_MD]


def test_the_legacy_writers_previous_installments_read():
    with open(os.path.join(ROOT, "lambdas", "emails", "chronicle_data.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert 'prev_installments = [d2f(i) for i in chapter_reads.readable(resp.get("Items", []))]' in src


def test_the_panel_script_source(monkeypatch):
    from emails import coach_panel_podcast_lambda as panel

    monkeypatch.setattr(panel, "table", _Table([{**r, "sk": "DATE#2026-12-01"} for r in _rows()[1:]]))
    assert panel._chronicle_md("2026-12-01") is None
    monkeypatch.setattr(panel, "table", _Table([{**_rows()[0], "sk": "DATE#2026-12-01"}]))
    assert panel._chronicle_md("2026-12-01") == CLEAN_MD


def test_the_read_aloud_podcast(monkeypatch):
    from emails import chronicle_podcast_lambda as pod

    monkeypatch.setattr(pod, "table", _Table([{**_rows()[1]}]))
    assert pod._content_for("2026-12-01", "Withdrawn") is None
    monkeypatch.setattr(pod, "table", _Table([{**_rows()[0], "sk": "DATE#2026-12-01"}]))
    assert pod._content_for("2026-12-01", "Ordinary") == CLEAN_MD


def test_the_rebuilds_sealed_plan_prologue():
    spec = importlib.util.spec_from_file_location("season_rebuild_6199", os.path.join(ROOT, "scripts", "season_rebuild.py"))
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    withdrawn = _Table([{**_rows()[1], "sk": sr.PLAN_PROLOGUE_SK}])
    assert sr._plan_prologue(withdrawn) == ""
    assert sr._with_plan_prologue("PROLOGUE", withdrawn) == "PROLOGUE", "nothing is said about a sealed-plan chapter"
    clean = _Table([{**_rows()[0], "sk": sr.PLAN_PROLOGUE_SK}])
    assert sr._with_plan_prologue("PROLOGUE", clean).endswith(CLEAN_MD)


def test_the_recall_corpus_skips_a_withdrawn_chapter():
    from ai import recall_indexer

    assert recall_indexer.chronicle_doc(_rows()[1], {}) is None
    assert recall_indexer.chronicle_doc(_rows()[0], {}) is not None


# ── GUARD THE SET ─────────────────────────────────────────────────────────────

# Modules that read a chapter's content_markdown for something other than a writer's prompt — each with its reason.
NOT_A_WRITER_READ = {
    "lambdas/content/autopublish_audit.py": "audits the row being published (and runs the private-call check on it)",
    "lambdas/content/chronicle_revision.py": "names the revisable fields; reads no row",
    "lambdas/content/chronicle_schema.py": "pure helpers over a body handed in by the caller",
    "lambdas/content/chronicle_share_kit.py": "builds the share kit from the installment being published",
    "lambdas/emails/chronicle_render.py": "renders a published installment for readers (serving; the routes refuse a withdrawn row)",
    "lambdas/emails/chronicle_store.py": "writes the new installment",
    "lambdas/emails/wednesday_chronicle_lambda.py": "reads prev_installments, filtered at emails/chronicle_data; writes the draft",
    "scripts/backfill_story_ledger_week.py": "derives a ledger row from one already-published week, no model",
    "scripts/season_promote.py": "writes promoted text (its private-call gate checks it)",
}
MARKER = "content_markdown"


def _modules_reading_chapters(marker: str = MARKER, top_dirs: tuple = ("lambdas", "scripts")) -> list:
    out = []
    for top in top_dirs:
        for dirpath, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "archive")]
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(dirpath, name)
                    with open(path, encoding="utf-8") as fh:
                        if marker in fh.read():
                            out.append(os.path.relpath(path, ROOT))
    return sorted(out)


def offenders(paths: list, read=None) -> list:
    """Every chapter reader that neither calls content.chapter_reads nor is registered with a reason."""
    read = read or (lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read())
    bad = []
    for p in paths:
        if p in NOT_A_WRITER_READ or p == "lambdas/content/chapter_reads.py":
            continue
        tree = ast.parse(read(p))
        calls = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "chapter_reads"
        }
        if not calls & {"writer_may_read", "readable", "is_withdrawn"}:
            bad.append(p)
    return bad


# premerge-gate: #6199 G1 — every content_markdown reader under lambdas/ and scripts/ reads through chapter_reads or is registered
def test_every_chapter_reader_reads_through_the_predicate_or_says_why_not():
    paths = _modules_reading_chapters()
    assert len(paths) >= 15, f"the sweep found only {len(paths)} readers — the walk itself is broken"
    bad = offenders(paths)
    assert not bad, "chapter readers that bypass content.chapter_reads.writer_may_read (#6199 G1):\n" + "\n".join(bad)
    stale = sorted(set(NOT_A_WRITER_READ) - set(paths))
    assert not stale, f"NOT_A_WRITER_READ names modules that no longer read chapters: {stale}"


def test_the_set_guard_reds_on_a_reader_that_bypasses_the_predicate():
    fake = {"lambdas/emails/new_reader.py": "def f(it):\n    return it.get('content_markdown')\n"}
    assert offenders(list(fake), read=fake.get) == ["lambdas/emails/new_reader.py"]
    fixed = {
        "lambdas/emails/new_reader.py": "def f(it):\n    return it.get('content_markdown') if chapter_reads.writer_may_read(it) else None\n"
    }
    assert offenders(list(fixed), read=fixed.get) == []


# Modules that touch a LEDGER row's ledger_json without handing it to a writer — each with its reason (#6199 G2).
LEDGER_NOT_A_WRITER_READ = {
    "lambdas/emails/chronicle_approve_lambda.py": "commits the desk's new ledger on publish (a write)",
    "lambdas/emails/wednesday_chronicle_lambda.py": "stores the desk's new ledger on the draft row (a write)",
    "lambdas/operational/story_season_qa.py": "checks a LEDGER row exists for each published week; reads no ledger text",
    "scripts/backfill_story_ledger_week.py": "writes a derived row; its previous ledger is read through latest_visible",
}


def test_every_ledger_reader_returns_the_public_view():
    """G2's set: a module that json-loads a LEDGER row's text for a writer goes through story_ledger.public_view."""
    paths = _modules_reading_chapters(marker="ledger_json")
    bad = [
        p for p in paths if p not in LEDGER_NOT_A_WRITER_READ and "public_view(" not in open(os.path.join(ROOT, p), encoding="utf-8").read()
    ]
    assert not bad, "ledger readers that bypass story_ledger.public_view (#6199 G2):\n" + "\n".join(bad)
    assert {"lambdas/content/story_ledger.py", "lambdas/emails/panelcast_desk.py"} <= set(paths)
    stale = sorted(set(LEDGER_NOT_A_WRITER_READ) - set(paths))
    assert not stale, f"LEDGER_NOT_A_WRITER_READ names modules that no longer touch ledger_json: {stale}"


# ── #6199 P on the second-edition publish path (#6193) ───────────────────────
# Every call of the edition gate (chapter_editions.gate_findings / public_view, imported as CE or by name) must pass
# private_calls= — the ONE private-call check — and only the registered rendering/fixture callers may pass NOT_WIRED.
EDITION_NOT_WIRED = {
    "scripts/publish_snapshot_chapter_editions.py": "fixture mode only: synthetic records, no call record exists; live mode carries the Site API's gated view",
    "scripts/chronicle_edition_preview.py": "the rendering pass after its gates (which ran the check on the real calls) — publishes nothing",
}


def edition_gate_offenders(paths: list, read=None) -> list:
    read = read or (lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read())
    bad = []
    for p in paths:
        tree = ast.parse(read(p))
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("gate_findings", "public_view")):
                continue
            if not (isinstance(n.func.value, ast.Name) and n.func.value.id in ("CE", "chapter_editions")):
                continue
            kw = {k.arg: k.value for k in n.keywords}
            if "private_calls" not in kw:
                bad.append(f"{p}:{n.lineno} calls {n.func.attr} without private_calls=")
            elif "NOT_WIRED" in ast.unparse(kw["private_calls"]) and p not in EDITION_NOT_WIRED:
                bad.append(f"{p}:{n.lineno} passes NOT_WIRED and is not a registered rendering/fixture caller")
    return bad


def test_every_edition_publish_path_runs_the_private_call_check():
    paths = [p for top in ("lambdas", "mcp", "scripts") for p in _modules_reading_chapters(marker="chapter_editions", top_dirs=(top,))]
    assert {"lambdas/web/site_api_chapters.py", "mcp/tools_chapter_corrections.py", "scripts/publish_snapshot_chapter_editions.py"} <= set(
        paths
    )
    bad = edition_gate_offenders(paths)
    assert not bad, "edition gate calls that skip the #6199 private-call check:\n" + "\n".join(bad)
    fake = {"mcp/new_tool.py": "def f(t):\n    return CE.gate_findings(t, tainted=None)\n"}
    assert edition_gate_offenders(list(fake), read=fake.get) == ["mcp/new_tool.py:2 calls gate_findings without private_calls="]
