"""tests/test_restart_pipeline_hooks.py — #1092 dry-run pipeline plumbing (no AWS).

Pins the post-verify hook sequence (build_post_verify_hooks) and the dedup pass's
pure logic (fingerprint / find_duplicate_groups / validate_source — generalized
from the verified eightsleep UTC-rollover duplicates). Nothing here touches AWS:
the hook builder is pure, and the dedup units run on fixture rows.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pipeline = _load("restart_pipeline")
dedup = _load("dedup_source_records")


# ── build_post_verify_hooks: the #1092 hook sequence ──────────────────────────


def test_default_hooks_are_prologue_fix_only():
    # Byte-compat guarantee: with no new flags, the ONLY behavior change is the
    # issue-sanctioned default-on fix_prologue hook.
    hooks = pipeline.build_post_verify_hooks()
    assert [n for n, _ in hooks] == ["fix_prologue_cycle_and_subscribe_ttl"]


def test_skip_prologue_fix_empties_the_default():
    assert pipeline.build_post_verify_hooks(skip_prologue_fix=True) == []


def test_full_hook_sequence_and_order():
    hooks = pipeline.build_post_verify_hooks(with_preregistration=True, dedup_sources=["eightsleep", "whoop"])
    assert [n for n, _ in hooks] == [
        "fix_prologue_cycle_and_subscribe_ttl",  # (a) — must follow the SSM cycle bump; post-verify satisfies it
        "seed_genesis_preregistration",  # (b) — opt-in --with-preregistration
        "dedup_eightsleep",  # (c) — one pass per --dedup-source, in order
        "dedup_whoop",
    ]


def test_hook_commands_are_run_step_compatible():
    # run_step strips "--apply" in dry-run mode — every hook must carry it so the
    # dry-run pipeline previews the hooks like existing sub-steps.
    hooks = pipeline.build_post_verify_hooks(with_preregistration=True, dedup_sources=["eightsleep"])
    for name, cmd in hooks:
        assert cmd[0] == "python3" and cmd[1].startswith("deploy/"), (name, cmd)
        assert "--apply" in cmd, f"hook {name} would never write even under --apply"


def test_dedup_hook_passes_the_source_through():
    ((_, cmd),) = [h for h in pipeline.build_post_verify_hooks(dedup_sources=["eightsleep"]) if h[0] == "dedup_eightsleep"]
    assert cmd[cmd.index("--source") + 1] == "eightsleep"


def test_build_sub_scripts_unchanged_by_1092():
    # The pre-existing sub-script sequence is untouched — hooks are additive.
    names = [n for n, _ in pipeline.build_sub_scripts(False, [], "2026-06-14", 4)]
    assert names == [
        "restart_phase_tag",
        "restart_intelligence_wipe",
        "restart_ledger_reset",
        "restart_chronicle_handler",
        "restart_media_reset",
        "restart_leadin_pages",
        "restart_character_rebuild",
        "restart_site_copy_sync",
        "restart_docs_update",
    ]


# ── clear_predict_week_subject: the #1198 reset step ─────────────────────────


class _FakeS3:
    def __init__(self):
        self.deletes = []

    def delete_object(self, Bucket=None, Key=None, **_kw):
        self.deletes.append((Bucket, Key))


def test_clear_predict_week_subject_dry_run_touches_no_s3(monkeypatch):
    # Dry-run previews only — it must never reach S3 (the whole pipeline is
    # dry-run-provable before an --apply).
    fake = _FakeS3()
    monkeypatch.setattr(pipeline.boto3, "client", lambda *a, **k: fake)
    pipeline.clear_predict_week_subject(apply=False)
    assert fake.deletes == []


def test_clear_predict_week_subject_apply_deletes_the_artifact(monkeypatch):
    # #1198: --apply retires the manual per-week predict-the-week subject so the
    # new cycle can't inherit the outgoing cycle's frozen open week.
    fake = _FakeS3()
    monkeypatch.setattr(pipeline.boto3, "client", lambda *a, **k: fake)
    pipeline.clear_predict_week_subject(apply=True)
    assert fake.deletes == [("matthew-life-platform", "site/config/current_challenge.json")]


# ── dedup_source_records: the generalized eightsleep pass ─────────────────────

# The verified instance (truth-audit finding 21): one physical night written under
# BOTH DATE#2026-07-10 and DATE#2026-07-11 — identical session, differing only in
# the date dimension + ingestion metadata.
_NIGHT = {
    "sleep_start": "2026-07-10T07:46:59Z",
    "sleep_end": "2026-07-10T14:40:29Z",
    "sleep_hours": Decimal("6.88"),
    "sleep_score": Decimal("77"),
}


def _row(sk: str, ingested: str, **extra):
    return {"pk": "USER#matthew#SOURCE#eightsleep", "sk": sk, "ingested_at": ingested, **_NIGHT, **extra}


def test_utc_rollover_duplicate_grouped_keep_earliest():
    rows = [
        _row("DATE#2026-07-11", "2026-07-11T01:15:00Z"),  # the forward-duplicated copy
        _row("DATE#2026-07-10", "2026-07-10T23:15:00Z"),  # the real wake date
        {
            "pk": "USER#matthew#SOURCE#eightsleep",
            "sk": "DATE#2026-07-09",
            "sleep_start": "2026-07-09T07:00:00Z",
            "sleep_score": Decimal("81"),
        },
    ]
    groups = dedup.find_duplicate_groups(rows)
    assert len(groups) == 1
    keeper, doomed = groups[0][0], groups[0][1:]
    assert keeper["sk"] == "DATE#2026-07-10"  # earliest kept — UTC rollover duplicates FORWARD
    assert [d["sk"] for d in doomed] == ["DATE#2026-07-11"]


def test_phase_and_metadata_differences_do_not_defeat_the_match():
    # The tagger may have stamped the two copies differently — still one session.
    rows = [
        _row("DATE#2026-07-10", "2026-07-10T23:15:00Z", phase="pilot", cycle=Decimal("4")),
        _row("DATE#2026-07-11", "2026-07-11T01:15:00Z", phase="experiment"),
    ]
    assert len(dedup.find_duplicate_groups(rows)) == 1


def test_no_data_marker_rows_never_group():
    # Gap-filled markers are content-identical BY DESIGN (the Withings backfill
    # wrote 8 identical no_data rows) — no session anchor, so never duplicates.
    rows = [{"pk": "p", "sk": f"DATE#2026-07-{d:02d}", "status": "no_data"} for d in range(1, 9)]
    assert dedup.find_duplicate_groups(rows) == []
    assert dedup.fingerprint(rows[0]) is None


def test_distinct_sessions_do_not_group():
    rows = [
        _row("DATE#2026-07-10", "2026-07-10T23:15:00Z"),
        {
            "pk": "USER#matthew#SOURCE#eightsleep",
            "sk": "DATE#2026-07-11",
            "sleep_start": "2026-07-11T07:30:00Z",
            "sleep_end": "2026-07-11T14:10:00Z",
            "sleep_hours": Decimal("6.88"),
            "sleep_score": Decimal("77"),
        },
    ]
    assert dedup.find_duplicate_groups(rows) == []


def test_validate_source_accepts_raw_timeseries_only():
    assert dedup.validate_source("eightsleep") is None
    assert dedup.validate_source("whoop") is None
    # experiment-scoped = the wipe's job (tombstone, never delete)
    assert "not raw_timeseries" in dedup.validate_source("insights")
    # cross-phase = never touched
    assert "not raw_timeseries" in dedup.validate_source("labs")
    # unknown = refuse loudly, never default
    assert "unknown source" in dedup.validate_source("not_a_source")
