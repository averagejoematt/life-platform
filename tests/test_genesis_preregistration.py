"""tests/test_genesis_preregistration.py — the #976 genesis pre-registration pair.

Pins the contracts that make the pre-registration moment trustworthy:
  1. The seeder's PREDICTION# records are in the EXACT shape handle_predictions
     (lambdas/web/site_api_coach.py) reads and the daily evaluator grades — pk/sk
     format, status vocabulary, eval spec built by coach_state_updater's own
     builder (parity by construction, asserted anyway).
  2. Re-running over the same frozen claims is idempotent (identical fixed sks).
  3. The pre-registered hypotheses pass the hypothesis engine's OWN validator
     (required fields, numeric criteria, #530 test_spec vocabulary).
  4. The published artifact carries ZERO reset/cycle/prior-attempt language
     (the presentation rule), references the frozen claims, links the grading
     ledger, and is dated genesis − 1.
  5. The deterministic fallback predictions themselves pass the seeder's validator
     (they are the guarantee that all 8 coaches can go on the record).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))


def _load(module_name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


seeder = _load("seed_genesis_preregistration", "deploy/seed_genesis_preregistration.py")
publisher = _load("publish_genesis_preregistration", "deploy/publish_genesis_preregistration.py")


def _fixture_frozen():
    """A frozen-file fixture shaped exactly like the seeder writes it."""
    coaches = {}
    for coach_id, coach_name, _domain in seeder.COACHES:
        fb = dict(seeder.FALLBACK_PREDICTIONS[coach_id], generator="fallback_deterministic")
        coaches[coach_id] = {"coach_name": coach_name, "predictions": [fb]}
    return {
        "genesis": seeder.EXPERIMENT_START_DATE,
        "generated_at": "2026-07-11T18:00:00+00:00",
        "coaches": coaches,
        "hypotheses": seeder.build_hypotheses(json.loads((REPO_ROOT / "config" / "user_goals.json").read_text())),
    }


GOALS = json.loads((REPO_ROOT / "config" / "user_goals.json").read_text())
FROZEN = _fixture_frozen()

# Derive the reset-sensitive dates from the live genesis so a re-anchor (restart
# pipeline) never reds main here again — the seeder builds prediction ids from
# EXPERIMENT_START_DATE and the publisher dates the artifact genesis − 1.
from datetime import date as _date, timedelta as _timedelta  # noqa: E402

GENESIS_COMPACT = seeder.EXPERIMENT_START_DATE.replace("-", "")
GENESIS_MINUS_1 = (_date.fromisoformat(seeder.EXPERIMENT_START_DATE) - _timedelta(days=1)).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# 1. PREDICTION# record shape — what handle_predictions + the evaluator expect
# ──────────────────────────────────────────────────────────────────────────────


def test_prediction_records_match_api_read_shape():
    records = seeder.build_prediction_records(FROZEN)
    # all 8 coaches on the record, roster ids exactly as the API maps them
    api_coach_pks = {f"COACH#{c}_coach" for c in ("sleep", "nutrition", "training", "mind", "physical", "glucose", "labs", "explorer")}
    assert {r["pk"] for r in records} == api_coach_pks

    for rec in records:
        assert rec["sk"].startswith(f"PREDICTION#pred_{GENESIS_COMPACT}_"), rec["sk"]
        assert rec["prediction_id"] == rec["sk"].split("PREDICTION#", 1)[1]
        assert rec["created_date"] == seeder.EXPERIMENT_START_DATE
        assert rec["status"] == "pending"  # in handle_predictions' _BUCKETS
        assert rec["claim_natural"].strip()
        # confidence is the numeric _parse_confidence output (existing record parity)
        assert isinstance(rec["confidence"], float) and 0.0 <= rec["confidence"] <= 1.0
        assert rec["subdomain"]
        assert rec["surfaced_to_subject"] is True
        assert rec["pre_registered"] is True
        assert rec["pre_registered_at"] == FROZEN["generated_at"]

        ev = rec["evaluation"]
        assert ev["type"] in ("directional", "qualitative")
        assert isinstance(ev["evaluation_window_days"], int) and ev["evaluation_window_days"] >= 7
        if ev["type"] == "directional":
            from experiment.measurable_metrics import MEASURABLE_METRICS

            base = ev["metric"]
            for suffix in ("_7day_avg", "_14day_avg", "_30day_avg"):
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
            assert base in MEASURABLE_METRICS, ev["metric"]
            assert ev["condition"] in ("up", "down")
            assert ev["threshold"] is None  # directional grading is EWMA, not threshold


def test_eval_spec_parity_with_coach_state_updater():
    """The seeder must emit byte-identical eval specs to the coach engine's builder."""
    from coach_state_updater import _build_prediction_eval_spec  # flat import — one module identity suite-wide

    records = seeder.build_prediction_records(FROZEN)
    by_sk = {r["sk"]: r for r in records}
    for coach_id, block in FROZEN["coaches"].items():
        for pred in block["predictions"]:
            sk = f"PREDICTION#pred_{GENESIS_COMPACT}_{seeder._slug(pred['claim_natural'])}"
            expected = _build_prediction_eval_spec(
                pred["metric"] or None,
                pred["direction"] if pred["metric"] else None,
                int(pred["window_days"]),
            )
            assert by_sk[sk]["evaluation"] == expected


