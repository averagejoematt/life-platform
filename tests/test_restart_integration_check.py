#!/usr/bin/env python3
"""
test_restart_integration_check.py — offline tests for the #1559 behavioral harness.

Pure-logic coverage of deploy/restart_integration_check.py: the present-None static
gate (classification + the STANDING repo-wide sweep over lambdas/emails/), the
ingestion plan derivation, the synthetic-payload dedup contract, freshness verdicts
(pinned clocks — never wall-time, memory: reference_golden_tests_wallclock), and the
report/exit semantics. No AWS, no network — every boto3 import in the harness is
lazy inside leg functions, asserted here so collection can never red on creds.
"""

import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "deploy"))
import restart_integration_check as ric  # noqa: E402

REPO = os.path.dirname(_HERE)


# ── the present-None static gate (genesis-week crash class) ───────────────────


def test_unguarded_fstring_pillar_chain_is_flagged():
    """THE guard-red case: the exact monday_compass_lambda.py:415 shape."""
    src = 'pd = char.get(f"pillar_{p}", {})\ns = pd.get("raw_score")\n'
    hits = ric.scan_present_none_hazards(src, "x.py")
    assert [(p, ln) for p, ln, _ in hits] == [("x.py", 1)]


def test_unguarded_pillars_superdict_is_flagged():
    """The monthly_digest_lambda.py:966 shape."""
    hits = ric.scan_present_none_hazards('pd = cs_c.get("pillars", {}).get(pname)\n')
    assert len(hits) == 1


def test_guarded_or_idiom_is_not_flagged():
    src = "\n".join(
        [
            'pd = rec.get(f"pillar_{p}") or {}',
            'prev = (cs_p.get("pillars") or {}).get(pname, {}).get("level")',
            'x = (d.get("this") or {}).get("withings") or {}',
        ]
    )
    assert ric.scan_present_none_hazards(src) == []


def test_non_pillar_dict_defaults_are_not_flagged():
    """The gate is scoped to the character-sheet pillar shapes the writer itself
    acknowledges can be present-None — not a blanket .get(k, {}) ban."""
    src = 'grades = data.get("this", {}).get("day_grades")\ncfg = obj.get("timeline", {})\n'
    assert ric.scan_present_none_hazards(src) == []


def test_single_quoted_variant_is_flagged():
    assert len(ric.scan_present_none_hazards("pd = char.get(f'pillar_{p}', {})\n")) == 1


def test_email_lambdas_carry_no_present_none_hazards():
    """THE STANDING GATE: no unguarded pillar chain-reads anywhere in
    lambdas/emails/. Proven RED against the 4 pre-fix sites
    (monday_compass:415, wednesday_chronicle:740-741, weekly_digest:590-611,
    monthly_digest:966) before the same-PR fixes turned it green — the
    reference_genesis_week_present_none class stays closed between resets."""
    hits = ric.scan_email_lambdas(os.path.join(REPO, "lambdas", "emails"))
    assert hits == [], "unguarded pillar chain-reads (fix with the `(d.get(k) or {}) ` idiom):\n" + "\n".join(
        f"  {p}:{ln}  {line}" for p, ln, line in hits
    )


# ── ingestion plan derivation ─────────────────────────────────────────────────

FAKE_REGISTRY = {
    "whoop": {},
    "garmin": {"paused": True},
    "apple_health": {"hae_datatypes": [{"key": "cgm"}]},
    "macrofactor": {},
    "supplements": {"freshness": False},
    "mystery_source": {},
}


def test_plan_classifies_probe_paused_webhook_eventdriven_unknown():
    plan = ric.build_ingestion_plan(
        FAKE_REGISTRY, fn_map={"whoop": "whoop-data-ingestion", "garmin": "garmin-data-ingestion", "apple_health": "hae"}
    )
    assert plan["whoop"] == ("probe", "whoop-data-ingestion")
    assert plan["garmin"][0] == "skip" and "paused" in plan["garmin"][1]
    assert plan["apple_health"] == ("healthcheck", "hae")
    assert plan["macrofactor"][0] == "skip" and "event-driven" in plan["macrofactor"][1]
    assert plan["supplements"][0] == "skip"
    assert plan["mystery_source"][0] == "skip" and "SOURCE_FN" in plan["mystery_source"][1]


