"""#4634 — the raw-archive KMS readability inventory counts every object whose key cannot decrypt.

Pure-function tests: no AWS. The fixture objects mirror what ``HeadObject`` returns
(``ServerSideEncryption`` + ``SSEKMSKeyId``) and what ``kms:DescribeKey`` reports
(``KeyState``, or ``NotFoundException`` → ``Missing``).
"""

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("raw_kms_readability_inventory", REPO / "scripts" / "raw_kms_readability_inventory.py")
rki = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rki  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(rki)
DEAD = "arn:aws:kms:us-west-2:000000000000:key/00000000-dead-0000-0000-000000000000"
LIVE = "arn:aws:kms:us-west-2:000000000000:key/11111111-live-1111-1111-111111111111"
PENDING = "arn:aws:kms:us-west-2:000000000000:key/22222222-pend-2222-2222-222222222222"
STATES = {DEAD: "Missing", LIVE: "Enabled", PENDING: "PendingDeletion"}


def _objs():
    O = rki.ObjectEnc
    return [
        O("raw/matthew/health_auto_export/2026/05/17_101500.json", "2026-05", "aws:kms", DEAD),
        O("raw/matthew/health_auto_export/2026/05/17_111500.json", "2026-05", "aws:kms", DEAD),
        O("raw/matthew/whoop/2026/05/17.json", "2026-05", "aws:kms", PENDING),
        O("raw/matthew/whoop/2026/05/18.json", "2026-05", "AES256"),
        O("raw/todoist/2026/05/16.json", "2026-05", "aws:kms", LIVE),
        O("raw/matthew/strava/activities/2026/04/01.json", "2026-04", "AES256"),
        O("raw/hevy/abc.json", "2026-06", "error"),
    ]


def test_dead_and_pending_keys_are_counted_live_and_sse_s3_are_not():
    inv = rki.build_inventory(_objs(), STATES.get)
    s = rki.summarize(inv)
    assert s["dead_key_objects"] == 3
    assert sorted(s["affected_objects"]) == [
        "raw/matthew/health_auto_export/2026/05/17_101500.json",
        "raw/matthew/health_auto_export/2026/05/17_111500.json",
        "raw/matthew/whoop/2026/05/17.json",
    ]
    cells = {(c["source_path"], c["month"]): c["dead_key"] for c in s["dead_key_cells"]}
    assert cells == {("raw/matthew/health_auto_export", "2026-05"): 2, ("raw/matthew/whoop", "2026-05"): 1}
    assert s["head_errors"] == 1
    assert s["objects_scanned"] == 7
    assert s["months_scanned"] == ["2026-04", "2026-05", "2026-06"]
    assert rki.verdict(s) == 1


def test_clean_archive_passes():
    O = rki.ObjectEnc
    objs = [O("raw/matthew/whoop/2026/05/18.json", "2026-05", "AES256"), O("raw/todoist/x.json", "2026-05", "aws:kms", LIVE)]
    s = rki.summarize(rki.build_inventory(objs, STATES.get))
    assert s["dead_key_objects"] == 0
    assert rki.verdict(s) == 0


def test_a_failed_sampled_read_fails_the_check_even_with_no_dead_key():
    s = rki.summarize(rki.build_inventory([], STATES.get), sampled={"raw/x.json": "FAIL(AccessDenied)"})
    assert rki.verdict(s) == 1


def test_output_never_carries_a_key_identifier():
    inv = rki.build_inventory(_objs(), STATES.get)
    s = rki.summarize(inv, backup={}, sampled={"raw/matthew/whoop/2026/05/17.json": "FAIL(KMS.NotFoundException)"})
    blob = json.dumps(s) + rki.render_markdown(s, "raw/")
    for kid in (DEAD, LIVE, PENDING):
        assert kid not in blob
        assert kid.split("/")[-1] not in blob
    assert set(s["kms_keys_seen"]) <= {"cmk-1", "cmk-2", "cmk-3"}


def test_push_source_with_no_backup_copy_is_unrecoverable_and_refetchable_source_is_not():
    inv = rki.build_inventory(_objs(), STATES.get)
    s = rki.summarize(inv, backup={"raw/matthew/whoop/2026/05/17.json": False})
    by = {b["source_path"]: b for b in s["by_source"]}
    hae = by["raw/matthew/health_auto_export"]
    assert hae["refetchable"].startswith("no")
    assert hae["backup_copies"] == 0 and hae["unrecoverable"] is True
    assert by["raw/matthew/whoop"]["unrecoverable"] is False


def test_a_backup_check_error_is_not_proof_of_absence():
    inv = rki.build_inventory(_objs(), STATES.get)
    errs = {k: "error(403)" for k in rki.summarize(inv)["affected_objects"]}
    by = {b["source_path"]: b for b in rki.summarize(inv, backup=errs)["by_source"]}
    hae = by["raw/matthew/health_auto_export"]
    assert hae["backup_unknown"] == 2 and hae["unrecoverable"] is False


