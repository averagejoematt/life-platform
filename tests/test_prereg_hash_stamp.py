"""tests/test_prereg_hash_stamp.py — the #1378 content-hash seal on the genesis freeze.

Pins the contracts that make the pre-registration a *checkable* public event:
  1. IMMUTABILITY (the CI gate): the committed frozen file's SHA-256 equals the
     committed stamp — ANY post-stamp edit to the frozen claims reds this suite.
  2. Tamper detection + write-path blocks: verify_stamp flags an edited file;
     write_stamp refuses to launder a same-genesis edit into a fresh stamp; the
     seeder's main() aborts before any DDB write; the S3 publish refuses to
     overwrite a published artifact with different bytes.
  3. Honesty (ADR-104): stamps are never backdated; re-stamping an unchanged file
     keeps the ORIGINAL stamped_at; when stamp postdates freeze, both dates are
     recorded and the public seal states both.
  4. The page carries the seal: hash + public artifact URL + verify command in the
     rendered body, presentation-rule clean (#976).
  5. Predict-the-week (criterion 3): the genesis-week subject derives from the
     FROZEN hypotheses' own test_specs, stamped with the freeze's hash.
  6. The genesis-eve email (criterion 2): carries the fingerprint + verify command
     + unsubscribe, and refuses to send on any day but genesis eve.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "deploy"))

import genesis_prereg_stamp as gps  # noqa: E402


def _load(module_name: str, rel_path: str):
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


seeder = _load("seed_genesis_preregistration", "deploy/seed_genesis_preregistration.py")
publisher = _load("publish_genesis_preregistration", "deploy/publish_genesis_preregistration.py")
predict_builder = _load("build_genesis_predict_week", "deploy/build_genesis_predict_week.py")
lock_email = _load("send_prereg_lock_email", "deploy/send_prereg_lock_email.py")

GOALS = json.loads((REPO_ROOT / "config" / "user_goals.json").read_text())

_CYCLE_LANGUAGE = re.compile(r"cycle|reset|restart|attempt|last time|previous|start(?:ing|ed)? over|try again", re.IGNORECASE)


def _fixture_frozen():
    coaches = {}
    for coach_id, coach_name, _domain in seeder.COACHES:
        fb = dict(seeder.FALLBACK_PREDICTIONS[coach_id], generator="fallback_deterministic")
        coaches[coach_id] = {"coach_name": coach_name, "predictions": [fb]}
    return {
        "genesis": seeder.EXPERIMENT_START_DATE,
        "generated_at": "2026-07-11T18:00:00+00:00",
        "coaches": coaches,
        "hypotheses": seeder.build_hypotheses(GOALS),
    }


def _fixture_stamp(frozen, sha="a" * 64, stamped_at=None):
    return {
        "artifact": "genesis_preregistration.json",
        "genesis": frozen["genesis"],
        "algorithm": "sha256",
        "sha256": sha,
        "frozen_generated_at": frozen["generated_at"],
        "stamped_at": stamped_at or frozen["generated_at"],
        "stamp_note": "test",
        "public_artifact_url": gps.artifact_url(frozen["genesis"]),
        "public_stamp_url": gps.stamp_url(frozen["genesis"]),
        "verify": f"curl -s {gps.artifact_url(frozen['genesis'])} | shasum -a 256",
    }


def _tmp_freeze(tmp_path, monkeypatch, genesis="2026-07-19", generated_at="2026-07-18T22:00:00+00:00"):
    """Point the stamp module at a tmp frozen file + tmp stamp path."""
    frozen_p = tmp_path / "genesis_preregistration.json"
    stamp_p = tmp_path / "genesis_preregistration.sha256.json"
    frozen_p.write_text(json.dumps({"genesis": genesis, "generated_at": generated_at, "coaches": {}, "hypotheses": []}, indent=2) + "\n")
    monkeypatch.setattr(gps, "FROZEN_PATH", frozen_p)
    monkeypatch.setattr(gps, "STAMP_PATH", stamp_p)
    return frozen_p, stamp_p


# ──────────────────────────────────────────────────────────────────────────────
# 1. THE IMMUTABILITY GATE — committed frozen file vs committed stamp
# ──────────────────────────────────────────────────────────────────────────────


def test_committed_stamp_matches_frozen_artifact():
    """The CI-level write-path block: editing the frozen pre-registration after it
    was stamped reds this test. Restore the file or lose the merge."""
    assert gps.FROZEN_PATH.exists(), "frozen pre-registration missing"
    assert gps.STAMP_PATH.exists(), (
        f"no hash stamp at {gps.STAMP_PATH} — the frozen pre-registration is not content-addressed; "
        "run: python3 deploy/genesis_prereg_stamp.py"
    )
    issues = gps.verify_stamp()
    assert issues == [], f"frozen pre-registration fails its hash stamp: {issues}"
    stamp = gps.load_stamp()
    frozen = json.loads(gps.FROZEN_PATH.read_text())
    assert stamp["sha256"] == gps.compute_sha256()
    assert stamp["genesis"] == frozen["genesis"]
    assert stamp["frozen_generated_at"] == frozen["generated_at"]


def test_committed_stamp_is_honest_about_time():
    """Never backdated; when the stamp postdates the freeze the note says so."""
    stamp = gps.load_stamp()
    assert stamp is not None
    assert stamp["stamped_at"] >= stamp["frozen_generated_at"], "stamp is backdated"
    if stamp["stamped_at"][:10] != stamp["frozen_generated_at"][:10]:
        assert stamp["frozen_generated_at"] in stamp["stamp_note"]
        assert stamp["stamped_at"] in stamp["stamp_note"]


# ──────────────────────────────────────────────────────────────────────────────
# 2. Tamper detection + write-path blocks
# ──────────────────────────────────────────────────────────────────────────────


def test_verify_detects_post_stamp_edit(tmp_path, monkeypatch):
    frozen_p, _ = _tmp_freeze(tmp_path, monkeypatch)
    gps.write_stamp(now=datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc))
    assert gps.verify_stamp() == []
    # the quiet post-hoc edit this whole feature exists to catch
    edited = json.loads(frozen_p.read_text())
    edited["coaches"]["sleep_coach"] = {"coach_name": "X", "predictions": [{"claim_natural": "revised to look right"}]}
    frozen_p.write_text(json.dumps(edited, indent=2) + "\n")
    issues = gps.verify_stamp()
    assert issues and any("HASH MISMATCH" in i for i in issues)


def test_write_stamp_refuses_to_launder_a_same_genesis_edit(tmp_path, monkeypatch):
    frozen_p, _ = _tmp_freeze(tmp_path, monkeypatch)
    gps.write_stamp(now=datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc))
    frozen_p.write_text(frozen_p.read_text().replace("2026-07-18T22:00:00", "2026-07-18T22:00:01"))
    with pytest.raises(SystemExit, match="REFUSED"):
        gps.write_stamp(now=datetime(2026, 7, 19, 7, 0, tzinfo=timezone.utc))


def test_write_stamp_fresh_for_a_new_genesis(tmp_path, monkeypatch):
    """A deliberate regeneration (new genesis after a re-anchor) stamps fresh."""
    frozen_p, _ = _tmp_freeze(tmp_path, monkeypatch, genesis="2026-07-19")
    gps.write_stamp(now=datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc))
    frozen_p.write_text(
        json.dumps({"genesis": "2026-10-04", "generated_at": "2026-10-03T20:00:00+00:00", "coaches": {}, "hypotheses": []}, indent=2) + "\n"
    )
    stamp = gps.write_stamp(now=datetime(2026, 10, 3, 20, 0, 1, tzinfo=timezone.utc))
    assert stamp["genesis"] == "2026-10-04"
    assert stamp["sha256"] == gps.compute_sha256()


def test_write_stamp_idempotent_keeps_original_stamped_at(tmp_path, monkeypatch):
    _tmp_freeze(tmp_path, monkeypatch)
    first = gps.write_stamp(now=datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc))
    again = gps.write_stamp(now=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc))
    assert again["stamped_at"] == first["stamped_at"], "re-stamping an unchanged file must not re-date the stamp"


def test_write_stamp_never_backdates(tmp_path, monkeypatch):
    _tmp_freeze(tmp_path, monkeypatch, generated_at="2026-07-18T22:00:00+00:00")
    with pytest.raises(SystemExit, match="never backdated"):
        gps.write_stamp(now=datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc))


def test_seeder_main_blocks_on_tampered_freeze(tmp_path, monkeypatch):
    """The DDB write path is behind the stamp check — a tampered freeze aborts main()."""
    frozen_p, _ = _tmp_freeze(tmp_path, monkeypatch, genesis=seeder.EXPERIMENT_START_DATE)
    gps.write_stamp(now=datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc))
    frozen_p.write_text(frozen_p.read_text().replace('"coaches": {}', '"coaches": { }'))
    monkeypatch.setattr(seeder, "FROZEN_PATH", frozen_p)
    monkeypatch.setattr(sys, "argv", ["seed_genesis_preregistration.py", "--apply"])
    with pytest.raises(SystemExit, match="hash-stamp check FAILED"):
        seeder.main()


def test_s3_publish_refuses_to_overwrite_different_published_bytes(tmp_path, monkeypatch):
    """Immutable post-publish: the public copy is never overwritten with new bytes."""
    _tmp_freeze(tmp_path, monkeypatch)
    stamp = gps.write_stamp(now=datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc))

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
        gps.publish_to_s3(stamp)


# ──────────────────────────────────────────────────────────────────────────────
# 3/4. The page carries the seal — hash on the page, honest dates, clean language
# ──────────────────────────────────────────────────────────────────────────────


def test_page_carries_hash_url_and_verify_command():
    frozen = _fixture_frozen()
    sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    stamp = _fixture_stamp(frozen, sha=sha, stamped_at="2026-07-19T05:00:00+00:00")
    record = publisher.build_chronicle_record(GOALS, frozen, stamp=stamp)
    md = record["content_markdown"]
    assert sha in md, "the content hash must be printed on the page"
    assert stamp["public_artifact_url"] in md
    assert "shasum -a 256" in md, "the page must tell readers exactly how to verify"
    assert sha in record["content_html"]
    # provenance fields queryable alongside the page
    assert record["prereg_sha256"] == sha
    assert record["prereg_artifact_url"] == stamp["public_artifact_url"]
    assert record["prereg_hash_stamped_at"] == stamp["stamped_at"]
    # the seal never displaces the signature closer
    assert md.strip().endswith("*Elena Voss, the day before Day 1*")
    # presentation rule holds with the seal present
    assert not _CYCLE_LANGUAGE.findall(md)


def test_page_seal_states_both_dates_when_stamp_postdates_freeze():
    frozen = _fixture_frozen()  # generated_at 2026-07-11
    stamp = _fixture_stamp(frozen, stamped_at="2026-07-19T05:00:00+00:00")
    md = publisher.build_body_markdown(GOALS, frozen, stamp)
    assert "July 11, 2026" in md and "July 19, 2026" in md, "a stamp that postdates the freeze must state both dates"


def test_page_seal_single_date_when_stamped_at_freeze_time():
    frozen = _fixture_frozen()
    stamp = _fixture_stamp(frozen, stamped_at="2026-07-11T18:30:00+00:00")
    md = publisher.build_body_markdown(GOALS, frozen, stamp)
    assert "frozen and fingerprinted July 11, 2026" in md


def test_page_without_stamp_carries_no_seal():
    md = publisher.build_body_markdown(GOALS, _fixture_frozen())
    assert "SHA-256" not in md and "shasum" not in md


# ──────────────────────────────────────────────────────────────────────────────
# 5. Predict-the-week derives from the FROZEN targets (criterion 3)
# ──────────────────────────────────────────────────────────────────────────────


def test_predict_week_derives_from_frozen_hypothesis_specs():
    frozen = _fixture_frozen()
    stamp = _fixture_stamp(frozen)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    ch = predict_builder.build_challenge(frozen, stamp, now=now)
    keys = [m["key"] for m in ch["predict_metrics"]]
    # h1 lever (calories @ plan kcal) + h2 lever (steps @ 6000) — weight excluded
    assert keys == ["calories", "steps"]
    assert "weight" not in json.dumps(keys)
    kcal = GOALS["targets"]["nutrition"]["daily_calories_target"]
    labels = " · ".join(m["label"] for m in ch["predict_metrics"])
    assert f"{kcal:,}" in labels, "the calorie label must carry the frozen test_spec's own threshold"
    assert "6,000" in labels, "the steps label must carry the frozen test_spec's own threshold"
    # provenance: entries are placed against THE frozen record
    assert ch["prereg_sha256"] == stamp["sha256"]
    assert ch["prereg_url"] == stamp["public_artifact_url"]
    assert ch["result"] is None
    assert not _CYCLE_LANGUAGE.findall(ch["title"] + " " + labels)


def test_predict_week_id_is_current_pacific_iso_week():
    """#1198 parity: _predict_subject fails closed unless week_id == the current PT ISO week."""
    frozen = _fixture_frozen()
    stamp = _fixture_stamp(frozen)
    now = datetime(2026, 7, 19, 23, 30, tzinfo=ZoneInfo("America/Los_Angeles"))  # Sunday PT → 2026-W29
    ch = predict_builder.build_challenge(frozen, stamp, now=now)
    iso = now.isocalendar()
    assert ch["week_id"] == f"{iso[0]}-W{iso[1]:02d}"
    # and the shape _predict_subject parses: lowercase non-empty keys, labels present
    mmap = {(m.get("key") or "").strip().lower(): m.get("label") for m in ch["predict_metrics"]}
    assert mmap and all(k and v for k, v in mmap.items())