def test_seeding_is_idempotent_over_frozen_claims():
    a = {r["sk"] for r in seeder.build_prediction_records(FROZEN)}
    b = {r["sk"] for r in seeder.build_prediction_records(FROZEN)}
    assert a == b
    assert len(a) == sum(len(blk["predictions"]) for blk in FROZEN["coaches"].values())  # no collisions


def test_fallback_predictions_pass_the_validator_and_presentation_rule():
    for coach_id, fb in seeder.FALLBACK_PREDICTIONS.items():
        issues = seeder.validate_prediction(fb)
        assert not issues, f"{coach_id}: {issues}"
        assert seeder.claim_is_clean(fb["claim_natural"]), coach_id


# ──────────────────────────────────────────────────────────────────────────────
# 2. HYPOTHESIS# — validated by the hypothesis engine's own rules
# ──────────────────────────────────────────────────────────────────────────────


def test_hypotheses_pass_engine_validation():
    from hypothesis_engine_lambda import validate_hypothesis  # flat import — one module identity suite-wide

    hyps = seeder.build_hypotheses(GOALS)
    assert len(hyps) >= 1
    for hyp in hyps:
        ok, issues = validate_hypothesis(hyp)
        assert ok, f"{hyp['hypothesis_id']}: {issues}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. The published artifact — presentation rule + content contract
# ──────────────────────────────────────────────────────────────────────────────

_CYCLE_LANGUAGE = re.compile(r"cycle|reset|restart|attempt|last time|previous|start(?:ing|ed)? over|try again", re.IGNORECASE)


def test_artifact_has_no_cycle_or_prior_attempt_language():
    record = publisher.build_chronicle_record(GOALS, FROZEN)
    for field in ("title", "stats_line", "content_markdown", "content_html", "subtitle"):
        hits = _CYCLE_LANGUAGE.findall(str(record[field]))
        assert not hits, f"{field} leaks cycle language: {sorted(set(hits))}"
    # and the rendered full page too (chrome + body)
    page = publisher.leadin.render_post_html(
        record["title"], record["stats_line"], record["content_html"], "Prologue · Part IV", record["date"], 4
    )
    body_zone = page.split("<main", 1)[1]
    assert not _CYCLE_LANGUAGE.findall(body_zone.split("</main>", 1)[0])


def test_artifact_content_contract():
    record = publisher.build_chronicle_record(GOALS, FROZEN)
    # dated genesis − 1, pre-genesis chronicle shape
    assert record["date"] == GENESIS_MINUS_1
    assert record["sk"] == f"DATE#{GENESIS_MINUS_1}"
    assert record["phase"] == "experiment"
    assert record["author"] == "Elena Voss"
    md = record["content_markdown"]
    # every frozen claim is quoted verbatim
    for block in FROZEN["coaches"].values():
        for pred in block["predictions"]:
            assert pred["claim_natural"] in md, pred["claim_natural"][:60]
        assert block["coach_name"] in md
    # the falsification framing + the grading ledger link
    assert 'href="/method/predictions/"' in md
    assert "come back and grade us" in md.lower()
    # the plan's real numbers (ADR-104: grounded, never fabricated)
    assert str(GOALS["timeline"]["start_weight_lbs"]) in md
    assert str(GOALS["targets"]["weight"]["goal_lbs"]) in md
    # #3535: these were hand-typed ("1,500" and "170") two lines after their
    # neighbours derived from GOALS, so a PLAN EDIT redded the test while a
    # regeneration bug could not. Derive them the same way, in the publisher's own
    # render form (`{:,}` for the calorie target, bare for the protein floor).
    nut = GOALS["targets"]["nutrition"]
    assert f"{nut['daily_calories_target']:,}" in md
    assert str(nut["daily_protein_min_g"]) in md
    # no fabricated "finish-line odds" number
    assert "odds" not in md.lower()


def test_artifact_series_label_is_prologue_for_pregenesis_date():
    all_dates = ["2026-07-06", "2026-07-08", "2026-07-09", "2026-07-11"]
    assert publisher.leadin.series_label("2026-07-11", all_dates, 0) == "Prologue · Part IV"
    assert publisher.leadin.seq_for("2026-07-11", all_dates, 0) == 4


def test_publisher_banned_language_gate_catches_a_dirty_claim():
    dirty = json.loads(json.dumps(FROZEN))
    first = next(iter(dirty["coaches"].values()))
    first["predictions"][0]["claim_natural"] = "This attempt will go better after the reset of cycle 5."
    assert publisher.banned_language_issues(first["predictions"][0]["claim_natural"])
    # and the seeder-side validator refuses it too
    assert any("presentation rule" in i for i in seeder.validate_prediction(first["predictions"][0]))