def test_a_readable_older_version_makes_a_push_object_recoverable():
    inv = rki.build_inventory(_objs(), STATES.get)
    keys = rki.summarize(inv)["affected_objects"]
    hae_keys = [k for k in keys if "health_auto_export" in k]
    s = rki.summarize(inv, backup={}, versions={k: True for k in hae_keys})
    hae = {b["source_path"]: b for b in s["by_source"]}["raw/matthew/health_auto_export"]
    assert hae["readable_older_version"] == 2 and hae["unrecoverable"] is False
    assert "Readable older version" in rki.render_markdown(s, "raw/")


def test_config_prefix_is_refused_and_skipped_in_wider_scans():
    assert rki.is_refused("config/")
    assert rki.is_refused("config/site/")
    assert not rki.is_refused("raw/")
    assert not rki.is_refused("config/", include_config=True)
    assert rki.is_skipped_key("config/anything.json")
    assert not rki.is_skipped_key("raw/config/x.json")
    assert rki.main(["--prefix", "config/"]) == 2


def test_source_path_follows_the_fractured_raw_layout():
    assert rki.source_path("raw/matthew/apple_health/2026/05/17.json.gz") == "raw/matthew/apple_health"
    assert rki.source_path("raw/todoist/2026/05/16.json") == "raw/todoist"
    assert rki.source_path("raw/hevy/abc.json") == "raw/hevy"
    assert rki.source_path("generated/x/y.json") == "generated/"
    assert rki.month_of(datetime(2026, 5, 17, 21, 44, tzinfo=timezone.utc)) == "2026-05"


def test_adr_053_carries_the_key_retention_rule():
    text = (REPO / "docs" / "DECISIONS.md").read_text()
    start = text.index("### ADR-053")
    section = text[start : text.index("\n### ADR-", start + 1)]
    assert "never scheduled for deletion" in section
    assert "re-encrypted" in section
    assert "raw_kms_readability_inventory.py" in section


def test_the_unrecoverable_inventory_is_recorded_without_key_identifiers():
    doc = REPO / "docs" / "audits" / "RAW_KMS_UNREADABLE_INVENTORY_2026-10.md"
    text = doc.read_text()
    assert "raw_kms_readability_inventory.py" in text
    assert "unrecoverable" in text.lower()
    assert "arn:aws:kms" not in text
    assert "5c50ca02" not in text


# ── box 1 (every prefix) + box 3 (the scheduled check) ───────────────────────

RECORD = REPO / "docs" / "audits" / "RAW_KMS_UNREADABLE_INVENTORY_2026-10.md"
WORKFLOW = REPO / ".github" / "workflows" / "raw-kms-readability.yml"


def _summary_with_dead(keys, head_errors=0, sampled=None):
    O = rki.ObjectEnc
    objs = [O(k, "2026-05", "aws:kms", DEAD) for k in keys] + [O("raw/matthew/whoop/2026/06/01.json", "2026-06", "AES256")]
    objs += [O(f"raw/hevy/err{i}.json", "2026-06", "error") for i in range(head_errors)]
    return rki.summarize(rki.build_inventory(objs, STATES.get), sampled=sampled)


def test_the_record_lists_exactly_the_25_known_dead_raw_objects():
    rec = rki.recorded_dead_keys(RECORD.read_text())
    assert len(rec) == 25
    assert all(k.startswith("raw/") for k in rec)
    assert sum("health_auto_export" in k for k in rec) == 14


def test_the_record_parser_refuses_a_record_without_its_section():
    try:
        rki.recorded_dead_keys("# nothing here\n- `raw/x.json`\n")
    except ValueError:
        return
    raise AssertionError("a record with no affected-objects section must not parse as an empty (all-clear) set")


def test_check_passes_only_when_the_dead_set_is_the_record():
    rec = {"raw/a.json", "raw/b.json"}
    s = _summary_with_dead(sorted(rec))
    cmp = rki.compare_to_record(s, rec, "raw/")
    assert cmp["matches_record"] and rki.check_verdict(s, cmp) == 0
    # The plain verdict stays red on the same data — that is why the check mode exists.
    assert rki.verdict(s) == 1


def test_a_new_dead_object_fails_the_check():
    s = _summary_with_dead(["raw/a.json", "raw/b.json", "raw/new.json"])
    cmp = rki.compare_to_record(s, {"raw/a.json", "raw/b.json"}, "raw/")
    assert cmp["new_dead"] == ["raw/new.json"]
    assert rki.check_verdict(s, cmp) == 1
    assert "raw/new.json" in rki.render_comparison(cmp, "raw/")


