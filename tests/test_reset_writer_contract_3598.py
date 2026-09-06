"""tests/test_reset_writer_contract_3598.py — the reset's WRITER contract, in three
one-function fixes (#3598; forensic RCA 2026-09-05, class 2).

Every test here is a contract test with a stated positive control: the assertion
FAILS against the pre-#3598 function and passes after. Where the old behaviour is
cheap to replay (a status left on a tombstone, a constant phase, a slug-keyed
archive) the replay is in the test so the assertion cannot be vacuous.

LEG 1 — the wipe voids what it tombstones (deploy/restart_intelligence_wipe.py::build_update).
  The 2026-09-03 wipe tombstoned cycle 15's unpublished Week-1 draft and left
  `status=draft`; on Day 0 the 18:00Z auto-publish sweep — keyed on status alone —
  published it (#3485). The tombstone now SETs status=voided (original preserved in
  status_before_tombstone). Proof: `_find_stale_drafts` with the #3485 READER guard
  removed still cannot select the row, while the identical un-tombstoned row is
  selected. Plus the recap pair: `_commit_recap` of an archived installment writes
  rows the reader hides, and the pre-#3485 recap shape would have survived the wipe.

LEG 2 — the stamp derives phase + cycle from the write's date
  (lambdas/experiment/phase_taxonomy.py::experiment_stamp, common/compute_metadata.py::tag_record).
  `experiment_stamp()` returned the constant phase and SSM's cycle, which the reset
  bumps BEFORE genesis — 10 of 24 served cycle-16 predictions were countdown-window
  writes stamped as the experiment (QS-1). Now `as_of = genesis-1` stamps
  pilot/closing-cycle and `as_of = genesis` stamps experiment/new-cycle, whatever SSM says.

LEG 3 — archive_one keyed on (slug, cycle) under a per-step work contract
  (deploy/restart_chronicle_handler.py::archive_one, deploy/restart_work_contract.py,
  restart_pipeline.py::run_step). `archive_one` was idempotent on the SLUG: every reused
  slug collided with the 2026-07-10 cycle-4 archival and the 09-04 report said
  `html_files_archived=0 / already_archived=29` — exit 0, and no reset since cycle 4
  archived a page. Now a slug with a cycle-4 archive archives again under cycle-16
  with acted_count=1, and a step reporting input>0 ∧ acted==0 with no named reason
  reds the pipeline even when its process exited 0.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "deploy", REPO_ROOT / "lambdas"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import restart_chronicle_handler as handler  # noqa: E402
import restart_work_contract as wc  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402
from experiment import phase_taxonomy as pt  # noqa: E402
from experiment.phase_filter import singleton_visible  # noqa: E402
from test_wipe_idempotency import _apply_update, wipe  # noqa: E402 — the real wipe + the if_not_exists simulator (#1202's test)

GENESIS = EXPERIMENT_START_DATE
EVE = (date.fromisoformat(GENESIS) - timedelta(days=1)).isoformat()
# A registry shaped like the live one around this genesis: the closing cycle opened
# four days earlier, the new cycle opens on GENESIS.
REGISTRY = {15: (date.fromisoformat(GENESIS) - timedelta(days=4)).isoformat(), 16: GENESIS}


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


# ═════════════════════════════════════════════════════════════════════════════
# LEG 1 — the wipe voids the status of what it tombstones
# ═════════════════════════════════════════════════════════════════════════════


def _tombstone(item: dict, **kw) -> dict:
    """Apply the REAL UpdateExpression the wipe writes for `item` (honouring if_not_exists)."""
    expr, names, values = wipe.build_update(kw.pop("extra", {"hidden": True}), "2026-09-03T03:42:05+00:00", 15, item=item, **kw)
    return _apply_update(item, expr, names, values)


def _draft(hours_ago: float = 72) -> dict:
    """Cycle 15's Week-1 draft exactly as the 09-03 wipe found it: in the auto-publish
    window by age, `draft` by status."""
    return {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": "DATE#2026-09-01",
        "date": "2026-09-01",
        "status": "draft",
        "generated_at": _iso(hours_ago),
    }


def test_the_tombstone_voids_a_draft_and_preserves_what_it_was():
    row = _tombstone(_draft())
    assert row["tombstone"] is True and row["phase"] == "pilot" and row["cycle"] == 15
    assert row["status"] == wipe.VOIDED_STATUS
    assert row["status_before_tombstone"] == "draft"


def test_a_status_no_writer_selects_on_is_left_alone():
    """A completed experiment stays `completed` in the cycle archive — the void is for
    the statuses a WRITER keys on (WRITER_SELECTABLE_STATUSES), not every status."""
    row = _tombstone({"pk": "USER#matthew#SOURCE#experiments", "sk": "EXP#x", "status": "completed"})
    assert row["status"] == "completed" and "status_before_tombstone" not in row


def test_a_row_with_no_status_gets_none_invented():
    row = _tombstone({"pk": "USER#matthew#SOURCE#insights", "sk": "DATE#2026-09-01"})
    assert "status" not in row and "status_before_tombstone" not in row


def test_the_original_status_survives_a_second_reset_generation():
    """#1202's rule applied to the new attr: a later reset never overwrites the first
    stamp. (The live guard skips tombstoned rows anyway; this is the write's own safety.)"""
    row = _tombstone(_draft())
    row["status"] = "draft"  # a hand-restored draft, then tombstoned again by the next reset
    expr, names, values = wipe.build_update({"hidden": True}, "2026-09-10T00:00:00+00:00", 16, item=row)
    _apply_update(row, expr, names, values)
    assert row["status"] == wipe.VOIDED_STATUS and row["status_before_tombstone"] == "draft" and row["cycle"] == 15


_APPROVE = REPO_ROOT / "lambdas" / "emails" / "chronicle_approve_lambda.py"


@pytest.fixture
def approve(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "matthew-life-platform")
    monkeypatch.setenv("CHRONICLE_AUTOPUBLISH_HOURS", "48")
    spec = importlib.util.spec_from_file_location("chronicle_approve_lambda_3598", _APPROVE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_status_keyed_writer_cannot_select_a_tombstoned_draft_even_without_the_reader_guard(approve, monkeypatch):
    """THE POSITIVE CONTROL for leg 1. The #3485 reader guard (`_publishable`) is
    switched OFF here, so the only thing between the sweep and the archived draft is
    what the WIPE wrote. Against the pre-#3598 build_update (status left `draft`) this
    row is selected — the exact 2026-09-04 18:00Z publish."""
    monkeypatch.setattr(approve, "_publishable", lambda item: True)
    archived = _tombstone(_draft(72))
    with mock.patch.object(approve.table, "query", return_value={"Items": [archived]}):
        assert approve._find_stale_drafts(48, 10) == []


def test_the_identical_draft_that_was_not_tombstoned_is_still_selected(approve, monkeypatch):
    """The pair (#3485's own negative control, kept): the void must be the WIPE's doing —
    the same row without the tombstone is the ordinary 'forgot to click' case."""
    monkeypatch.setattr(approve, "_publishable", lambda item: True)
    with mock.patch.object(approve.table, "query", return_value={"Items": [_draft(72)]}):
        assert [d["date"] for d in approve._find_stale_drafts(48, 10)] == ["2026-09-01"]


def test_replaying_the_old_tombstone_shape_reaches_the_sweep(approve, monkeypatch):
    """Non-vacuity of the control above: strip ONLY the void (the pre-#3598 tombstone —
    tombstone + phase=pilot + cycle, status still draft) and the sweep selects it."""
    monkeypatch.setattr(approve, "_publishable", lambda item: True)
    old_shape = _tombstone(_draft(72))
    old_shape["status"] = old_shape.pop("status_before_tombstone")
    with mock.patch.object(approve.table, "query", return_value={"Items": [old_shape]}):
        assert len(approve._find_stale_drafts(48, 10)) == 1


# ── the recap pair: a CoOwned singleton's survival across the wipe ──────────────


def _commit(approve, item: dict) -> list[dict]:
    writes: list[dict] = []
    with mock.patch.object(approve.table, "put_item", side_effect=lambda Item: writes.append(Item)):
        approve._commit_recap(item)
    assert {w["sk"] for w in writes} == {"RECAP#2026-09-01", "RECAP#latest"}
    return writes


def test_a_recap_committed_from_an_archived_installment_is_hidden_from_the_reader(approve):
    """RECAP#latest is co-owned (the publish path re-puts it). Replaying a publish of the
    archived installment AFTER the wipe must not resurrect a visible recap: every row
    the real `_commit_recap` writes fails `singleton_visible` — the wipe's tombstone
    survives the writer."""
    archived = _tombstone(_draft(72))
    archived["draft_recap_json"] = json.dumps({"story_so_far": "cycle 15, week 1"})
    writes = _commit(approve, archived)
    assert all(not singleton_visible(w) for w in writes), [(w["sk"], w.get("phase")) for w in writes]


def test_the_pre_3485_recap_shape_would_have_survived_the_wipe(approve):
    """The negative control the RCA asks for: the pre-#3485 `_commit_recap` carried no
    provenance. Replay that shape — the same rows with the inherited phase/cycle
    stripped — and the survival assertion above FAILS: the reader would serve it."""
    archived = _tombstone(_draft(72))
    archived["draft_recap_json"] = json.dumps({"story_so_far": "cycle 15, week 1"})
    writes = _commit(approve, archived)
    pre_3485 = [{k: v for k, v in w.items() if k not in ("phase", "cycle")} for w in writes]
    assert all(singleton_visible(w) for w in pre_3485)


# ═════════════════════════════════════════════════════════════════════════════
# LEG 2 — the stamp derives phase + cycle from the write's date
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def bumped_ssm(monkeypatch):
    """SSM as the reset leaves it BEFORE genesis: already the NEW cycle's number."""
    from coach import coach_checkin

    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 16)


def test_the_eve_of_genesis_stamps_pilot_and_the_closing_cycle(bumped_ssm):
    """THE POSITIVE CONTROL for leg 2: pre-#3598 this returned {experiment, 16} — the
    constant phase and the bumped SSM — for a write the day before Day 1."""
    assert pt.experiment_stamp(as_of=EVE, cycle_geneses=REGISTRY) == {"phase": "pilot", "cycle": 15}


def test_genesis_day_stamps_the_experiment_and_the_new_cycle(bumped_ssm):
    assert pt.experiment_stamp(as_of=GENESIS, cycle_geneses=REGISTRY) == {"phase": EXPERIMENT_PHASE_CURRENT, "cycle": 16}


def test_the_default_as_of_is_the_pacific_write_day(bumped_ssm, monkeypatch):
    """No caller passes a date — the 14 live writers call experiment_stamp() bare. The
    default is the write's own Pacific calendar day, so the countdown window stamps
    pilot without a single call site changing."""
    monkeypatch.setattr(pt, "_write_date", lambda: EVE)
    assert pt.experiment_stamp(cycle_geneses=REGISTRY)["phase"] == "pilot"
    monkeypatch.setattr(pt, "_write_date", lambda: GENESIS)
    assert pt.experiment_stamp(cycle_geneses=REGISTRY)["phase"] == EXPERIMENT_PHASE_CURRENT


def test_the_live_registry_is_the_default_cycle_source(bumped_ssm, monkeypatch):
    """The real CYCLE_GENESES (site_api_data) is what a bare call reads — the bumped SSM
    value is never consulted while the registry answers."""
    from web.site_api_data import CYCLE_GENESES

    monkeypatch.setattr(pt, "_write_date", lambda: EVE)
    stamp = pt.experiment_stamp()
    assert stamp["phase"] == "pilot"
    assert stamp["cycle"] == pt.cycle_for_date(EVE, CYCLE_GENESES) == max(c for c, g in CYCLE_GENESES.items() if g <= EVE)


def test_pre_genesis_with_no_registry_reports_no_cycle_rather_than_ssm(bumped_ssm):
    """ADR-104: an unknown provenance is reported, never invented. SSM is KNOWN wrong
    pre-genesis, so it is not the fallback there."""
    assert pt.experiment_stamp(as_of=EVE, cycle_geneses={}) == {"phase": "pilot"}


def test_post_genesis_with_no_registry_falls_back_to_ssm(bumped_ssm):
    """Post-genesis SSM and the registry agree by construction — the legacy read survives
    as the fallback so an import failure never strips provenance from a Day-N write."""
    assert pt.experiment_stamp(as_of=GENESIS, cycle_geneses={}) == {"phase": EXPERIMENT_PHASE_CURRENT, "cycle": 16}


def test_include_phase_false_still_derives_the_cycle_from_the_date(bumped_ssm):
    assert pt.experiment_stamp(include_phase=False, as_of=EVE, cycle_geneses=REGISTRY) == {"cycle": 15}


def test_the_stamp_never_raises(monkeypatch):
    def _boom():
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(pt, "_cycle_geneses", _boom)
    from coach import coach_checkin

    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: (_ for _ in ()).throw(RuntimeError("ssm")))
    assert pt.experiment_stamp(as_of=GENESIS) == {"phase": EXPERIMENT_PHASE_CURRENT}


