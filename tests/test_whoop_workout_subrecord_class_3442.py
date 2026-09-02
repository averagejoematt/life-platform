"""tests/test_whoop_workout_subrecord_class_3442.py — the whoop #WORKOUT# sub-record
clobber class (#3442).

The whoop raw partition stores per-workout sub-records under DATE#<d>#WORKOUT#<uuid>
sort keys alongside the plain DATE#<d> day row. Eight date-keyed consumers indexed
that partition assuming one record per date, so the sub-record (sorted AFTER the day
row, carrying per-workout strain and none of the day fields) last-write-won over the
day row, or polluted counts. Prior art: field_notes' 2026-W26 "20 nights of sleep in
one week" incident, fixed at that one site only.

Fixtures are WIRE SNAPSHOTS of the real whoop partition (field-pruned, sk grammar and
field presence/absence verbatim — the fixture-must-be-the-wire rule):
  - whoop_sk_zoo_2026w35.json          — the W35 candidate set (2026-08-17..30)
  - whoop_sk_zoo_acwr_2026-08-31.json  — the ACWR 84-day lookback for 2026-08-31

The regression targets are the calc-proof verifier's byte-exact reproductions,
re-derived live on 2026-09-02:
  - weekly correlation hrv_vs_recovery: n=11 r=0.9799 WITH the clobber (the stored
    W35 record, byte-exact) vs n=14 r=0.9666 from true day rows
  - ACWR target 2026-08-31: 0.945 published (clobbered, 24/85 window days corrupted)
    vs 1.040 from true day rows

Fully offline: no AWS, no network. Fakes are hand-written (never MagicMock).
"""

import ast
import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common import digest_utils  # noqa: E402

_FIXTURES = os.path.join(_REPO, "tests", "fixtures")


def _load(name):
    with open(os.path.join(_FIXTURES, name)) as f:
        return json.load(f)["records"]


W35_ZOO = _load("whoop_sk_zoo_2026w35.json")
ACWR_ZOO = _load("whoop_sk_zoo_acwr_2026-08-31.json")


# ══════════════════════════════════════════════════════════════════════════════
# The predicate itself
# ══════════════════════════════════════════════════════════════════════════════


def test_fixture_is_the_wire():
    """The zoo really contains both shapes — a filter test over a subs-free fixture
    would be a vacuous negative control."""
    subs = [r for r in W35_ZOO if not digest_utils.is_day_row(r)]
    days = [r for r in W35_ZOO if digest_utils.is_day_row(r)]
    assert len(days) == 14 and len(subs) == 5
    # The defect mechanism: a sub-record shares its day's `date` but not its fields.
    assert all("#WORKOUT#" in r["sk"] for r in subs)
    assert all("hrv" not in r and "recovery_score" not in r for r in subs)
    assert all("strain" in r for r in subs)  # per-workout strain — the clobber payload


def test_day_row_predicate():
    assert digest_utils.is_day_row({"sk": "DATE#2026-08-18"})
    assert not digest_utils.is_day_row({"sk": "DATE#2026-08-18#WORKOUT#5c539cdb-08c2-40cb-bed2-46a9420a9c4e"})
    assert not digest_utils.is_day_row({"sk": "DATE#2026-08-18#journal#daily#abc"})
    assert not digest_utils.is_day_row({"sk": "PROFILE#v1"})
    # sk-absent = synthetic/field-stripped record — cannot be a sub-record, never dropped
    assert digest_utils.is_day_row({})
    assert digest_utils.filter_day_rows(W35_ZOO) == [r for r in W35_ZOO if digest_utils.is_day_row(r)]


# ══════════════════════════════════════════════════════════════════════════════
# query_range: the paved road is day-rows-only
# ══════════════════════════════════════════════════════════════════════════════


class _FakeTable:
    """Hand-written paginating fake: serves the zoo in two pages to prove the
    filter survives pagination."""

    def __init__(self, items):
        self._pages = [items[: len(items) // 2], items[len(items) // 2 :]]

    def query(self, **kwargs):
        if "ExclusiveStartKey" in kwargs:
            return {"Items": self._pages[1]}
        return {"Items": self._pages[0], "LastEvaluatedKey": {"sk": "cursor"}}


def test_query_range_returns_day_rows_only():
    out = digest_utils.query_range(_FakeTable(W35_ZOO), "whoop", "2026-08-17", "2026-08-30", include_pilot=True)
    assert len(out) == 14
    assert all("#WORKOUT#" not in r["sk"] for r in out.values())
    # 2026-08-18 had a workout sub-record sorted after the day row; the day row
    # (hrv-bearing) must be the one that survives — the exact clobber this fixes.
    assert out["2026-08-18"].get("hrv") is not None


# ══════════════════════════════════════════════════════════════════════════════
# Regression 1 — weekly correlation hrv_vs_recovery through the REAL path
# ══════════════════════════════════════════════════════════════════════════════


def _wc():
    sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))
    import weekly_correlation_compute_lambda as wc

    return wc