def test_every_skip_carries_a_reason():
    plan = ric.build_ingestion_plan(FAKE_REGISTRY, fn_map={})
    for src, (kind, val) in plan.items():
        if kind == "skip":
            assert isinstance(val, str) and len(val) > 10, f"{src} skip must state its reason"


def test_source_fn_map_matches_real_registry():
    """The hand-carried SOURCE_FN map must never name a source the registry
    dropped (the reverse — registry sources without a map entry — is an honest
    skip row at runtime, not an error)."""
    import lambdas.source_registry as sr

    unknown = set(ric.SOURCE_FN) - set(sr.SOURCE_REGISTRY)
    assert unknown == set(), f"SOURCE_FN names sources absent from SOURCE_REGISTRY: {unknown}"


def test_real_registry_plan_pauses_garmin_and_probes_whoop():
    import lambdas.source_registry as sr

    plan = ric.build_ingestion_plan(sr.SOURCE_REGISTRY)
    assert plan["whoop"] == ("probe", "whoop-data-ingestion")
    assert plan["garmin"][0] == "skip" and "paused" in plan["garmin"][1]
    assert plan["apple_health"][0] == "healthcheck"


# ── synthetic payload: the dedup contract (ADR-104 tagging) ───────────────────


def test_synthetic_payload_carries_duplicate_timestamp_and_tags():
    p = ric.build_synthetic_metrics_payload()
    assert p["integration_test"] is True
    water = next(m for m in p["data"]["metrics"] if m["name"] == "Water")
    ts = [r["date"] for r in water["data"]]
    assert len(ts) == 3 and len(set(ts)) == 2, "must carry exactly one duplicated timestamp to prove dedup"
    assert all(r.get("source") == ric.SYNTHETIC_SOURCE for r in water["data"])
    assert all(ric.SYNTHETIC_DATE in r["date"] for r in water["data"])
    # the contract: duplicate collapses, distinct reading survives
    assert ric.synthetic_water_expected_ml() == 350.0


def test_synthetic_date_is_impossible():
    """2099 can never collide with a real capture day — the isolation guarantee
    that makes the delete-protected raw/ residue honest rather than polluting."""
    assert ric.SYNTHETIC_DATE.startswith("2099")


def test_som_payload_shape_matches_hae_automation():
    p = ric.build_synthetic_som_payload()
    entries = p["data"]["stateOfMind"]
    assert entries[0]["kind"] == "dailyMood" and -1 <= entries[0]["valence"] <= 1


# ── freshness verdicts (pinned clocks) ────────────────────────────────────────

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def test_fresh_within_threshold():
    status, detail = ric.freshness_verdict("2026-07-19", 48, now=_NOW)
    assert status == "fresh" and "36h" in detail


def test_stale_past_own_threshold():
    status, _ = ric.freshness_verdict("2026-07-13", 168, now=_NOW)
    assert status == "stale"


def test_no_rows_is_honest_no_data():
    status, detail = ric.freshness_verdict(None, 48, now=_NOW)
    assert status == "no-data" and "no DATE# rows" in detail


def test_default_threshold_is_48h():
    assert ric.freshness_verdict("2026-07-17", None, now=_NOW)[0] == "stale"
    assert ric.freshness_verdict("2026-07-19", None, now=_NOW)[0] == "fresh"


# ── report / exit semantics ───────────────────────────────────────────────────


def test_report_fails_only_on_fail_rows(capsys):
    r = ric.Report()
    r.add("ops", "a", ric.PASS)
    r.add("ops", "b", ric.SKIP, "stated reason")
    assert not r.failed
    r.add("ops", "c", ric.FAIL, "boom")
    assert r.failed
    table = r.render_table()
    assert "1 pass · 1 fail · 1 skipped-with-reason" in table
    assert "stated reason" in table  # skips are never silent


def test_module_import_is_offline_safe():
    """boto3 must never be imported at module scope — collection on a credless
    CI runner has to survive (memory: layer-dep import collection red)."""
    import ast

    with open(os.path.join(REPO, "deploy", "restart_integration_check.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    top_level = {n.names[0].name.split(".")[0] for n in tree.body if isinstance(n, ast.Import)} | {
        (n.module or "").split(".")[0] for n in tree.body if isinstance(n, ast.ImportFrom)
    }
    assert "boto3" not in top_level and "lambdas" not in top_level