def test_cycle_for_date_is_the_highest_genesis_at_or_before_the_date():
    assert pt.cycle_for_date(REGISTRY[15], REGISTRY) == 15
    assert pt.cycle_for_date(EVE, REGISTRY) == 15
    assert pt.cycle_for_date(GENESIS, REGISTRY) == 16
    assert pt.cycle_for_date("2020-01-01", REGISTRY) is None  # before cycle 1: reported, not clamped
    assert pt.cycle_for_date(GENESIS, {}) is None and pt.cycle_for_date(GENESIS, None) is None
    # Registry order does not matter — it sorts by genesis, and string keys are tolerated.
    assert pt.cycle_for_date(GENESIS, {"16": GENESIS, "15": REGISTRY[15]}) == 16


def test_tag_record_stamps_an_undated_record_with_the_write_days_phase(monkeypatch):
    """The compute-side chokepoint (`tag_record`) took the constant phase for any record
    without a DATE# sk. A STATE#current singleton written in the countdown window is
    now pilot — the same rule as experiment_stamp."""
    from common import compute_metadata as cm

    monkeypatch.setattr(cm, "_emit_write_metric", lambda source_id: None)
    assert cm.tag_record({"pk": "p", "sk": "STATE#current"}, source_id="x", as_of=EVE)["phase"] == "pilot"
    assert cm.tag_record({"pk": "p", "sk": "STATE#current"}, source_id="x", as_of=GENESIS)["phase"] == EXPERIMENT_PHASE_CURRENT
    # The dated-sk rule and the explicit override are unchanged.
    assert cm.tag_record({"pk": "p", "sk": f"DATE#{GENESIS}"}, source_id="x", as_of=EVE)["phase"] == EXPERIMENT_PHASE_CURRENT
    assert cm.tag_record({"pk": "p", "sk": "STATE#current"}, source_id="x", phase="pilot", as_of=GENESIS)["phase"] == "pilot"