# ──────────────────────────────────────────────────────────────────────────────
# 4. Seeder validation semantics
# ──────────────────────────────────────────────────────────────────────────────


def test_validate_prediction_rejects_unfalsifiable_claims():
    base = {
        "claim_natural": "Things will probably improve somehow over the coming period of time",
        "metric": "",
        "direction": None,
        "window_days": 14,
        "confidence": "medium",
    }
    issues = seeder.validate_prediction(base)
    assert any("no number" in i for i in issues)

    bad_metric = dict(base, claim_natural="HRV rises 5 ms in 14 days", metric="vibes_index", direction="up")
    assert any("MEASURABLE_METRICS" in i for i in seeder.validate_prediction(bad_metric))

    no_dir = dict(base, claim_natural="Weight changes by 2 lbs in 14 days", metric="weight_lbs", direction=None)
    assert any("direction" in i for i in seeder.validate_prediction(no_dir))


def test_frozen_genesis_mismatch_refuses(tmp_path, monkeypatch):
    stale = {"genesis": "2026-06-14", "generated_at": "x", "coaches": {}}
    p = tmp_path / "genesis_preregistration.json"
    p.write_text(json.dumps(stale))
    monkeypatch.setattr(seeder, "FROZEN_PATH", p)
    import pytest

    with pytest.raises(SystemExit, match="never silently changes"):
        seeder.load_frozen()


# ──────────────────────────────────────────────────────────────────────────────
# #1970: the seeder's PREDICTION# writes must carry the write-time phase stamp —
# COACH#* is the tagger-blind partition (restart_phase_tag.py only reaches
# USER#matthew#SOURCE#* pks), so an unstamped row survives PHASE_FILTER_EXPRESSION
# forever and leaks into the next reset cycle. _stamped() is the seeder's own
# call-site (same pattern as coach_state_updater._put_item / dispute_docket._stamped);
# write_predictions() is where it must actually apply on every put_item.
# ──────────────────────────────────────────────────────────────────────────────


def test_stamped_merges_write_time_provenance(monkeypatch):
    import experiment.phase_taxonomy as taxonomy

    monkeypatch.setattr(taxonomy, "experiment_stamp", lambda **kw: {"phase": "experiment", "cycle": 12})
    rec = {"pk": "COACH#sleep_coach", "sk": "PREDICTION#pred_x", "claim_natural": "x"}
    stamped = seeder._stamped(rec)
    assert stamped["phase"] == "experiment"
    assert stamped["cycle"] == 12
    # the item's own keys survive untouched
    assert stamped["pk"] == "COACH#sleep_coach" and stamped["sk"] == "PREDICTION#pred_x"


def test_stamped_never_clobbers_an_existing_phase(monkeypatch):
    """The item's own keys win (matches the coach_state_updater/dispute_docket
    precedent) — a caller-supplied phase is never overwritten by the stamp."""
    import experiment.phase_taxonomy as taxonomy

    monkeypatch.setattr(taxonomy, "experiment_stamp", lambda **kw: {"phase": "pilot", "cycle": 99})
    rec = {"pk": "COACH#sleep_coach", "sk": "PREDICTION#pred_x", "phase": "experiment", "cycle": 12}
    stamped = seeder._stamped(rec)
    assert stamped["phase"] == "experiment" and stamped["cycle"] == 12


def test_stamped_fails_soft_on_stamp_error(monkeypatch):
    """experiment_stamp() itself never raises (fail-soft by contract), but _stamped
    defensively wraps the import/call too, matching dispute_docket._stamped — a
    provenance stamp must never break a write."""
    import experiment.phase_taxonomy as taxonomy

    def _boom(**kw):
        raise RuntimeError("ssm down")

    monkeypatch.setattr(taxonomy, "experiment_stamp", _boom)
    rec = {"pk": "COACH#sleep_coach", "sk": "PREDICTION#pred_x"}
    assert seeder._stamped(rec) == rec


def test_write_predictions_stamps_every_item(monkeypatch):
    """The regression this issue exists to prevent: every PREDICTION# row
    write_predictions() puts must carry the write-time phase (+cycle) stamp."""
    import boto3
    import experiment.phase_taxonomy as taxonomy

    class _FakeTable:
        def __init__(self):
            self.puts = []

        def put_item(self, Item):
            self.puts.append(Item)

    fake_table = _FakeTable()

    class _FakeResource:
        def Table(self, name):
            return fake_table

    monkeypatch.setattr(boto3, "resource", lambda *a, **kw: _FakeResource())
    monkeypatch.setattr(taxonomy, "experiment_stamp", lambda **kw: {"phase": "experiment", "cycle": 12})

    records = seeder.build_prediction_records(FROZEN)
    seeder.write_predictions(records)

    assert len(fake_table.puts) == len(records) and records, "the fixture must actually produce records to prove anything"
    for item in fake_table.puts:
        assert item.get("phase") == "experiment", f"{item.get('sk')} missing phase — the #1970 regression"
        assert item.get("cycle") == 12
        assert item["pk"].startswith("COACH#") and item["sk"].startswith("PREDICTION#")
