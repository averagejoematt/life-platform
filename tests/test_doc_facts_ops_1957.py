"""#1957 — the operational-claim half of the wiki drift gate must actually BITE.

The 2026-07-16 accuracy pass fixed six false claims in ARCHITECTURE.md and the same six
classes came back by 2026-07-28, because the #1205 guard only ever compared lines quoting
a literal `cron(...)`. So the deliverable is the widened gate, and the deliverable's
deliverable is THIS file: every new rule is proved on a synthetic drifted claim of its own
class (the #1189 non-vacuous-scan lesson — a scan that matches nothing passes forever).

Each class gets three tests:
  1. PLANTED violation in a scratch file → the rule reports it (proves it can fail);
  2. CORRECTED text in a scratch file → silence (proves it isn't reporting everything);
  3. the REAL repo tree → silence (proves the fixes in this PR actually landed, and
     future drift reds CI rather than waiting for a review panel).
"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_REPO / "tests"))
import repo_scan_cache  # noqa: E402


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ops():
    return _load("scripts/doc_facts_ops.py", "_ops_1957")


@pytest.fixture(scope="module")
def facts():
    return _load("scripts/check_doc_facts.py", "_facts_1957")


def _scratch(tmp_path, text, name="scratch.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return [p]


# ── ground truth is really discovered (a vacuous discoverer disables everything) ──
def test_cutoffs_discovered_from_budget_guard(ops):
    cutoffs = ops.budget_tier_cutoffs()
    assert len(cutoffs) >= 10, cutoffs
    # ADR-125's whole point: reader narrative outlives internal AI, the ask endpoint last.
    assert cutoffs["ensemble"] < cutoffs["coach_narrative"] < cutoffs["website_ai"]


def test_cdk_function_names_discovered(ops):
    names = ops.cdk_function_names()
    assert len(names) >= 90, len(names)
    assert "daily-brief" in names
    # constant-assigned names count too, else a correct doc row looks like a ghost
    assert "life-platform-mcp" in names


def test_granted_secrets_discovered(ops):
    granted = ops.cdk_granted_secrets()
    assert "life-platform/ai-keys" in granted
    assert all(g.startswith("life-platform/") for g in granted)


def test_secret_literal_is_parseable_and_stamped(ops):
    count, verified = ops.stamped_secret_fact()
    assert count and count > 10
    assert isinstance(verified, dt.date)


# ── A. budget-tier semantics ─────────────────────────────────────────────────
_LADDER_BAD = "SSM `/life-platform/budget-tier` → `budget_guard.py` gates AI features (1=coaches, 2=website AI, 3=hard cutoff).\n"
_LADDER_GOOD = (
    "SSM `/life-platform/budget-tier` → `budget_guard.py` gates AI features " "(1=internal/dev AI, 2=reader narratives, 3=hard cutoff).\n"
)


def test_tier_semantics_fires_on_pre_adr125_ladder(ops, facts, tmp_path):
    hits = ops.tier_semantics_hits(_scratch(tmp_path, _LADDER_BAD), ops.budget_tier_cutoffs(), facts.marker_is_exempt)
    assert len(hits) == 2, hits  # coaches@1 and website AI@2 are both wrong
    assert "coach_narrative" in hits[0] and "website_ai" in hits[1]


def test_tier_semantics_silent_on_live_ladder(ops, facts, tmp_path):
    assert ops.tier_semantics_hits(_scratch(tmp_path, _LADDER_GOOD), ops.budget_tier_cutoffs(), facts.marker_is_exempt) == []


def test_tier_semantics_honours_drift_ok_marker(ops, facts, tmp_path):
    text = _LADDER_BAD.rstrip("\n") + " <!-- drift-ok: quoting the pre-ADR-125 ladder -->\n"
    assert ops.tier_semantics_hits(_scratch(tmp_path, text), ops.budget_tier_cutoffs(), facts.marker_is_exempt) == []


def test_tier_semantics_ignores_lines_that_are_not_about_the_gate(ops, facts, tmp_path):
    """An equals sign in unrelated prose must never be read as a tier claim."""
    text = "Scoring weights: 1=coaches, 2=website AI in the legacy rubric.\n"
    assert ops.tier_semantics_hits(_scratch(tmp_path, text), ops.budget_tier_cutoffs(), facts.marker_is_exempt) == []


def test_tier_semantics_clean_on_real_docs(ops, facts):
    hits = ops.tier_semantics_hits(facts._scan_files(), ops.budget_tier_cutoffs(), facts.marker_is_exempt)
    assert hits == [], "\n".join(hits)


# ── B. doc tables naming a Lambda the CDK does not declare ───────────────────
_TABLE_BAD = "| Source | Lambda | S3 Trigger Path |\n|---|---|---|\n| Apple Health | `apple-health-ingestion` | `imports/*.xml` |\n"
_TABLE_GOOD = "| Source | Lambda | S3 Trigger Path |\n|---|---|---|\n| MacroFactor | `macrofactor-data-ingestion` | `uploads/*.csv` |\n"


def test_lambda_name_fires_on_retired_function(ops, facts, tmp_path):
    hits = ops.lambda_name_hits(_scratch(tmp_path, _TABLE_BAD), ops.cdk_function_names(), facts.line_is_exempt)
    assert len(hits) == 1 and "apple-health-ingestion" in hits[0]


def test_lambda_name_silent_on_live_function(ops, facts, tmp_path):
    assert ops.lambda_name_hits(_scratch(tmp_path, _TABLE_GOOD), ops.cdk_function_names(), facts.line_is_exempt) == []


def test_lambda_name_ignores_non_lambda_resources(ops, facts, tmp_path):
    """The candidate filter is the DERIVED suffix set — an SNS topic or a CloudTrail
    trail sharing the table has no Lambda-shaped suffix and is never judged."""
    text = "| Resource | Lambda | Name |\n|---|---|---|\n| Audit | `life-platform-trail` | trail |\n"
    assert ops.lambda_name_hits(_scratch(tmp_path, text), ops.cdk_function_names(), facts.line_is_exempt) == []


def test_lambda_name_ignores_columns_that_are_not_function_columns(ops, facts, tmp_path):
    text = "| Source | Path |\n|---|---|\n| Apple Health | `apple-health-ingestion` |\n"
    assert ops.lambda_name_hits(_scratch(tmp_path, text), ops.cdk_function_names(), facts.line_is_exempt) == []


def test_lambda_name_allows_an_explicitly_retired_row(ops, facts, tmp_path):
    text = "| Source | Lambda | Note |\n|---|---|---|\n| Apple Health | `apple-health-ingestion` | retired, ADR-103 |\n"
    assert ops.lambda_name_hits(_scratch(tmp_path, text), ops.cdk_function_names(), facts.line_is_exempt) == []


def test_lambda_name_clean_on_real_docs(ops, facts):
    hits = ops.lambda_name_hits(facts._scan_files(), ops.cdk_function_names(), facts.line_is_exempt)
    assert hits == [], "\n".join(hits)


# ── C. alarm inventory ───────────────────────────────────────────────────────
def test_alarm_count_fires_on_stale_inventory(ops, facts, tmp_path):
    hits = ops.alarm_count_hits(_scratch(tmp_path, "CloudWatch: 50 alarms total.\n"), 81, facts.line_is_exempt)
    assert len(hits) == 1 and "claims 50" in hits[0]


def test_alarm_count_honours_the_approximation(ops, facts, tmp_path):
    assert ops.alarm_count_hits(_scratch(tmp_path, "CloudWatch: ~81 metric alarms.\n"), 81, facts.line_is_exempt) == []


def test_alarm_count_ignores_incident_prose(ops, facts, tmp_path):
    """ "3 alarms sat red for 9 days" is a story about incidents, not an inventory claim."""
    assert ops.alarm_count_hits(_scratch(tmp_path, "3 alarms sat red for nine days.\n"), 81, facts.line_is_exempt) == []


def test_alarm_count_ignores_assigned_parameters(ops, facts, tmp_path):
    """An `=`-assigned number is a PARAMETER, not an inventory count.

    2026-08-22: `docs/PROPORTIONALITY.md:84` said "the Period=86400 alarms are re-cut"
    (the #2912 flap-detector row). The old lookbehind excluded `[\\w.$]` but not `=`, so
    the CloudWatch period parsed as a claim of 86400 alarms and red-mained BOTH `Docs CI`
    and `test / Unit Tests` off one line.
    """
    for line in (
        "the Period=86400 alarms are re-cut",
        "Threshold=500 alarms would page nightly",
        "EvaluationPeriods=1440 alarms",
    ):
        assert ops.alarm_count_hits(_scratch(tmp_path, line + "\n"), 108, facts.line_is_exempt) == [], line


def test_alarm_count_still_fires_when_the_number_merely_follows_punctuation(ops, facts, tmp_path):
    """The `=` carve-out must not blind the rule to real claims after other punctuation."""
    hits = ops.alarm_count_hits(_scratch(tmp_path, "CloudWatch (prod): 500 alarms total.\n"), 108, facts.line_is_exempt)
    assert len(hits) == 1 and "claims 500" in hits[0]


def test_alarm_count_clean_on_real_docs(ops, facts):
    truth = facts._ground_truth()["alarm_count"]
    hits = ops.alarm_count_hits(facts._scan_files(), truth, facts.line_is_exempt)
    assert hits == [], "\n".join(hits)


# ── D. secret inventory: count vs table, deleted-but-granted, freshness ──────
_SECRETS_DOC = """## Secrets Manager

**{n} active secrets**

| Secret | Used By |
|---|---|
| `life-platform/whoop` | Whoop Lambda |
| `life-platform/ai-keys` | inference fallback |
| ~~`life-platform/notion`~~ | **SOFT-DELETED** |
"""


def _secrets_scratch(tmp_path, n):
    p = tmp_path / "arch.md"
    p.write_text(_SECRETS_DOC.format(n=n), encoding="utf-8")
    return p


def test_secret_count_must_match_the_table(ops, tmp_path):
    doc = _secrets_scratch(tmp_path, 21)
    hits = ops.secret_inventory_hits(doc, 21, dt.date(2026, 8, 1), set(), today=dt.date(2026, 8, 2))
    assert len(hits) == 1 and "lists 2 live secrets but the stamped count is 21" in hits[0]


def test_secret_deleted_but_granted_is_flagged(ops, tmp_path):
    doc = _secrets_scratch(tmp_path, 2)
    granted = {"life-platform/notion"}
    hits = ops.secret_inventory_hits(doc, 2, dt.date(2026, 8, 1), granted, today=dt.date(2026, 8, 2))
    assert len(hits) == 1 and "life-platform/notion" in hits[0]


def test_secret_inventory_silent_when_consistent_and_fresh(ops, tmp_path):
    doc = _secrets_scratch(tmp_path, 2)
    assert ops.secret_inventory_hits(doc, 2, dt.date(2026, 8, 1), set(), today=dt.date(2026, 8, 2)) == []


def test_secret_verification_stamp_goes_stale(ops, tmp_path):
    """The count can't be derived from the repo, so its VERIFICATION DATE is what CI
    holds — this is the rule that ends 'manufactured freshness' on a stale fact."""
    doc = _secrets_scratch(tmp_path, 2)
    stale = dt.date(2026, 8, 2) - dt.timedelta(days=ops.SECRET_VERIFY_MAX_AGE_DAYS + 1)
    hits = ops.secret_inventory_hits(doc, 2, stale, set(), today=dt.date(2026, 8, 2))
    assert len(hits) == 1 and "--refresh-secrets" in hits[0]


def test_secret_inventory_reports_an_unparseable_literal(ops, tmp_path):
    """A gate that silently no-ops when its ground truth vanishes is worse than none."""
    doc = _secrets_scratch(tmp_path, 2)
    hits = ops.secret_inventory_hits(doc, None, None, set())
    assert len(hits) == 1 and "vacuous" in hits[0]


def test_secret_inventory_clean_on_real_docs(ops):
    count, verified = ops.stamped_secret_fact()
    hits = ops.secret_inventory_hits(ops.ARCHITECTURE_PATH, count, verified, ops.cdk_granted_secrets())
    assert hits == [], "\n".join(hits)


# ── the whole gate still exits 0 on the real tree ────────────────────────────
def test_gate_passes_on_the_repo():
    # #3224: the SAME byte-identical scan of the SAME unmutated tree is asserted by
    # three tests (here, test_doc_facts_ops_2003.py, test_wiki_checkers.py) and cost
    # 15.4s of local wall-clock EACH — 8.1s of it the gate census #3126/#3156 put on
    # the auto-discovery path. Routed through the shared per-process cache so the
    # suite pays for it once. The assertion is unchanged; only the spawn is shared.
    r = repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")
    assert r.returncode == 0, r.stdout + r.stderr
