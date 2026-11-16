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
words that the list approves are public, so those tests use the real entries (tests/fixtures/prereg_cycle17_approved_calls.json —
a labelled copy, not the seal; the sealed file itself is private since 2026-11-11).
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
sys.path.insert(0, str(ROOT / "tests"))

import sealed_prereg  # noqa: E402
from common import (
    narrative_allowlist as NA,  # noqa: E402
    narrative_provenance as NP,  # noqa: E402
    prediction_publication as PP,  # noqa: E402
    prediction_publication_registry as REG,  # noqa: E402
)
from web import narrative_publication as G  # noqa: E402

# The sealed file is private since 2026-11-11 (owner ruling item 3); the approved calls' words come from a labelled
# test copy (tests/sealed_prereg.py), and every sealed call's words only from the private original when present.
SEALED = set(sealed_prereg.sealed_call_texts())
EXCLUDED_LEAD_DAYS = {"2026-10-02", "2026-10-07", "2026-10-17", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"}


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sealed_row(entry: NA.Entry) -> dict:
    claim = next(c for c in SEALED if _sha(c) == entry.text_sha256)
    return {"pk": entry.pk, "sk": entry.sk, "claim_natural": claim, "status": "refuted", "prediction_id": entry.sk[len("PREDICTION#") :]}


@pytest.fixture
def cr2_on(monkeypatch):
    monkeypatch.setattr(NA, "CR2_PUBLIC", True)


@pytest.fixture
def ldl_counterfactual(monkeypatch):
    """The serving path's positive control. Since the owner ruled the LDL target private (2026-11-11) every sealed call
    is withheld (each generation prompt read it — test_goals_field_privacy pins that); to keep proving an approved,
    unchanged call CAN be served, these tests restore the pre-ruling classification of that one field."""
    from common import goals_field_privacy as GFP

    f = "targets.biomarkers.ldl_target_mg_dl"
    monkeypatch.setattr(GFP, "_PRIVATE", tuple(p for p in GFP._PRIVATE if p != f))
    monkeypatch.setattr(GFP, "_PUBLIC_SAFE", GFP._PUBLIC_SAFE + (f,))


def _calls():
    return [e for e in NA.APPROVED if e.sk.startswith("PREDICTION#")]


def _worded():
    """The approved calls whose words are available here: all 14 with the private original, else the 8 the labelled
    test copy still carries (six are stand-ins since the 2026-11-11 privacy cleanup, tests/sealed_prereg.py)."""
    return sealed_prereg.with_words(_calls())


def _leads():
    return [e for e in NA.APPROVED if e.sk.startswith("LEAD_DAILY#")]


# ── dark ─────────────────────────────────────────────────────────────────────────────────────


def test_the_cr2_switch_is_on_and_opens_only_inside_the_scope():
    """Owner GO 2026-11-11 (second message, item 1): CR2_PUBLIC is on. It is active ONLY inside the CR2 scope."""
    assert NA.CR2_PUBLIC is True, "CR2 was released by the owner's GO of 2026-11-11 (second message)"
    assert not NA.active(), "outside the CR2 scope nothing is active"
    with NA.serving(NA.SCOPE_CR2):
        assert NA.active()
    with NA.serving("cr3"):
        assert not NA.active()


def test_only_the_cr2_route_module_enters_the_cr2_scope():
    """Exactly ONE module outside the allowlist opens the scope — the CR2 route's (web.site_api_coach_room, whose
    ``scope_for`` opens it for ``/api/coach_room_words`` only; tests/test_coach_room_words_cr2.py pins that). A second
    opener would widen the approved words to another surface."""
    hits = []
    for p in (ROOT / "lambdas").rglob("*.py"):
        if p.name == "narrative_allowlist.py":
            continue
        if re.search(r"\bserving\(\s*(?:NA\.)?SCOPE_CR2|narrative_allowlist\.serving\(|NA\.serving\(|_SCOPE\.set\(", p.read_text()):
            hits.append(str(p.relative_to(ROOT)))
    assert hits == ["lambdas/web/site_api_coach_room.py"]


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
    unmatched = len(_calls()) - len(_worded())
    # Without the private original the six stand-in calls cannot be matched; with it, every one must be.
    assert sealed_prereg.stand_in_count() == 6
    assert unmatched == (0 if sealed_prereg.sealed_path() else 6), unmatched
    for e in _calls():
        assert PP.digest(e.pk, e.sk[len("PREDICTION#") :]) in REG.PUBLIC_DIGESTS, e.sk
    for e in _worded():
        assert e.text_sha256 in sealed_hashes, e.sk
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
    row = _sealed_row(_worded()[0])
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
    row = _sealed_row(_worded()[1])
    G.begin_request()
    assert G.gate_item(dict(row)) == row and G.withheld_count() == 1
    assert G.is_tainted(row["claim_natural"])


def test_in_scope_an_approved_unchanged_call_is_served(cr2_on, ldl_counterfactual):
    e = _worded()[2]
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
    row = {**_sealed_row(_worded()[3]), "provenance": record}
    with NA.serving(NA.SCOPE_CR2):
        G.begin_request()
        out = G.gate_item(dict(row))
        assert G.withheld_count() == 1 and "provenance" not in out
        assert NA.record_for(row) is None
        strict = G.gate_item(dict(row), strict=True)
        assert strict["claim_natural"] == ""


def test_a_listed_row_whose_words_changed_is_not_the_approved_row(cr2_on):
    row = _sealed_row(_worded()[4])
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


def test_only_the_cr2_scope_is_honoured(cr2_on, ldl_counterfactual):
    row = _sealed_row(_worded()[5])
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


# ── owner-ruled call wording (owner ruling 2026-11-14, wording batch v1) ───────────────────────────────────────────
# The ruled calls' words are published by this change, but this file carries none of them: the gate tests use a
# synthetic entry, and the real list is checked structurally (keys, hashes, the live call registry).

_RULED_TEXT = "A synthetic recovery forecast: tomorrow's score will land near sixty, inside a wide interval."
_RULED_KEY = ("COACH#sleep_coach", "PREDICTION#pred_20260920_a_synthetic_owner_ruled_fixture")


@pytest.fixture
def owner_ruled(monkeypatch):
    e = NA.Entry(_RULED_KEY[0], _RULED_KEY[1], "claim_natural", _sha(_RULED_TEXT), ())
    monkeypatch.setattr(NA, "OWNER_RULED_INDEX", {**NA.OWNER_RULED_INDEX, _RULED_KEY: e})
    monkeypatch.setattr(NA, "_OWNER_RULED_HASHES", frozenset(NA._OWNER_RULED_HASHES | {e.text_sha256}))
    return {
        "pk": e.pk,
        "sk": e.sk,
        "claim_natural": _RULED_TEXT,
        "status": "refuted",
        "outcome": "refuted",
        "confidence": "0.5",
        "prediction_id": e.sk[len("PREDICTION#") :],
    }


#: Owner ruling 2026-11-15 (#6079): the two calls approved only WITH a dated note, and the one kept withheld.
_NOTE_REQUIRED = {
    ("COACH#glucose_coach", "PREDICTION#pred_20260914_recovery_will_soften_to_roughly_59_tomo"),
    ("COACH#explorer_coach", "PREDICTION#pred_20260906_sleep_model_expects_approximately_7_hour"),
}
_SCOPE_NOTED = {
    ("COACH#sleep_coach", "PREDICTION#pred_20260917_deep_sleep_percentage_will_rise_as_zone"),
    ("COACH#sleep_coach", "PREDICTION#pred_20260918_deep_sleep_percentage_will_rise_as_zone"),
}
# Call 5 is named by its partition, filing day and words' hash only: its stored id is a slug of withheld words.
_CALL_5_PK, _CALL_5_SK_PREFIX = "COACH#sleep_coach", "PREDICTION#pred_20260915_"
_CALL_5_SHA = "78a7fc16a7e7db4e2c6103f373eeed2c793d826fcd361c1f3b5e167d474903fe"  # a hash, not the words


def test_the_owner_ruled_set_is_fourteen_keys_and_hashes_and_nothing_else():
    """12 ruled 2026-11-14 + the 2 the owner approved with a dated note on 2026-11-15 (#6079)."""
    assert len(NA.OWNER_RULED) == 14 and len(NA.OWNER_RULED_INDEX) == 14
    assert {(e.pk, e.sk) for e in NA.OWNER_RULED if e.note_required} == _NOTE_REQUIRED
    for e in NA.OWNER_RULED:
        assert e.pk.startswith("COACH#") and e.sk.startswith("PREDICTION#pred_202609") and e.field == "claim_natural"
        assert (
            re.fullmatch(r"[0-9a-f]{64}", e.text_sha256) and e.families == ()
        ), "an owner exception names no family: it claims nothing about the inputs"
        assert (e.pk, e.sk) not in NA.INDEX, "a ruled call is not also a CR2 allowlist entry"
        assert PP.digest(e.pk, e.sk[len("PREDICTION#") :]) in REG.PUBLIC_DIGESTS, f"{e.sk}: not in the public call registry"
    assert len({e.text_sha256 for e in NA.OWNER_RULED}) == 14


def test_an_owner_ruled_call_is_served_on_every_route_with_its_record_untouched(owner_ruled):
    """No scope: the ledger, the call pages and the Coaching Room read through one gate and get one decision. The
    grade fields ride through unchanged — approving words changes no verdict."""
    row = owner_ruled
    for scope in (None, NA.SCOPE_CR2):
        G.begin_request()
        if scope:
            with NA.serving(scope):
                out = G.gate_item(dict(row))
        else:
            out = G.gate_item(dict(row))
        assert out == row and G.withheld_count() == 0
        assert not G.is_tainted(row["claim_natural"])


def test_an_owner_ruled_call_survives_a_wire_taint_left_by_another_row(owner_ruled):
    """Another withheld graded row can carry the same sentence (a later call restating it). Its taint must not blank
    the ruled words in a request where the gate published them — and must still blank them where it did not."""
    row = owner_ruled
    twin = {
        "pk": row["pk"],
        "sk": "PREDICTION#pred_20260922_restates_it",
        "claim_natural": f"As said two days ago: {_RULED_TEXT} That call still stands.",
    }
    G.begin_request()
    G.gate_item(dict(twin))
    assert G.is_tainted(_RULED_TEXT), "with the ruled call not read in this request, the shared sentence is withheld at the wire"
    G.begin_request()
    G.gate_item(dict(twin))
    G.gate_item(dict(row))
    body = json.loads(G.annotate({"statusCode": 200, "body": json.dumps({"claim": _RULED_TEXT, "twin": twin["claim_natural"]})})["body"])
    assert body["claim"] == _RULED_TEXT and body["twin"] == "", "only the ruled words are released; the unruled call stays withheld"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(claim_natural=r["claim_natural"] + " "),  # the words changed: not the ruled record
        lambda r: r.update(provenance={"v": 1, "families": ["whoop", "journal_presence"], "producer": "t"}),  # its own record decides
        lambda r: r.update(
            provenance={"v": 1, "families": ["whoop"], "producer": "t"}
        ),  # ...even a public one: then it is not this exception
        lambda r: r.update(sk=r["sk"] + "_x"),  # another record with the same words
        lambda r: r.update(claim_natural=None),
    ],
)
def test_an_owner_ruled_call_fails_closed_when_it_is_not_exactly_the_ruled_record(owner_ruled, mutate):
    row = dict(owner_ruled)
    mutate(row)
    assert NA.owner_ruled_words(row) is False
    G.begin_request()
    G.gate_item(dict(row))
    if row.get("provenance", {}).get("families") != ["whoop"]:
        assert G.withheld_count() == 1