def test_tag_record_default_as_of_is_the_write_day(monkeypatch):
    from common import compute_metadata as cm

    monkeypatch.setattr(cm, "_emit_write_metric", lambda source_id: None)
    monkeypatch.setattr(pt, "_write_date", lambda: EVE)
    assert cm.tag_record({"pk": "p", "sk": "STATE#current"}, source_id="x")["phase"] == "pilot"


# ═════════════════════════════════════════════════════════════════════════════
# LEG 3 — archive_one keyed on (slug, cycle) under a per-step work contract
# ═════════════════════════════════════════════════════════════════════════════


class _Pager:
    def __init__(self, objects):
        self._objects = objects

    def paginate(self, Bucket=None, Prefix=""):
        return [{"Contents": [{"Key": k} for k in sorted(self._objects) if k.startswith(Prefix)]}]


class FakeS3:
    """Objects are (body, content_type, metadata). head_object raises a real ClientError."""

    def __init__(self, objects: dict):
        self.objects = {k: (v if isinstance(v, tuple) else (v, "text/html", {})) for k, v in objects.items()}
        self.copies: list[dict] = []
        self.puts: list[str] = []

    def get_paginator(self, op):
        return _Pager(self.objects)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        body, ct, meta = self.objects[Key]
        return {"ContentLength": len(body), "ContentType": ct, "Metadata": dict(meta)}

    def copy_object(self, **kw):
        self.copies.append(kw)
        body, ct, _ = self.objects[kw["CopySource"]["Key"]]
        self.objects[kw["Key"]] = (body, ct, dict(kw.get("Metadata") or {}))
        return {}

    def put_object(self, Bucket, Key, Body, ContentType="text/html", **kw):
        self.puts.append(Key)
        self.objects[Key] = (Body.decode() if isinstance(Body, bytes) else Body, ContentType, dict(kw.get("Metadata") or {}))
        return {}


