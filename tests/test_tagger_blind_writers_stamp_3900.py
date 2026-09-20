"""#3900 — the tagger-blind families stamp `phase`/`cycle` at their write sites.

`deploy/restart_phase_tag.py` reaches only `USER#matthew#SOURCE#*` pks, so a row on PERSONA#elena,
the bare USER#matthew pk (SOURCE#coach_thread#…), COACH#commitments or NARRATIVE#arc that carries no
write-time `phase` is admitted by PHASE_FILTER_EXPRESSION's `attribute_not_exists(phase)` as CURRENT
across every reset. Live 2026-09-19: 35 such rows (PERSONA 19, coach_thread 14, commitments 1, arc 1).

Residual (2026-09-20, the 18:31Z nightly): the box-1 census above was FOUR families, not the whole
class — `ENSEMBLE#dispute` (the inter-coach dialogue thread, #540) already carried a correct taxonomy
ruling (EXPERIMENT_SCOPED, pre-dating this issue) and was already in the backfill's `_ENSEMBLE_PKS`
list, but its writer (`inter_coach_dialogue_lambda._air_one`) never called `experiment_stamp_for` —
two live W38 rows. `test_the_dispute_thread_writer_is_stamped` below is the fifth writer this file's
census must not let escape again.

Every assertion here is against the taxonomy's OWN stamp (`experiment_stamp()`), never a literal, and
each writer is exercised through its real entry point with a capturing table. Mutation control per
writer: delete its `experiment_stamp_for(...)` spread → that test reds on the missing `phase`.
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from experiment import phase_taxonomy as tax  # noqa: E402

EXPECTED = tax.experiment_stamp()  # {"phase": <current>, "cycle": <n>} — the one derivation


class _CaptureTable:
    def __init__(self, items=None):
        self.puts: list[dict] = []
        self.items = items or {}

    def put_item(self, Item):  # noqa: N803 — boto3 kwarg
        self.puts.append(Item)

    def get_item(self, Key):  # noqa: N803
        return {"Item": self.items.get((Key["pk"], Key["sk"]))}

    def query(self, **kw):
        return {"Items": []}

    def update_item(self, **kw):
        pass


def _assert_stamped(item: dict, where: str):
    assert item.get("phase") == EXPECTED["phase"], f"{where}: no write-time phase stamp ({item.get('pk')}/{item.get('sk')})"
    assert item.get("cycle") == EXPECTED["cycle"], f"{where}: no cycle stamp"


def test_the_taxonomy_still_rules_all_five_families_experiment_scoped():
    """The stamps below are CLASS-GATED; if a ruling changes, this names it before a writer goes quiet."""
    for pk, sk in (
        ("PERSONA#elena", "CALLBACK#2026-09-08#x"),
        ("PERSONA#elena", "MOTIF#state"),
        ("USER#matthew", "SOURCE#coach_thread#explorer#2026-09-07"),
        ("COACH#commitments", "TALLY#current"),
        ("NARRATIVE#arc", "HISTORY#2026-09-14"),
        ("ENSEMBLE#dispute", "THREAD#2026-W38#protein_deficit_urgency"),
    ):
        assert tax.should_phase_stamp(pk, sk), (pk, sk)


def test_write_coach_thread_stamps_the_bare_user_pk(monkeypatch):
    from intelligence import intelligence_common as ic

    table = _CaptureTable()
    monkeypatch.setattr(ic, "table", table)
    assert ic.write_coach_thread("explorer", {"position_summary": "x"}) is True
    (item,) = table.puts
    assert item["pk"].startswith("USER#") and item["sk"].startswith("SOURCE#coach_thread#explorer#")
    _assert_stamped(item, "intelligence_common.write_coach_thread")


def test_the_critics_thread_entry_is_stamped():
    from coach import critics

    class _IR:
        inputs_snapshot = {"critics": {"engine": "critics@1.0.0", "verdicts": [{"critic": "joints", "verdict": "approve"}]}}
        routine_id = "r-1"

    item = critics.thread_entry(_IR(), today="2026-09-20")
    assert item["sk"] == "SOURCE#coach_thread#training#2026-09-20#critics"
    _assert_stamped(item, "critics.thread_entry")


def test_the_pain_flag_thread_row_is_stamped(monkeypatch):
    from training import training_notes as tn

    table = _CaptureTable()
    monkeypatch.setattr(tn, "save_insight", lambda **kw: None, raising=False)
    tn.elevate_pain(table, {"date": "2026-09-20", "exercise": "squat", "text": "sharp pain in the left knee"})
    rows = [p for p in table.puts if str(p.get("sk", "")).startswith("SOURCE#coach_thread#training_coach#")]
    assert rows, f"no pain thread row written: {[p.get('sk') for p in table.puts]}"
    _assert_stamped(rows[0], "training_notes.elevate_pain")


def test_every_elena_persona_write_is_stamped(monkeypatch):
    import emails.elena_state_updater as esu

    table = _CaptureTable()
    monkeypatch.setattr(esu, "table", table)
    extraction = {
        "threads_opened": [{"slug": "sleep-debt", "summary": "s", "type": "pattern"}],
        "callbacks_made": [{"slug": "weigh-in", "promise": "we'll check the scale next week"}],
        "motifs": ["the long game"],
        "stance": {"headline_stance": "steady", "positions": ["p"], "how_my_stance_changed": "", "receipts": []},
    }
    state = {"open_threads": [], "pending_callbacks": [], "motifs": [], "stance": {}}
    esu.apply_extraction(extraction, "2026-09-20", 3, state)
    kinds = {str(p["sk"]).split("#")[0] for p in table.puts}
    assert {"THREAD", "CALLBACK", "MOTIF", "STANCE"} <= kinds, kinds
    for p in table.puts:
        assert p["pk"] == "PERSONA#elena"
        _assert_stamped(p, f"elena_state_updater {p['sk']}")


def test_the_commitment_tally_is_stamped():
    from coach import commitment_grading as cg

    table = _CaptureTable()
    cg.write_tally(table, [{"sk": "COMMITMENT#x", "status": "kept"}], {}, "2026-09-20", logging.getLogger("t"))
    (item,) = table.puts
    assert (item["pk"], item["sk"]) == (cg.ROLLUP_PK, cg.ROLLUP_SK)
    _assert_stamped(item, "commitment_grading.write_tally")


def test_the_arc_history_row_takes_the_full_stamp_and_state_current_stays_cycle_only(monkeypatch):
    """The #3900 ruling: STATE#current's `phase` IS the arc state (cycle-only, #1233); HISTORY#<date> has
    no arc state in `phase`, so it carries the taxonomy phase like every reset wipe already wrote."""
    from coach import coach_computation_engine as cce

    # an in-cycle arc in "building_momentum"; six of six trends down → the detector moves it to "setback"
    table = _CaptureTable(
        items={("NARRATIVE#arc", "STATE#current"): {"phase": "building_momentum", "entered_date": "2026-09-10", "cycle": EXPECTED["cycle"]}}
    )
    monkeypatch.setattr(cce, "table", table, raising=False)
    monkeypatch.setattr(cce, "EXPERIMENT_START", "2026-09-06", raising=False)
    trends = {"physical": {f"m{i}": {"direction": "down"} for i in range(6)}}
    out = cce._detect_arc_transition(trends, {}, {}, "2026-09-20")
    assert out is not None, "the synthetic trend set must produce a transition, or this test exercises nothing"
    by_sk = {p["sk"]: p for p in table.puts}
    assert "STATE#current" in by_sk and any(sk.startswith("HISTORY#") for sk in by_sk), list(by_sk)
    state = by_sk["STATE#current"]
    assert state["cycle"] == EXPECTED["cycle"] and state["phase"] != EXPECTED["phase"], "STATE#current keeps the ARC phase, cycle-only"
    (hist,) = [p for sk, p in by_sk.items() if sk.startswith("HISTORY#")]
    _assert_stamped(hist, "coach_computation_engine HISTORY#")


def test_the_dispute_thread_writer_is_stamped(monkeypatch):
    """The fifth writer (2026-09-20 residual): ENSEMBLE#dispute's `_air_one` — the only
    put_item site in inter_coach_dialogue_lambda.py — must carry the write-time stamp."""
    from coach import inter_coach_dialogue_lambda as icd, persona_registry

    table = _CaptureTable()
    monkeypatch.setattr(icd, "table", table)
    monkeypatch.setattr(icd.boto3, "client", lambda *a, **kw: object())
    monkeypatch.setattr(persona_registry, "load_registry", lambda s3, bucket: {"personas": {}})
    monkeypatch.setattr(icd, "_voice", lambda s3, coach_config_key: ("", ""))
    monkeypatch.setattr(icd, "generate_gated_turn", lambda system, user, allowed_sources: ("a reply", []))

    pick = {
        "topic": {
            "sk": "ACTIVE#protein_deficit_urgency_and_progression_gating",
            "topic": "protein deficit urgency",
            "positions": {"nutrition": "a", "training": "b"},
            "cycle_count": 2,
        },
        "coach_a": "nutrition",
        "coach_b": "training",
        "influence_weight": 1.0,
    }
    icd._air_one(pick, "2026-W38")
    (item,) = [p for p in table.puts if p.get("pk") == icd.DISPUTE_PK]
    assert item["sk"] == "THREAD#2026-W38#protein_deficit_urgency_and_progression_gating"
    _assert_stamped(item, "inter_coach_dialogue_lambda._air_one")


def test_the_backfill_names_the_four_families_with_their_sk_scope():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "backfill_3900", os.path.join(os.path.dirname(__file__), "..", "deploy", "backfill_coach_ensemble_phase_stamps.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_3900"] = mod
    spec.loader.exec_module(mod)
    fams = dict(mod.target_families())
    assert fams["PERSONA#elena"] is None
    assert fams["COACH#commitments"] is None
    assert fams["NARRATIVE#arc"] == "HISTORY#", "STATE#current is cycle-only by ruling; the backfill must not set phase on it"
    assert fams["USER#matthew"] == "SOURCE#coach_thread#", "the bare USER#matthew pk holds many families; only coach_thread is in scope"
    # #3900 residual: ENSEMBLE#dispute needs no new list entry — it has been in _ENSEMBLE_PKS
    # (and so in target_pks()/target_families()) since this tool's original creation (#1970),
    # unprefixed, which already covers both live W38 THREAD# rows.
    assert fams["ENSEMBLE#dispute"] is None

    # the prefixed query really scopes by sk
    class _T:
        def __init__(self):
            self.kw = None

        def query(self, **kw):
            self.kw = kw
            return {"Items": []}

    t = _T()
    mod.query_unstamped(t, "USER#matthew", "SOURCE#coach_thread#")
    assert t.kw["KeyConditionExpression"].get_expression()["operator"] == "AND"