def test_the_owner_ruled_switch_and_the_private_word_belt(owner_ruled, monkeypatch):
    row = owner_ruled
    monkeypatch.setattr(NA, "OWNER_RULED_PUBLIC", False)
    G.begin_request()
    G.gate_item(dict(row))
    assert G.withheld_count() == 1 and G.is_tainted(row["claim_natural"]), "the switch off withholds every ruled call again"
    monkeypatch.setattr(NA, "OWNER_RULED_PUBLIC", True)
    monkeypatch.setattr(PP, "words_name_private_activity", lambda *t: True)
    assert NA.owner_ruled_words(row) is False, "words that name private activity are never released, ruled or not"


def test_an_unlisted_historical_call_is_still_withheld_everywhere(owner_ruled):
    """Negative control: the ruling covers the listed records and no others — the other unapproved calls stay withheld."""
    other = {
        "pk": owner_ruled["pk"],
        "sk": "PREDICTION#pred_20260921_never_ruled",
        "claim_natural": "A synthetic historical call nobody ruled on, with enough words.",
    }
    G.begin_request()
    assert G.gate_item(dict(other)) == other and G.withheld_count() == 1 and G.is_tainted(other["claim_natural"])
    assert (
        "owner_ruled_words" not in (ROOT / "lambdas" / "web" / "site_api_coach_room.py").read_text()
    ), "the Room reads through the gate, not a list of its own"


