"""tests/test_restart_pipeline_hooks.py — #1092 dry-run pipeline plumbing (no AWS).

Pins the post-verify hook sequence (build_post_verify_hooks) and the dedup pass's
pure logic (fingerprint / find_duplicate_groups / validate_source — generalized
from the verified eightsleep UTC-rollover duplicates). Nothing here touches AWS:
the hook builder is pure, and the dedup units run on fixture rows.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pipeline = _load("restart_pipeline")
dedup = _load("dedup_source_records")


# ── build_post_verify_hooks: the #1092 hook sequence ──────────────────────────


def test_default_hooks_are_prologue_fix_only():
    # Byte-compat guarantee: with no new flags, the ONLY behavior change is the
    # issue-sanctioned default-on fix_prologue hook.
    hooks = pipeline.build_post_verify_hooks()
    assert [n for n, _ in hooks] == ["fix_prologue_cycle_and_subscribe_ttl"]


def test_skip_prologue_fix_empties_the_default():
    assert pipeline.build_post_verify_hooks(skip_prologue_fix=True) == []


def test_full_hook_sequence_and_order():
    hooks = pipeline.build_post_verify_hooks(with_preregistration=True, dedup_sources=["eightsleep", "whoop"])
    assert [n for n, _ in hooks] == [
        "fix_prologue_cycle_and_subscribe_ttl",  # (a) — must follow the SSM cycle bump; post-verify satisfies it
        "seed_genesis_preregistration",  # (b) — opt-in --with-preregistration
        "dedup_eightsleep",  # (c) — one pass per --dedup-source, in order
        "dedup_whoop",
    ]


def test_hook_commands_are_run_step_compatible():
    # run_step strips "--apply" in dry-run mode — every hook must carry it so the
    # dry-run pipeline previews the hooks like existing sub-steps.
    hooks = pipeline.build_post_verify_hooks(with_preregistration=True, dedup_sources=["eightsleep"])
    for name, cmd in hooks:
        assert cmd[0] == "python3" and cmd[1].startswith("deploy/"), (name, cmd)
        assert "--apply" in cmd, f"hook {name} would never write even under --apply"


def test_dedup_hook_passes_the_source_through():
    ((_, cmd),) = [h for h in pipeline.build_post_verify_hooks(dedup_sources=["eightsleep"]) if h[0] == "dedup_eightsleep"]
    assert cmd[cmd.index("--source") + 1] == "eightsleep"


def test_build_sub_scripts_sequence():
    # The sub-script sequence, pinned. sync_doc_metadata (2026-07-18) MUST be last so the
    # reset converges the genesis/cycle doc literals (SCHEMA.md, CLAUDE.md, site_api_common)
    # itself — leaving it out reds the doc-facts gate on the commit of the reset artifacts.
    names = [n for n, _ in pipeline.build_sub_scripts(False, [], "2026-06-14", 4)]
    assert names == [
        "restart_phase_tag",
        "restart_intelligence_wipe",
        "restart_ledger_reset",
        "restart_chronicle_handler",
        "restart_media_reset",
        "restart_leadin_pages",
        "restart_character_rebuild",
        "restart_site_copy_sync",
        "restart_docs_update",
        "sync_doc_metadata",
    ]
    # The doc-literal sync must run AFTER restart_docs_update (docs first, then literal reconcile).
    assert names.index("sync_doc_metadata") > names.index("restart_docs_update")


# ── clear_predict_week_subject: the #1198 reset step ─────────────────────────


class _FakeS3:
    def __init__(self):
        self.deletes = []

    def delete_object(self, Bucket=None, Key=None, **_kw):
        self.deletes.append((Bucket, Key))


def test_clear_predict_week_subject_dry_run_touches_no_s3(monkeypatch):
    # Dry-run previews only — it must never reach S3 (the whole pipeline is
    # dry-run-provable before an --apply).
    fake = _FakeS3()
    monkeypatch.setattr(pipeline.boto3, "client", lambda *a, **k: fake)
    pipeline.clear_predict_week_subject(apply=False)
    assert fake.deletes == []


def test_clear_predict_week_subject_apply_deletes_the_artifact(monkeypatch):
    # #1198: --apply retires the manual per-week predict-the-week subject so the
    # new cycle can't inherit the outgoing cycle's frozen open week.
    fake = _FakeS3()
    monkeypatch.setattr(pipeline.boto3, "client", lambda *a, **k: fake)
    pipeline.clear_predict_week_subject(apply=True)
    assert fake.deletes == [("matthew-life-platform", "site/config/current_challenge.json")]


# ── dedup_source_records: the generalized eightsleep pass ─────────────────────

# The verified instance (truth-audit finding 21): one physical night written under
# BOTH DATE#2026-07-10 and DATE#2026-07-11 — identical session, differing only in
# the date dimension + ingestion metadata.
_NIGHT = {
    "sleep_start": "2026-07-10T07:46:59Z",
    "sleep_end": "2026-07-10T14:40:29Z",
    "sleep_hours": Decimal("6.88"),
    "sleep_score": Decimal("77"),
}


def _row(sk: str, ingested: str, **extra):
    return {"pk": "USER#matthew#SOURCE#eightsleep", "sk": sk, "ingested_at": ingested, **_NIGHT, **extra}


def test_utc_rollover_duplicate_grouped_keep_earliest():
    rows = [
        _row("DATE#2026-07-11", "2026-07-11T01:15:00Z"),  # the forward-duplicated copy
        _row("DATE#2026-07-10", "2026-07-10T23:15:00Z"),  # the real wake date
        {
            "pk": "USER#matthew#SOURCE#eightsleep",
            "sk": "DATE#2026-07-09",
            "sleep_start": "2026-07-09T07:00:00Z",
            "sleep_score": Decimal("81"),
        },
    ]
    groups = dedup.find_duplicate_groups(rows)
    assert len(groups) == 1
    keeper, doomed = groups[0][0], groups[0][1:]
    assert keeper["sk"] == "DATE#2026-07-10"  # earliest kept — UTC rollover duplicates FORWARD
    assert [d["sk"] for d in doomed] == ["DATE#2026-07-11"]


def test_phase_and_metadata_differences_do_not_defeat_the_match():
    # The tagger may have stamped the two copies differently — still one session.
    rows = [
        _row("DATE#2026-07-10", "2026-07-10T23:15:00Z", phase="pilot", cycle=Decimal("4")),
        _row("DATE#2026-07-11", "2026-07-11T01:15:00Z", phase="experiment"),
    ]
    assert len(dedup.find_duplicate_groups(rows)) == 1


def test_no_data_marker_rows_never_group():
    # Gap-filled markers are content-identical BY DESIGN (the Withings backfill
    # wrote 8 identical no_data rows) — no session anchor, so never duplicates.
    rows = [{"pk": "p", "sk": f"DATE#2026-07-{d:02d}", "status": "no_data"} for d in range(1, 9)]
    assert dedup.find_duplicate_groups(rows) == []
    assert dedup.fingerprint(rows[0]) is None


def test_distinct_sessions_do_not_group():
    rows = [
        _row("DATE#2026-07-10", "2026-07-10T23:15:00Z"),
        {
            "pk": "USER#matthew#SOURCE#eightsleep",
            "sk": "DATE#2026-07-11",
            "sleep_start": "2026-07-11T07:30:00Z",
            "sleep_end": "2026-07-11T14:10:00Z",
            "sleep_hours": Decimal("6.88"),
            "sleep_score": Decimal("77"),
        },
    ]
    assert dedup.find_duplicate_groups(rows) == []


def test_validate_source_accepts_raw_timeseries_only():
    assert dedup.validate_source("eightsleep") is None
    assert dedup.validate_source("whoop") is None
    # experiment-scoped = the wipe's job (tombstone, never delete)
    assert "not raw_timeseries" in dedup.validate_source("insights")
    # cross-phase = never touched
    assert "not raw_timeseries" in dedup.validate_source("labs")
    # unknown = refuse loudly, never default
    assert "unknown source" in dedup.validate_source("not_a_source")


# ── #1199: void open pre-registered bets to the CROSS_PHASE calibration ledger ──
#
# The reset tombstones open hypotheses + coach PREDICTION#s but never changes their
# status, so an open bet goes phase-hidden while still 'pending' and the weekly engine
# (with_phase_filter) can never re-see it to grade it — every reset silently dropped
# accountability. void_open_bets_at_reset writes one 'voided_at_reset' row per open bet.
# The regression guard: count(open hypotheses + predictions) == count(void CALIB# rows).

_GENESIS = "2026-08-01"
_CLOSING_CYCLE = 6


class _FakeTable:
    """Minimal DynamoDB Table stand-in: begins_with(sk) query by pk (string
    KeyConditionExpression, like restart_intelligence_wipe) + put_item capture."""

    def __init__(self, items_by_pk):
        self._by_pk = items_by_pk
        self.puts = []

    def query(self, **kwargs):
        vals = kwargs["ExpressionAttributeValues"]
        pk, skp = vals[":pk"], vals.get(":skp", "")
        items = [i for i in self._by_pk.get(pk, []) if str(i.get("sk", "")).startswith(skp)]
        return {"Items": items}

    def put_item(self, Item=None, **_kw):
        self.puts.append(Item)


def _fixture_table():
    """2 open hypotheses + 2 open predictions that MUST be voided, plus terminal and
    already-tombstoned bets that MUST NOT be — so the count invariant is non-vacuous
    (a collector that ignored status/tombstone would over-count to 8)."""
    return _FakeTable(
        {
            pipeline.HYPOTHESES_PK: [
                {
                    "sk": "HYPOTHESIS#a",
                    "status": "pending",
                    "hypothesis_id": "hyp_a",
                    "hypothesis": "A",
                    "confidence": "high",
                    "test_spec": {"direction": "higher"},
                    "created_at": "2026-07-10T00:00:00Z",
                },
                {"sk": "HYPOTHESIS#b", "status": "confirming", "hypothesis_id": "hyp_b", "hypothesis": "B", "confidence": "medium"},
                {"sk": "HYPOTHESIS#c", "status": "confirmed", "hypothesis_id": "hyp_c"},  # terminal — skip
                {"sk": "HYPOTHESIS#d", "status": "refuted", "hypothesis_id": "hyp_d"},  # terminal — skip
                {"sk": "HYPOTHESIS#e", "status": "pending", "hypothesis_id": "hyp_e", "tombstone": True},  # prior cycle — skip
            ],
            "COACH#sleep_coach": [
                {
                    "sk": "PREDICTION#p1",
                    "status": "pending",
                    "prediction_id": "p1",
                    "coach_id": "sleep_coach",
                    "confidence": 0.8,
                    "claim_natural": "sleep improves",
                    "subdomain": "sleep",
                    "created_date": "2026-07-01",
                },
                {"sk": "PREDICTION#p3", "status": "refuted", "prediction_id": "p3", "coach_id": "sleep_coach"},  # terminal — skip
            ],
            "COACH#mind_coach": [
                {"sk": "PREDICTION#p2", "status": "confirming", "prediction_id": "p2", "coach_id": "mind_coach", "confidence": 0.6},
                {
                    "sk": "PREDICTION#p4",
                    "status": "pending",
                    "prediction_id": "p4",
                    "coach_id": "mind_coach",
                    "tombstone": True,
                },  # already archived by a prior reset — skip
            ],
        }
    )


def test_collect_open_bets_excludes_terminal_and_tombstoned():
    # Non-vacuous: exactly the 2 open hypotheses + 2 open predictions, nothing else.
    bets = pipeline.collect_open_bets(_fixture_table())
    kinds = sorted(k for k, _ in bets)
    ids = sorted((b.get("hypothesis_id") or b.get("prediction_id")) for _, b in bets)
    assert kinds == ["hypothesis", "hypothesis", "prediction", "prediction"]
    assert ids == ["hyp_a", "hyp_b", "p1", "p2"]  # hyp_c/d (terminal), hyp_e/p4 (tombstoned), p3 excluded


def test_void_dry_run_counts_all_open_but_writes_nothing():
    fake = _fixture_table()
    n = pipeline.void_open_bets_at_reset(_GENESIS, _CLOSING_CYCLE, apply=False, table=fake)
    assert n == 4
    assert fake.puts == []  # dry-run is read-only — the whole pipeline is dry-run-provable


def test_void_apply_writes_one_calib_row_per_open_bet():
    # THE regression guard: count(open hypotheses + predictions) == count(void CALIB# rows).
    fake = _fixture_table()
    open_bets = pipeline.collect_open_bets(fake)
    n = pipeline.void_open_bets_at_reset(_GENESIS, _CLOSING_CYCLE, apply=True, table=fake)
    assert n == len(open_bets) == len(fake.puts) == 4
    for row in fake.puts:
        assert row["pk"] == pipeline.CALIBRATION_PK  # CROSS_PHASE ledger — survives the wipe
        assert row["sk"].startswith(f"CALIB#{_GENESIS}#void#")
        assert row["outcome"] == "voided_at_reset"
        assert row["voided_at_reset"] is True
        assert row["cycle"] == _CLOSING_CYCLE  # stamped with the CLOSING cycle
        assert row["record_type"] in ("hypothesis_void", "prediction_void")
    # None of the terminal/tombstoned bets leaked a row.
    voided_ids = {r.get("hypothesis_id") or r.get("prediction_id") for r in fake.puts}
    assert voided_ids == {"hyp_a", "hyp_b", "p1", "p2"}


def test_void_rows_are_cross_phase_and_not_brier_scorable():
    # Ties the fix to the taxonomy + calibration coverage: the ledger row classifies
    # CROSS_PHASE (never wiped) and 'voided_at_reset' is excluded from the Brier curve.
    sys.path.insert(0, str(REPO_ROOT / "lambdas"))
    import calibration_core
    import phase_taxonomy

    row = pipeline.build_void_calib_item(
        "hypothesis",
        {"sk": "HYPOTHESIS#a", "status": "pending", "hypothesis_id": "hyp_a", "confidence": "high"},
        _GENESIS,
        _CLOSING_CYCLE,
        "2026-08-01T00:00:00Z",
    )
    assert phase_taxonomy.classify(row["pk"], row["sk"]) == phase_taxonomy.CROSS_PHASE
    assert calibration_core.outcome_to_binary(row["outcome"]) is None
    assert calibration_core.pairs_from_calibration_rows([row]) == []  # never distorts calibration


def test_void_sk_is_idempotent_and_kind_namespaced():
    # Re-running the reset (same genesis) overwrites the same row; a hypothesis and a
    # prediction sharing an id can't collide (kind is in the sk).
    hyp = {"sk": "HYPOTHESIS#x", "status": "pending", "hypothesis_id": "shared", "confidence": "low"}
    pred = {"sk": "PREDICTION#x", "status": "pending", "prediction_id": "shared", "coach_id": "sleep_coach"}
    a = pipeline.build_void_calib_item("hypothesis", hyp, _GENESIS, _CLOSING_CYCLE, "t1")
    a2 = pipeline.build_void_calib_item("hypothesis", hyp, _GENESIS, _CLOSING_CYCLE, "t2")
    p = pipeline.build_void_calib_item("prediction", pred, _GENESIS, _CLOSING_CYCLE, "t1")
    assert a["sk"] == a2["sk"] == f"CALIB#{_GENESIS}#void#hyp#shared"
    assert p["sk"] == f"CALIB#{_GENESIS}#void#pred#sleep_coach#shared"
    assert a["sk"] != p["sk"]


# ── #1234: pk-family census PREFLIGHT (the ADR-077 totality guard) ─────────────
#
# The taxonomy's totality guarantee was fail-loud only for USER#…#SOURCE# families;
# a NEW non-SOURCE top-level family (the next COACH#-like tier) would silently
# survive every reset. run_census_preflight scans the live table, reduces to
# distinct pk families, classify()es a representative of each, and FAILS the reset
# on any unclassified family. These tests are NON-VACUOUS: they plant an unknown
# family and assert the preflight raises (not silently passes), and they assert the
# preflight is wired into restart_pipeline's dry-run sequence (main). All of them
# reference symbols (run_census_preflight / CensusPreflightError) that DID NOT EXIST
# before the fix, so the whole block is red on pre-fix code — the guard is real.

# A set of KNOWN families that must all classify() cleanly: one SOURCE family, plus
# three distinct non-SOURCE top-level families (COACH# / PULSE / READING#).
_KNOWN_PAGE = [
    {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-04-01"},  # SOURCE#whoop → raw_timeseries
    {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-04-02"},  # same family — folds to one rep
    {"pk": "COACH#sleep_coach", "sk": "PREDICTION#p1"},  # COACH → experiment_scoped
    {"pk": "PULSE", "sk": "DATE#2026-04-04"},  # PULSE → system_state
    {"pk": "READING#abc", "sk": "STATE#x"},  # READING → cross_phase
]


class _FakeScanTable:
    """Minimal DynamoDB Table stand-in for a paginated pk+sk scan (no AWS). Serves
    one page per scan() call, setting LastEvaluatedKey while pages remain."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = 0
        self.projections = []

    def scan(self, **kwargs):
        self.projections.append(kwargs.get("ProjectionExpression"))
        i = self.calls
        self.calls += 1
        items = self.pages[i] if i < len(self.pages) else []
        resp = {"Items": items}
        if i < len(self.pages) - 1:  # more pages queued → signal pagination
            resp["LastEvaluatedKey"] = {"pk": "__next__"}
        return resp


