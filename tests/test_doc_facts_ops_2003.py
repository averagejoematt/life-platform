"""#2003 — the ingestion-cadence half of the wiki drift gate must actually BITE.

CLAUDE.md's ingest bullet hand-stated Garmin as a live "4x daily" EventBridge pull
two months after ADR-074 paused it and the rule was removed — while
`lambdas/ingestion/source_registry.py` (`paused: True`) and
`cdk/stacks/ingestion_stack.py` (no `schedule=` on the garmin Lambda) both already
told the truth. Same shape as the #1957 gate: every rule here is proved on a
synthetic drifted claim of its own class (the #1189 non-vacuous-scan lesson — a scan
that matches nothing passes forever), following the structure of
tests/test_doc_facts_ops_1957.py:
  1. PLANTED violation in a scratch file -> the rule reports it;
  2. CORRECTED text in a scratch file -> silence;
  3. the REAL repo tree -> silence (proves the CLAUDE.md/ARCHITECTURE.md/
     DEPENDENCY_GRAPH.md/RUNBOOK.md fixes in this PR actually landed).
"""

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ops():
    return _load("scripts/doc_facts_ops.py", "_ops_2003")


@pytest.fixture(scope="module")
def facts():
    return _load("scripts/check_doc_facts.py", "_facts_2003")