def test_w35_hrv_vs_recovery_regression(monkeypatch):
    wc = _wc()
    fixture_by_source = {"whoop": W35_ZOO}
    monkeypatch.setattr(wc, "fetch_range", lambda source, s, e: list(fixture_by_source.get(source, [])))
    series = wc.assemble_daily_series("2026-08-17", "2026-08-30")
    results = wc.compute_correlations(series)
    hv = results["hrv_vs_recovery"]
    # The verifier's byte-exact "without" reproduction: every workout day present.
    assert hv["n_days"] == 14
    assert abs(hv["pearson_r"] - 0.9666) < 0.0001


def test_w35_clobber_control():
    """Positive control: the PRE-fix index (last-write-wins, no day-row filter)
    reproduces the stored W35 record byte-exact — n=11, r=0.9799. If this stops
    matching, the fixture no longer encodes the defect and the regression above
    proves nothing."""
    by_date = {}
    for r in W35_ZOO:  # the old index_by_date, verbatim minus the filter
        d = r.get("date") or r.get("sk", "").replace("DATE#", "")[:10]
        if d:
            by_date[d] = r
    xs, ys = [], []
    for d in sorted(by_date):
        r = by_date[d]
        if r.get("hrv") is not None and r.get("recovery_score") is not None:
            xs.append(float(r["hrv"]))
            ys.append(float(r["recovery_score"]))
    assert len(xs) == 11  # 3 workout-day rows clobbered into field-absent fragments
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    assert abs(round(num / den, 4) - 0.9799) < 0.0001


# ══════════════════════════════════════════════════════════════════════════════
# Regression 2 — ACWR through the real strain builder
# ══════════════════════════════════════════════════════════════════════════════


def _acwr():
    sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))
    import acwr_compute_lambda as acwr

    return acwr


def test_acwr_2026_08_31_regression():
    acwr = _acwr()
    # Fixed path: day rows only — the handler now applies filter_day_rows.
    series, n = acwr._build_daily_strain(digest_utils.filter_day_rows(ACWR_ZOO), "2026-06-08", "2026-08-31")
    fixed, _, _ = acwr._ewma_acwr(series)
    assert fixed == 1.040
    # Control: the unfiltered wire reproduces the published (corrupted) 0.945.
    series_c, _ = acwr._build_daily_strain(ACWR_ZOO, "2026-06-08", "2026-08-31")
    clobbered, _, _ = acwr._ewma_acwr(series_c)
    assert clobbered == 0.945
    corrupted = sum(1 for (d1, v1), (_, v2) in zip(series_c, series) if v1 != v2)
    assert corrupted == 24  # the verifier's 24/85 census


def test_acwr_handler_filters_the_wire():
    """Source pin: the handler must filter the whoop fetch before building the
    series — the numeric test above proves the math, this proves the running path."""
    src = open(os.path.join(_REPO, "lambdas", "compute", "acwr_compute_lambda.py")).read()
    fetch = src.index('_fetch_range("whoop"')
    build = src.index("_build_daily_strain(whoop_items")
    filt = src.index("filter_day_rows(whoop_items)")
    assert fetch < filt < build


# ══════════════════════════════════════════════════════════════════════════════
# Regression 3 — the inventory count (intelligence_common)
# ══════════════════════════════════════════════════════════════════════════════


class _InventoryFake:
    """Answers intelligence_common's per-partition queries. Whoop serves the W35
    zoo; every other partition is empty. Records the kwargs whoop was asked with."""

    def __init__(self):
        self.whoop_kwargs = []

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = getattr(getattr(cond, "_values", [None])[0], "_values", [None, None])[1] if cond is not None else None
        blob = str(getattr(pk, "value", pk))
        if "whoop" in blob:
            self.whoop_kwargs.append(kwargs)
            if "ProjectionExpression" in kwargs and kwargs.get("ScanIndexForward") is None:
                pass
            if kwargs.get("Select") == "COUNT":
                return {"Count": len(W35_ZOO)}
            items = [{"sk": r["sk"]} for r in W35_ZOO]
            if kwargs.get("ScanIndexForward") is False:
                items = list(reversed(items))[: kwargs.get("Limit", len(items))]
            return {"Items": items}
        if kwargs.get("Select") == "COUNT":
            return {"Count": 0}
        return {"Items": []}


