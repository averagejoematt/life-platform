"""tests/test_narrative_allowlist_cr2.py — the owner-approved historical coach words for CR2 (owner ruling 2026-11-09, D).

What is pinned:
  * DARK: the CR2 switch is off on main and no Lambda enters the CR2 scope, so every live surface reads the
    approved rows exactly as before (withheld);
  * THE SET: 35 entries (21 lead reads, 14 sealed calls), keys and hashes only, public families only; every sealed
    call's hash is the hash of a claim in the frozen pre-registration artifact, and every sealed call is public
    under the live call registry; no excluded day is listed;
  * FAIL CLOSED: with the switch on and inside the scope, an approved, unchanged, unrecorded row is served; a row
    not on the list (negative control), a listed row carrying a private-family record, a listed row whose words
    changed, and a listed row whose words name private activity all stay withheld.

The lead reads' words are private until CR2 ships, so their gate tests use a synthetic entry; the sealed calls'
words are already public in ``deploy/generated/genesis_preregistration.json``, so those tests use the real entries.
"""

# premerge-gate: CR2 historical words (owner 2026-11-09 D): reads the frozen pre-registration artifact and rglobs lambdas/ for a route opening the CR2 scope — a diff that regenerates the artifact or wires a route must red before merge, not after.
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from common import (
    narrative_allowlist as NA,  # noqa: E402
    narrative_provenance as NP,  # noqa: E402
    prediction_publication as PP,  # noqa: E402
    prediction_publication_registry as REG,  # noqa: E402
)
from web import narrative_publication as G  # noqa: E402