def _scratch(tmp_path, text, name="scratch.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return [p]


# ── ground truth is really discovered (a vacuous discoverer disables everything) ──
def test_paused_discovery_survives_both_assignment_forms(ops, tmp_path):
    """Guard the SET of assignment forms, not the one the file happens to use today.

    #1677 annotated `SOURCE_REGISTRY: dict[str, dict[str, Any]] = {...}` to settle a
    mypy widening. That turns the node from `ast.Assign` into `ast.AnnAssign`, and the
    walk matched only the former — so it returned `{}` and the paused-source gate went
    BLIND rather than red. A checker that silently finds nothing is worse than one that
    fails: `assert 'garmin' in {}` was the only reason anyone noticed.

    Both forms must discover the same paused set, and a `**` splice (also #1677) must
    not break the walk either.
    """
    body = '"paused_one": {"label": "One", "paused": True},\n' '    "live_one": {"label": "Two"},\n'
    forms = {
        "plain": f"SOURCE_REGISTRY = {{\n    {body}}}\n",
        "annotated": f"SOURCE_REGISTRY: dict[str, dict[str, object]] = {{\n    {body}}}\n",
        "annotated_with_splice": ("EXTRA = {}\n" f"SOURCE_REGISTRY: dict[str, dict[str, object]] = {{\n    {body}    **EXTRA,\n}}\n"),
    }
    found = {}
    for name, src in forms.items():
        f = tmp_path / f"{name}.py"
        f.write_text(src, encoding="utf-8")
        found[name] = ops.ingestion_paused_sources(f)

    for name, got in found.items():
        assert got == {"paused_one": "One"}, f"{name} form discovered {got!r}"


def test_paused_sources_discovered_from_registry(ops):
    paused = ops.ingestion_paused_sources()
    # garmin is the only source paused per ADR-074 at time of writing; the assertion
    # is a floor (>=1, and specifically garmin), not an exact set, so a FUTURE second
    # pause doesn't break this test.
    assert "garmin" in paused
    assert paused["garmin"].lower() == "garmin"


def test_scheduled_lambda_count_discovered_from_cdk(ops):
    n = ops.ingestion_scheduled_lambda_count()
    assert isinstance(n, int) and n >= 10, n
    # garmin must NOT be counted — it is paused and carries no schedule= kwarg.
    # (Sanity floor, not an exact pin: the fleet grows over time.)


# ── E1. paused source named next to live-cadence language ────────────────────
_GARMIN_BAD = "Garmin at 4x daily due to OAuth rate limits.\n"
_GARMIN_BAD_TABLE = "| Garmin | `garmin-data-ingestion` | 4x daily (cron 0 0,6,14,22) | API pull |\n"
_GARMIN_GOOD = "Garmin — paused (vendor anti-automation, ADR-074 — no live EventBridge rule).\n"
_GARMIN_GOOD_TABLE = "| Garmin | `garmin-data-ingestion` | Paused (ADR-074) — no live rule | API pull |\n"


def test_paused_cadence_fires_on_live_cadence_claim(ops, facts, tmp_path):
    hits = ops.ingestion_paused_cadence_hits(_scratch(tmp_path, _GARMIN_BAD), ops.ingestion_paused_sources(), facts.line_is_exempt)
    assert len(hits) == 1 and "garmin" in hits[0]


def test_paused_cadence_fires_on_live_cadence_claim_in_a_table(ops, facts, tmp_path):
    hits = ops.ingestion_paused_cadence_hits(_scratch(tmp_path, _GARMIN_BAD_TABLE), ops.ingestion_paused_sources(), facts.line_is_exempt)
    assert len(hits) == 1 and "garmin" in hits[0]


def test_paused_cadence_silent_when_the_line_says_paused(ops, facts, tmp_path):
    assert ops.ingestion_paused_cadence_hits(_scratch(tmp_path, _GARMIN_GOOD), ops.ingestion_paused_sources(), facts.line_is_exempt) == []


def test_paused_cadence_silent_on_corrected_table_row(ops, facts, tmp_path):
    hits = ops.ingestion_paused_cadence_hits(_scratch(tmp_path, _GARMIN_GOOD_TABLE), ops.ingestion_paused_sources(), facts.line_is_exempt)
    assert hits == []


def test_paused_cadence_ignores_unrelated_cadence_language(ops, facts, tmp_path):
    """A live source's cadence (no paused source named) must never be flagged."""
    text = "Whoop pulls hourly during active hours.\n"
    assert ops.ingestion_paused_cadence_hits(_scratch(tmp_path, text), ops.ingestion_paused_sources(), facts.line_is_exempt) == []


def test_paused_cadence_honours_historical_framing(ops, facts, tmp_path):
    text = "Garmin was 4x daily until the vendor's anti-automation crackdown.\n"
    assert ops.ingestion_paused_cadence_hits(_scratch(tmp_path, text), ops.ingestion_paused_sources(), facts.line_is_exempt) == []


def test_paused_cadence_clean_on_real_docs(ops, facts):
    hits = ops.ingestion_paused_cadence_hits(facts._scan_files(), ops.ingestion_paused_sources(), facts.line_is_exempt)
    assert hits == [], "\n".join(hits)


# ── E2. hand-stated scheduled-ingestion-Lambda count vs the CDK ──────────────
def test_scheduled_count_fires_on_stale_claim(ops, facts, tmp_path):
    truth = ops.ingestion_scheduled_lambda_count()
    stale = truth + 1
    text = f"{stale} scheduled ingestion Lambda functions pull from APIs on EventBridge.\n"
    hits = ops.ingestion_scheduled_count_hits(_scratch(tmp_path, text), truth, facts.line_is_exempt)
    assert len(hits) == 1 and f"claims {stale}" in hits[0]


def test_scheduled_count_silent_on_correct_claim(ops, facts, tmp_path):
    truth = ops.ingestion_scheduled_lambda_count()
    text = f"{truth} scheduled ingestion Lambda functions pull from APIs on EventBridge.\n"
    assert ops.ingestion_scheduled_count_hits(_scratch(tmp_path, text), truth, facts.line_is_exempt) == []


def test_scheduled_count_ignores_unrelated_numbers(ops, facts, tmp_path):
    """A bare Lambda-count claim with no 'scheduled ingestion Lambda functions'
    phrasing must never be judged by this narrow rule (lambda_count subset counts
    are deliberately NOT policed — see check_doc_facts.py's FACT_SPECS note)."""
    text = "There are 99 Lambdas across 9 CDK stacks.\n"
    assert ops.ingestion_scheduled_count_hits(_scratch(tmp_path, text), 14, facts.line_is_exempt) == []


def test_scheduled_count_clean_on_real_docs(ops, facts):
    truth = ops.ingestion_scheduled_lambda_count()
    hits = ops.ingestion_scheduled_count_hits(facts._scan_files(), truth, facts.line_is_exempt)
    assert hits == [], "\n".join(hits)


# ── the whole gate still exits 0 on the real tree ────────────────────────────
def test_gate_passes_on_the_repo():
    import subprocess

    r = subprocess.run(["python3", "scripts/check_doc_facts.py"], cwd=_REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
