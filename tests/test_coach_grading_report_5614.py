"""tests/test_coach_grading_report_5614.py — the grading and provenance report (#5614, epic #5607).

A small captured-shape row set, no AWS, no network. Proves: the report's denominator IS coach_record's on the same rows
(per coach and pooled, a docket bet's two sides kept apart), the legacy / restated / re-verified / docket classification,
the correction audit's pairing and served flags, that the script cannot write (source scan + a handle that only queries +
GET-only HTTP), and that two runs on unchanged rows are byte-identical outside the run-time field.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "coach_grading_report.py")
sys.path.insert(0, os.path.join(ROOT, "lambdas"))


def _load():
    spec = importlib.util.spec_from_file_location("coach_grading_report_5614", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load()
from coach import coach_record  # noqa: E402

GENESIS = R.EXPERIMENT_START_DATE
AS_OF = "2026-11-02"


def _notes(algo):
    return json.dumps({"actual_value": 1.0, "reason": "r", "algo_version": algo})


def _row(coach, slug, status, outcome_date, *, ev=None, algo="1.0", **extra):
    pid = f"pred_{slug}"
    row = {
        "pk": f"COACH#{coach}_coach",
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "coach_id": f"{coach}_coach",
        "status": status,
        "outcome": status,
        "outcome_date": outcome_date,
        "created_date": "2026-10-01",
        "confidence": 0.5,
        "claim_natural": f"Recovery will rise ({slug}).",
        "evaluation": {"type": "directional", "metric": "recovery_score", "condition": "up", "evaluation_window_days": 7},
        "subdomain": "recovery",
        "phase": "experiment",
    }
    if algo is not None:
        row["outcome_notes"] = _notes(algo)
    if ev is not None:
        row["evaluator_version"] = ev
    row.update(extra)
    return row


CORR_AT = "2026-11-01T18:11:57Z"
ENTRY = {
    "original_status": "confirmed",
    "original_outcome_date": "2026-10-20",
    "original_outcome_notes": _notes("1.0"),
    "corrected_status": "expired",
    "corrected_outcome_date": "2026-10-28",
    "corrected_outcome_notes": _notes("1.1"),
    "corrected_at": CORR_AT,
    "reason": "#5533 (e): HR regime",
    "evaluator_version": "1.1",
}


def fixture() -> dict:
    docket = dict(source="dispute_docket", algo=None, evaluation=None)
    sleep = [
        _row("sleep", "legacy_a", "confirmed", "2026-10-10"),
        _row("sleep", "legacy_b", "refuted", "2026-10-11"),
        _row("sleep", "reverified", "refuted", "2026-10-12", ev="1.1", algo="1.1", quality_flags=[]),
        _row("sleep", "restated", "refuted", "2026-10-13", ev="1.1", algo="1.0", quality_flags=["low_power"]),
        _row("sleep", "docket_x", "confirmed", "2026-10-14", **docket),
        # the #4216 re-write of the same docket row: a later outcome_date, never counted twice
        {**_row("sleep", "docket_x", "confirmed", "2026-10-20", **docket), "sk": "PREDICTION#pred_docket_x-2"},
        _row("sleep", "pre_genesis", "confirmed", "2026-08-01"),  # resolved before Day 1: lifetime only
        _row("sleep", "tomb", "refuted", "2026-10-01", tombstone=True),  # archived cycle: lifetime only
        _row("sleep", "open", "pending", ""),
        _row("sleep", "obs", "observation", "", evaluation={"type": "qualitative"}),
        _row(
            "sleep",
            "corrected",
            "expired",
            "2026-10-28",
            ev="1.1",
            algo="1.1",
            corrections=[ENTRY],
            original_grade={"status": "confirmed", "snapshot_at": CORR_AT},
        ),
        _row(
            "sleep",
            "respec",
            "refuted",
            "2026-10-15",
            respecified_at="2026-10-11T02:48:10Z",
            respecified_reason="#4618: re-derived",
            respecified_from={"status": "pending"},
            verdict_correction={"issue": "#4617", "new_status": "refuted", "prior": {"status": "confirmed", "outcome_date": "2026-09-30"}},
        ),
        # a journal-silenced row: counted in K of N, never listed on the ledger
        _row("sleep", "the_journal_has_gone_silent", "confirmed", "2026-10-16", claim_natural="The journal has gone silent this week."),
    ]
    explorer = [
        # the OTHER side of the same docket bet, under the same id on another partition — a second call
        _row("explorer", "docket_x", "refuted", "2026-10-14", **docket),
        _row("explorer", "legacy_c", "confirmed", "2026-10-18"),
    ]
    corrections = {
        "sleep": [
            {
                "pk": "COACH#sleep_coach",
                "sk": f"CORRECTION#pred_corrected#{CORR_AT}",
                "prediction_id": "pred_corrected",
                "coach_id": "sleep_coach",
                **ENTRY,
            }
        ]
    }
    preds = {s: [] for s in R._CALIB_COACH_NAMES}
    preds["sleep"], preds["explorer"] = sleep, explorer
    return {"predictions": preds, "corrections": corrections, "diary_corrected": [], "summaries": []}


@pytest.fixture()
def report():
    return R.build_report(fixture(), as_of=AS_OF, api=None, git={"sha": "test", "dirty_paths": []})


def test_denominator_is_coach_records_on_the_same_rows(report):
    rows = fixture()["predictions"]
    total = 0
    for short, prs in rows.items():
        want = coach_record.record_from_rows(prs, genesis=GENESIS, as_of=AS_OF)
        got = report["coaches"][short]["cycle"]["record"]
        assert got == want, short
        total += want["n"]
        life = coach_record.record_from_rows(prs, genesis=GENESIS, career=True)
        assert report["coaches"][short]["lifetime"]["n"] == life["n"], short
    oc = report["overall"]["cycle"]
    assert oc["n"] == total
    # sleep: legacy_a, legacy_b, reverified, restated, docket_x (once), respec, journal-silenced = 7; explorer: 2
    assert report["coaches"]["sleep"]["cycle"]["n"] == 7
    assert report["coaches"]["explorer"]["cycle"]["n"] == 2
    assert oc["n"] == 9 and oc["k_right"] == 4  # sleep: legacy_a, docket_x, journal-silenced; explorer: legacy_c
    assert oc["pct"] is None  # 9 < PERCENT_FLOOR
    assert oc["calls"]["expired"] == 1 and oc["calls"]["pending"] == 1 and oc["calls"]["observational"] == 1
    assert report["overall"]["lifetime"]["n"] == total + 2  # + pre_genesis + tombstoned
    assert oc["wilson95_pct"] is not None and oc["confidence"]["at_exactly_0_5"] == 9


def test_legacy_and_reverified_classification(report):
    pv = report["provenance"]
    ids = {
        k: sorted(r["coach"] + ":" + r["prediction_id"] for r in pv[k])
        for k in ("legacy_unverified", "restated", "reverified", "no_version_no_notes")
    }
    assert ids["legacy_unverified"] == sorted(
        [
            "sleep:pred_legacy_a",
            "sleep:pred_legacy_b",
            "sleep:pred_respec",
            "sleep:pred_the_journal_has_gone_silent",
            "explorer:pred_legacy_c",
        ]
    )
    assert ids["restated"] == ["sleep:pred_restated"]
    assert ids["reverified"] == ["sleep:pred_reverified"]
    assert ids["no_version_no_notes"] == ["explorer:pred_docket_x", "sleep:pred_docket_x"]
    assert pv["graded"]["n"] == report["overall"]["cycle"]["n"]
    assert sum(pv["graded"]["by_class"].values()) == pv["graded"]["n"]
    # the corrected row left N (expired) and is re-verified among the settled rows
    assert [r["prediction_id"] for r in pv["settled_rows"]] == ["pred_corrected"]
    assert pv["settled_not_graded"]["by_class"]["reverified_current"] == 1


def test_provenance_class_rule():
    assert R.provenance_class({"evaluator_version": "1.1", "outcome_notes": _notes("1.1")}, "1.1") == R.REVERIFIED
    assert R.provenance_class({"evaluator_version": "1.1", "outcome_notes": _notes("1.0")}, "1.1") == R.RESTATED
    assert R.provenance_class({"outcome_notes": _notes("1.0")}, "1.1") == R.LEGACY
    assert R.provenance_class({}, "1.1") == R.NO_VERSION
    assert R.provenance_class({"outcome_notes": _notes("1.1")}, "1.1") == R.OTHER


def test_correction_audit_and_ledger_split(report):
    ca = report["corrections"]
    assert ca["by_channel"] == {"corrections": 1, "respecified": 1, "verdict_correction": 1}
    main = [e for e in ca["entries"] if e["channel"] == "corrections"][0]
    assert main["ledger_row"] is True and main["entry_served_with_row"] is True
    assert (main["original_status"], main["corrected_status"], main["corrected_at"]) == ("confirmed", "expired", CORR_AT)
    assert main["entry_served_live"] is None  # no API read
    legacy = [e for e in ca["entries"] if e["channel"] != "corrections"]
    assert all(e["entry_served_with_row"] is False and e["ledger_row"] is False for e in legacy)
    respec = [e for e in legacy if e["channel"] == "respecified"][0]
    assert respec["original_outcome_date"] is None and respec["corrected_status"] is None  # not stored → null, never inferred
    assert ca["ledger_rows_without_row_entry"] == []
    lg = report["ledger"]
    assert lg["withheld_journal_silence"] == 1 and lg["withheld_graded"] == 1
    assert lg["record_total"] == lg["served"] + 1


def test_reconciliation_flags_a_drifted_api_number(report):
    api = {
        "predictions": {
            "overall": {**report["overall"]["cycle"]["calls"], "confirmed": 999, "lifetime": report["overall"]["lifetime"]["calls"]}
        },
        "coaches": {"coaches": []},
        "calibration": {"coaches": [], "platform": {"n": 0, "strata": {}}},
        "ledger_export": [],
    }
    rec = R.reconcile(report, api, served_ids=set(), local_items={})
    fields = {(m["surface"], m["field"]) for m in rec["unexplained"]}
    assert ("/api/predictions overall", "confirmed") in fields
    assert ("/api/predictions overall", "refuted") not in fields
    retired = [m for m in rec["mismatches"] if m["surface"] == "/api/coaches" and m["field"].startswith("training.")]
    assert retired and "retired seat" in retired[0]["explanation"]


# ── read-only by construction ────────────────────────────────────────────────────────────────────────────────────────

WRITE_VERBS = re.compile(
    r"\b(put_item|update_item|delete_item|batch_writer|batch_write_item|transact_write_items|delete_table|create_table|"
    r"update_table|write_stamp|apply_correction|revert_correction|stamp_quality|unstamp_quality|write_summary|put_object|"
    r"delete_object|put_parameter|invoke)\b"
)


def test_script_source_names_no_write_verb():
    with open(SCRIPT, encoding="utf-8") as fh:
        src = fh.read()
    assert not WRITE_VERBS.findall(src)
    assert not re.search(r"method\s*=\s*['\"](POST|PUT|PATCH|DELETE)['\"]", src)
    assert src.count("urllib.request.Request(") == 1 and 'method="GET"' in src


def test_table_handle_only_queries():
    calls = []

    class Fake:
        def query(self, **kw):
            calls.append("query")
            return {"Items": []}

        def put_item(self, **kw):  # pragma: no cover — must be unreachable
            calls.append("put_item")

    t = R.ReadOnlyTable(Fake())
    for verb in ("put_item", "update_item", "delete_item", "batch_writer", "meta"):
        with pytest.raises(PermissionError):
            getattr(t, verb)
    with pytest.raises(PermissionError):
        t.anything = 1
    rows = R.read_rows(t)
    assert set(calls) == {"query"}
    assert rows["predictions"] and all(v == [] for v in rows["predictions"].values())


def test_api_reads_are_get_only(monkeypatch):
    seen = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return json.dumps(self.body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen.append((req.get_method(), req.full_url))
        return Resp({"pages": 2} if "ledger_export" in req.full_url else {})

    monkeypatch.setattr(R.urllib.request, "urlopen", fake_urlopen)
    api = R.fetch_api()
    assert {m for m, _ in seen} == {"GET"}
    assert len(api["ledger_export"]) == 2 and len(seen) == 5


# ── reproducibility ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_two_runs_on_unchanged_rows_are_byte_identical(tmp_path):
    fx = tmp_path / "rows.json"
    fx.write_text(json.dumps(fixture()))
    outs = []
    for name in ("a", "b"):
        d = tmp_path / name
        assert R.main(["--out", str(d), "--offline", str(fx), "--no-api", "--as-of", AS_OF]) == 0
        outs.append(d)
    a_md, b_md = ((d / "report.md").read_bytes() for d in outs)
    assert a_md == b_md
    a, b = (json.loads((d / "report.json").read_text()) for d in outs)
    assert set(a) == {"run", "report"} and "run_at" in a["run"]
    assert a["report"] == b["report"]
    assert a["run"]["run_at"].encode() not in a_md
    rp = a["report"]["reproducibility"]
    assert rp["evaluator_version"] == R.CURRENT and rp["rows_read"]["prediction_rows_total"] == 15 and len(rp["input_sha256"]) == 64


def test_input_hash_ignores_query_order_and_tracks_content():
    fx = fixture()
    h = R.input_hash(fx)
    rev = {**fx, "predictions": {k: list(reversed(v)) for k, v in fx["predictions"].items()}}
    assert R.input_hash(rev) == h
    fx["predictions"]["sleep"][0]["status"] = "refuted"
    assert R.input_hash(fx) != h
