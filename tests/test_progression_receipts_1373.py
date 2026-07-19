"""tests/test_progression_receipts_1373.py — progression receipts (#1373).

Every XP/level change gets an audit-grade receipt: contributing input-row KEYS,
engine formula version, config hash, per-pillar transition inputs/outputs, and
a deterministic replay digest. These tests pin the four acceptance criteria:

  AC1 — the receipt stores input-row keys + formula version + config hash +
        digest (and the sheet item itself never carries the raw capture);
  AC2 — deterministic replay of the stored inputs (through the SAME engine
        functions, after a full DynamoDB Decimal round-trip) reproduces the
        digest; a mismatch is detected and labeled;
  AC4 — mutate a config value → the replay digest mismatch is detected, with
        config_drift set (the guard this file exists to keep red-capable);
  ADR-104 — no receipt is ever fabricated for a change with no recorded
        inputs, and a tampered/nondeterministic receipt reads as the ALARM
        case (mismatch with NO drift flags).

Run with:   python3 -m pytest tests/test_progression_receipts_1373.py -v
"""

import copy
import os
import sys
from decimal import Decimal

# ── Add lambdas/ to import path ──
LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

import character_engine as ce  # noqa: E402
import progression_receipts as pr  # noqa: E402
from numeric import floats_to_decimal  # noqa: E402
from test_character_math_v2 import V2_CONFIG  # noqa: E402 — the engine-test config fixture

PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]


def _cfg():
    return copy.deepcopy(V2_CONFIG)


def _data(date="2026-08-01"):
    """A minimally-instrumented day (movement has real inputs, rows carry keys)."""
    return {
        "date": date,
        "strava_7d": [
            {"date": date, "moving_time_minutes": 45, "average_heartrate": 120, "pk": "USER#matthew#SOURCE#strava", "sk": f"DATE#{date}"}
        ],
        "apple": {"steps": 9000, "pk": "USER#matthew#SOURCE#apple_health", "sk": f"DATE#{date}"},
    }


def _sheet(prev=None, histories=None, date="2026-08-01", config=None):
    return ce.compute_character_sheet(_data(date), prev, histories or {}, config or _cfg())


def _receipt(record=None, config=None, input_rows=None):
    config = config or _cfg()
    record = record if record is not None else _sheet(config=config)
    return pr.build_receipt(record, config, input_rows=input_rows or [])


def _ddb_round_trip(receipt):
    """What replay actually sees in production: the stored Decimal item."""
    return floats_to_decimal(pr._norm(receipt))


