"""#5776 — the block design review: each new block's selection as a proposal, the owner's approval as drafting's pins.

Must-fail controls: the proposal lists every accessory slot (drop one and it says which); an approval becomes the
engine's owner pins (and without one, live drafting serves the pools — or the prior block's picks, said so); the
experiment slot holds for its block only; the narration falls back to the deterministic text when the model fails or
is paused; a gate's value never reaches the proposal. Real library + real catalog, deep-copied; no AWS, no clock.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    block_design_review as bdr,  # noqa: E402
    exercise_library as xl,  # noqa: E402
    selection_engine as se,  # noqa: E402
    training_charter as tc,  # noqa: E402
    variant_rotation as vr,  # noqa: E402
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
WEEK7 = {"week": 7, "block": 2, "session_role": "upper_heavy", "date": "2026-11-12"}  # block 2, phase 1
SLOT = "upper_heavy.db_curl"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv(xl.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(xl, "_overlay_from_local", lambda: None)
    monkeypatch.setattr(xl, "_overlay_from_s3", lambda: None)
    tc.reset_cache()
    se._LIB_CACHE.clear()
    yield
    tc.reset_cache()
    se._LIB_CACHE.clear()


def _lib(status: str = "proposed") -> dict:
    lib = copy.deepcopy(LIB0)
    lib["status"] = status
    return lib


def _proposal(block: int = 2, *, sel=None, **kw) -> dict:
    lib = _lib()
    sel = sel or se.select_week(bdr.block_position(block), copy.deepcopy(CAT0), lib, None, missing=[])
    return bdr.build_proposal(block, sel, lib, CAT0, **kw)


def _slot(p: dict, sid: str) -> dict:
    return next(s for s in p["slots"] if s["slot_id"] == sid)


def _alt_key(p: dict, sid: str = SLOT) -> str:
    return next(a["catalog_key"] for a in _slot(p, sid)["alternatives"] if a.get("catalog_key"))


def _row(p: dict, decisions=None) -> dict:
    return bdr.approval_item(p, decisions, approved_at="2026-11-11T00:00:00+00:00")


def _live(approvals) -> dict:
    cat = copy.deepcopy(CAT0)
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=[], ledger_state="injected")
    return se.apply(copy.deepcopy(rot), cat, rows=[], lib=_lib("approved"), overlay=None, target_date="2026-11-12", approvals=approvals)


# ── the proposal lists every slot ────────────────────────────────────────────
def test_the_proposal_lists_every_accessory_slot_and_says_which_is_missing():
    p = _proposal()
    assert [s["slot_id"] for s in p["slots"]] == [s["slot_id"] for s in vr.slots()]
    assert p["complete"] and p["missing_slots"] == []
    for s in p["slots"]:
        assert s["why"]["this"] and s["why"]["now"] and s["replaces"]["title"], s["slot_id"]
        if not s.get("pinned") and s.get("pick"):
            assert all(a["movement_id"] != s["pick"]["movement_id"] for a in s["alternatives"])
    # control: a selection missing a slot is named, never silently short
    sel = se.select_week(bdr.block_position(2), copy.deepcopy(CAT0), _lib(), None, missing=[])
    sel["slots"] = [s for s in sel["slots"] if s["slot_id"] != SLOT]
    short = bdr.build_proposal(2, sel, _lib(), CAT0)
    assert not short["complete"] and short["missing_slots"] == [SLOT]


def test_alternatives_follow_the_engines_rank_and_the_proposal_is_deterministic():
    p = _proposal()
    ranks = [a["rank"] for a in _slot(p, SLOT)["alternatives"]]
    assert ranks == sorted(ranks)
    assert json.dumps(_proposal(), sort_keys=True) == json.dumps(p, sort_keys=True)


def test_replaces_reads_the_prior_approval_then_the_ledger_then_the_template():
    p = _proposal()
    assert _slot(p, SLOT)["replaces"]["source"] == "the template accessory"
    rows = [
        {"sk": vr.ledger_sk(1, SLOT), "block": 1, "phase_1": {"variant": "hammer_curl_dumbbell"}, "phase_2": {"variant": "spider_curl"}}
    ]
    assert _slot(_proposal(rows=rows), SLOT)["replaces"]["catalog_key"] == "spider_curl"
    prior = {"block": 1, "pins": {SLOT: {"catalog_key": "bicep_curl_cable"}}}
    got = _slot(_proposal(rows=rows, prior=prior), SLOT)["replaces"]
    assert got["catalog_key"] == "bicep_curl_cable" and got["source"] == "approved for block 1"


# ── gates: the value state, never the value ──────────────────────────────────
def test_unlocks_next_names_the_gate_state_and_never_a_value():
    p0 = _proposal()
    locked = [(s["slot_id"], u) for s in p0["slots"] for u in s["unlocks_next"]]
    assert locked, "the library has gate-locked movements for some slot"
    sid, u = locked[0]
    gid = u["gates"][0]["gate"]
    assert u["gates"][0]["state"] == bdr.LOCK_STATE_WORDS["not_evaluated"]
    secret = 987.6
    row = {"state": "locked", "input": "measured", "reason": f"mean {secret} above the threshold", "value_seen": {"mean_lb_7d": secret}}
    for inp, phrase in (("measured", "locked: measured, standard not yet met"), ("not_set", "locked: threshold not set")):
        ev = {"week_start": "2026-11-09", "gates": {gid: row | {"input": inp}}}
        p = _proposal(gate_eval=ev)
        got = next(x for x in _slot(p, sid)["unlocks_next"] if x["movement_id"] == u["movement_id"])
        assert next(g for g in got["gates"] if g["gate"] == gid)["state"] == phrase
        dumped = json.dumps(p) + bdr.render_markdown(p) + json.dumps(bdr._narration_facts(p))
        assert str(secret) not in dumped and "value_seen" not in dumped
    assert bdr.gate_phrase({"state": "unlocked", "input": "measured"}) == "unlocked"


# ── the experiment slot ──────────────────────────────────────────────────────
EXP = {"slot_id": SLOT, "technique": "lengthened partials", "experiment_id": "EXPERIMENT#test", "outcome_metric": "e1RM trend"}


def test_the_experiment_slot_is_empty_by_default_and_validated_when_pinned():
    assert _proposal()["experiment"]["state"] == "empty"
    p = _proposal(experiment=EXP)
    assert p["experiment"]["state"] == "pinned" and p["experiment"]["block"] == 2 and p["experiment"]["muscle"] == "biceps"
    for bad in ({**EXP, "experiment_id": ""}, {**EXP, "slot_id": "nope"}, {**EXP, "slot_id": "shoulders_arms.farmers_walk"}):
        with pytest.raises(ValueError):
            _proposal(experiment=bad)


# ── the approval becomes the engine's pins ───────────────────────────────────
def test_approval_row_takes_the_proposal_or_a_listed_alternative_and_refuses_anything_else():
    p = _proposal()
    alt = _alt_key(p)
    row = _row(p, {SLOT: alt, "upper_heavy.db_lateral_raise": "incumbent"})
    assert row["sk"] == "BLOCKREVIEW#APPROVED#B002" and row["tier"] == "owner_only"
    assert row["pins"][SLOT] == {"catalog_key": alt, "decision": "alternative"}
    assert row["pins"]["upper_heavy.db_lateral_raise"]["decision"] == "incumbent"
    assert not set(row["pins"]) & set(vr.PINNED_SLOTS)
    with pytest.raises(ValueError):
        _row(p, {SLOT: "barbell_back_squat"})
    with pytest.raises(ValueError):
        _row(p, {"no.such_slot": alt})


def test_an_approval_becomes_the_drafts_owner_pins():
    p = _proposal()
    alt = _alt_key(p)
    res = bdr.resolve([_row(p, {SLOT: alt})], 2)
    assert res["state"] == "approved" and res["pins"][SLOT]["catalog_key"] == alt
    out = _live(res)
    assert out["variants"]["db_curl"] == alt
    served = next(s for s in out["slots"] if s["slot_id"] == SLOT)
    assert served["source"] == "owner_approved"
    assert out["selection"]["approval"]["state"] == "approved"
    # control: the same draft with no approval on record serves the pools, said so
    rot = vr.plan(WEEK7, copy.deepcopy(CAT0), role="upper_heavy", rows=[], ledger_state="injected")
    none = _live(bdr.resolve([], 2))
    assert none["variants"] == rot["variants"] and "no owner-approved block proposal" in none["selection_note"]
    failed = _live({"state": "read_failed", "pins": {}, "note": "read_failed: X"})
    assert failed["variants"] == rot["variants"]


def test_an_unapproved_block_falls_back_to_the_prior_blocks_picks_said_so():
    p1 = _proposal(1)
    alt = _alt_key(p1)
    res = bdr.resolve([_row(p1, {SLOT: alt})], 2)
    assert res["state"] == "prior_block" and res["approved_block"] == 1 and "block 1's approved picks serve" in res["note"]
    assert _live(res)["variants"]["db_curl"] == alt


def test_the_experiment_holds_for_its_block_only():
    exp_key = "spider_curl"
    p = _proposal(experiment={**EXP, "catalog_key": exp_key})
    alt = _alt_key(p)
    row = _row(p, {SLOT: alt})
    now = bdr.resolve([row], 2)
    assert now["pins"][SLOT]["catalog_key"] == exp_key and now["pins"][SLOT]["experiment"]["experiment_id"] == "EXPERIMENT#test"
    out = _live(now)
    served = next(s for s in out["slots"] if s["slot_id"] == SLOT)
    assert out["variants"]["db_curl"] == exp_key and served["experiment"]["technique"] == "lengthened partials"
    # negative control: the next block, unpinned, drops it — the slot's approved pick serves, no experiment
    nxt = bdr.resolve([row], 3)
    assert nxt["state"] == "prior_block" and nxt["experiment"] is None
    assert nxt["pins"][SLOT] == {"catalog_key": alt, "source": "prior_block", "approved_block": 2, "experiment": None}


def test_an_approved_movement_the_slot_can_no_longer_serve_is_refused_not_forced():
    p = _proposal()
    row = _row(p)
    row["pins"][SLOT] = {"catalog_key": "barbell_back_squat", "decision": "alternative"}
    out = _live(bdr.resolve([row], 2))
    rot = vr.plan(WEEK7, copy.deepcopy(CAT0), role="upper_heavy", rows=[], ledger_state="injected")
    served = next(s for s in out["slots"] if s["slot_id"] == SLOT)
    assert out["variants"]["db_curl"] == rot["variants"]["db_curl"] and "approval_note" in served


def test_shadow_mode_records_the_approval_but_serves_the_pools():
    p = _proposal()
    cat = copy.deepcopy(CAT0)
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=[], ledger_state="injected")
    res = bdr.resolve([_row(p, {SLOT: _alt_key(p)})], 2)
    out = se.apply(copy.deepcopy(rot), cat, rows=[], lib=_lib("proposed"), overlay=None, approvals=res)
    assert out["variants"] == rot["variants"] and out["selection"]["approval"]["state"] == "approved"


def test_for_session_reads_the_approval_beside_the_ledger_only(monkeypatch):
    seen = []
    monkeypatch.setattr(bdr, "load_failsoft", lambda block, table=None: seen.append(block) or bdr.resolve([], block))
    monkeypatch.setattr(vr, "load_rows_failsoft", lambda block, table=None: ([], "read"))
    se._LIB_CACHE.update(lib=_lib("proposed"), at=float("inf"))
    vr.for_session(WEEK7, copy.deepcopy(CAT0), rows=[], select=True)
    assert seen == []  # an injected ledger reads no approval
    out = vr.for_session(WEEK7, copy.deepcopy(CAT0), select=True)
    assert seen == [2] and out["selection"]["approval"]["state"] == "none"


def test_load_failsoft_names_a_failed_read():
    class Boom:
        def query(self, **kw):
            raise RuntimeError("no")

    got = bdr.load_failsoft(2, Boom())
    assert got["state"] == "read_failed" and got["pins"] == {}


# ── the narration ────────────────────────────────────────────────────────────
def test_narration_failure_falls_back_to_the_deterministic_text(monkeypatch):
    p = _proposal()
    want = bdr.deterministic_summary(p)
    got = bdr.narrate(p, call=lambda body: (_ for _ in ()).throw(RuntimeError("bedrock down")))
    assert got["status"] == "failed" and got["text"] == want and got["source"] == "deterministic"
    assert bdr.narrate(p, call=lambda body: {"content": []})["text"] == want
    ok = bdr.narrate(p, call=lambda body: {"content": [{"type": "text", "text": "Three slots change."}]})
    assert ok["status"] == "ok" and ok["text"] == "Three slots change." and ok["source"] == "model"
    from training import panel_judge

    monkeypatch.setattr(panel_judge, "_allowed", lambda route: (False, "paused by the budget guard"))
    paused = bdr.narrate(p)
    assert paused["status"] == "paused" and paused["text"] == want


def test_the_model_never_sees_the_volume_numbers():
    vol = {
        "version": "v",
        "block_end": "2026-11-08",
        "caveat": "c",
        "muscles": [{"muscle": "biceps", "response": "flat", "proposal": {"sets_per_wk": 777}}],
    }
    p = _proposal(volume_report=vol)
    assert p["volume_response"]["state"] == "supplied" and "777" in bdr.render_markdown(p)
    assert "777" not in json.dumps(bdr._narration_facts(p))


# ── the script ───────────────────────────────────────────────────────────────
def test_the_script_refuses_an_output_dir_inside_the_repo(capsys):
    import block_design_review as cli

    assert cli.main(["propose", "--block", "2", "--out", str(REPO / "scratch-5776")]) == 1
    assert "refusing" in capsys.readouterr().out
    assert not (REPO / "scratch-5776").exists()


def test_approve_is_a_dry_run_without_apply(tmp_path, capsys, monkeypatch):
    import block_design_review as cli

    monkeypatch.setattr(cli, "_table", lambda: (_ for _ in ()).throw(AssertionError("no AWS on a dry run")))
    f = tmp_path / "proposal.json"
    f.write_text(json.dumps(_proposal()))
    assert cli.main(["approve", "--proposal", str(f)]) == 0
    assert "DRY RUN" in capsys.readouterr().out
