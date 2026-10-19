"""tests/test_training_charter_loader_5068.py — the charter loader's contract (#5068 / #5087, ADR-164).

Lazy, cached, fail-soft; the twin merges over the public half and is reported, never
invented; a denied S3 read is one warning line and a public-only charter, not a crash.
No live clock is read for any literal here (the cache uses time.monotonic for a TTL only).
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from training import plan_engine, training_charter as tc  # noqa: E402

_real_from_local_file = tc._from_local_file
_real_from_s3 = tc._from_s3


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No network and no owner twin from the laptop: the public file is the only channel."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(tc, "_from_local_file", lambda b: _real_from_local_file(b) if b == tc.PUBLIC_BASENAME else None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def test_absent_twin_is_public_only_and_says_so():
    c = tc.load_charter()
    assert c["public_loaded"] and c["public_source"] == "local"
    assert c["private_loaded"] is False and c["private_keys"] == []
    assert "target_picture" not in c and "appearance_brief" not in c
    assert c["version"] == tc.charter_version()


def test_the_env_twin_merges_over_the_public_half(monkeypatch):
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps({"_README": "x", "target_picture": {"waist_in": 1}, "appearance_brief": "b"}))
    tc.reset_cache()
    c = tc.load_charter()
    assert c["private_loaded"] is True and c["private_keys"] == ["appearance_brief", "target_picture"]
    assert c["target_picture"] == {"waist_in": 1} and "_README" not in c["private_keys"]
    assert tc.charter_value("target_picture.waist_in") == 1
    assert c["steps"]["floor"] == 12000, "the public half is untouched by the overlay"


def test_a_malformed_env_twin_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, "{not json")
    tc.reset_cache()
    c = tc.load_charter()
    assert c["private_loaded"] is False and c["public_loaded"] is True


def test_charter_value_defaults_and_copies():
    assert tc.charter_value("steps.target") == 15000
    assert tc.charter_value("no.such.path") is None
    assert tc.charter_value("no.such.path", default=7) == 7
    seq = tc.charter_value("split.sequence")
    seq.append("x")
    assert tc.charter_value("split.sequence")[-1] != "x", "a caller cannot mutate the cache"


def test_a_missing_public_file_is_reported_never_fabricated(monkeypatch):
    monkeypatch.setattr(tc, "_from_local_file", lambda b: None)
    tc.reset_cache()
    c = tc.load_charter()
    assert c["public_loaded"] is False and c["public_source"] == "absent"
    assert tc.charter_version() is None
    assert tc.charter_value("steps.floor") is None
    assert tc.public_view() == {}


def test_a_denied_s3_read_is_one_warning_and_fail_soft(monkeypatch, caplog):
    from botocore.exceptions import ClientError

    class _S3:
        def get_object(self, **kw):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": 403}}, "GetObject")

    monkeypatch.setitem(sys.modules, "boto3", type("boto3", (), {"client": staticmethod(lambda *a, **k: _S3())}))
    with caplog.at_level(logging.WARNING, logger=tc.__name__):
        assert _real_from_s3(tc.PRIVATE_S3_KEY) is None
    assert any("AccessDenied" in r.getMessage() for r in caplog.records), "a denial is named, not absorbed (#2655 class)"


def test_an_absent_s3_object_is_quiet(monkeypatch, caplog):
    from botocore.exceptions import ClientError

    class _S3:
        def get_object(self, **kw):
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")

    monkeypatch.setitem(sys.modules, "boto3", type("boto3", (), {"client": staticmethod(lambda *a, **k: _S3())}))
    with caplog.at_level(logging.WARNING, logger=tc.__name__):
        assert _real_from_s3(tc.PRIVATE_S3_KEY) is None
    assert not caplog.records


def test_an_absent_twin_is_cached_for_the_full_ttl_not_reprobed_per_call(monkeypatch):
    """The twin's absence is the designed state until the owner uploads it: one S3 probe per
    TTL per container, not one per plan build (review of PR #5118)."""
    probes = []
    monkeypatch.setattr(tc, "_from_s3", lambda key: probes.append(key) or None)
    tc.reset_cache()
    tc.load_charter()
    tc.load_charter()
    tc.charter_value("steps.floor")
    assert probes == [tc.PRIVATE_S3_KEY], probes
    assert tc._cache is not None and tc._cache_ttl == tc._CACHE_TTL_SECONDS


def test_a_missing_public_half_is_reprobed_quickly(monkeypatch):
    monkeypatch.setattr(tc, "_from_local_file", lambda b: None)
    tc.reset_cache()
    tc.load_charter()
    assert tc._cache is not None and tc._cache_ttl == tc._MISS_TTL_SECONDS


def test_a_denied_s3_read_warns_once_per_container_then_debug(monkeypatch, caplog):
    from botocore.exceptions import ClientError

    class _S3:
        def get_object(self, **kw):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": 403}}, "GetObject")

    monkeypatch.setitem(sys.modules, "boto3", type("boto3", (), {"client": staticmethod(lambda *a, **k: _S3())}))
    with caplog.at_level(logging.DEBUG, logger=tc.__name__):
        assert _real_from_s3(tc.PRIVATE_S3_KEY) is None
        assert _real_from_s3(tc.PRIVATE_S3_KEY) is None
        assert _real_from_s3(tc.PUBLIC_S3_KEY) is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2 and {tc.PRIVATE_S3_KEY in r.getMessage() for r in warnings} == {True, False}, [
        r.getMessage() for r in warnings
    ]
    assert sum(1 for r in caplog.records if r.levelno == logging.DEBUG) == 1
    tc.reset_cache()
    with caplog.at_level(logging.WARNING, logger=tc.__name__):
        caplog.clear()
        assert _real_from_s3(tc.PRIVATE_S3_KEY) is None
    assert len(caplog.records) == 1, "reset_cache() forgets the once-per-container set (a new container warns again)"


def test_the_import_path_reads_nothing(monkeypatch):
    """#3675 inertness: importing the loader opens no file and no channel."""
    import importlib

    opened = []
    monkeypatch.setattr("builtins.open", lambda *a, **k: opened.append(a[0]) or (_ for _ in ()).throw(OSError("no reads at import")))
    importlib.reload(tc)
    assert tc._cache is None and opened == []
    monkeypatch.undo()
    tc.reset_cache()


def test_plan_engine_stamps_the_charter_version():
    block = plan_engine.constraint_block(
        date="2026-09-14",
        weight_lb=319.7,
        walk_hr_wk_now=1.14,
        recovery_tier="yellow",
        acwr_flag="safe",
        muscle_volume={"quads": 8, "chest": 6},
        days_since_movement={"squat": 3, "bench": 1},
        reference={
            "proven_target": {"band": "310-319", "band_distance_lb": 1, "n_effective": 4.0, "evidence_tier": "low", "volume_citable": False}
        },
        protein_days_missed_7d=1,
        readiness_low_streak_days=0,
        anchor_lift_drop_pct=2.0,
        anchor_lift_drop_sessions=1,
        pain_flag_sites=[],
        pain_layer_status="ok",
        weight_stall_days=3,
        adherence_on_plan=True,
    )
    assert (
        block["charter_version"] == tc.charter_version() == json.loads((_REPO / "config" / "training_charter.json").read_text())["version"]
    )


def test_the_cache_bookkeeping_never_reaches_a_caller():
    """C1 review nit (#5084): the TTL used to ride the cached object as `_ttl` and came back
    from load_charter(). It is module state now; no `_`-prefixed key but the file's own note."""
    c = tc.load_charter()
    assert "_ttl" not in c
    assert not [k for k in c if k.startswith("_") and k != "_README"], sorted(c)


def test_public_view_reads_through_the_cache(monkeypatch):
    """C1 review nit (#5084): public_view() called _load_public() directly, re-reading the file on
    every call. It reads the cached public half now: one public read per TTL, whoever asks."""
    reads = []
    monkeypatch.setattr(
        tc, "_from_local_file", lambda b: reads.append(b) or (_real_from_local_file(b) if b == tc.PUBLIC_BASENAME else None)
    )
    tc.reset_cache()
    tc.load_charter()
    tc.public_view()
    tc.public_view()
    tc.prompt_prefix(published=True)
    tc.prompt_prefix(published=False)
    assert reads.count(tc.PUBLIC_BASENAME) == 1, reads


def test_public_view_never_carries_a_twin_key_that_shadows_a_public_one(monkeypatch):
    """Routing public_view() through the MERGED cache must not let the twin in: it reads the
    cached PUBLIC half, so a twin that overrides a whitelisted public key changes nothing."""
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps({"steps": {"floor": 1, "target": 2}}))
    tc.reset_cache()
    assert tc.load_charter()["steps"]["floor"] == 1, "the merged view takes the twin (that is its contract)"
    assert tc.public_view()["steps"]["floor"] == 12000