PAGE = "<html><body><article>Week 5, cycle 15: 326.24 lbs at the start.</article></body></html>"
REASON = f"experiment_restart_{GENESIS}"


def _bucket():
    """The 09-04 state: a live page whose slug was ALREADY archived by the cycle-4 reset."""
    return FakeS3(
        {
            "blog/week-05.html": PAGE,
            "blog/archive/pilot/week-05.html": (
                "<html>cycle 4's week-05</html>",
                "text/html",
                {"tombstoned_reason": "experiment_restart_2026-07-10"},
            ),
        }
    )


def test_a_slug_with_a_cycle_4_archive_archives_again_under_cycle_16():
    """THE POSITIVE CONTROL for leg 3: pre-#3598 the destination was the constant
    `blog/archive/pilot/week-05.html`, which existed → (dest, False): 'already archived',
    nothing copied, and the 09-04 report's `html_files_archived=0`."""
    s3 = _bucket()
    dest, did, why = handler.archive_one(s3, "blog/week-05.html", "blog/", "blog/archive/", True, "NOW", cycle=16)
    assert (dest, did, why) == ("blog/archive/cycle-16/week-05.html", True, None)
    assert s3.objects[dest][0] == PAGE and s3.objects[dest][2]["tombstoned_reason"] == REASON
    assert s3.objects["blog/archive/pilot/week-05.html"][0] == "<html>cycle 4's week-05</html>"  # history untouched
    assert s3.objects["blog/week-05.html"][1] == "application/json"  # the original is tombstone-overwritten as before


