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