def test_census_preflight_passes_on_known_families():
    # The 5 rows fold to 4 distinct families (whoop dedups) — all classify cleanly.
    fake = _FakeScanTable([_KNOWN_PAGE])
    n = pipeline.run_census_preflight(table=fake)
    assert n == 4
    # It projected only pk+sk (the cheap scan) and actually classified something.
    assert fake.projections and all(p == "pk, sk" for p in fake.projections)


def test_census_preflight_paginates_the_scan():
    # Families split across pages must all be seen (LastEvaluatedKey drives the loop).
    pages = [_KNOWN_PAGE[:2], _KNOWN_PAGE[2:]]
    fake = _FakeScanTable(pages)
    assert pipeline.run_census_preflight(table=fake) == 4
    assert fake.calls == 2  # both pages consumed; the last returns no LastEvaluatedKey, ending the loop


def test_census_preflight_FAILS_on_planted_unknown_family():
    # THE regression guard (non-vacuous): plant a brand-new top-level family with
    # no SOURCE_CLASS entry and no _PK_RULES predicate — the next COACH#-like tier.
    # classify() must raise KeyError on it and the preflight must FAIL the reset.
    pages = [_KNOWN_PAGE + [{"pk": "SQUAD#alpha", "sk": "STATE#current"}]]
    fake = _FakeScanTable(pages)
    with pytest.raises(pipeline.CensusPreflightError) as ei:
        pipeline.run_census_preflight(table=fake)
    msg = str(ei.value)
    assert "SQUAD" in msg  # the failure names the unclassified family
    assert "SQUAD#alpha" in msg  # ...and its representative pk — proof classify() ran on it