def test_a_dry_run_reports_the_same_action_without_writing():
    s3 = _bucket()
    dest, did, why = handler.archive_one(s3, "blog/week-05.html", "blog/", "blog/archive/", False, "NOW", cycle=16)
    assert did is True and why is None and dest.startswith("blog/archive/cycle-16/")
    assert s3.copies == [] and s3.puts == []


def test_a_re_run_under_the_same_genesis_is_a_named_skip():
    s3 = _bucket()
    handler.archive_one(s3, "blog/week-05.html", "blog/", "blog/archive/", True, "NOW", cycle=16)
    s3.objects["blog/week-05.html"] = (PAGE, "text/html", {})  # the page restored, as a re-run would find it mid-way
    dest, did, why = handler.archive_one(s3, "blog/week-05.html", "blog/", "blog/archive/", True, "LATER", cycle=16)
    assert did is False and "re-run" in why and "cycle-16" in why
    assert len(s3.copies) == 1


def test_a_same_cycle_archive_from_a_different_genesis_is_overwritten_not_skipped():
    """The 2026-09-04 in-place re-anchor: cycle 16 kept its number while the genesis
    moved a day. Same cycle segment, different reason → archive again."""
    s3 = _bucket()
    s3.objects["blog/archive/cycle-16/week-05.html"] = (PAGE, "text/html", {"tombstoned_reason": "experiment_restart_2026-09-04"})
    _, did, why = handler.archive_one(s3, "blog/week-05.html", "blog/", "blog/archive/", True, "NOW", cycle=16)
    assert did is True and why is None
    assert s3.objects["blog/archive/cycle-16/week-05.html"][2]["tombstoned_reason"] == REASON


