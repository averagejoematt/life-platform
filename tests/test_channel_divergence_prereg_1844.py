"""tests/test_channel_divergence_prereg_1844.py — the #1844 spoken-vs-typed channel
divergence pre-registration: content-hash seal + registration-content contract.

Mirrors tests/test_prereg_hash_stamp.py (#1378) applied to the second frozen
pre-registration artifact this codebase carries. Pins:
  1. IMMUTABILITY: the committed frozen file's SHA-256 equals the committed stamp.
  2. Tamper detection + write-path blocks (same behavior as the genesis stamp module,
     re-verified here since this is a second, independent instance of the pattern).
  3. Honesty (ADR-104): stamps are never backdated; re-stamping an unchanged file
     keeps the ORIGINAL stamped_at.
  4. REGISTRATION CONTENT (ADR-105 / #1844's AC1-4): the frozen artifact actually
     states hypothesis + comparison metrics + n floor + analysis trigger + the
     coder-version gate + the calibration check — registration-time content checks,
     not analysis (there is no analysis code in this story).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(module_name: str, rel_path: str):
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


cds = _load("channel_divergence_prereg_stamp", "deploy/channel_divergence_prereg_stamp.py")

_CYCLE_LANGUAGE_BANNED = ("password", "secret", "api_key", "ssn", "social security")


def _tmp_freeze(tmp_path, monkeypatch, experiment_id="spoken-vs-typed-divergence_2026-07-27", registered_at="2026-07-27T20:00:00+00:00"):
    """Point the stamp module at a tmp frozen file + tmp stamp path."""
    frozen_p = tmp_path / "channel_divergence_prereg.json"
    stamp_p = tmp_path / "channel_divergence_prereg.sha256.json"
    frozen_p.write_text(json.dumps({"experiment_id": experiment_id, "registered_at": registered_at, "hypothesis": {}}, indent=2) + "\n")
    monkeypatch.setattr(cds, "FROZEN_PATH", frozen_p)
    monkeypatch.setattr(cds, "STAMP_PATH", stamp_p)
    return frozen_p, stamp_p


# ──────────────────────────────────────────────────────────────────────────────
# 1. THE IMMUTABILITY GATE — committed frozen file vs committed stamp
# ──────────────────────────────────────────────────────────────────────────────


def test_committed_stamp_matches_frozen_artifact():
    """The CI-level write-path block: editing the frozen pre-registration after it
    was stamped reds this test. Restore the file or lose the merge."""
    assert cds.FROZEN_PATH.exists(), "frozen pre-registration missing"
    assert cds.STAMP_PATH.exists(), (
        f"no hash stamp at {cds.STAMP_PATH} — the frozen pre-registration is not content-addressed; "
        "run: python3 deploy/channel_divergence_prereg_stamp.py"
    )
    issues = cds.verify_stamp()
    assert issues == [], f"frozen pre-registration fails its hash stamp: {issues}"
    stamp = cds.load_stamp()
    frozen = json.loads(cds.FROZEN_PATH.read_text())
    assert stamp["sha256"] == cds.compute_sha256()
    assert stamp["experiment_id"] == frozen["experiment_id"]
    assert stamp["frozen_registered_at"] == frozen["registered_at"]
    assert stamp["sha256"] == hashlib.sha256(cds.FROZEN_PATH.read_bytes()).hexdigest()


def test_committed_stamp_is_honest_about_time():
    """Never backdated; when the stamp postdates registration the note says so."""
    stamp = cds.load_stamp()
    assert stamp is not None
    assert stamp["stamped_at"] >= stamp["frozen_registered_at"], "stamp is backdated"
    if stamp["stamped_at"][:10] != stamp["frozen_registered_at"][:10]:
        assert stamp["frozen_registered_at"] in stamp["stamp_note"]
        assert stamp["stamped_at"] in stamp["stamp_note"]


# ──────────────────────────────────────────────────────────────────────────────
# 2. Tamper detection + write-path blocks
# ──────────────────────────────────────────────────────────────────────────────


def test_verify_detects_post_stamp_edit(tmp_path, monkeypatch):
    frozen_p, _ = _tmp_freeze(tmp_path, monkeypatch)
    cds.write_stamp(now=datetime(2026, 7, 27, 21, 0, tzinfo=timezone.utc))
    assert cds.verify_stamp() == []
    edited = json.loads(frozen_p.read_text())
    edited["hypothesis"] = {"primary": "revised to look right"}
    frozen_p.write_text(json.dumps(edited, indent=2) + "\n")
    issues = cds.verify_stamp()
    assert issues and any("HASH MISMATCH" in i for i in issues)


def test_write_stamp_refuses_to_launder_a_same_experiment_edit(tmp_path, monkeypatch):
    frozen_p, _ = _tmp_freeze(tmp_path, monkeypatch)
    cds.write_stamp(now=datetime(2026, 7, 27, 21, 0, tzinfo=timezone.utc))
    frozen_p.write_text(frozen_p.read_text().replace("2026-07-27T20:00:00", "2026-07-27T20:00:01"))
    with pytest.raises(SystemExit, match="REFUSED"):
        cds.write_stamp(now=datetime(2026, 7, 27, 22, 0, tzinfo=timezone.utc))


def test_write_stamp_idempotent_keeps_original_stamped_at(tmp_path, monkeypatch):
    _tmp_freeze(tmp_path, monkeypatch)
    first = cds.write_stamp(now=datetime(2026, 7, 27, 21, 0, tzinfo=timezone.utc))
    again = cds.write_stamp(now=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc))
    assert again["stamped_at"] == first["stamped_at"], "re-stamping an unchanged file must not re-date the stamp"


def test_write_stamp_never_backdates(tmp_path, monkeypatch):
    _tmp_freeze(tmp_path, monkeypatch, registered_at="2026-07-27T20:00:00+00:00")
    with pytest.raises(SystemExit, match="never backdated"):
        cds.write_stamp(now=datetime(2026, 7, 26, 0, 0, tzinfo=timezone.utc))


def test_s3_publish_refuses_to_overwrite_different_published_bytes(tmp_path, monkeypatch):
    """Immutable post-publish: the public copy is never overwritten with new bytes."""
    _tmp_freeze(tmp_path, monkeypatch)
    stamp = cds.write_stamp(now=datetime(2026, 7, 27, 21, 0, tzinfo=timezone.utc))

    import boto3

    class _Body:
        def __init__(self, b):
            self._b = b

        def read(self):
            return self._b

    class _FakeS3:
        def get_object(self, Bucket, Key):
            return {"Body": _Body(b"SOMETHING ELSE ENTIRELY")}

        def put_object(self, **kw):  # pragma: no cover — must never be reached
            raise AssertionError("put_object must not be called over a divergent published artifact")

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeS3())
    with pytest.raises(SystemExit, match="immutable"):
        cds.publish_to_s3(stamp)


def test_publish_never_invoked_without_apply(monkeypatch, capsys):
    """main() without --apply must never touch AWS — the dry-run default this whole
    worktree's non-negotiables rely on (sealing/publish is a from-main ops step)."""
    monkeypatch.setattr(sys, "argv", ["channel_divergence_prereg_stamp.py"])

    def _boom(*a, **k):  # pragma: no cover — must never be reached
        raise AssertionError("publish_to_s3 must not run without --apply")

    monkeypatch.setattr(cds, "publish_to_s3", _boom)
    assert cds.main() == 0
    assert "DRY RUN" in capsys.readouterr().out