def _manual_record(cfg, raw=75.0, prev=None, date="2026-08-01"):
    """A record whose single (movement) transition has FULL coverage, built
    through the engine's own functions — so XP genuinely flows (the engine-run
    fixture day is coverage-held for most pillars, which holds XP and would
    make band-mutation tests vacuous)."""
    level_state = ce.evaluate_level_changes(
        "movement",
        raw,
        prev,
        cfg,
        data_coverage=1.0,
        raw_score=raw,
        unadjusted_level_score=raw,
        raw_score_unblended=raw,
        presence_dark=False,
    )
    prev_xp = (prev or {}).get("xp_total", 0)
    prev_debt = (prev or {}).get("xp_debt", 0)
    xp_earned, xp_delta, new_xp, new_debt = ce.pillar_xp_transition(raw, prev_xp, prev_debt, 0, False, cfg, day_number=30)
    leveling = cfg["leveling"]
    xp_buffer = ce._roll_xp_buffer(
        (prev or {}).get("xp_buffer"), prev_xp, new_xp, leveling["xp_per_level"], buffer_cap=leveling.get("xp_buffer_cap")
    )
    transition = {
        "inputs": {
            "prev": prev,
            "level_score": raw,
            "unadjusted_level_score": raw,
            "raw_score": raw,
            "raw_score_unblended": raw,
            "data_coverage": 1.0,
            "presence_dark": False,
            "not_instrumented": False,
            "bonus_xp": 0,
        },
        "outputs": {
            "level": level_state["level"],
            "tier": level_state["tier"],
            "streak_above": level_state["streak_above"],
            "streak_below": level_state["streak_below"],
            "coverage_hold": bool(level_state.get("coverage_hold", False)),
            "xp_earned": xp_earned,
            "xp_delta": xp_delta,
            "xp_total": new_xp,
            "xp_debt": new_debt,
            "xp_buffer": xp_buffer,
            "events": [
                {k: ev.get(k) for k in ("type", "pillar", "old_level", "new_level", "old_tier", "new_tier") if k in ev}
                for ev in level_state.get("events", [])
            ],
        },
    }
    headline_level = level_state["level"]  # single pillar, weight renormalizes to 1
    headline_events = []
    if headline_level > 1:
        headline_events.append({"type": "character_level_up", "old_level": 1, "new_level": headline_level})
    return {
        "date": date,
        "engine_version": ce.ENGINE_VERSION,
        "progression_transitions": {
            "day_number": 30,
            "pillars": {"movement": transition},
            "headline": {"inputs": {"prev_character_level": 1}, "outputs": {"character_level": headline_level, "events": headline_events}},
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# AC1 · capture + receipt contents
# ══════════════════════════════════════════════════════════════════════════════


def test_engine_captures_transitions_for_every_pillar_and_headline():
    rec = _sheet()
    tr = rec.get("progression_transitions")
    assert tr, "engine must capture transitions at fire time"
    assert set(tr["pillars"].keys()) == set(PILLARS)
    for name in PILLARS:
        t = tr["pillars"][name]
        assert "inputs" in t and "outputs" in t
        assert "level_score" in t["inputs"] and "raw_score" in t["inputs"]
        assert "level" in t["outputs"] and "xp_delta" in t["outputs"]
    assert tr["headline"]["outputs"]["character_level"] == rec["character_level"]


def test_receipt_carries_formula_version_config_hash_inputs_and_digest():
    cfg = _cfg()
    rows = [{"pk": "USER#matthew#SOURCE#strava", "sks": ["DATE#2026-08-01"]}]
    receipt = _receipt(config=cfg, input_rows=rows)
    assert receipt["engine_version"] == ce.ENGINE_VERSION
    assert receipt["config_hash"] == pr.config_hash(cfg)
    assert receipt["input_rows"] == rows
    assert len(receipt["digest"]) == 64  # sha256 hex


def test_stored_sheet_item_never_carries_the_raw_capture():
    """The capture persists to the RECEIPT partition only — the sheet item is
    stripped (size + single-source-of-truth)."""

    class _Tbl:
        item = None

        def put_item(self, Item):
            _Tbl.item = Item

    rec = _sheet()
    ce.store_character_sheet(_Tbl(), "USER#matthew#SOURCE#", rec)
    assert _Tbl.item is not None
    assert "progression_transitions" not in _Tbl.item
    assert _Tbl.item["pk"] == "USER#matthew#SOURCE#character_sheet"


def test_no_transitions_means_no_receipt_adr104():
    """A record with no captured inputs (sick-day freeze, pre-#1373 history)
    must yield None — a receipt is never fabricated."""
    assert pr.build_receipt({"date": "2026-08-01"}, _cfg()) is None
    assert pr.build_receipt({"date": "2026-08-01", "progression_transitions": {"pillars": {}}}, _cfg()) is None


# ══════════════════════════════════════════════════════════════════════════════
# AC2 · deterministic replay reproduces the digest (through the DDB round-trip)
# ══════════════════════════════════════════════════════════════════════════════


def test_replay_reproduces_digest_from_the_stored_decimal_item():
    cfg = _cfg()
    receipt = _receipt(config=cfg)
    verdict = pr.replay(_ddb_round_trip(receipt), cfg, engine=ce)
    assert verdict["digest_match"] is True
    assert verdict["outputs_match"] is True
    assert verdict["config_drift"] is False
    assert verdict["engine_drift"] is False
    assert verdict["mismatches"] == []


def test_replay_reproduces_digest_across_a_multi_day_chain():
    """Day 2 replays clean too — prev-state inputs (levels/XP/streaks/buffer)
    round-trip and re-feed the gates exactly."""
    cfg = _cfg()
    day1 = _sheet(config=cfg)
    hist = {p: [60.0] * 10 for p in PILLARS}
    day2 = ce.compute_character_sheet(_data("2026-08-02"), day1, hist, cfg)
    receipt = pr.build_receipt(day2, cfg, input_rows=[])
    verdict = pr.replay(_ddb_round_trip(receipt), cfg, engine=ce)
    assert verdict["digest_match"] is True, verdict["mismatches"]


def test_store_receipt_item_is_decimal_only_and_keyed_right():
    """boto3 rejects Python floats — the stored item must be float-free, at
    FULL precision (Decimal(str(x)) round-trips exactly; see module doc)."""

    class _Tbl:
        item = None

        def put_item(self, Item):
            _Tbl.item = Item

    receipt = _receipt()
    pr.store_receipt(_Tbl(), "USER#matthew#SOURCE#character_receipt", receipt)
    item = _Tbl.item
    assert item["pk"] == "USER#matthew#SOURCE#character_receipt"
    assert item["sk"] == "DATE#2026-08-01"

    def _no_floats(obj, path="item"):
        assert not isinstance(obj, float), f"float leaked into DDB item at {path}"
        if isinstance(obj, dict):
            for k, v in obj.items():
                _no_floats(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                _no_floats(v, f"{path}[{idx}]")

    _no_floats(item)
    # And the round-trip of THAT item still replays clean.
    verdict = pr.replay(item, _cfg(), engine=ce)
    assert verdict["digest_match"] is True


# ══════════════════════════════════════════════════════════════════════════════
# AC4 · mutate a config value → replay digest mismatch is DETECTED
# ══════════════════════════════════════════════════════════════════════════════


def test_config_mutation_is_detected_as_digest_mismatch_with_config_drift():
    cfg = _cfg()
    item = _ddb_round_trip(_receipt(config=cfg))

    mutated = copy.deepcopy(cfg)
    mutated["leveling"]["xp_per_level"] = 50  # the technologist changed the math
    verdict = pr.replay(item, mutated, engine=ce)
    assert verdict["digest_match"] is False, "a mutated config MUST break the replay digest"
    assert verdict["config_drift"] is True, "…and be attributed to config drift, not mystery"


def test_pillar_weight_mutation_breaks_the_headline_replay():
    """Headline replay recomputes from CURRENT config weights — a weight edit
    is drift, because the weights are covered by config_hash, not stored."""
    cfg = _cfg()
    item = _ddb_round_trip(_receipt(config=cfg))
    mutated = copy.deepcopy(cfg)
    for p in mutated["pillars"].values():
        p["weight"] = 999  # grotesque on purpose — must not replay clean
    verdict = pr.replay(item, mutated, engine=ce)
    assert verdict["digest_match"] is False
    assert verdict["config_drift"] is True


def test_xp_band_mutation_changes_replayed_outputs():
    """Not just the hash: a band change actually re-runs to DIFFERENT outputs
    (xp_delta), proving replay executes the math rather than comparing hashes."""
    cfg = _cfg()
    record = _manual_record(cfg, raw=75.0)  # full coverage — XP genuinely flows
    item = _ddb_round_trip(pr.build_receipt(record, cfg, input_rows=[]))
    # Sanity: the same item replays clean under the unmutated config first.
    assert pr.replay(item, cfg, engine=ce)["verified"] is True
    mutated = copy.deepcopy(cfg)
    mutated["xp_bands"] = [{"min_raw_score": 0, "xp": 50}]  # everything earns 50
    verdict = pr.replay(item, mutated, engine=ce)
    assert verdict["verified"] is False
    assert verdict["config_drift"] is True
    assert any(m["field"] in ("xp_delta", "xp_total", "xp_earned") for m in verdict["mismatches"]), verdict["mismatches"][:5]


def test_tampered_outputs_read_as_the_alarm_case_no_drift_flags():
    """A receipt whose stored outputs no longer follow from its stored inputs —
    with an UNCHANGED config and engine — is the nondeterminism/tamper alarm.
    NB the DIGEST alone cannot see a forged output (the replayed digest is
    built over the honest recomputation) — outputs_match is the tripwire,
    which is exactly why the verdict's `verified` combines both."""
    cfg = _cfg()
    receipt = _receipt(config=cfg)
    tampered = copy.deepcopy(receipt)
    tampered["transitions"]["pillars"]["movement"]["outputs"]["level"] = 99  # forged level
    verdict = pr.replay(_ddb_round_trip(tampered), cfg, engine=ce)
    assert verdict["verified"] is False
    assert verdict["outputs_match"] is False
    assert verdict["config_drift"] is False and verdict["engine_drift"] is False
    assert any(m["pillar"] == "movement" and m["field"] == "level" for m in verdict["mismatches"])


def test_engine_version_drift_is_labeled():
    cfg = _cfg()
    receipt = _receipt(config=cfg)
    receipt["engine_version"] = "0.0.1"  # a receipt from an older formula
    receipt["digest"] = pr.digest_of(receipt)
    verdict = pr.replay(_ddb_round_trip(receipt), cfg, engine=ce)
    assert verdict["engine_drift"] is True
    assert verdict["digest_match"] is False


# ══════════════════════════════════════════════════════════════════════════════
# input-row provenance (compute lambda helper) — honest by construction
# ══════════════════════════════════════════════════════════════════════════════


def test_collect_input_rows_records_only_fetched_rows(monkeypatch):
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    os.environ.setdefault("EMAIL_RECIPIENT", "t@example.com")
    os.environ.setdefault("EMAIL_SENDER", "t@example.com")
    from compute import character_sheet_lambda as csl

    data = _data()
    data["hevy_workout_days_7d"] = ["2026-07-30"]
    rows = csl.collect_input_rows(data, history_records=[{"pk": "USER#matthew#SOURCE#character_sheet", "sk": "DATE#2026-07-31"}])
    by_pk = {r.get("pk"): r for r in rows if "pk" in r}
    assert by_pk["USER#matthew#SOURCE#apple_health"]["sks"] == ["DATE#2026-08-01"]
    assert by_pk["USER#matthew#SOURCE#strava"]["sks"] == ["DATE#2026-08-01"]
    assert by_pk["USER#matthew#SOURCE#character_sheet"]["sks"] == ["DATE#2026-07-31"]
    # Sources that were NOT fetched never appear — no fabricated provenance.
    assert "USER#matthew#SOURCE#whoop" not in by_pk
    derived = [r for r in rows if r.get("derived") == "hevy_workout_days_7d"]
    assert derived and derived[0]["values"] == ["2026-07-30"]


# ══════════════════════════════════════════════════════════════════════════════
# /api/character_receipt — read-only drill-down endpoint
# ══════════════════════════════════════════════════════════════════════════════


class _FakeTable:
    def __init__(self, items_by_sk=None):
        self.items = items_by_sk or {}

    def get_item(self, Key=None, **kw):
        item = self.items.get(Key["sk"])
        return {"Item": item} if item else {}

    def put_item(self, Item=None, **kw):
        self.items[Item["sk"]] = Item

    def query(self, **kw):
        # latest-first, single item — mirrors ScanIndexForward=False Limit=1
        if not self.items:
            return {"Items": []}
        latest = sorted(self.items.keys())[-1]
        return {"Items": [self.items[latest]]}


def _endpoint(monkeypatch, items_by_sk):
    from web import site_api_vitals as vitals

    monkeypatch.setattr(vitals, "table", _FakeTable(items_by_sk))
    return vitals


def _stored_receipt_item(cfg):
    receipt = _receipt(config=cfg)
    item = pr.store_receipt(_FakeTable(), "USER#matthew#SOURCE#character_receipt", receipt)
    return item


def test_endpoint_absent_date_answers_available_false(monkeypatch):
    import json as _json

    vitals = _endpoint(monkeypatch, {})
    resp = vitals.handle_character_receipt(date="2026-01-01")
    body = _json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["available"] is False
    assert "never" in body["reason"] or "ADR-104" in body["reason"]


def test_endpoint_serves_stored_receipt_by_date(monkeypatch):
    import json as _json

    cfg = _cfg()
    item = _stored_receipt_item(cfg)
    vitals = _endpoint(monkeypatch, {"DATE#2026-08-01": item})
    resp = vitals.handle_character_receipt(date="2026-08-01")
    body = _json.loads(resp["body"])
    assert body["available"] is True
    assert body["receipt"]["engine_version"] == ce.ENGINE_VERSION
    assert len(body["receipt"]["digest"]) == 64
    assert body["replay"] is None  # verify not requested
    assert "pk" not in body["receipt"] and "sk" not in body["receipt"]


def test_endpoint_rejects_malformed_date(monkeypatch):
    vitals = _endpoint(monkeypatch, {})
    assert vitals.handle_character_receipt(date="20-01-01")["statusCode"] == 400


def test_endpoint_verify_replays_against_live_config(monkeypatch):
    import io
    import json as _json

    cfg = _cfg()
    item = _stored_receipt_item(cfg)
    vitals = _endpoint(monkeypatch, {"DATE#2026-08-01": item})

    class _FakeS3:
        def get_object(self, Bucket=None, Key=None):
            return {"Body": io.BytesIO(_json.dumps(cfg).encode())}

    class _FakeBoto3:
        @staticmethod
        def client(*a, **k):
            return _FakeS3()

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3)
    resp = vitals.handle_character_receipt(date="2026-08-01", verify=True)
    body = _json.loads(resp["body"])
    assert body["replay"]["digest_match"] is True
    assert body["replay"]["config_drift"] is False


def test_endpoint_verify_labels_config_drift(monkeypatch):
    import io
    import json as _json

    cfg = _cfg()
    item = _stored_receipt_item(cfg)
    vitals = _endpoint(monkeypatch, {"DATE#2026-08-01": item})

    drifted = copy.deepcopy(cfg)
    drifted["leveling"]["xp_per_level"] = 42

    class _FakeS3:
        def get_object(self, Bucket=None, Key=None):
            return {"Body": io.BytesIO(_json.dumps(drifted).encode())}

    class _FakeBoto3:
        @staticmethod
        def client(*a, **k):
            return _FakeS3()

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3)
    resp = vitals.handle_character_receipt(date="2026-08-01", verify=True)
    body = _json.loads(resp["body"])
    assert body["replay"]["digest_match"] is False
    assert body["replay"]["config_drift"] is True


# ══════════════════════════════════════════════════════════════════════════════
# canonicalization — the digest survives the int/float/Decimal identity swamp
# ══════════════════════════════════════════════════════════════════════════════


def test_norm_makes_int_float_decimal_agree():
    assert pr.canonical_json({"a": 3}) == pr.canonical_json({"a": 3.0}) == pr.canonical_json({"a": Decimal("3")})
    assert pr.canonical_json({"a": 2.5}) == pr.canonical_json({"a": Decimal("2.5")})
    assert pr.canonical_json({"a": True}) != pr.canonical_json({"a": 1})  # bools stay bools