def test_a_tombstone_stub_source_is_a_named_skip_not_an_archive():
    s3 = FakeS3({"blog/week-00.html": ('{"tombstone": true}', "application/json", {})})
    _, did, why = handler.archive_one(s3, "blog/week-00.html", "blog/", "blog/archive/", True, "NOW", cycle=16)
    assert did is False and "tombstone stub" in why and s3.copies == []


def test_an_unreadable_cycle_keys_on_the_genesis_never_the_constant_pilot():
    assert handler.cycle_archive_prefix("blog/archive/", None, GENESIS) == f"blog/archive/genesis-{GENESIS}/"
    assert handler.cycle_archive_prefix("blog/archive/", 16, GENESIS) == "blog/archive/cycle-16/"
    assert not any(a.endswith("pilot/") for _p, a, _i in handler.CHRONICLE_PREFIXES)


def test_the_live_listing_excludes_every_archive_generation():
    s3 = FakeS3(
        {
            "blog/week-05.html": PAGE,
            "blog/archive/pilot/week-05.html": PAGE,
            "blog/archive/cycle-16/week-05.html": PAGE,
            "blog/index.html": PAGE,
            "blog/notes.txt": "x",
        }
    )
    assert handler.list_chronicle_html(s3, "blog/", "blog/archive/", "blog/index.html") == ["blog/week-05.html"]


# ── the work contract ─────────────────────────────────────────────────────────

THE_0904_REPORT = {
    "step": "restart_chronicle_handler:html_archive",
    "input_count": 29,
    "acted_count": 0,
    "skipped_count": 29,
    "reason": None,
}


def test_the_2026_09_04_report_is_a_violation():
    """29 found, 0 acted, 'already archived' — exit 0 on the night. Red now."""
    assert wc.violation(THE_0904_REPORT) is not None


def test_a_named_computed_reason_or_any_action_passes():
    assert wc.violation({**THE_0904_REPORT, "reason": "29× source is a tombstone stub left by a prior reset (no page to archive)"}) is None
    assert wc.violation({**THE_0904_REPORT, "acted_count": 1}) is None
    assert wc.violation({**THE_0904_REPORT, "input_count": 0, "skipped_count": 0}) is None


def test_work_report_prints_one_parseable_line(capsys):
    rec = wc.work_report("s", input_count=3, acted_count=3)
    out = capsys.readouterr().out
    assert wc.parse_work_reports(out) == [rec] and rec["reason"] is None and rec["skipped_count"] == 0
    assert wc.parse_work_reports("WORK_CONTRACT not-json\nnoise\n") == []


def test_the_handlers_html_contract_names_only_computed_skips():
    red = handler.html_work_contract(29, 0, {})
    assert wc.violation(red) is not None
    named = handler.html_work_contract(29, 0, {"source is a tombstone stub left by a prior reset (no page to archive)": 29})
    assert wc.violation(named) is None and named["skipped_count"] == 29 and "29×" in named["reason"]
    acted = handler.html_work_contract(29, 29, {})
    assert acted["reason"] is None and wc.violation(acted) is None


def test_the_handlers_journal_contract_reds_on_orphans_it_did_not_touch():
    stats = {"scanned": 3, "kept_live": 0, "not_html": 1, "archived": 0, "annotated": 0, "already_current": 0, "no_anchor": 2}
    assert wc.violation(handler.journal_work_contract(stats)) is not None  # 2 orphans, no anchor, nothing done
    stats.update({"already_current": 2, "no_anchor": 0})
    assert wc.violation(handler.journal_work_contract(stats)) is None  # the re-run, named
    stats.update({"already_current": 0, "annotated": 2})
    assert handler.journal_work_contract(stats)["acted_count"] == 2