# ──────────────────────────────────────────────────────────────────────────────
# 3. Registration content — AC1-4 (registration only, no analysis code)
# ──────────────────────────────────────────────────────────────────────────────


def _frozen():
    return json.loads(cds.FROZEN_PATH.read_text())


def test_ac1_hypothesis_metrics_n_floor_and_trigger_present():
    f = _frozen()
    assert f["hypothesis"]["primary"]
    assert len(f["hypothesis"]["directional"]) == 3
    metric_ids = {m["id"] for m in f["comparison_metrics"]}
    assert metric_ids == {"theme_distribution", "sentiment_distribution", "specificity"}
    assert f["n_floor"]["per_channel"] == 20
    assert f["n_floor"]["absolute_floor"] == 5
    assert "analysis_trigger" in f and f["analysis_trigger"]["rule"]
    assert f["analysis_trigger"]["outer_bound"]
    assert f["registered_at"]
    assert f["contract"]


def test_ac1_n_floor_and_trigger_derive_from_diary_start_honestly():
    f = _frozen()
    assert f["analysis_trigger"]["diary_start_date"] == "2026-07-26"
    assert "cadence_caveat" in f["analysis_trigger"]
    # the later-of pattern: n floor OR a date floor, whichever is later — never a
    # bare calendar date alone (the driving instruction this story was built against)
    rule = f["analysis_trigger"]["rule"].lower().replace(" ", "_")
    assert "later" in rule
    assert "n_floor" in rule


def test_ac2_channels_match_the_live_entry_channel_enum():
    """#1843: entry_channel() (lambdas/flourishing.py) is the single source of truth
    for channel values — the registered comparison groups must match it exactly, not
    a stale or invented enum."""
    sys.path.insert(0, str(REPO_ROOT / "lambdas"))
    import flourishing

    f = _frozen()
    groups = f["data_source"]["channel_values"]
    assert set(groups["spoken"]) == {flourishing.CHANNEL_VIDEO_DIARY, flourishing.CHANNEL_SOLO_RECORDING}
    assert set(groups["typed"]) == {flourishing.CHANNEL_JOURNAL}


def test_ac2_coder_version_gate_states_detection_method_and_the_known_gap():
    f = _frozen()
    gate = f["coder_version_gate"]
    assert gate["coder_as_of_registration"]["schema_version"] == 2
    assert "enriched_schema_version" in gate["detection_method"]["schema_version_changes"]
    # the honest gap: model swaps aren't stamped per-entry — must be named, not hidden
    assert "not" in gate["detection_method"]["model_swaps_without_a_schema_bump"].lower()
    assert gate["invalidation_rule"]


def test_ac3_calibration_check_specified_with_source_and_threshold_no_implementation():
    f = _frozen()
    calib = f["calibration_check"]
    assert calib["fields"]["enriched_mood"]
    assert calib["fields"]["morning_mood"]
    assert "pearson_r" in calib["method"]
    assert "min" in calib["method"].lower()
    assert calib["threshold"]
    assert "NOT IMPLEMENTED" in calib["implementation_status"]


def test_ac4_publication_notes_landing_surface_and_gradebeat_both_outcomes():
    f = _frozen()
    pub = f["publication"]
    assert "/data/" in pub["landing_surface"]
    assert "publishable" in pub["outcome_is_graded_either_way"].lower()
    assert pub["public_artifact_route"].startswith("generated/experiments/prereg/")


def test_no_banned_private_content_in_frozen_artifact():
    """The repo is public; prereg artifacts historically publish (#728/#976) — this
    one must carry nothing that can't be public."""
    text = cds.FROZEN_PATH.read_text().lower()
    for token in _CYCLE_LANGUAGE_BANNED:
        assert token not in text, f"banned/private token '{token}' found in the public prereg artifact"