def test_inventory_counts_whoop_day_rows(monkeypatch):
    from intelligence import intelligence_common as ic

    fake = _InventoryFake()
    monkeypatch.setattr(ic, "table", fake)
    inv = ic.build_data_inventory()
    assert inv["whoop"]["records"] == 14  # 19 wire rows, 5 of them #WORKOUT# fragments
    # And the count read really was the sk projection, not Select=COUNT.
    assert any("ProjectionExpression" in k and k.get("Select") != "COUNT" for k in fake.whoop_kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# Prior-art convergence
# ══════════════════════════════════════════════════════════════════════════════


def test_field_notes_converged_on_shared_predicate():
    from intelligence import field_notes_lambda as fn

    assert fn._DAY_SK_RE is digest_utils.DAY_SK_RE


# ══════════════════════════════════════════════════════════════════════════════
# THE SET GUARD (#3442 acceptance box 1) — a 9th member cannot re-join silently
# ══════════════════════════════════════════════════════════════════════════════
#
# Census: every module under lambdas/ + mcp/ that passes the literal "whoop" to a
# query/fetch-shaped call. Each current site is REGISTERED below with its lane:
#
#   shared-guard — references the #3442 predicate (filter_day_rows / is_day_row /
#                  DAY_SK_RE); the paved road.
#   non-member   — verified clean by the 2026-09-02 calculation-proof pass or by
#                  the mechanism named in the reason (exact-key fetch_date reads,
#                  first-match indexing where the day row sorts first, field-absent-
#                  safe extraction, or an explicit downstream filter).
#
# A NEW module querying whoop, or a changed site-count in a registered one, fails
# this test until the author either adopts the shared predicate or registers the
# site here with its verified mechanism. That is the guard-the-SET contract: the
# 2026-W26 incident was fixed at one site and the class regrew to eight — additions
# now land through a conscious lane choice, never silently.

_QUERYISH = ("query", "fetch")

# module (repo-relative) → (expected literal-"whoop" query sites, lane, reason)
_WHOOP_CONSUMER_REGISTRY = {
    "lambdas/common/digest_utils.py": (0, "shared-guard", "home of the predicate; query_range is day-rows-only"),
    "lambdas/compute/acwr_compute_lambda.py": (1, "shared-guard", "filter_day_rows after the whoop fetch (#3442 member 2)"),
    "lambdas/compute/weekly_correlation_compute_lambda.py": (1, "shared-guard", "is_day_row in index_by_date (#3442 member 1)"),
    "lambdas/ingestion/enrichment_lambda.py": (1, "shared-guard", "filter_day_rows on the by-date whoop index (#3442 member 5)"),
    "lambdas/intelligence/ai_expert_analyzer_lambda.py": (2, "shared-guard", "filter_day_rows on both whoop fetches (#3442 member 6)"),
    "lambdas/intelligence/field_notes_lambda.py": (1, "shared-guard", "_DAY_SK_RE is the shared predicate (the 2026-W26 prior art)"),
    "lambdas/emails/chronicle_data.py": (
        1,
        "shared-guard",
        "reads via digest_utils.query_range (day-rows-only) injected from wednesday_chronicle (#3442 member 3)",
    ),
    "lambdas/coach/coach_domain_facts.py": (2, "non-member", "verified clean 2026-09-02 — field-absent-safe extraction over the list"),
    "lambdas/coach/coach_event_triggers.py": (1, "non-member", "verified clean 2026-09-02 — field-absent-safe extraction"),
    "lambdas/coach/spiral_breaker.py": (1, "non-member", "explicit local #WORKOUT# skip — a pre-existing local instance of the guard"),
    "lambdas/compute/character_sheet_lambda.py": (
        2,
        "non-member",
        "fetch_date = exact-key day read; fetch_range field-absent-safe (calc-proof non-member)",
    ),
    "lambdas/compute/circadian_compliance_lambda.py": (1, "non-member", "calc-proof verified non-member (explicit handling)"),
    "lambdas/compute/daily_insight_compute_lambda.py": (3, "non-member", "daily_* verified field-absent-safe (calc-proof non-member)"),
    "lambdas/compute/daily_metrics_compute_lambda.py": (5, "non-member", "daily_* verified field-absent-safe (calc-proof non-member)"),
    "lambdas/compute/dashboard_refresh_lambda.py": (1, "non-member", "fetch_date = exact-key day read"),
    "lambdas/compute/personal_baselines_lambda.py": (1, "non-member", "field-absent-safe per-field series extraction"),
    "lambdas/content/output_writers.py": (4, "non-member", "field-absent-safe extraction (calc-proof sweep)"),
    "lambdas/emails/daily_brief_lambda.py": (7, "non-member", "fetch_date exact-key + field-absent-safe ranges (calc-proof sweep)"),
    "lambdas/emails/monday_compass_lambda.py": (
        1,
        "non-member",
        "single-day query, [0] first-match — the day row sorts before its sub-records",
    ),
    "lambdas/emails/monthly_digest_lambda.py": (
        0,
        "shared-guard",
        "filter_day_rows on both raw arms before ex_whoop (#3442 member 7; fetch is via SOURCES loop, no literal site)",
    ),
    "lambdas/intelligence/challenge_generator_lambda.py": (1, "non-member", "field-absent-safe context summary"),
    "lambdas/web/site_api_autonomic.py": (1, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "lambdas/web/site_api_body.py": (2, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "lambdas/web/site_api_fingerprint.py": (1, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "lambdas/web/site_api_freshness.py": (1, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "lambdas/web/site_api_nutrition.py": (1, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "lambdas/web/site_api_pulse.py": (1, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "lambdas/web/site_api_rollups.py": (7, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "lambdas/web/site_api_sleep.py": (2, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "lambdas/web/site_api_training.py": (1, "non-member", "site_api_* verified explicit filters (calc-proof non-member)"),
    "mcp/tools_health.py": (2, "non-member", "field-absent-safe tool extraction"),
    "mcp/tools_training.py": (1, "non-member", "field-absent-safe tool extraction"),
}

_GUARD_TOKENS = ("filter_day_rows", "is_day_row", "DAY_SK_RE", "digest_utils.query_range")


def _census():
    found = {}
    for root in ("lambdas", "mcp"):
        for dirpath, _, files in os.walk(os.path.join(_REPO, root)):
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                p = os.path.join(dirpath, f)
                rel = os.path.relpath(p, _REPO)
                try:
                    tree = ast.parse(open(p).read())
                except SyntaxError:
                    continue
                n = 0
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                    if not any(t in name.lower() for t in _QUERYISH):
                        continue
                    if any(isinstance(a, ast.Constant) and a.value == "whoop" for a in node.args):
                        n += 1
                if n:
                    found[rel.replace(os.sep, "/")] = n
    return found


def test_whoop_consumer_set_guard():
    found = _census()
    problems = []
    for rel, n in sorted(found.items()):
        if rel == "tests/" or rel.startswith("tests/"):
            continue
        reg = _WHOOP_CONSUMER_REGISTRY.get(rel)
        if reg is None:
            problems.append(
                f"NEW whoop consumer: {rel} ({n} site(s)). Filter with common.digest_utils."
                f" filter_day_rows/is_day_row (the #3442 predicate) or register it here with"
                f" a verified mechanism — sub-records (DATE#<d>#WORKOUT#<uuid>) otherwise"
                f" clobber or pollute date-keyed reads."
            )
        elif reg[0] != n and reg[0] != 0:
            problems.append(
                f"{rel}: literal-whoop query sites changed ({reg[0]} registered, {n} found)."
                f" Re-verify the new/changed site against #3442 and update the registry."
            )
    # Registered shared-guard modules must actually reference the predicate.
    for rel, (n, lane, _reason) in _WHOOP_CONSUMER_REGISTRY.items():
        path = os.path.join(_REPO, rel)
        if lane == "shared-guard" and os.path.exists(path):
            src = open(path).read()
            if not any(tok in src for tok in _GUARD_TOKENS):
                problems.append(f"{rel} is registered shared-guard but no longer references the #3442 predicate.")
    # And registered modules that vanished should be pruned (keeps the registry honest).
    for rel in _WHOOP_CONSUMER_REGISTRY:
        if not os.path.exists(os.path.join(_REPO, rel)):
            problems.append(f"{rel} is registered but no longer exists — prune the registry entry.")
    assert not problems, "\n".join(problems)