def test_a_recorded_object_that_now_reads_fails_the_check_until_the_record_is_updated():
    s = _summary_with_dead(["raw/a.json"])
    cmp = rki.compare_to_record(s, {"raw/a.json", "raw/refetched.json"}, "raw/")
    assert cmp["recorded_now_readable_or_gone"] == ["raw/refetched.json"]
    assert rki.check_verdict(s, cmp) == 1


def test_the_record_is_compared_only_within_the_scanned_prefix():
    s = _summary_with_dead(["raw/a.json"])
    cmp = rki.compare_to_record(s, {"raw/a.json", "generated/elsewhere.json"}, "raw/")
    assert cmp["matches_record"] and cmp["recorded_in_scope"] == 1


def test_a_head_error_or_a_failed_sampled_read_fails_the_check_even_when_the_record_matches():
    s = _summary_with_dead(["raw/a.json"], head_errors=1)
    assert rki.check_verdict(s, rki.compare_to_record(s, {"raw/a.json"}, "raw/")) == 1
    s = _summary_with_dead(["raw/a.json"], sampled={"raw/matthew/whoop/2026/06/01.json": "FAIL(AccessDenied)"})
    assert rki.check_verdict(s, rki.compare_to_record(s, {"raw/a.json"}, "raw/")) == 1


def test_the_readable_sample_never_draws_a_dead_or_unheadable_object():
    import random

    O = rki.ObjectEnc
    objs = [O("raw/dead.json", "2026-05", "aws:kms", DEAD), O("raw/err.json", "2026-05", "error")]
    objs += [O(f"raw/ok{i}.json", "2026-06", "AES256") for i in range(5)]
    picked = rki.readable_sample(objs, ["raw/dead.json"], 50, rng=random.Random(0))
    assert sorted(picked) == [f"raw/ok{i}.json" for i in range(5)]
    assert rki.readable_sample(objs, ["raw/dead.json"], 0) == []


def test_the_prefix_rollup_covers_every_top_level_prefix():
    O = rki.ObjectEnc
    objs = [
        O("raw/matthew/whoop/2026/05/17.json", "2026-05", "aws:kms", DEAD),
        O("raw/todoist/2026/03/01.json", "2026-03", "AES256"),
        O("generated/a/b.json", "2026-06", "AES256"),
        O("rootfile.json", "2026-07", "AES256"),
    ]
    roll = {r["prefix"]: r for r in rki.summarize(rki.build_inventory(objs, STATES.get))["by_prefix"]}
    assert set(roll) == {"raw/", "generated/", "(root)"}
    assert roll["raw/"]["objects"] == 2 and roll["raw/"]["dead_key"] == 1 and roll["raw/"]["months"] == 2
    assert roll["generated/"]["sse_s3"] == 1


def test_the_inventory_record_covers_every_prefix_and_names_config_as_pending():
    text = RECORD.read_text()
    for p in ("raw/", "generated/", "site/", "exports/", "imports/", "uploads/"):
        assert f"| `{p}` |" in text, p
    assert "| `config/` |" in text and "pending" in text.split("| `config/` |")[1].split("\n")[0]
    assert "--include-config" in text


def test_the_scheduled_workflow_runs_the_check_unpiped_under_a_role_that_can_read_raw():
    wf = WORKFLOW.read_text()
    assert "schedule:" in wf and "workflow_dispatch" in wf
    run_line = next(ln for ln in wf.splitlines() if "raw_kms_readability_inventory.py" in ln and "python3" in ln)
    assert "--check-against-record" in run_line and "--prefix raw/" in run_line and "--sample-readable" in run_line
    assert "|" not in run_line.split("raw_kms_readability_inventory.py", 1)[1].replace("||", ""), "a pipe would swallow the exit code"
    assert "exit $rc" in wf
    assert "role/github-actions-remediation-role" in wf
    perms = json.loads((REPO / "infra" / "iam" / "github-actions-remediation-role.permissions.json").read_text())
    stmts = {st.get("Sid"): st for st in perms["Statement"]}
    assert "raw/*" in stmts["S3List"]["Condition"]["StringLike"]["s3:prefix"]
    assert "s3:GetObject" in json.dumps(stmts["S3Read"]["Action"])
    assert stmts["S3Read"]["Resource"] == "arn:aws:s3:::matthew-life-platform/*"


def test_the_scheduled_workflow_is_registered_watched():
    sys.path.insert(0, str(REPO / "scripts"))
    import scheduled_workflow_registry as swr

    assert swr.WATCH_POLICY["raw-kms-readability.yml"]["watched"] is True


def test_a_passing_sampled_read_is_counted_not_named():
    s = _summary_with_dead([], sampled={"raw/whoop/sleep/2022/04/30.json": "ok", "raw/x/2023/01/01.json": "FAIL(AccessDenied)"})
    md = rki.render_markdown(s, "raw/")
    assert "1 of 2 decrypted" in md
    assert "raw/x/2023/01/01.json" in md and "raw/whoop/sleep/2022/04/30.json" not in md
