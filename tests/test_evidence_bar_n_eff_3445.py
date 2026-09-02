"""tests/test_evidence_bar_n_eff_3445.py — the Evidence Bar's discoveries block and
served `n_eff` (#3445, review:calc-proof-2026-09).

Two co-located ADR-104 defects on one public surface, both fixed here:

1. **Double-dead ledger discoveries block.** `site_api_ledger.discoveries()`'s
   ai_findings loop required `item["correlations"]` to be a LIST of `{r, n}`
   dicts. `weekly_correlation_compute_lambda.store_correlations` has only ever
   written it as a MAP keyed by pair label -> `{pearson_r, n_days, n_eff,
   fdr_significant, ...}` (see `store_correlations`, and the live fixture
   below, pulled verbatim from the `life-platform` table). The `isinstance`
   check made the loop `continue` on every real record — structurally always
   `[]` — with no other producer of `ai_findings` to ever populate it.

2. **Served `n_eff` equalled raw n.** Both call sites into the ONE sanctioned
   evidence function (`stats_core.correlation_evidence`, ADR-105) omitted the
   `n_eff=` kwarg, so it silently fell back to raw n (`ne = float(n_int)`).
   `correlation_evidence`'s `level` (`>=21 high / >=8 medium / else low`)
   drives what the front-end calls a claim's confidence — grading on raw n
   instead of the autocorrelation-corrected effective n can render a claim
   "medium" that the real independent information in the series doesn't
   support.

The fixture (`tests/fixtures/site_api/weekly_correlations_record_3445.json`)
is a byte-shaped copy of a REAL stored `weekly_correlations` record (queried
2026-09-02, `WEEK#2026-W35`) — fixture-must-be-the-wire: a future
producer/reader shape drift reds this test instead of quietly going back to
serving `[]`. It carries a genuine live level flip: `steps_vs_sleep` has
`n_days=11` (raw-n level "medium") but `n_eff=7.7` (true level "low") while
still `fdr_significant=True` — exactly the "graded medium on a sample the
data doesn't support" risk the issue named.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "web"), _REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_discovery, site_api_ledger  # noqa: E402

_FIXTURE_PATH = os.path.join(_REPO, "tests", "fixtures", "site_api", "weekly_correlations_record_3445.json")

with open(_FIXTURE_PATH) as _f:
    _LIVE_RECORD = json.load(_f)


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


class _RaisingS3:
    """discoveries() reads config/experiment_library.json first; the ai_findings
    block under test doesn't depend on it — degrade it honestly (as production
    already does on a real S3 failure) so this test isolates the block it's for."""

    def get_object(self, **kwargs):
        raise RuntimeError("not needed for this test")


class _FakeBoto3:
    def client(self, *a, **k):
        return _RaisingS3()


def _discoveries_body(record=_LIVE_RECORD):
    table = FakeDdbTable(rows=[record])
    resp = site_api_ledger.discoveries(_g={"boto3": _FakeBoto3(), "table": table})
    return _body(resp)


# ── Leg 1: the discoveries block reads the real stored MAP shape ────────────


def test_ai_findings_nonempty_against_the_live_store_shape():
    body = _discoveries_body()
    # The double-dead bug served [] unconditionally. Against the byte-shaped
    # live fixture this must now be non-empty.
    assert body["ai_findings"] != []
    pairs = {(f["metric_a"], f["metric_b"]) for f in body["ai_findings"]}
    # Both FDR-significant pairs in the fixture surface...
    assert ("Resting HR", "Recovery") in pairs
    assert ("Steps", "Sleep Score") in pairs
    # ...the non-significant insufficient-data pair does not.
    assert ("Calories", "Day Grade") not in pairs


def test_correlations_map_shape_with_no_significant_pair_is_honestly_empty():
    # A record whose correlations are all non-significant must serve an empty
    # ai_findings list — not raise, not fabricate a finding.
    record = dict(_LIVE_RECORD)
    record["correlations"] = {"calories_vs_day_grade": _LIVE_RECORD["correlations"]["calories_vs_day_grade"]}
    body = _discoveries_body(record)
    assert body["ai_findings"] == []