def test_census_preflight_also_fails_on_a_new_source_family():
    # Strengthens the SOURCE guard too: a NEW source under USER#…#SOURCE# is its own
    # family whose representative classify() cannot resolve → the reset fails loudly
    # (the tagger merely report-catches this today; the preflight aborts).
    pages = [_KNOWN_PAGE + [{"pk": "USER#matthew#SOURCE#brandnew_wearable", "sk": "DATE#2026-08-01"}]]
    with pytest.raises(pipeline.CensusPreflightError) as ei:
        pipeline.run_census_preflight(table=_FakeScanTable(pages))
    assert "brandnew_wearable" in str(ei.value)


def test_census_preflight_refuses_an_empty_census():
    # Guards the vacuous-scan trap: a scan that silently returns nothing must NOT be
    # certified as "all families covered" — it must fail rather than pass vacuously.
    with pytest.raises(pipeline.CensusPreflightError) as ei:
        pipeline.run_census_preflight(table=_FakeScanTable([[]]))
    assert "ZERO pk families" in str(ei.value)


def test_pk_family_mirrors_classify_keying():
    # The family key folds a #SOURCE# pk to its base source (sub-keys collapse) and
    # every other pk to its top-level prefix — the granularity classify() decides at.
    assert pipeline._pk_family("USER#matthew#SOURCE#whoop") == "SOURCE#whoop"
    assert pipeline._pk_family("USER#matthew#SOURCE#email_log#daily_brief") == "SOURCE#email_log"
    assert pipeline._pk_family("USER#matthew#SOURCE#training_notes#EXERCISE#42") == "SOURCE#training_notes"
    assert pipeline._pk_family("COACH#sleep_coach") == "COACH"
    assert pipeline._pk_family("PULSE") == "PULSE"