def test_the_wipes_contract_names_only_the_idempotent_re_run():
    grand = {"total": 40, "to_tombstone": 0, "skipped_already": 29, "skipped_mode": 11, "applied": 0, "errors": 0}
    assert wc.violation(wipe.work_contract(grand, apply=True)) is None  # every in-scope row already tombstoned
    grand.update({"to_tombstone": 5, "errors": 5})
    assert wc.violation(wipe.work_contract(grand, apply=True)) is not None  # five to do, five errors: no reason
    assert wc.violation(wipe.work_contract(grand, apply=False)) is None  # dry-run plans five
    grand.update({"applied": 5, "errors": 0})
    assert wipe.work_contract(grand, apply=True)["acted_count"] == 5


def _pipeline():
    if "restart_pipeline" in sys.modules:
        return sys.modules["restart_pipeline"]
    spec = importlib.util.spec_from_file_location("restart_pipeline", REPO_ROOT / "deploy" / "restart_pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["restart_pipeline"] = mod
    spec.loader.exec_module(mod)
    return mod


def _step(rec: dict | None, exit_code: int = 0) -> list[str]:
    line = wc.WORK_CONTRACT_PREFIX + json.dumps(rec) if rec is not None else "no report"
    return [sys.executable, "-c", f"import sys; print({line!r}); sys.exit({exit_code})"]


def test_run_step_reds_a_zero_exit_step_that_hid_zero_work():
    log: list[str] = []
    rc = _pipeline().run_step("restart_chronicle_handler", _step(THE_0904_REPORT), True, log)
    assert rc == wc.WORK_CONTRACT_EXIT
    assert any("WORK CONTRACT" in line and "29" in line for line in log)


def test_run_step_passes_a_named_reason_an_action_and_a_silent_step():
    p = _pipeline()
    assert p.run_step("s", _step({**THE_0904_REPORT, "reason": "29× tombstone stubs"}), True, []) == 0
    assert p.run_step("s", _step({**THE_0904_REPORT, "acted_count": 29}), True, []) == 0
    assert p.run_step("s", _step(None), True, []) == 0  # no report is not a failure — only a report that hides zero is


def test_run_step_keeps_the_steps_own_nonzero_exit():
    assert _pipeline().run_step("s", _step({**THE_0904_REPORT, "acted_count": 29}, exit_code=3), True, []) == 3


def test_run_step_applies_the_contract_in_dry_run_too():
    """`--apply` is stripped in dry-run; the contract is not."""
    cmd = _step(THE_0904_REPORT) + ["--apply"]
    assert _pipeline().run_step("s", cmd, False, []) == wc.WORK_CONTRACT_EXIT


def test_the_registered_steps_that_report_are_the_ones_this_fix_wired():
    """Both scripts emit through the shared helper (a grep-level structural check so a
    refactor that drops the report is visible here, not at the next reset)."""
    for rel in ("deploy/restart_intelligence_wipe.py", "deploy/restart_chronicle_handler.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "from restart_work_contract import work_report" in src and "work_report(" in src, rel
    pipeline_src = (REPO_ROOT / "deploy" / "restart_pipeline.py").read_text(encoding="utf-8")
    assert "work_contract_rc(name, proc.stdout, log)" in pipeline_src


def test_no_derived_artifacts_registry_and_no_reverify_workflow():
    """The RCA's rent register REJECTED both; the acceptance says so explicitly."""
    assert not (REPO_ROOT / ".github" / "workflows" / "restart-reverify.yml").exists()
    for rel in ("deploy/restart_work_contract.py", "deploy/restart_chronicle_handler.py", "deploy/restart_intelligence_wipe.py"):
        assert "DERIVED_ARTIFACTS" not in (REPO_ROOT / rel).read_text(encoding="utf-8"), rel
