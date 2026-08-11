"""
tests/test_coach_sim_scoreboard_2539.py — the coach-sim standing measure (#2539).

The load-bearing assertion here is the READ-BACK: a later run must recover the previous
run's numbers from the stored ``COACHSIM#scoreboard`` partition, not from a scratch file
that whoever ran it still happens to have on disk. Everything else in this issue is
plumbing around that one property, so it is tested as a round trip (write the baseline,
read it back through the public reader, diff a synthetic later run against it) rather
than as two independent unit tests that could both pass while the pair is broken.

Also guarded, because each one is a way this measure could quietly become a lie:
  * the deterministic subset spends nothing — no bedrock_client import path is reachable;
  * an empty corpus reports NO metrics rather than a flattering set of zeros (ADR-104);
  * the limitations ride with the stored row, not only in a doc;
  * the cadence's budget reason is stored, so "why isn't this a CI gate" is answerable
    from the scoreboard itself;
  * COACHSIM# is CROSS_PHASE, so a reset cannot erase the trend.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))

from coach import coach_sim_scoreboard as sb  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402

FIXTURE_CORPUS = ROOT / "tests" / "fixtures" / "coach_sim_replay"


class FakeTable:
    """Minimal in-memory stand-in for the DDB table resource. Deliberately not a mock:
    the round-trip test has to prove a real read recovers what a real write stored, and
    a MagicMock would return whatever the assertion asked for."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item):  # noqa: N803 — boto3's kwarg name
        self.items[(Item["pk"], Item["sk"])] = json.loads(json.dumps(Item, default=str))

    def get_item(self, Key):  # noqa: N803
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}


# ── the read-back proof (acceptance box 5) ───────────────────────────────────


def test_baseline_writes_then_reads_back_from_the_stored_scoreboard():
    table = FakeTable()
    sb.seed_baseline(table=table)

    latest = sb.read_latest(table=table)
    assert latest, "nothing stored at COACHSIM#scoreboard/latest after seeding"
    assert latest["run_date"] == "2026-08-10"
    # The headline the issue exists to make trackable, recovered from storage.
    assert float(latest["panel"]["ai_verdict_pct"]) == 64.0
    assert int(latest["panel"]["ai_verdict_n"]) == 77
    assert float(latest["deterministic"]["em_dash_reply_rate"]) == 0.77
    assert int(latest["deterministic"]["median_reply_chars"]) == 195
    assert latest["honesty_gate"] == {"sent": 516, "regenerated": 13, "held": 7}

    # The immutable per-run row exists alongside latest, so the trend is a query.
    assert sb.read_run("2026-08-10", table=table)["run_date"] == "2026-08-10"


def test_a_later_run_diffs_against_the_stored_baseline_not_a_scratch_file():
    table = FakeTable()
    sb.seed_baseline(table=table)

    # A later run that improved the em-dash habit and shortened replies.
    later = sb.build_run_record(
        "2026-09-01",
        deterministic={
            "em_dash_reply_rate": 0.41,
            "closing_question_rate": 0.20,
            "formatting_violations": 0,
            "median_reply_chars": 150,
            "median_reply_inbound_ratio": 3.1,
        },
    )
    previous = sb.read_latest(table=table)  # ← the read-back, from storage
    trend = sb.delta_vs(later, previous)

    assert trend["from_run"] == "2026-08-10" and trend["to_run"] == "2026-09-01"
    assert trend["metrics"]["em_dash_reply_rate"]["direction"] == "better"
    assert trend["metrics"]["em_dash_reply_rate"]["change"] == pytest.approx(-0.36)
    assert trend["metrics"]["median_reply_chars"]["direction"] == "better"
    assert trend["metrics"]["closing_question_rate"]["direction"] == "flat"

    sb.write_run(later, table=table)
    assert sb.read_latest(table=table)["run_date"] == "2026-09-01"
    assert sb.read_run("2026-08-10", table=table)["run_date"] == "2026-08-10", "the baseline row was overwritten"


def test_seed_is_idempotent_and_never_demotes_a_newer_latest():
    table = FakeTable()
    sb.write_run(sb.build_run_record("2026-09-01", deterministic={"em_dash_reply_rate": 0.4}), table=table)
    sb.seed_baseline(table=table)
    assert sb.read_latest(table=table)["run_date"] == "2026-09-01", "seeding the old baseline clobbered a newer run"
    assert sb.read_run("2026-08-10", table=table), "the baseline row was not backfilled"
    assert sb.seed_baseline(table=table) == {"skipped": "already_seeded", "run_date": "2026-08-10"}


def test_an_unmeasured_metric_is_unmeasured_not_a_delta_of_zero():
    """ADR-104. A deterministic-only replay has no panel and may not carry every key;
    reporting that as 'held flat' would be the flattering lie the honesty rules forbid."""
    trend = sb.delta_vs({"run_date": "b", "deterministic": {}}, {"run_date": "a", "deterministic": {"em_dash_reply_rate": 0.77}})
    assert trend["metrics"]["em_dash_reply_rate"]["status"] == "unmeasured"
    assert "change" not in trend["metrics"]["em_dash_reply_rate"]