# ── owner-ruled notes (owner ruling 2026-11-15, #6079) ─────────────────────────────────────────────────────────────


def test_the_four_notes_are_the_ruled_records_and_carry_only_the_ruling():
    """Calls 1 and 2: published only with their note. Calls 6 and 8: already published, the scope note beside them.
    Every note is dated, labelled by kind, carries no ISO date (the page writes dates in words) and none of the coach's
    words; nothing else is noted."""
    assert set(NA.OWNER_NOTES) == _NOTE_REQUIRED | _SCOPE_NOTED
    kinds = {k: n.kind for k, n in NA.OWNER_NOTES.items()}
    assert kinds == {
        ("COACH#glucose_coach", "PREDICTION#pred_20260914_recovery_will_soften_to_roughly_59_tomo"): "clarification",
        ("COACH#explorer_coach", "PREDICTION#pred_20260906_sleep_model_expects_approximately_7_hour"): "grading_explanation",
        **{k: "scope" for k in _SCOPE_NOTED},
    }
    for key, n in NA.OWNER_NOTES.items():
        assert key in NA.OWNER_RULED_INDEX, f"{key}: a note on a record whose words are not ruled public"
        assert n.required == (key in _NOTE_REQUIRED) == NA.OWNER_RULED_INDEX[key].note_required, key
        assert n.dated == NA.OWNER_NOTES_AT == "2026-11-15" and n.kind in NA.NOTE_KINDS
        assert n.text.strip() and n.short.strip() and not re.search(r"\d{4}-\d{2}-\d{2}", n.text + n.short), key
    clar = NA.OWNER_NOTES[("COACH#glucose_coach", "PREDICTION#pred_20260914_recovery_will_soften_to_roughly_59_tomo")]
    assert "12 September" in clar.text and "13 September" in clar.text and "have not been changed" in clar.text
    grading = NA.OWNER_NOTES[("COACH#explorer_coach", "PREDICTION#pred_20260906_sleep_model_expects_approximately_7_hour")]
    for fact in ("about 7 hours", "1.2 hours", "8.4 hours", "5.4 to 8.7 hours", "Both statements are true", "has not been changed"):
        assert fact in grading.text, fact
    for key in _SCOPE_NOTED:
        t = NA.OWNER_NOTES[key].text
        assert "not tested" in t and "neither establishes nor refutes" in t and "adenosine" in t and "Zone 2" in t


