"""tests/test_recall_reset_window_2858.py — the reset window was a recall-corpus blind spot.

2026-08-17, the first organic qa-smoke ALARM of the repaired alarm pipeline (#2670): the
2026-08-16 installment was MISSING from the recall corpus and the 2026-07-21 stored link
diverged from the derived scheme. Same class as #2705 — but a different mechanism, which
is why that fix did not cover it:

  MISSING 2026-08-16 — #2705 hardened the ONE publish site it knew about (the approve
  lambda's #1384 hook: failures got a distinct FAILED status and ERROR-level logs). The
  cycle-14 same-day reset published through a DIFFERENT site entirely:
  `publish_genesis_preregistration.py` mints `status=published` with a bare put_item and
  carried no recall hook at all, so the prereg installment (sk DATE#2026-08-16) never
  reached the corpus and nothing logged anything anywhere. Not a race — a second,
  unhooked publish path that only a reset exercises.

  DIVERGENT 2026-07-21 — the corpus row was embedded 2026-08-09 while the installment
  was a wiped, invisible prior-cycle record (honest link "": no reader page). The reset's
  chronicle handler then resurrected + re-dated it as a visible published lead-in, which
  changed the DERIVED reader link under an unchanged text. #2366 built the free repair
  path for exactly this rot, but nothing in the reset ever ran it.

Pinned here:
  1. the prereg publisher indexes what it publishes — publish ⇒ index, one operation;
  2. its main() has no bare chronicle put_item left to drift back;
  3. a real indexing failure is a non-zero exit (attended script → honest exit code),
     while a band-2 budget pause is not a fault (ADR-125 / #2705 AC3's distinction),
     and indexing never blocks the publish itself;
  4. the restart pipeline carries a recall_corpus_sync step ordered after the chronicle
     handler + leadin pages (visibility settled), present even under --skip-chronicle
     (the phase wipe alone rotates visibility), dry-run-strippable via --apply;
  5. the 07-21 mechanism itself: a row embedded while invisible is REPAIRED to the
     resurrected installment's live link — never skipped as UNCHANGED, never re-embedded.

No AWS, no Bedrock: fakes + injected embed throughout, mirroring test_recall_indexer.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))


def _load(name: str):
    """Path-load a deploy/ script (they are scripts, not a package) — reusing an
    already-loaded instance so this file composes with the other suites that load the
    same modules (test_restart_pipeline_hooks, test_genesis_preregistration)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pipeline = _load("restart_pipeline")
publisher = _load("publish_genesis_preregistration")

from ai import recall_indexer as ri, semantic_recall as sr  # noqa: E402

CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"


def _vec(text):
    """Deterministic stand-in for Titan — row content matters here, not geometry."""
    return [float(len(text) % 7), 1.0, 0.0]


def _record(date="2026-08-16", *, sk=None, title="The Plan, On the Record"):
    """A chronicle record in the shape `build_chronicle_record` writes (the fields the
    indexer reads), for the fused publish path to exercise."""
    return {
        "pk": CHRONICLE_PK,
        "sk": sk or f"DATE#{date}",
        "date": date,
        "title": title,
        "subtitle": "Prologue",
        "content_markdown": "Sixteen predictions, frozen before day one.",
        "status": "published",
        "phase": "experiment",
        "cycle": 14,
    }


class FakeTable:
    """Minimal DDB double (mirrors tests/test_recall_indexer.py): one chronicle
    partition to query, one recall partition to read/write. A chronicle put also joins
    the queryable partition, so the fused publish path sees its own write when it
    derives the reader-link ordering."""

    def __init__(self, installments=(), rows=None):
        self.installments = list(installments)
        self.rows = dict(rows or {})
        self.puts = []
        self.updates = []

    def query(self, **kwargs):
        return {"Items": list(self.installments)}

    def get_item(self, Key):  # noqa: N803 — boto3's parameter name
        item = self.rows.get(Key["sk"])
        return {"Item": item} if item else {}

    def put_item(self, Item):  # noqa: N803 — boto3's parameter name
        self.puts.append(Item)
        self.rows[Item["sk"]] = Item
        if str(Item["sk"]).startswith("DATE#"):
            self.installments = [i for i in self.installments if i.get("sk") != Item["sk"]] + [Item]

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues=None):  # noqa: N803
        """Applies the exact contract `refresh_metadata` emits: a name WITH a value is a
        SET, a name with no value is a REMOVE."""
        self.updates.append(UpdateExpression)
        row = self.rows.setdefault(Key["sk"], {})
        values = ExpressionAttributeValues or {}
        for ph, attr in ExpressionAttributeNames.items():
            vph = ":v" + ph[2:]
            if vph in values:
                row[attr] = values[vph]
            else:
                row.pop(attr, None)
        return {}


# ── 1+2: the second publish site is fused to the indexer ─────────────────────