def test_legacy_flat_list_shape_still_accepted():
    # Defensive: a hypothetical legacy record already shaped as a flat list of
    # {r, n, metric_a, metric_b, fdr_significant} dicts must still work — the
    # fix widens acceptance (map OR list), it never narrows it.
    record = dict(_LIVE_RECORD)
    record["correlations"] = [
        {
            "metric_a": "hrv",
            "metric_b": "recovery_score",
            "r": 0.5,
            "n": 30,
            "fdr_significant": True,
        }
    ]
    body = _discoveries_body(record)
    assert len(body["ai_findings"]) == 1
    assert body["ai_findings"][0]["metric_a"] == "HRV"


# ── Leg 2: served n_eff is the stored effective n, not raw n ────────────────


def test_ai_findings_evidence_carries_true_n_eff_no_flip_case():
    body = _discoveries_body()
    rhr = next(f for f in body["ai_findings"] if f["metric_a"] == "Resting HR")
    assert rhr["n"] == 11
    assert rhr["n_eff"] == 10.6
    assert rhr["evidence"]["n_eff"] == 10.6
    # 10.6 and 11 both clear the medium (>=8) threshold — no flip here.
    assert rhr["evidence"]["level"] == "medium"


def test_ai_findings_evidence_level_flips_on_true_n_eff():
    body = _discoveries_body()
    steps = next(f for f in body["ai_findings"] if f["metric_a"] == "Steps")
    assert steps["n"] == 11  # raw n alone would grade "medium" (>=8)
    assert steps["n_eff"] == 7.7  # true effective n drops it below 8
    assert steps["evidence"]["n_eff"] == 7.7
    assert steps["evidence"]["level"] == "low"
    # Regression pin: the bug's exact shape (n_eff dropped, ne defaults to n)
    # would have graded this "medium" — a claim the effective sample doesn't
    # support, and one the site actually served (fdr_significant=True).
    assert steps["evidence"]["level"] != "medium"


# ── /api/correlations (site_api_discovery.correlations) — the same leg ──────


def _correlations_pairs(record=_LIVE_RECORD):
    table = FakeDdbTable(rows=[record])
    resp = site_api_discovery.correlations(event=None, _g={"table": table})
    body = _body(resp)
    return body["correlations"]["pairs"]


def test_correlations_endpoint_n_eff_flip_on_live_fixture():
    pairs = _correlations_pairs()
    steps = next(p for p in pairs if p["field_a"] == "steps" and p["field_b"] == "sleep_score")
    assert steps["n"] == 11
    assert steps["evidence"]["n_eff"] == 7.7
    assert steps["evidence"]["level"] == "low"

    rhr = next(p for p in pairs if p["field_a"] == "resting_hr" and p["field_b"] == "recovery_score")
    assert rhr["evidence"]["n_eff"] == 10.6
    assert rhr["evidence"]["level"] == "medium"


def test_correlations_endpoint_missing_n_eff_falls_back_to_raw_n_honestly():
    # A record predating n_eff (no key at all) must not crash or fabricate a
    # value — correlation_evidence's own None-fallback takes over.
    record = dict(_LIVE_RECORD)
    calories = dict(_LIVE_RECORD["correlations"]["calories_vs_day_grade"])
    record["correlations"] = {"calories_vs_day_grade": {**calories, "pearson_r": 0.4, "n_days": 25, "fdr_significant": True}}
    pairs = _correlations_pairs(record)
    cal = pairs[0]
    assert "n_eff" not in _LIVE_RECORD["correlations"]["calories_vs_day_grade"]
    assert cal["evidence"]["n_eff"] == 25  # falls back to raw n, not fabricated
    assert cal["evidence"]["level"] == "high"