PREREG = json.loads((ROOT / "deploy" / "generated" / "genesis_preregistration.json").read_text())
SEALED = {p["claim_natural"] for c in PREREG["coaches"].values() for p in c["predictions"]}
EXCLUDED_LEAD_DAYS = {"2026-10-02", "2026-10-07", "2026-10-17", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"}


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sealed_row(entry: NA.Entry) -> dict:
    claim = next(c for c in SEALED if _sha(c) == entry.text_sha256)
    return {"pk": entry.pk, "sk": entry.sk, "claim_natural": claim, "status": "refuted", "prediction_id": entry.sk[len("PREDICTION#") :]}


@pytest.fixture
def cr2_on(monkeypatch):
    monkeypatch.setattr(NA, "CR2_PUBLIC", True)


def _calls():
    return [e for e in NA.APPROVED if e.sk.startswith("PREDICTION#")]


def _leads():
    return [e for e in NA.APPROVED if e.sk.startswith("LEAD_DAILY#")]


# ── dark ─────────────────────────────────────────────────────────────────────────────────────


def test_the_cr2_switch_is_off_on_main():
    assert NA.CR2_PUBLIC is False, "flipping CR2_PUBLIC is the CR2 release — the owner's GO, not a routine change"
    assert not NA.active()
    with NA.serving(NA.SCOPE_CR2):
        assert not NA.active()


def test_no_lambda_enters_the_cr2_scope_yet():
    """No route serves the approved words while CR2 is dark: nothing outside the module opens the scope."""
    hits = []
    for p in (ROOT / "lambdas").rglob("*.py"):
        if p.name == "narrative_allowlist.py":
            continue
        if re.search(r"\bserving\(\s*(?:NA\.)?SCOPE_CR2|narrative_allowlist\.serving\(|NA\.serving\(", p.read_text()):
            hits.append(str(p.relative_to(ROOT)))
    assert hits == []


# ── the set ──────────────────────────────────────────────────────────────────────────────────


def test_the_approved_set_is_keys_and_hashes_with_public_families():
    assert len(NA.APPROVED) == 35 and len(_leads()) == 21 and len(_calls()) == 14
    assert len(NA.INDEX) == len(NA.APPROVED), "a duplicated key"
    for e in NA.APPROVED:
        assert re.fullmatch(r"[0-9a-f]{64}", e.text_sha256), e
        assert all(NP.classify(f) == NP.PUBLIC for f in e.families), e
    for e in _leads():
        assert e.pk == "COACH#eli_marsh" and e.field == "text"
        assert e.families == NA.DERIVED_FROM_CITED, "a lead read's families come from its own cited block, never a list"
        day = e.sk.split("#", 1)[1]
        assert "2026-10-01" <= day <= "2026-11-03" and day not in EXCLUDED_LEAD_DAYS, e.sk
    for e in _calls():
        assert e.field == "claim_natural" and e.sk.startswith("PREDICTION#pred_20260906_"), e
        assert NP.is_publishable({"v": NP.SCHEMA_VERSION, "families": list(e.families)}), e
        assert set(e.families) == {"experiments", "persona"}, e


def test_every_sealed_call_is_the_sealed_artifacts_words_and_public_in_the_live_registry():
    """Derivation guard: the hash is of a frozen pre-registration claim, and the live call policy lists the call
    public (the two the owner's 2026-11-09 ruling keeps private are not on the list)."""
    sealed_hashes = {_sha(c) for c in SEALED}
    for e in _calls():
        assert e.text_sha256 in sealed_hashes, e.sk
        assert PP.digest(e.pk, e.sk[len("PREDICTION#") :]) in REG.PUBLIC_DIGESTS, e.sk
        assert PP.classify_call(e.pk, _sealed_row(e)) == (PP.PUBLIC, "registry"), e.sk


def test_the_module_carries_no_coach_words():
    src = (ROOT / "lambdas" / "common" / "narrative_allowlist.py").read_text()
    body = re.sub(r'"(?:COACH#|PREDICTION#|LEAD_DAILY#)[^"]*"', '""', src)  # record keys are allowed
    words = re.sub(r"[^a-z0-9]+", " ", body.lower()).split()
    runs = {" ".join(words[i : i + 8]) for i in range(len(words) - 7)}
    for claim in SEALED:
        cw = re.sub(r"[^a-z0-9]+", " ", claim.lower()).split()
        assert not any(" ".join(cw[i : i + 8]) in runs for i in range(len(cw) - 7)), claim[:40]


# ── the gate ─────────────────────────────────────────────────────────────────────────────────


def test_switch_off_an_approved_call_stays_withheld_in_every_scope():
    row = _sealed_row(_calls()[0])
    for scope in (None, NA.SCOPE_CR2):
        G.begin_request()
        if scope:
            with NA.serving(scope):
                out = G.gate_item(dict(row))
                assert G.is_tainted(row["claim_natural"])
        else:
            out = G.gate_item(dict(row))
            assert G.is_tainted(row["claim_natural"])
        assert out == row and G.withheld_count() == 1


def test_switch_on_outside_the_scope_nothing_changes(cr2_on):
    """Every live route reads outside the scope: an approved row is withheld exactly as before."""
    row = _sealed_row(_calls()[1])
    G.begin_request()
    assert G.gate_item(dict(row)) == row and G.withheld_count() == 1
    assert G.is_tainted(row["claim_natural"])


def test_in_scope_an_approved_unchanged_call_is_served(cr2_on):
    e = _calls()[2]
    row = _sealed_row(e)
    G.begin_request()
    G.gate_item(dict(row))  # an earlier, out-of-scope request in the same container taints the words
    G.begin_request()
    with NA.serving(NA.SCOPE_CR2):
        out = G.gate_item(dict(row))
        assert out == row and G.withheld_count() == 0
        assert not G.is_tainted(row["claim_natural"])
        other = "If the fixture subject's notebook has gone quiet through Friday, the writing stays dark."
        G.gate_item({"pk": "COACH#mind_coach", "sk": "PREDICTION#pred_20261102_fixture", "claim_natural": other})
        body = json.loads(G.annotate({"statusCode": 200, "body": json.dumps({"a": row["claim_natural"], "b": other})})["body"])
        assert body == {"a": row["claim_natural"], "b": ""}, "the approved words are served; every other withheld text is not"
    assert G.is_tainted(row["claim_natural"]), "out of the scope again, the words are withheld at the wire"


def test_negative_control_a_historical_row_not_on_the_list_stays_withheld(cr2_on):
    """A pre-2026-11-03 row with no record and no entry — the case for every other historical coach text."""
    rows = [
        {
            "pk": "COACH#mind_coach",
            "sk": "PREDICTION#pred_20260906_not_on_the_list",
            "claim_natural": "A synthetic day-one call that was never approved for any surface.",
        },
        {
            "pk": "COACH#eli_marsh",
            "sk": "LEAD_DAILY#2026-10-29",
            "text": "A synthetic lead read for a day the check excluded.",
            "generated_at": "x",
        },
        {"pk": "COACH#sleep_coach", "sk": "OUTPUT#2026-10-12#daily", "content": "A synthetic historical coach read, never approved."},
    ]
    with NA.serving(NA.SCOPE_CR2):
        G.begin_request()
        # A graded-record row is carried unchanged to the handler and withheld at the wire.
        assert G.gate_item(dict(rows[0])) == rows[0] and G.is_tainted(rows[0]["claim_natural"])
        for r in rows[1:]:
            out = G.gate_item(dict(r))
            assert out[G.PUBLICATION_KEY]["state"] == "withheld"
            assert all(v == "" for k, v in out.items() if k in ("text", "content"))
        assert G.withheld_count() == 3
        assert NA.record_for(rows[0]) is None


@pytest.mark.parametrize(
    "record",
    [
        {"v": 1, "families": ["experiments", "journal_presence"], "producer": "t"},
        {"v": 1, "families": ["persona", "state_of_mind"], "producer": "t"},
        {"v": 1, "families": ["experiments", NP.UNRECORDED], "producer": "t"},
        {"v": 2, "families": ["experiments"], "producer": "t"},
        {"v": 1, "families": [], "producer": "t"},
        None,
    ],
)
def test_a_listed_row_carrying_a_private_or_broken_record_fails_closed(cr2_on, record):
    """The row's own record decides — the allowlist never overrides a private-family marker."""
    row = {**_sealed_row(_calls()[3]), "provenance": record}
    with NA.serving(NA.SCOPE_CR2):
        G.begin_request()
        out = G.gate_item(dict(row))
        assert G.withheld_count() == 1 and "provenance" not in out
        assert NA.record_for(row) is None
        strict = G.gate_item(dict(row), strict=True)
        assert strict["claim_natural"] == ""


def test_a_listed_row_whose_words_changed_is_not_the_approved_row(cr2_on):
    row = _sealed_row(_calls()[4])
    row["claim_natural"] = row["claim_natural"] + " "
    with NA.serving(NA.SCOPE_CR2):
        assert NA.record_for(row) is None
        G.begin_request()
        G.gate_item(dict(row), strict=True)
        assert G.withheld_count() == 1


_PUBLIC_CITED = [
    {"metric": "hrv", "value": "50", "as_of": "2026-10-05", "source_field": "whoop.hrv"},
    {"metric": "weight", "value": "250.0", "as_of": "2026-10-04", "source_field": "withings.weight_lbs"},
    {"metric": "start", "value": "Sunday, September 6", "as_of": "2026-09-06", "source_field": "profile.journey_start_date"},
]


def _synthetic_lead(monkeypatch, text: str, cited=None) -> dict:
    cited = _PUBLIC_CITED if cited is None else cited
    row = {"pk": "COACH#eli_marsh", "sk": "LEAD_DAILY#2026-10-05", "text": text, "generated_at": "2026-10-05T17:07:05Z", "cited": cited}
    e = NA.Entry(row["pk"], row["sk"], "text", _sha(text), NA.DERIVED_FROM_CITED)
    monkeypatch.setattr(NA, "INDEX", {**NA.INDEX, (e.pk, e.sk): e})
    return row


def test_in_scope_an_approved_lead_read_is_served_and_out_of_scope_withheld(cr2_on, monkeypatch):
    row = _synthetic_lead(monkeypatch, "A synthetic dated lead read: weight down and recovery steady this morning.")
    with NA.serving(NA.SCOPE_CR2):
        G.begin_request()
        out = G.gate_item(dict(row))
        assert out["text"] == row["text"] and G.PUBLICATION_KEY not in out and G.withheld_count() == 0
    G.begin_request()
    out = G.gate_item(dict(row))
    assert out["text"] == "" and out[G.PUBLICATION_KEY]["state"] == "withheld"


def test_a_listed_row_whose_words_name_private_activity_fails_closed(cr2_on, monkeypatch):
    row = _synthetic_lead(monkeypatch, "A synthetic lead read that says the journal went quiet this week.")
    with NA.serving(NA.SCOPE_CR2):
        assert NA.record_for(row) is None
        G.begin_request()
        assert G.gate_item(dict(row))[G.PUBLICATION_KEY]["state"] == "withheld"


def test_only_the_cr2_scope_is_honoured(cr2_on):
    row = _sealed_row(_calls()[5])
    with NA.serving("cr3"):
        assert NA.record_for(row) is None
    with NA.serving(NA.SCOPE_CR2):
        assert NA.record_for(row)["producer"] == NA.PRODUCER


def test_a_listed_lead_read_takes_its_families_from_its_own_cited_block(cr2_on, monkeypatch):
    row = _synthetic_lead(monkeypatch, "A synthetic dated lead read: weight down and recovery steady this morning.")
    with NA.serving(NA.SCOPE_CR2):
        assert set(NA.record_for(row)["families"]) == {"whoop", "withings", "experiments", "persona"}


@pytest.mark.parametrize("field", ["journal.days_since_last_entry", "state_of_mind.valence", "a_source_nobody_classified.x"])
def test_a_listed_lead_read_whose_cited_block_names_a_private_field_fails_closed(cr2_on, monkeypatch, field):
    cited = _PUBLIC_CITED + [{"metric": "m", "value": "3", "as_of": "2026-10-05", "source_field": field}]
    row = _synthetic_lead(monkeypatch, "A synthetic dated lead read: weight down and recovery steady this morning.", cited)
    with NA.serving(NA.SCOPE_CR2):
        G.begin_request()
        out = G.gate_item(dict(row))
        assert out["text"] == "" and out[G.PUBLICATION_KEY]["state"] == "withheld"
