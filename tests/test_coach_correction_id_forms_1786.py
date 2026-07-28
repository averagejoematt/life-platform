"""test_coach_correction_id_forms_1786.py — the S5 injection actually reaches a coach.

#1786: the #1711/S5 prompt-memory injection was a live NO-OP. The ledger's WRITERS and
the coach pipeline's READER spell a coach id differently, and `_item_ref_matches`
compared the raw strings:

  writers →  `coach_correction_resolver.build_item_ref` stores the S3 archive `variant`
             ("mind_coach") · `mcp/tools_coach_intelligence` stores f"{bare}_coach" ·
             older rows carry the BARE form ("mind") or NO `coach` key at all
  reader  →  `ai_calls._run_coach_v2_pipeline` passes the SUFFIXED pipeline id
             ("mind_coach", "sleep_coach", …)

Live evidence at filing: 6 open corrections, `item_ref.coach` = [None ×5, "mind" ×1] —
zero of them reached any of the 8 pipeline coaches, and the failure was silent
(`_coach_corrections_block` fails soft to "" and only logs on a NON-empty block).

Why this file exists ON TOP OF `test_coach_corrections_prompt_memory_1697.py`: that file
seeds SUFFIXED fixtures and reads with the SUFFIXED id, so it passes on both sides of the
bug. The mismatch only shows up in a test that spans the REAL write→read join, over the
REAL id forms, for the REAL pipeline roster — which is what this file pins:

  1. every id form a live writer produces reaches its coach (`test_every_written_id_form_reaches_its_coach`)
  2. the exact live ledger shapes (no-coach ×N + bare ×1) reach EVERY pipeline coach id
     (`test_live_ledger_shapes_reach_every_pipeline_coach`) — the adversarial repro
  3. scoping is still real: a named coach's row does not leak to another coach, and a
     different SURFACE never leaks into the coach_brief block

The pipeline roster is READ OUT OF `ai_calls` (not hardcoded), so adding a coach without
a matching ledger form fails here rather than silently dropping that coach's corrections.

Fully offline — no AWS, no Bedrock (in-memory `FakeDdbTable`).

Run with:   python3 -m pytest tests/test_coach_correction_id_forms_1786.py -v
"""

import os
import re
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import coach_correction_resolver as ccr  # noqa: E402
import coach_corrections as cc  # noqa: E402
import coach_dossier as cd  # noqa: E402
from ai import ai_calls  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

_AI_CALLS_SRC = os.path.join(os.path.dirname(__file__), "..", "lambdas", "ai", "ai_calls.py")


def _pipeline_coach_ids():
    """The coach ids `ai_calls` actually passes to `_run_coach_v2_pipeline` — read from
    the source so the roster can't drift out from under this test."""
    with open(_AI_CALLS_SRC, encoding="utf-8") as fh:
        src = fh.read()
    ids = sorted(set(re.findall(r"_run_coach_v2_pipeline\(\s*[\"']([a-z_]+)[\"']", src)))
    assert ids, "no _run_coach_v2_pipeline coach ids found — the reader wiring moved"
    return ids


PIPELINE_COACH_IDS = _pipeline_coach_ids()


def _ledger_table():
    """A fake that serves back what was WRITTEN to it (the canned-`rows` flavor would
    make this a write-only test — the whole point here is the write→read join)."""
    return FakeDdbTable(rows=[], query_hook=lambda t, **_kw: {"Items": list(t.store.values())})


def _write(table, item_ref, text, *, cid, cls="stale-baseline", date="2026-07-22"):
    """Write through the REAL ledger writer (not a hand-built row)."""
    return cc.write_correction(
        table,
        item_ref,
        text,
        cls,
        now=datetime.fromisoformat(f"{date}T12:00:00+00:00").astimezone(timezone.utc),
        correction_id=cid,
    )


def _review_pack_ref(coach_variant, *, n=3):
    """The item_ref the review-pack channel really stores — built by the shared
    resolver from an S3 qa_archive entry (variant is the SUFFIXED coach id, e.g. the
    live archive key `coach_brief--mind_coach--2026-07-22`)."""
    entry = {
        "surface": "coach_brief",
        "variant": coach_variant,
        "date": "2026-07-22",
        "_key": f"qa-archive/2026-07-22/coach_brief--{coach_variant}--2026-07-22.json",
    }
    return ccr.build_item_ref(n, entry)