# ── the limitations + cadence ride with the numbers (boxes 1 and 4) ──────────


def test_limitations_are_stored_beside_the_run_not_only_in_prose():
    table = FakeTable()
    sb.seed_baseline(table=table)
    stored = sb.read_limitations(table=table)
    ids = {lim["id"] for lim in stored["limitations"]}
    assert "subject_is_not_matthew" in ids
    assert "deterministic_layer_alone_is_insufficient" in ids
    body = json.dumps(stored)
    assert "2537" in body, "the finding the cheap layer nearly missed must be named, with its issue"
    assert "2518" in body, "the harness-drift limitation must name the fidelity bug it came from"


def test_cadence_records_the_budget_reason_it_is_not_a_ci_gate():
    cadence = sb.CADENCE
    assert cadence["mode"] == "on_demand"
    reason = cadence["not_a_ci_gate_because"]
    assert "ADR-063" in reason and "ADR-125" in reason
    assert "85" in reason, "the ceiling the cost is measured against must be named"
    assert cadence["cost_usd_per_run"] > 0
    # The $0 layer is the one that repeats, and it is advisory until explicitly promoted.
    subset = cadence["deterministic_subset"]
    assert subset["cost_usd"] == 0.0
    assert subset["posture"] == "advisory"
    assert "ADR-108" in subset["promotion_rule"]


# ── cross-phase classification (box 2) ───────────────────────────────────────


@pytest.mark.parametrize("sk", ["latest", "RUN#2026-08-10", "LIMITATIONS"])
def test_coachsim_partition_is_cross_phase(sk):
    assert phase_taxonomy.classify(sb.SCOREBOARD_PK, sk) == phase_taxonomy.CROSS_PHASE


def test_coachsim_is_classified_the_same_way_as_its_sibling_harness():
    """If VOICEFIDELITY# is ever reclassified, this one should be reconsidered with it —
    they measure the same kind of thing and diverging silently would be an accident."""
    assert phase_taxonomy.classify("COACHSIM#scoreboard", "latest") == phase_taxonomy.classify("VOICEFIDELITY#scoreboard", "latest")


# ── the deterministic subset is real, and free (box 3) ───────────────────────


def test_deterministic_replay_over_the_fixture_costs_nothing_and_fires():
    from coach_sim_replay import deterministic_metrics, load_corpus, manifest

    convos = load_corpus(str(FIXTURE_CORPUS))
    det = deterministic_metrics(convos)

    # Each detector must actually fire on this fixture — a corpus where every metric
    # reads zero proves the metrics are wired, not that they work.
    assert det["replies_measured"] > 0
    assert det["em_dash_reply_rate"] > 0
    assert det["closing_question_rate"] > 0
    assert det["formatting_violations"] > 0, "the markdown-bullet reply in the fixture did not trip the formatting detector"
    assert det["assistant_ism_hits"] > 0
    assert det["balanced_clause_replies"] > 0
    assert det["max_structural_collapse_ratio"] is not None, "structural collapse needs >=4 coaches on one archetype in the fixture"

    man = manifest(str(FIXTURE_CORPUS), convos)
    assert man["conversations"] == len(convos) and man["replies"] == det["replies_measured"]
    assert len(man["sha256"]) == 64


def test_empty_corpus_reports_no_metrics_rather_than_zeros():
    from coach_sim_replay import deterministic_metrics

    assert deterministic_metrics([]) == {}


def test_the_replay_runner_imports_no_bedrock_path():
    """$0 is a property of the code, not of an intention. The replay module must not pull
    in the inference chokepoint at all — if it can call Bedrock, one flag away it will."""
    import ast

    import coach_sim_replay

    tree = ast.parse(Path(coach_sim_replay.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}" for a in node.names)
    assert not any("bedrock" in name for name in imported), sorted(imported)
    assert not any("ai_calls" in name for name in imported), sorted(imported)

    # And it is not reachable transitively through what it does import. Checked in a
    # FRESH interpreter: sys.modules in this session is polluted by every other test that
    # imported the chokepoint, so an in-process assertion here would pass or fail on test
    # ordering rather than on this module's imports.
    env = dict(os.environ, PYTHONPATH=f"{ROOT / 'lambdas'}{os.pathsep}{ROOT / 'scripts'}")
    probe = "import sys, coach_sim_replay; print(any('bedrock' in m for m in sys.modules))"
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False", "importing the replay path pulled in the inference chokepoint"


def test_replay_cli_runs_advisory_and_exits_zero():
    """Advisory first (ADR-108). Promotion to blocking must be a deliberate decision with a
    measured flag rate behind it — until then this must never be able to red a build."""
    env = dict(os.environ, PYTHONPATH=f"{ROOT / 'lambdas'}{os.pathsep}{ROOT / 'scripts'}")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "coach_sim_replay.py"), "--corpus", str(FIXTURE_CORPUS), "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["deterministic"]["replies_measured"] > 0
    assert payload["trend"] is None, "a bare replay must not hit DynamoDB"
    assert {lim["id"] for lim in payload["limitations"]} >= {"subject_is_not_matthew"}