def test_the_prereg_publisher_indexes_what_it_publishes():
    """The exact live gap: sk DATE#2026-08-16 published by this script, corpus empty.
    Publish must leave BOTH rows — the record and its embedding — in one call."""
    rec = _record()
    table = FakeTable()

    status = publisher.publish_record(table, rec, embed=_vec)

    assert status == ri.INDEXED
    assert table.rows[rec["sk"]] == rec  # the chronicle record landed
    row = table.rows[sr.sk_for(sr.KIND_CHRONICLE, "2026-08-16")]  # and so did its embedding
    assert (row["artifact_pk"], row["artifact_sk"]) == (CHRONICLE_PK, "DATE#2026-08-16")
    # The only visible published installment → week-01; a real page, never a dead slug.
    assert row["link"] == "/journal/posts/week-01/"


def test_main_publishes_only_through_the_fused_path():
    """No bare chronicle put_item left in main() to quietly become a third unhooked
    publish site — the drift that made this incident possible."""
    src = inspect.getsource(publisher.main)
    assert "publish_record(" in src
    assert "put_item" not in src


# ── 3: loud on real failure, quiet on honest pause, never blocking ───────────


def test_a_real_indexing_failure_is_a_nonzero_exit_but_never_blocks_the_publish():
    rec = _record()
    table = FakeTable()

    def _boom(text):
        raise RuntimeError("bedrock down")

    status = publisher.publish_record(table, rec, embed=_boom)

    assert status == ri.FAILED
    assert table.rows[rec["sk"]] == rec  # fail-soft: the publish itself landed first
    assert publisher.final_exit_code(0, status) == 1  # …but the run says so, loudly


def test_a_budget_pause_and_leadin_exit_codes_pass_through_honestly():
    # A band-2 pause is the corpus deliberately not advancing (ADR-125) — the freshness
    # check reports it as paused, and an exit code that redded on it would train the
    # operator to ignore the red (#2705 AC3's FAILED-vs-skip distinction).
    assert publisher.final_exit_code(0, ri.SKIPPED_BUDGET) == 0
    assert publisher.final_exit_code(0, ri.INDEXED) == 0
    assert publisher.final_exit_code(3, ri.INDEXED) == 3  # leadin machinery failures still propagate


# ── 4: the reset itself converges the corpus ─────────────────────────────────


def _step_names(skip_chronicle=False):
    return [n for n, _ in pipeline.build_sub_scripts(skip_chronicle, [], "2026-08-10")]


def test_the_reset_pipeline_carries_a_recall_corpus_sync_step():
    names = _step_names()
    assert "recall_corpus_sync" in names
    # After visibility settles: the chronicle handler resurrects/re-dates, the leadin
    # pages rebuild from the now-visible records — only then is the derived link
    # ordering the one the corpus must match.
    assert names.index("recall_corpus_sync") > names.index("restart_chronicle_handler")
    assert names.index("recall_corpus_sync") > names.index("restart_leadin_pages")

    cmd = dict(pipeline.build_sub_scripts(False, [], "2026-08-10"))["recall_corpus_sync"]
    assert cmd[:2] == ["python3", "deploy/backfill_recall_embeddings.py"]
    assert (REPO_ROOT / cmd[1]).is_file()
    assert "--apply" in cmd  # run_step strips exactly this token on dry-run → preview, zero spend
    assert "chronicle" in cmd


def test_the_sync_survives_skip_chronicle():
    """--skip-chronicle skips the resurrections, not the phase wipe — visibility still
    rotates, so the corpus still needs converging."""
    names = _step_names(skip_chronicle=True)
    assert "recall_corpus_sync" in names
    assert names.index("recall_corpus_sync") > names.index("restart_leadin_pages")


# ── 5: the 2026-07-21 mechanism, pinned ──────────────────────────────────────


def test_a_row_embedded_while_invisible_is_repaired_when_the_reset_resurrects_it():
    """Live shape on 2026-08-17: DOC#chronicle#2026-07-21 stored link "" (embedded
    2026-08-09 while the installment was wiped — honestly no page), then the reset
    resurrected DATE#2026-07-21 as a visible published lead-in dated 2026-08-16. The
    unchanged-text gate must REPAIR the link (free, no re-embed), never early-return
    UNCHANGED — and never spend to do it."""
    leadin = _record("2026-08-16", sk="DATE#2026-07-21", title="The Night Before Everything")
    prereg = _record("2026-08-16")
    installments = [leadin, prereg]

    doc = ri.chronicle_doc(leadin, ri.published_post_links(installments))
    corpus_sk = sr.sk_for(sr.KIND_CHRONICLE, "2026-07-21")
    stored = {"sk": corpus_sk, "text_sha": sr.sha_text(doc["text"]), "link": "", "cycle": 12}
    table = FakeTable(installments, rows={corpus_sk: stored})

    def _no_spend(text):
        raise AssertionError("a metadata repair must not re-embed")

    assert ri.index_document(table, doc, embed=_no_spend) == ri.REPAIRED
    row = table.rows[corpus_sk]
    # (2026-08-16, DATE#2026-07-21) sorts before (2026-08-16, DATE#2026-08-16) → week-01.
    assert row["link"] == "/journal/posts/week-01/"
    assert row["cycle"] == 14  # the re-stamped cycle rides along (#1828)