def test_the_call_the_ruling_keeps_withheld_stays_withheld():
    """The sleep coach's deep-sleep call of 2026-09-15: KEEP WITHHELD — no sleep-coach call filed that day is on any
    list or carries a note, its words (by hash) are pinned nowhere, and a row filed that day is withheld everywhere."""
    keys = set(NA.OWNER_RULED_INDEX) | set(NA.OWNER_NOTES) | set(NA.INDEX)
    assert not [k for k in keys if k[0] == _CALL_5_PK and k[1].startswith(_CALL_5_SK_PREFIX)]
    assert _CALL_5_SHA not in {e.text_sha256 for e in NA.OWNER_RULED + NA.APPROVED}
    row = {
        "pk": _CALL_5_PK,
        "sk": _CALL_5_SK_PREFIX + "a_synthetic_stand_in",
        "claim_natural": "A synthetic stand-in for the withheld words.",
    }
    assert NA.owner_ruled_words(row) is False and NA.owner_note(row) is None
    G.begin_request()
    G.gate_item(dict(row))
    assert G.withheld_count() == 1 and G.is_tainted(row["claim_natural"])


_NOTE = NA.Note(
    kind="clarification",
    dated="2026-11-15",
    required=True,
    text="A synthetic dated clarification: the reading it cites belongs to the night before.",
    short="Dated clarification (synthetic).",
)


@pytest.fixture
def ruled_with_note(monkeypatch, owner_ruled):
    """The synthetic owner-ruled call, approved only WITH its note."""
    e = NA.OWNER_RULED_INDEX[_RULED_KEY]._replace(note_required=True)
    monkeypatch.setattr(NA, "OWNER_RULED_INDEX", {**NA.OWNER_RULED_INDEX, _RULED_KEY: e})
    monkeypatch.setattr(NA, "OWNER_NOTES", {**NA.OWNER_NOTES, _RULED_KEY: _NOTE})
    return owner_ruled


