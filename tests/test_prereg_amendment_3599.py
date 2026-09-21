"""#3599 box 3, second half — "a wrong seal already published gets a visible amendment
record, never an edit".

THE SPECIMENS ARE BOTH LIVE, PUBLISHED SEALS
────────────────────────────────────────────
`tests/fixtures/prereg_cycle16_2026-09-05.json` and `prereg_cycle17_2026-09-06.json`
are byte-identical to what the public prereg route serves today (curled 2026-09-20;
each fixture's sha256 is asserted against its committed stamp below, so neither can
quietly become synthetic).

Two things the issue's own framing got wrong, both measured here rather than argued:

  1. THE CYCLE-16 ARTIFACT IS NOT GONE. `s3://matthew-life-platform/generated/
     experiments/prereg/genesis-2026-09-05.json` is live and hash-verifying today, as
     are six older seals. A pre-seal gate protects the NEXT freeze; the amendment
     record is the only instrument that can reach these eight.
  2. "FAILS ON TWO COUNTS" IS RIGHT ONLY IF THE COMPARAND IS. Judged against today's
     constants the cycle-16 seal reports 7 blocking findings, three of them
     BASELINE_MISMATCH against 327.34. But `git show` on `lambdas/common/constants.py`
     says EXPERIMENT_BASELINE_WEIGHT_LBS WAS 324.64 for the whole of cycle 16 (set by
     the 2026-09-03 re-anchor, replaced by the 2026-09-05 one) — exactly what that
     artifact asserts. Judged at the facts in force when it was minted it reports 4,
     and the baseline clause is silent. An amendment built from the wrong comparand
     would publish a FALSE correction in the name of honesty, which is why
     `facts_in_force()` refuses a prior cycle rather than substituting today's numbers.

Cycle 17 is the amendable case and its baseline finding is real: the seal was minted
2026-09-06T02:13Z asserting a 326.2 lb start, and #3649 superseded that override with
the Day-1 weigh-in of 327.34 at 12:55 PT the same day. The sealed bytes and the served
site have disagreed about the cycle's starting weight ever since.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "deploy"), str(REPO / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import prereg_amendment as amend  # noqa: E402
import prereg_truth_gate as gate  # noqa: E402

FIX = REPO / "tests" / "fixtures"
CYCLE16 = FIX / "prereg_cycle16_2026-09-05.json"
CYCLE16_STAMP = FIX / "prereg_cycle16_2026-09-05.stamp.json"
CYCLE17 = FIX / "prereg_cycle17_2026-09-06.json"
CYCLE17_STAMP = REPO / "deploy" / "generated" / "genesis_preregistration.sha256.json"

#: The baseline constant in force for the whole of cycle 16 — read from git history
#: (`git show 17de015f0 -- lambdas/common/constants.py`), not from the artifact it is
#: used to judge.
CYCLE16_BASELINE_LBS = 324.64

#: Measured 2026-09-20 over the published cycle-16 bytes at the facts in force then.
CYCLE16_VERDICT_AT_ITS_OWN_FACTS = {
    gate.COACH_NOT_OPERATIONAL: 1,
    gate.COACH_NAME_MISMATCH: 1,
    gate.MIN_EFFECT_UNDERIVED: 2,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def c17_stamp() -> dict:
    return json.loads(CYCLE17_STAMP.read_text())


@pytest.fixture(scope="module")
def c17_bytes() -> bytes:
    return CYCLE17.read_bytes()


@pytest.fixture(scope="module")
def current_facts() -> dict:
    from common.constants import EXPERIMENT_START_DATE

    return amend.facts_in_force(str(EXPERIMENT_START_DATE))


@pytest.fixture()
def record(c17_bytes, c17_stamp, current_facts) -> dict:
    findings = amend.standing_findings(json.loads(c17_bytes), current_facts)
    return amend.build_amendment(
        c17_bytes,
        c17_stamp,
        findings,
        current_facts,
        author="matthew",
        reason="the sealed start weight was superseded by the Day-1 weigh-in (#3649)",
    )


class _FakeS3:
    """Records every call. A publish test that used a real client would be a deploy."""

    def __init__(self, existing: bytes | None = None):
        self.existing = existing
        self.puts: list[dict] = []

    def get_object(self, Bucket, Key):
        if self.existing is None:
            raise RuntimeError("NoSuchKey")

        class _B:
            def __init__(self, b):
                self._b = b

            def read(self):
                return self._b

        return {"Body": _B(self.existing)}

    def put_object(self, **kw):
        self.puts.append(kw)
        return {}


# ── the specimens are the published seals ────────────────────────────────────


def test_both_specimens_are_the_published_seals_byte_for_byte():
    assert _sha(CYCLE16) == json.loads(CYCLE16_STAMP.read_text())["sha256"]
    assert _sha(CYCLE17) == json.loads(CYCLE17_STAMP.read_text())["sha256"]


def test_the_cycle16_seal_still_exists_and_still_fails_at_todays_constants():
    """The issue's own positive control, and the reason an amendment is needed at all:
    that artifact was not superseded out of existence — it is still served."""
    people, retired = gate.repo_coach_bylines()
    findings = gate.audit_prereg_truth(
        json.loads(CYCLE16.read_text()), baseline_lbs=gate.repo_baseline_lbs(), coach_bylines=people, retired_ids=retired
    )
    assert gate.summarize(findings)[gate.COACH_NOT_OPERATIONAL] == 1
    assert len(gate.blocking(findings)) == 7


def test_the_cycle16_baseline_finding_is_a_comparand_artifact_not_a_defect():
    """At the baseline that was in force when it was minted, the clause is silent —
    and the OTHER findings survive, so this is not a blanket exoneration."""
    people, retired = gate.repo_coach_bylines()
    findings = gate.audit_prereg_truth(
        json.loads(CYCLE16.read_text()), baseline_lbs=CYCLE16_BASELINE_LBS, coach_bylines=people, retired_ids=retired
    )
    assert gate.summarize(findings) == CYCLE16_VERDICT_AT_ITS_OWN_FACTS
    assert gate.BASELINE_MISMATCH not in gate.summarize(findings)


# ── facts_in_force: the refusal that keeps an amendment from being a false one ─


def test_a_prior_cycles_seal_refuses_to_be_judged_at_todays_constants():
    with pytest.raises(amend.FactsNotInForce) as e:
        amend.facts_in_force("2026-09-05")
    assert "not the current cycle" in str(e.value)


def test_a_prior_cycle_still_refuses_when_only_half_the_facts_are_supplied():
    with pytest.raises(amend.FactsNotInForce):
        amend.facts_in_force("2026-09-05", baseline_lbs=CYCLE16_BASELINE_LBS)
    with pytest.raises(amend.FactsNotInForce):
        amend.facts_in_force("2026-09-05", coach_bylines={"sleep_coach": "Dr. Lisa Park"})


def test_supplied_facts_are_used_verbatim_and_say_so():
    facts = amend.facts_in_force("2026-09-05", baseline_lbs=CYCLE16_BASELINE_LBS, coach_bylines={"sleep_coach": "Dr. Lisa Park"})
    assert facts["baseline_weight_lbs"] == CYCLE16_BASELINE_LBS
    assert facts["operational_coaches"] == {"sleep_coach": "Dr. Lisa Park"}
    assert facts["basis"] == "supplied-for-a-prior-cycle"


def test_the_current_genesis_resolves_from_the_repo_not_a_hand_number(current_facts):
    assert current_facts["baseline_weight_lbs"] == gate.repo_baseline_lbs()
    assert current_facts["operational_coaches"] == gate.repo_coach_bylines()[0]
    assert current_facts["basis"] == "repo-constants-at-current-genesis"


def test_an_empty_roster_refuses_rather_than_vouching_for_nothing():
    with pytest.raises(amend.FactsNotInForce):
        amend.facts_in_force("2026-09-05", baseline_lbs=1.0, coach_bylines={})


# ── the record shape ─────────────────────────────────────────────────────────


def test_the_record_over_the_live_cycle17_seal_validates(record, c17_bytes):
    assert amend.validate_amendment(record, artifact_bytes=c17_bytes) == []
    assert record["amends"]["sha256"] == _sha(CYCLE17)
    assert record["amendment_id"] == "genesis-2026-09-06/A1"


def test_the_record_carries_the_superseded_baseline_correction(record):
    corrections = [c for c in record["corrections"] if c["kind"] == gate.BASELINE_MISMATCH]
    assert corrections, "the #3649 supersession is the live amendable defect"
    assert all(c["correct_value"] == f"{gate.repo_baseline_lbs()} lbs" for c in corrections)


def test_a_record_that_names_other_bytes_is_refused(record, c17_bytes):
    problems = amend.validate_amendment(record, artifact_bytes=CYCLE16.read_bytes())
    assert any("is not the sha256 of the artifact handed in" in p for p in problems)
    assert amend.validate_amendment(record, artifact_bytes=c17_bytes) == []


@pytest.mark.parametrize("key", amend.FORBIDDEN_PAYLOAD_KEYS)
def test_a_record_carrying_an_artifact_payload_is_a_replacement_not_an_amendment(record, c17_bytes, key):
    record = {**record, key: {"sleep_coach": {}}}
    assert any("replacement pre-registration" in p for p in amend.validate_amendment(record, artifact_bytes=c17_bytes))


def test_a_backdated_record_is_refused(record, c17_bytes):
    earlier = (datetime.fromisoformat(record["amends"]["stamped_at"]) - timedelta(seconds=1)).isoformat()
    record = {**record, "authored_at": earlier}
    assert any("predates the seal it amends" in p for p in amend.validate_amendment(record, artifact_bytes=c17_bytes))


def test_a_record_with_no_corrections_is_refused(record, c17_bytes):
    record = {**record, "corrections": []}
    assert any("nothing to correct" in p for p in amend.validate_amendment(record, artifact_bytes=c17_bytes))


def test_a_correction_kind_outside_the_gates_set_is_refused(record, c17_bytes):
    """Guard the SET: a new truth-gate clause cannot reach the public record as an
    unlabelled correction."""
    record = {**record, "corrections": [{**record["corrections"][0], "kind": "VIBES_MISMATCH"}]}
    assert any("outside the gate's finding kinds" in p for p in amend.validate_amendment(record, artifact_bytes=c17_bytes))


def test_a_correction_silent_on_both_the_value_and_the_reason_is_refused(record, c17_bytes):
    mute = {**record["corrections"][0], "correct_value": None, "correction_unknown_reason": None}
    record = {**record, "corrections": [mute]}
    assert any("neither a corrected value nor why there is none" in p for p in amend.validate_amendment(record, artifact_bytes=c17_bytes))


@pytest.mark.parametrize("kind", gate.FINDING_KINDS)
def test_every_finding_kind_the_gate_can_emit_has_a_correction_shape(kind, current_facts):
    """The two sets are wired, not merely adjacent — a kind added to the gate with no
    amendment shape would produce a correction that says nothing."""
    finding = gate.Finding(kind, "coaches.physical_coach", "detail")
    entry = amend.correction_for(finding, current_facts)
    assert entry["correct_value"] or entry["correction_unknown_reason"]


# ── the ledger appends, it never rewrites ────────────────────────────────────


def test_the_ledger_preserves_every_earlier_entry(record):
    first = {**record, "amendment_id": "genesis-2026-09-06/A1", "sequence": 1}
    ledger = amend.append_to_ledger(None, first)
    assert ledger["amendments"] == [first]
    second = {**record, "amendment_id": "genesis-2026-09-06/A2", "sequence": 2}
    grown = amend.append_to_ledger(ledger, second)
    assert grown["amendments"] == [first, second]
    assert grown["record_type"] == amend.LEDGER_TYPE


def test_a_second_record_built_against_a_stale_ledger_is_refused(record, c17_bytes):
    prior = [{**record, "amendment_id": "genesis-2026-09-06/A1", "sequence": 1}]
    problems = amend.validate_amendment(record, artifact_bytes=c17_bytes, prior=prior)
    assert any("the ledger appends, it never rewrites" in p for p in problems)
    assert any("already exists in the ledger" in p for p in problems)


def test_publish_writes_the_amendment_key_and_never_the_artifact(record, c17_bytes):
    s3 = _FakeS3()
    ledger = amend.publish(record, c17_bytes, s3=s3)
    assert len(s3.puts) == 1
    put = s3.puts[0]
    assert put["Key"] == "generated/experiments/prereg/genesis-2026-09-06.amendments.json"
    assert put["Bucket"] == amend.S3_BUCKET
    assert json.loads(put["Body"])["amendments"] == ledger["amendments"] == [record]
    assert all("genesis-2026-09-06.json" != p["Key"].rsplit("/", 1)[-1] for p in s3.puts)


def test_publish_appends_to_a_live_ledger_rather_than_replacing_it(record, c17_bytes):
    first = {**record, "amendment_id": "genesis-2026-09-06/A1", "sequence": 1}
    s3 = _FakeS3(existing=json.dumps(amend.append_to_ledger(None, first)).encode())
    second = {**record, "amendment_id": "genesis-2026-09-06/A2", "sequence": 2}
    ledger = amend.publish(second, c17_bytes, s3=s3)
    assert [a["amendment_id"] for a in ledger["amendments"]] == ["genesis-2026-09-06/A1", "genesis-2026-09-06/A2"]


def test_publish_refuses_a_record_that_would_overwrite_a_published_entry(record, c17_bytes):
    first = {**record, "amendment_id": "genesis-2026-09-06/A1", "sequence": 1}
    s3 = _FakeS3(existing=json.dumps(amend.append_to_ledger(None, first)).encode())
    with pytest.raises(SystemExit) as e:
        amend.publish({**first}, c17_bytes, s3=s3)
    assert "not a publishable amendment" in str(e.value)
    assert s3.puts == [], "a refused publish writes nothing"


def test_publish_refuses_a_record_about_different_bytes(record):
    s3 = _FakeS3()
    with pytest.raises(SystemExit):
        amend.publish(record, CYCLE16.read_bytes(), s3=s3)
    assert s3.puts == []


# ── the reader surface reads the same key the publisher writes ───────────────


def test_the_site_api_reads_the_key_the_publisher_writes():
    """The #1980 stamp-key parity rule, extended to the amendment ledger: deploy/ is
    never in the lambda bundle, so the two literals cannot be shared — they are pinned
    equal instead."""
    from web.site_api_common import _prereg_amendment_key

    assert _prereg_amendment_key("2026-09-06") == amend.amendment_key("2026-09-06")


def test_the_reader_summarises_a_published_ledger(record, monkeypatch):
    from web import site_api_common as common

    ledger = amend.append_to_ledger(None, record)
    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: ledger)
    served = common.prereg_amendments("2026-09-06")
    assert [a["amendment_id"] for a in served] == [record["amendment_id"]]
    kinds = {c["kind"] for c in served[0]["corrections"]}
    assert kinds == set(gate.summarize(amend.standing_findings(json.loads(CYCLE17.read_text()), amend.facts_in_force("2026-09-06"))))
    assert all(c["correct_value"] for c in served[0]["corrections"]), "every served correction says what is true instead"


def test_the_reader_never_serves_the_sealed_bytes_back(record, monkeypatch):
    """An amendment is a correction, not a second artifact — even if a malformed
    record smuggled one in, the served shape cannot carry it."""
    from web import site_api_common as common

    smuggled = {**record, "coaches": {"sleep_coach": {"coach_name": "x"}}, "hypotheses": [{"id": "h1"}]}
    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: amend.append_to_ledger(None, smuggled))
    served = common.prereg_amendments("2026-09-06")
    assert set(served[0]) == {"amendment_id", "authored_at", "reason", "corrections"}


def test_an_absent_or_unreadable_ledger_is_honest_empty(monkeypatch):
    from web import site_api_common as common

    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: {})
    assert common.prereg_amendments("2026-09-06") == []
    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: {"amendments": "not-a-list"})
    assert common.prereg_amendments("2026-09-06") == []


def test_the_seal_block_carries_no_amendment_keys_until_one_is_published(monkeypatch):
    """The normal state: nothing amended, nothing added to the #1980 seal block."""
    from web import site_api_common as common

    common._prereg_seal_cache = None
    common._prereg_seal_attempted = False
    stamp = json.loads(CYCLE17_STAMP.read_text())
    monkeypatch.setattr(common, "EXPERIMENT_START", stamp["genesis"])
    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: stamp if key.endswith(".sha256.json") else {})
    seal = common.prereg_seal_meta()
    common._prereg_seal_cache = None
    common._prereg_seal_attempted = False
    assert seal["sha256"] == stamp["sha256"]
    assert "amendments" not in seal and "amendments_url" not in seal


def test_a_published_amendment_travels_with_the_seal(record, monkeypatch):
    from web import site_api_common as common

    common._prereg_seal_cache = None
    common._prereg_seal_attempted = False
    stamp = json.loads(CYCLE17_STAMP.read_text())
    ledger = amend.append_to_ledger(None, record)
    monkeypatch.setattr(common, "EXPERIMENT_START", stamp["genesis"])
    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: stamp if key.endswith(".sha256.json") else ledger)
    seal = common.prereg_seal_meta()
    common._prereg_seal_cache = None
    common._prereg_seal_attempted = False
    assert seal["amendments"][0]["amendment_id"] == record["amendment_id"]
    assert seal["amendments_url"] == "https://averagejoematt.com/experiments/prereg/genesis-2026-09-06.amendments.json"
    assert seal["sha256"] == stamp["sha256"], "the seal's own hash is untouched by an amendment"