def test_predict_week_refuses_an_empty_subject():
    frozen = _fixture_frozen()
    frozen["hypotheses"] = []
    with pytest.raises(SystemExit, match="refusing to emit an empty subject"):
        predict_builder.build_challenge(frozen, _fixture_stamp(frozen))


# ──────────────────────────────────────────────────────────────────────────────
# 6. The genesis-eve email (criterion 2)
# ──────────────────────────────────────────────────────────────────────────────


def test_lock_email_carries_fingerprint_verify_and_unsubscribe():
    frozen = _fixture_frozen()
    sha = "f" * 64
    stamp = _fixture_stamp(frozen, sha=sha)
    subject, html = lock_email.build_email(stamp, frozen["genesis"], "reader+test@example.com")
    assert subject == "Predictions lock tonight — make yours"
    assert sha in html
    assert stamp["public_artifact_url"] in html
    assert "shasum -a 256" in html
    assert "/cockpit/" in html, "the CTA must point at the predict-the-week surface"
    assert "action=unsubscribe" in html and "reader%2Btest%40example.com" in html
    assert not _CYCLE_LANGUAGE.findall(re.sub(r"<[^>]+>", " ", html))


def test_lock_email_refuses_any_day_but_genesis_eve():
    genesis = "2026-07-19"
    lock_email.check_timing(date(2026, 7, 18), genesis)  # the eve — allowed
    for wrong in (date(2026, 7, 19), date(2026, 7, 17), date(2026, 7, 25)):
        with pytest.raises(SystemExit, match="genesis eve"):
            lock_email.check_timing(wrong, genesis)