# ── 1. Every id form a live writer produces reaches its coach ────────────────
@pytest.mark.parametrize("coach_id", PIPELINE_COACH_IDS)
def test_every_written_id_form_reaches_its_coach(coach_id):
    """For EVERY coach the pipeline runs: the suffixed review-pack form, the bare
    legacy form, and a coach-less surface-wide row all land in that coach's block."""
    bare = coach_id.removesuffix("_coach")
    table = _ledger_table()
    _write(table, _review_pack_ref(coach_id), f"SUFFIXED-{bare}: stop citing the 315 lbs baseline", cid="aaaa1111")
    _write(table, {"surface": "coach_brief", "coach": bare}, f"BARE-{bare}: no 8h-streak claim without the log", cid="bbbb2222")
    _write(table, {"surface": "coach_brief", "date": "2026-07-22"}, "NOCOACH: pre-genesis baselines are not current", cid="cccc3333")

    block = ai_calls._coach_corrections_block(coach_id, surface="coach_brief", table=table)
    assert block, f"{coach_id}: S5 injected nothing — the correction ledger is unreachable again"
    assert f"SUFFIXED-{bare}" in block
    assert f"BARE-{bare}" in block, f"{coach_id}: the bare ledger form ('{bare}') did not reach the suffixed reader id"
    assert "NOCOACH" in block, f"{coach_id}: a surface-wide (no-coach) correction reached nobody"


# ── 2. The exact live ledger shapes (the adversarial repro) ──────────────────
def test_live_ledger_shapes_reach_every_pipeline_coach():
    """The ledger as it stood at filing — 5 rows with NO `coach` key and 1 bare `mind`
    row — reaches every pipeline coach (the `mind` row only reaching `mind_coach`).
    Before the fix this returned "" for all 8 ids."""
    table = _ledger_table()
    for i in range(5):
        _write(
            table,
            {"surface": "coach_brief", "pack_number": i + 1, "date": "2026-07-2%d" % (i + 1)},
            f"UNSCOPED-{i}: a correction logged without a coach",
            cid=f"dddd{i}{i}{i}{i}",
        )
    _write(table, {"surface": "coach_brief", "coach": "mind"}, "MINDROW: the stale-baseline correction", cid="eeee5555")

    for coach_id in PIPELINE_COACH_IDS:
        block = ai_calls._coach_corrections_block(coach_id, surface="coach_brief", table=table)
        assert block, f"{coach_id}: zero of the live open corrections were injected"
        assert "UNSCOPED-" in block
        if coach_id == "mind_coach":
            assert "MINDROW" in block, "the live bare-form 'mind' row still misses mind_coach"
        else:
            assert "MINDROW" not in block, f"{coach_id}: the mind coach's correction leaked"


# ── 3. Scoping is still real ─────────────────────────────────────────────────
def test_named_coach_row_does_not_leak_across_coaches():
    """A row that NAMES a coach reaches only that coach — in either spelling."""
    table = _ledger_table()
    _write(table, _review_pack_ref("mind_coach"), "MIND-ONLY suffixed row", cid="aaaa1111")
    _write(table, {"surface": "coach_brief", "coach": "sleep"}, "SLEEP-ONLY bare row", cid="bbbb2222")

    mind = ai_calls._coach_corrections_block("mind_coach", surface="coach_brief", table=table)
    sleep = ai_calls._coach_corrections_block("sleep_coach", surface="coach_brief", table=table)
    assert "MIND-ONLY" in mind and "SLEEP-ONLY" not in mind
    assert "SLEEP-ONLY" in sleep and "MIND-ONLY" not in sleep
    # A coach named by neither row gets nothing to inject (honest-when-empty).
    assert ai_calls._coach_corrections_block("labs_coach", surface="coach_brief", table=table) == ""


def test_other_surfaces_never_leak_into_the_coach_brief_block():
    """The dossier channel writes to its own surface — an unscoped-by-coach match must
    not cross surfaces (surface stays an exact-match axis)."""
    table = _ledger_table()
    _write(
        table,
        {"surface": cd.CORRECTION_SURFACE, "coach": "mind_coach", "record_sk": "MEMORY#2026-07-20#x", "action": "retract"},
        "DOSSIER-ROW: retracted memory",
        cid="aaaa1111",
        cls="other",
    )
    _write(table, {"surface": "coach_dossier", "date": "2026-07-22"}, "DOSSIER-UNSCOPED", cid="bbbb2222", cls="other")
    for coach_id in PIPELINE_COACH_IDS:
        assert ai_calls._coach_corrections_block(coach_id, surface="coach_brief", table=table) == ""


def test_normalization_is_one_way_and_leaves_non_coach_variants_alone():
    """`normalize_coach_id` only STRIPS a `_coach` suffix — a surface whose archive
    `variant` isn't a coach id (e.g. a chronicle variant) still matches only itself."""
    table = _ledger_table()
    _write(table, {"surface": "chronicle", "coach": "elena"}, "ELENA-ROW", cid="aaaa1111", cls="framing")
    assert "ELENA-ROW" in cc.corrections_prompt_block(table, surface="chronicle", coach="elena")
    assert cc.corrections_prompt_block(table, surface="chronicle", coach="margaret") == ""