def test_a_call_ruled_with_a_note_is_served_with_it(ruled_with_note):
    row = ruled_with_note
    G.begin_request()
    assert G.gate_item(dict(row)) == row and G.withheld_count() == 0
    assert NA.owner_note(row) == {
        "kind": "clarification",
        "dated": "2026-11-15",
        "required": True,
        "text": _NOTE.text,
        "short": _NOTE.short,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda notes: notes.pop(_RULED_KEY),  # the note removed
        lambda notes: notes.update({_RULED_KEY: _NOTE._replace(text="  ")}),  # the note emptied
        lambda notes: notes.update({_RULED_KEY: _NOTE._replace(short="")}),  # no short form for the list surfaces
        lambda notes: notes.update({_RULED_KEY: _NOTE._replace(kind="owner_note")}),  # an unknown kind
    ],
)
def test_removing_the_note_withholds_the_words(ruled_with_note, monkeypatch, mutate):
    """The ruling is "publish WITH the note": without a complete note the words are withheld on every route, exactly
    like an unruled call — the requirement is pinned on the entry, so it cannot be dropped with the note."""
    notes = dict(NA.OWNER_NOTES)
    mutate(notes)
    monkeypatch.setattr(NA, "OWNER_NOTES", notes)
    row = ruled_with_note
    assert NA.owner_ruled_words(row) is False and NA.owner_note(row) is None
    G.begin_request()
    G.gate_item(dict(row))
    assert G.withheld_count() == 1 and G.is_tainted(row["claim_natural"])


def test_the_wire_empties_the_words_from_any_object_that_lacks_their_note(ruled_with_note):
    """Belt at the wire: the gate published the words, but an object that serves them without the note beside them (a
    route that forgot it, a list of strings, a changed note) has them emptied. The words with the note pass."""
    row = ruled_with_note
    G.begin_request()
    G.gate_item(dict(row))
    note = NA.owner_note(row)
    body = {
        "with": {"claim": row["claim_natural"], "owner_note": note},
        "without": {"claim": row["claim_natural"]},
        "changed": {"claim": row["claim_natural"], "owner_note": {**note, "text": "another note"}},
        "nested_null": {"text": row["claim_natural"], "owner_note": None},
        "listed": [row["claim_natural"]],
    }
    out = json.loads(G.annotate({"statusCode": 200, "body": json.dumps(body)})["body"])
    assert out["with"]["claim"] == row["claim_natural"]
    assert out["without"]["claim"] == "" and out["changed"]["claim"] == "" and out["nested_null"]["text"] == ""
    assert out["listed"] == [""]


def test_a_scope_note_never_holds_words_and_the_unnoted_calls_are_untouched(owner_ruled):
    """``required=False`` (calls 6 and 8): the words are served exactly as before with or without the note, and the
    wire belt never touches them; a ruled call with no note at all is served with ``owner_note`` null."""
    row = owner_ruled
    G.begin_request()
    G.gate_item(dict(row))
    assert NA.owner_note(row) is None and NA.required_note_for_text(row["claim_natural"]) is None
    out = json.loads(G.annotate({"statusCode": 200, "body": json.dumps({"claim": row["claim_natural"]})})["body"])
    assert out["claim"] == row["claim_natural"]
    for key in _SCOPE_NOTED:
        assert NA.OWNER_RULED_INDEX[key].note_required is False and NA.OWNER_NOTES[key].required is False


def test_the_ledger_routes_serve_the_note_beside_the_words(ruled_with_note, monkeypatch):
    """/api/ledger_export (the snapshot's source) serves ``owner_note`` beside the words and null on every other row;
    a row whose words are held carries no note."""
    from web import site_api_ledger_export as LE

    monkeypatch.setattr(LE, "_dossier_safe", lambda text: True)
    row = {**ruled_with_note, "created_date": "2026-09-20", "evaluation": {"type": "directional", "metric": "hrv", "condition": "up"}}
    short = row["pk"][len("COACH#") : -len("_coach")]
    item = LE.export_item(short, row)
    assert item["claim"] == row["claim_natural"] and item["owner_note"]["text"] == _NOTE.text
    other = {**row, "sk": "PREDICTION#pred_20260921_never_ruled"}
    assert LE.export_item(short, other)["owner_note"] is None
    monkeypatch.setattr(LE, "_dossier_safe", lambda text: False)
    held = LE.export_item(short, row)
    assert held["claim"] == "" and held["owner_note"] is None
