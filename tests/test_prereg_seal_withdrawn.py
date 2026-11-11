"""tests/test_prereg_seal_withdrawn.py — owner ruling 2026-11-11, item 3: no surface claims the seal can be checked
while the file served at the sealed address does not hash to it.

The cycle-17 pre-registration (genesis 2026-09-06) was sealed with a published SHA-256. On 2026-11-10 the served file
became a placeholder because the original carries two calls the owner ruled private. The original is kept privately and
unchanged; it is not republished, and nothing is re-hashed or presented as the seal. These tests pin:

  1. the withdrawal record (lambdas/web/prereg_seal_state.py) to the committed stamp — same digest, the right call
     counts (with the private original, tests/sealed_prereg.py) — that it carries no call's wording, and that no
     tracked file is the sealed (private) file;
  2. the Site API (``prereg_seal_meta``): the verify command and file link only when the served bytes match;
     otherwise the digest, the stamp link and the reason — for a placeholder, an unreadable file, and an unregistered
     mismatch;
  3. the snapshot producer (``guard_seal`` / ``live_calibration``): it re-checks the served file itself, fails closed
     on any fetch failure or foreign origin, and never trusts a served ``verify``;
  4. the published www fixture is in the unverifiable shape (the page built from it offers no check; the dist half is
     www/tests/prereg_seal.test.mjs).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

REPO = Path(__file__).resolve().parent.parent
for p in (str(REPO / "lambdas"), str(REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import publish_snapshot_calibration as producer  # noqa: E402
import sealed_prereg  # noqa: E402
from web import (
    prereg_seal_state as rule,  # noqa: E402
    site_api_common as common,  # noqa: E402
)

GENESIS = "2026-09-06"
STAMP = json.loads((REPO / "deploy" / "generated" / "genesis_preregistration.sha256.json").read_text())
PLACEHOLDER = b'{"tombstone": true}'
# The sealed bytes are private since 2026-11-11 (tests/sealed_prereg.py). The "served file matches" cases use a
# synthetic file and a stamp naming ITS digest — never the cycle-17 seal.
SYNTHETIC_BODY = b'{"genesis": "2099-01-01", "synthetic": true}'
SYNTHETIC_STAMP = dict(STAMP, genesis="2099-01-01", sha256=hashlib.sha256(SYNTHETIC_BODY).hexdigest())


def _gps():
    spec = importlib.util.spec_from_file_location("_gps_withdrawn", REPO / "deploy" / "genesis_prereg_stamp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 1. the withdrawal record ---------------------------------------------------------------------------------------------


def test_the_withdrawal_names_the_published_digest():
    w = rule.WITHDRAWN[GENESIS]
    assert STAMP["genesis"] == GENESIS
    assert w["sha256"] == STAMP["sha256"] == sealed_prereg.SEALED_SHA256, "the withdrawal describes the published seal"


def test_the_repo_no_longer_carries_the_sealed_file():
    """Owner ruling 2026-11-11: the sealed file carries withdrawn calls, so neither of the directories where copies of
    it lived (the frozen artifacts and the test fixtures) may hold its bytes again, under any name."""
    hits = []
    for d in (REPO / "deploy" / "generated", REPO / "tests" / "fixtures"):
        for p in d.iterdir():
            if p.is_file() and p.stat().st_size == 11578 and hashlib.sha256(p.read_bytes()).hexdigest() == STAMP["sha256"]:
                hits.append(str(p.relative_to(REPO)))
    assert hits == [], f"the sealed (private) file is in the repo tree again: {hits}"


def test_the_withdrawal_counts_match_the_sealed_file_and_the_words():
    w = rule.WITHDRAWN[GENESIS]
    sealed = json.loads(sealed_prereg.require_sealed_path().read_text())
    total = sum(len(c["predictions"]) for c in sealed["coaches"].values())
    assert w["calls_total"] == total == 16
    assert 0 < w["calls_withdrawn"] < total
    words = {2: "two", 16: "sixteen"}
    assert f"{words[w['calls_withdrawn']]} of its {words[w['calls_total']]} calls" in w["text"]


def test_the_withdrawal_text_carries_no_call_wording():
    text = rule.WITHDRAWN[GENESIS]["text"].lower()
    for claim in sealed_prereg.sealed_call_texts():  # every call with the private original; the approved ones without
        claim = claim.lower()
        for i in range(0, max(1, len(claim) - 24)):
            assert claim[i : i + 24] not in text


def test_artifact_key_parity_with_the_publisher():
    gps = _gps()
    for g in (GENESIS, "2027-01-04"):
        assert common._prereg_artifact_key(g) == gps.artifact_key(g)


# 2. the Site API ------------------------------------------------------------------------------------------------------


def _meta(monkeypatch, served, stamp=STAMP):
    monkeypatch.setattr(common, "_prereg_seal_cache", None)
    monkeypatch.setattr(common, "_prereg_seal_attempted", False)
    monkeypatch.setattr(common, "EXPERIMENT_START", stamp["genesis"])
    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: dict(stamp) if key.endswith(".sha256.json") else {})
    seen = []

    def _bytes(key, name):
        seen.append(key)
        return served

    monkeypatch.setattr(common, "_load_s3_bytes", _bytes)
    seal = common.prereg_seal_meta()
    assert seen == [f"generated/experiments/prereg/genesis-{stamp['genesis']}.json"], "the hash is taken over the served file"
    return seal


@pytest.mark.parametrize("served", [PLACEHOLDER, None], ids=["placeholder", "unreadable"])
def test_api_offers_no_check_when_the_served_file_does_not_match(monkeypatch, served):
    seal = _meta(monkeypatch, served)
    assert seal["verifiable"] is False
    assert "verify" not in seal and "artifact_url" not in seal
    assert seal["sha256"] == STAMP["sha256"], "the digest stays published"
    assert seal["stamp_url"] == STAMP["public_stamp_url"]
    assert seal["unverifiable_text"] == rule.WITHDRAWN[GENESIS]["text"]


def test_api_offers_the_check_when_the_served_file_matches(monkeypatch):
    seal = _meta(monkeypatch, SYNTHETIC_BODY, SYNTHETIC_STAMP)
    assert seal["verifiable"] is True
    assert seal["verify"] == STAMP["verify"] and seal["artifact_url"] == STAMP["public_artifact_url"]
    assert "unverifiable_text" not in seal


def test_an_unregistered_mismatch_gets_the_generic_reason():
    ok, text = rule.assess("2099-01-01", "ab" * 32, b"anything")
    assert ok is False and text == rule.GENERIC_TEXT
    ok, text = rule.assess(GENESIS, "ab" * 32, PLACEHOLDER)
    assert ok is False and text == rule.GENERIC_TEXT, "the withdrawal explains only the digest it names"


# 3. the snapshot producer ---------------------------------------------------------------------------------------------

SERVED_SEAL = {
    "genesis": GENESIS,
    "sha256": STAMP["sha256"],
    "artifact_url": STAMP["public_artifact_url"],
    "stamp_url": STAMP["public_stamp_url"],
    "verify": STAMP["verify"],
    "stamped_at": STAMP["stamped_at"],
}


def _raise(url):
    raise OSError("unreachable")


@pytest.mark.parametrize(
    "get_bytes",
    [lambda u: PLACEHOLDER, _raise, None],
    ids=["placeholder", "fetch-fails", "no-fetcher"],
)
def test_producer_strips_the_check_when_the_served_file_does_not_match(get_bytes):
    out = producer.guard_seal(dict(SERVED_SEAL), get_bytes, log=lambda m: None)
    assert out["verifiable"] is False
    assert "verify" not in out and "artifact_url" not in out
    assert out["sha256"] == STAMP["sha256"] and out["unverifiable_text"] == rule.WITHDRAWN[GENESIS]["text"]


def test_producer_never_fetches_off_the_site_origin():
    fetched = []
    seal = dict(SERVED_SEAL, artifact_url="https://example.com/genesis.json")
    out = producer.guard_seal(seal, lambda u: fetched.append(u) or PLACEHOLDER, log=lambda m: None)
    assert fetched == [] and out["verifiable"] is False


def test_producer_keeps_the_check_when_the_served_file_matches():
    seal = dict(SERVED_SEAL, genesis=SYNTHETIC_STAMP["genesis"], sha256=SYNTHETIC_STAMP["sha256"])
    out = producer.guard_seal(seal, lambda u: SYNTHETIC_BODY, log=lambda m: None)
    assert out["verifiable"] is True and out["verify"] == STAMP["verify"]


def test_producer_does_not_trust_a_served_verifiable_flag():
    out = producer.guard_seal(dict(SERVED_SEAL, verifiable=True), lambda u: PLACEHOLDER, log=lambda m: None)
    assert out["verifiable"] is False and "verify" not in out


def test_live_calibration_applies_the_guard():
    payloads = {
        producer.CALIBRATION_PATH: {"coaches": [], "prereg_seal": dict(SERVED_SEAL)},
        producer.PREDICTIONS_PATH: {"overall": {"decided": 0, "confirmed": 0}},
    }
    out = producer.live_calibration(payloads.__getitem__, lambda m: None, get_bytes=lambda u: PLACEHOLDER)
    seal = out["calibration"]["prereg_seal"]
    assert seal["verifiable"] is False and "verify" not in seal


# 4. the published fixture ---------------------------------------------------------------------------------------------


def test_the_www_fixture_seal_is_in_the_unverifiable_shape():
    fx = json.loads((REPO / "www" / "content" / "fixtures" / "calibration.json").read_text())
    seal = fx["calibration"]["prereg_seal"]
    assert seal["verifiable"] is False
    assert "verify" not in seal and "artifact_url" not in seal
    assert seal["unverifiable_text"] == rule.WITHDRAWN[GENESIS]["text"]