def test_census_preflight_is_wired_into_the_dry_run_sequence(monkeypatch):
    # (b) The preflight must actually run in restart_pipeline's dry-run path. Drive
    # main() in DRY-RUN (no --apply) with the census patched to record + abort; it
    # sits BEFORE any AWS/subprocess step, so reaching it proves the wiring.
    called = {"n": 0}

    def _fake_preflight(table=None):
        called["n"] += 1
        raise pipeline.CensusPreflightError("planted — wiring probe")

    monkeypatch.setattr(pipeline, "run_census_preflight", _fake_preflight)
    # Keep main() offline up to the preflight (it sits before Withings/void/subprocess).
    monkeypatch.setattr(pipeline, "read_cycle_from_ssm", lambda: 6)
    monkeypatch.setattr(
        sys,
        "argv",
        ["restart_pipeline.py", "--genesis", "2026-09-01", "--override-weight-lbs", "300", "--no-close-cycle", "--skip-deploy"],
    )
    # A failed census aborts the reset (sys.exit(4)) — that abort IS the wiring proof.
    with pytest.raises(SystemExit) as ei:
        pipeline.main()
    assert ei.value.code == 4
    assert called["n"] == 1  # the dry-run path invoked the preflight exactly once


def test_skip_census_preflight_flag_bypasses_it(monkeypatch):
    # The escape hatch must genuinely skip the preflight (no scan attempted).
    def _boom(table=None):
        raise AssertionError("preflight ran despite --skip-census-preflight")

    monkeypatch.setattr(pipeline, "run_census_preflight", _boom)
    monkeypatch.setattr(pipeline, "read_cycle_from_ssm", lambda: 6)
    # Stop main() right after the preflight gate so we don't march into AWS steps.
    monkeypatch.setattr(pipeline, "fetch_withings_for", lambda *_a, **_k: (_ for _ in ()).throw(SystemExit(99)))
    monkeypatch.setattr(
        sys,
        "argv",
        ["restart_pipeline.py", "--genesis", "2026-09-01", "--skip-census-preflight", "--no-close-cycle", "--skip-deploy"],
    )
    with pytest.raises(SystemExit) as ei:
        pipeline.main()
    assert ei.value.code == 99  # reached Withings fetch (past the skipped preflight), never raised from _boom
