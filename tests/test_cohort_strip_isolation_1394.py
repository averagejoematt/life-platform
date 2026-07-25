"""tests/test_cohort_strip_isolation_1394.py — structural isolation of the cohort
partition from Matthew's own statistics (#1394, epic #1366, AC3).

The load-bearing privacy invariant of the Cohort Strip: participant-reported numbers
live in their OWN DynamoDB partition family (`COHORT#<metric>#<week>`) and are NEVER
pooled into Matthew's statistics or calibration. This test asserts that BOTH
directions of the wall hold, statically, so it genuinely bites if a future change
wires the two data sets together:

  A. NO stats/calibration pipeline source references the cohort partition family.
     (If someone starts reading COHORT# rows in the character engine, a compute
     Lambda, the stats core, or the calibration core → this test fails.)
  B. The cohort handlers themselves NEVER touch a Matthew data partition
     (`USER#…#SOURCE#…` / USER_PREFIX). Matthew's dot on the strip comes from the
     weekly config, not a read of his own partitions.

The file list is asserted non-empty and every entry must exist, so the scan can
never vacuously pass.
"""

import inspect
import io
import os
import sys
import tokenize

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import site_api_social as se  # noqa: E402

# Matthew's statistics + calibration surfaces. Every one queries HIS OWN
# `USER#…#SOURCE#…` partitions — none may ever reach into the cohort family.
_PIPELINE_FILES = [
    "lambdas/stats_core.py",
    "lambdas/calibration_core.py",
    "lambdas/eyeball_calibration.py",
    "lambdas/character_engine.py",
    "lambdas/insight_writer.py",
    "lambdas/measurable_metrics.py",
    "lambdas/compute/character_sheet_lambda.py",
    "lambdas/compute/daily_metrics_compute_lambda.py",
    "lambdas/compute/daily_insight_compute_lambda.py",
    "lambdas/compute/adaptive_mode_lambda.py",
    "lambdas/compute/hypothesis_engine_lambda.py",
    "lambdas/compute/personal_baselines_lambda.py",
    "lambdas/compute/weekly_correlation_compute_lambda.py",
    "lambdas/compute/forecast_engine_lambda.py",
    # The calibration read surface served to the site.
    "lambdas/web/site_api_data.py",
]

# The whole compute directory is swept too (defense against a new pipeline Lambda
# quietly pooling cohort numbers). Combined with the explicit list above.
_COMPUTE_DIR = os.path.join(_REPO, "lambdas", "compute")

_COHORT_TOKENS = ("COHORT#", "COHORT_PK_PREFIX", "_cohort_partition", "cohort_submit", "cohort_strip")


def _sweep_files():
    files = list(_PIPELINE_FILES)
    for name in sorted(os.listdir(_COMPUTE_DIR)):
        if name.endswith(".py") and name != "__init__.py":
            rel = os.path.join("lambdas", "compute", name)
            if rel not in files:
                files.append(rel)
    return files


def test_pipeline_file_list_is_real_and_present():
    """Guard against a vacuous pass — the list is non-empty and every file exists."""
    files = _sweep_files()
    assert len(files) >= 12
    for rel in files:
        assert os.path.exists(os.path.join(_REPO, rel)), f"pipeline file missing: {rel}"


def test_stats_pipelines_never_reference_the_cohort_partition():
    """DIRECTION A: no stats/calibration source may reference the cohort family."""
    offenders = []
    for rel in _sweep_files():
        src = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        for tok in _COHORT_TOKENS:
            if tok in src:
                offenders.append(f"{rel} references cohort token {tok!r}")
    assert not offenders, "Matthew's stats/calibration pipeline must NEVER read the cohort partition. Offenders:\n  " + "\n  ".join(
        offenders
    )


def _code_without_comments(src: str) -> str:
    """Return `src` with comment tokens removed — the invariant is about CODE, not the
    prose in comments (which legitimately names the USER#…#SOURCE# family it avoids)."""
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            out.append(tok.string)
    except tokenize.TokenError:
        return src
    return " ".join(out)


def test_cohort_handlers_never_touch_matthew_partitions():
    """DIRECTION B: the cohort handlers only touch the COHORT family, never USER#…#SOURCE#."""
    for fn in (se._handle_cohort_submit, se.handle_cohort_strip):
        raw = inspect.getsource(fn)
        assert "COHORT#" in raw or "_cohort_partition" in raw, f"{fn.__name__} does not use the cohort partition"
        code = _code_without_comments(raw)  # comments legitimately reference the family they avoid
        assert "USER#" not in code, f"{fn.__name__} references a USER partition in code"
        assert "USER_PREFIX" not in code, f"{fn.__name__} references USER_PREFIX in code"
        assert "SOURCE#" not in code, f"{fn.__name__} references a SOURCE partition in code"


def test_cohort_partition_prefix_is_disjoint_from_user_family():
    """The prefix constant is a distinct family — it can never collide with USER#…#SOURCE#."""
    assert se.COHORT_PK_PREFIX == "COHORT#"
    pk = se._cohort_partition("resting_heart_rate", "2026-W30")
    assert pk == "COHORT#resting_heart_rate#2026-W30"
    assert not pk.startswith("USER#")
    assert "SOURCE#" not in pk
