"""tests/test_emf_namespace_ledger_2837.py — #2837's derivation guard over the EMF estate.

The defect: 743 custom-metric series across 35 namespaces with **no inventory or
owner**, added ad hoc by ~16 emitting modules, so sprawl was visible only when
the CloudWatch bill landed (MetricMonitorUsage $4.41 Jun -> $16.46 Jul,
overtaking AlarmMonitorUsage). A one-time audit fixes today and rots by
Thursday; what has to hold is that **a namespace cannot exist without a row
that names its consumer**.

So this guards the registry in BOTH directions, which is the derivation-guard
pattern and the half most registries skip:

  * a namespace the tree emits with no ledger row reds — you cannot ship a new
    namespace without deciding, at PR time, what will read it;
  * a ledger row whose emitter is gone reds — the ledger cannot decay into a
    hand-list describing code that no longer exists.

And it grades the verdicts against derived reality, so the classification
cannot go stale in either direction either: a `keep` must name a consumer that
actually exists, and a `retire-candidate` that has since grown an alarm must be
reclassified rather than quietly staying on a kill list.

THE SECOND HALF — the discriminators. A registry guard is only as good as the
discovery under it, and this discovery has four non-obvious rules that a
well-meaning simplification would each break. Those are pinned against the REAL
modules that motivated them (`reference_fixture_must_be_the_wire`: a fixture
proving a rule about a shape nobody ships proves nothing):

  * `notion_lambda`'s `User-Agent: LifePlatform/1.0` header is NOT a namespace;
  * `site_api_common` emits `LifePlatform/SiteAPI` through an IMPORTED constant
    and never writes the literal (#3002 forbids it), so a literal scan misses
    the estate's largest namespace entirely;
  * `traffic_digest_lambda` names three namespaces it only QUERIES — a reader,
    not a producer;
  * `timeout_watchdog` emits through a defaulted parameter, and
    `monitoring_stack` mints two namespaces from log text with no Python
    emitter at all.

The live half (`deploy/emf_series_census.py`) is exercised for its OFFLINE
contract only — that it skips loudly rather than passing silently. CI
pull-request lanes have no AWS credentials, and a check that cannot fail is the
failure mode this repo has filed twice.
"""

import ast
import collections
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "deploy"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import emf_namespace_discovery as disc  # noqa: E402
import emf_namespace_ledger as ledger  # noqa: E402
import emf_series_census as census  # noqa: E402

PRODUCERS = disc.discover_producers()
CONSUMERS = disc.discover_consumers()
LEDGER = ledger.LEDGER


def _kinds(ns):
    return disc.consumer_kinds(ns, CONSUMERS)


# ── the registry, both directions ─────────────────────────────────────────────


def test_every_emitted_namespace_is_registered():
    """A namespace the tree writes with no ledger row reds — at PR time, before the bill.

    This is the whole outcome the issue asks for: "every namespace names its
    consumer or gets retired." A new namespace is a decision, and the decision
    is made here or it is made by CloudWatch's invoice three weeks later.
    """
    missing = sorted(set(PRODUCERS) - set(LEDGER))
    assert not missing, (
        f"{len(missing)} emitted namespace(s) have no row in deploy/emf_namespace_ledger.py: {missing}. "
        "Add a row naming the owner, the consumer (alarm/dashboard/reader/ritual) or the retirement "
        "rationale, and a series budget."
    )


def test_the_ledger_does_not_rot():
    """A row whose emitter is gone reds — no describing code that no longer exists.

    The other direction of the same set equality. Together these two make the
    ledger's key set *identical* to the producer set, which is a stronger claim
    than either containment alone and the reason there is no third state to
    drift into.
    """
    stale = sorted(set(LEDGER) - set(PRODUCERS))
    assert not stale, (
        f"ledger rows with no emitter anywhere in the tree: {stale}. Either the emitter was removed "
        "(drop the row — the live series age out on their own and the census reports them as live "
        "orphans meanwhile) or discovery cannot see a new emit shape (fix "
        "deploy/emf_namespace_discovery.py)."
    )


def test_the_ledger_carries_no_retired_namespace_spellings():
    """A dead namespace is NOT recorded here, and #3002 is why.

    The first draft of this ledger carried `LifePlatform/SiteApi` — the casing
    twin #3002 removed from the tree — as an "orphan" row, so the census would
    not report its residual live series as a surprise.
    `test_no_case_twin_namespaces_anywhere` redded on it immediately, and
    correctly: #3002's rule is that the twin spelling is unexpressible ANYWHERE
    in the repo, and an inventory file is exactly the sort of well-meaning
    exception that makes a repo-wide rule stop being one. Live-but-unwritten
    namespaces are the census's job — it can see CloudWatch, and it needs no
    literal to name what it read.
    """
    canonical = disc.shared_namespace_constants()["SITE_API_METRIC_NAMESPACE"]
    lowered = {ns.lower() for ns in LEDGER}
    assert canonical.lower() in lowered, "sanity: the canonical site-API namespace IS registered"
    assert sum(1 for ns in LEDGER if ns.lower() == canonical.lower()) == 1, "exactly one spelling of the site-API namespace may appear"


# ── the verdicts, graded against derived reality ─────────────────────────────


def test_keep_rows_name_a_real_consumer():
    """`keep` means something reads it. A document ritual counts — if the document exists."""
    unjustified = []
    for ns, row in LEDGER.items():
        if row["verdict"] != ledger.KEEP:
            continue
        if _kinds(ns):
            continue
        ritual = row["ritual_consumer"]
        if ritual and os.path.exists(os.path.join(_REPO, ritual)):
            continue
        unjustified.append(ns if not ritual else f"{ns} (ritual_consumer {ritual!r} does not exist)")
    assert not unjustified, (
        f"'{ledger.KEEP}' rows with no alarm, dashboard, code reader or existing ritual_consumer: "
        f"{sorted(unjustified)}. A namespace nobody reads is a '{ledger.RETIRE_CANDIDATE}'."
    )


def test_retire_candidates_are_still_unread():
    """A candidate that has since grown a consumer must leave the kill list.

    The direction registries forget. Without it the retirement table slowly
    fills with namespaces that are now load-bearing, and the next person to act
    on it deletes something alarmed — exactly what ADR-116 forbids.
    """
    now_consumed = {ns: sorted(_kinds(ns)) for ns, row in LEDGER.items() if row["verdict"] == ledger.RETIRE_CANDIDATE and _kinds(ns)}
    assert not now_consumed, (
        f"'{ledger.RETIRE_CANDIDATE}' rows that now HAVE a consumer: {now_consumed}. "
        f"Reclassify as '{ledger.KEEP}' — acting on a stale kill list is how silent-failure coverage "
        "gets traded for dollars (ADR-116)."
    )


def test_retire_candidates_do_not_claim_a_ritual_consumer():
    """A row cannot be both 'nothing reads it' and 'this document reads it'."""
    contradictory = sorted(ns for ns, row in LEDGER.items() if row["verdict"] == ledger.RETIRE_CANDIDATE and row["ritual_consumer"])
    assert not contradictory, f"rows marked {ledger.RETIRE_CANDIDATE} while naming a ritual_consumer: {contradictory}"


@pytest.mark.parametrize("ns", sorted(LEDGER))
def test_row_is_well_formed(ns):
    row = LEDGER[ns]
    assert row["verdict"] in ledger.VERDICTS, f"{ns}: unknown verdict {row['verdict']!r}"
    assert row["cardinality"] in (ledger.FIXED, ledger.FAN_OUT), f"{ns}: unknown cardinality {row['cardinality']!r}"
    # A fan-out row must name what multiplies it — that is the only actionable
    # lever when the census reds, and "fan-out, driver unknown" is not a plan.
    if row["cardinality"] == ledger.FAN_OUT:
        assert row["driver"], f"{ns}: fan-out rows must name the population that multiplies the series"
    else:
        assert row["driver"] is None, f"{ns}: fixed-cardinality rows must not name a driver"
    assert row["owner"], f"{ns}: every namespace names an owner"
    assert len(row["note"]) > 40, f"{ns}: the note must say why, not just that"
    assert isinstance(row["live_series"], int) and row["live_series"] >= 0
    assert isinstance(row["series_budget"], int) and row["series_budget"] >= 0
    assert row["series_budget"] >= row["live_series"], f"{ns}: budget is below the measured series count — it would red on day one"


def test_no_case_insensitive_namespace_twins():
    """Defense in depth for #3002: CloudWatch namespaces are case-sensitive.

    `LifePlatform/SiteAPI` and `LifePlatform/SiteApi` were both live and every
    alarm read one of them, so `ContentFilterFallback` — a privacy control
    degrading — was emitted where nothing looked for nine days.
    """
    seen = {}
    for ns in LEDGER:
        seen.setdefault(ns.lower(), []).append(ns)
    twins = {k: v for k, v in seen.items() if len(v) > 1}
    assert not twins, f"namespaces differing only by case (#3002's defect class): {twins}"


def test_shared_namespace_constants_are_registered():
    """Every literal in `lambdas/common/metric_namespaces.py` has a row.

    That module is where #3002 put the canonical spellings so emitters import
    rather than retype. A constant added there is a namespace by definition.
    """
    missing = sorted(v for v in disc.shared_namespace_constants().values() if v not in LEDGER)
    assert not missing, f"namespace constants with no ledger row: {missing}"


# ── the discriminators, pinned to the modules that motivated them ────────────


def test_user_agent_header_is_not_a_namespace():
    """`notion_lambda` sends `User-Agent: LifePlatform/1.0`. A grep calls that a namespace."""
    assert "LifePlatform/1.0" not in PRODUCERS
    assert "LifePlatform/1.0" not in disc.discover_readers()
    assert "LifePlatform/1.0" not in LEDGER
    src = open(os.path.join(_REPO, "lambdas", "ingestion", "notion_lambda.py"), encoding="utf-8").read()
    assert '"LifePlatform/1.0"' in src, "the header this rule exists for is gone — re-verify the discriminator still has a subject"


def test_imported_namespace_constant_resolves_to_its_emitter():
    """#3002 forbids `lambdas/web/` from writing the literal, so the import must be followed.

    A literal-only producer scan reports the estate's LARGEST namespace as
    emitted by nobody.
    """
    emitters = PRODUCERS.get("LifePlatform/SiteAPI", {}).get(disc.PRODUCER_EMIT, set())
    assert "lambdas/web/site_api_common.py" in emitters, f"site_api_common must resolve as a SiteAPI emitter; got {sorted(emitters)}"
    src = open(os.path.join(_REPO, "lambdas", "web", "site_api_common.py"), encoding="utf-8").read()
    assert "LifePlatform/SiteAPI" not in src, "site_api_common now contains the literal — #3002's guard should have caught this first"


def test_a_metric_reader_is_not_counted_as_a_producer():
    """`traffic_digest_lambda` holds three namespace constants and emits to ONE of them.

    What separates the four is *resolution*: the constants it queries with are
    passed through a helper (`_daily_sums(cw, QA_SMOKE_NAMESPACE, ...)`), so
    they never reach a `put_metric_data` kwarg or an EMF entry.
    """
    readers = disc.discover_readers()
    for ns in ("LifePlatform/QaSmoke", "LifePlatform/QA", "LifePlatform/Budget"):
        assert "lambdas/operational/traffic_digest_lambda.py" in readers.get(ns, set()), f"{ns}: traffic digest should read it"
        assert "lambdas/operational/traffic_digest_lambda.py" not in PRODUCERS.get(ns, {}).get(
            disc.PRODUCER_EMIT, set()
        ), f"{ns}: traffic digest queries it, it does not write it"
    # …and the one it does write.
    assert "lambdas/operational/traffic_digest_lambda.py" in PRODUCERS["LifePlatform/Traffic"][disc.PRODUCER_EMIT]


def test_a_test_file_is_never_counted_as_a_consumer():
    """A namespace may not justify its own `keep` verdict with its own regression test.

    Found by running this module's first full table: THIS file was reported as the
    sole "reader" of `LifePlatform/SiteAPI` (it names the namespace to assert about
    #3002), which would have let any namespace with a test look consumed. `tests/`
    is swept for PRODUCERS — `tests/golden_brief_eval.py` really does emit to
    production CloudWatch — and never for readers.
    """
    readers = disc.discover_readers()
    from_tests = sorted((ns, m) for ns, mods in readers.items() for m in mods if m.startswith("tests/"))
    assert not from_tests, f"test files counted as metric consumers: {from_tests}"
    # …while the CI harness that genuinely writes production metrics is still a producer.
    assert "tests/golden_brief_eval.py" in PRODUCERS["LifePlatform/GoldenBrief"][disc.PRODUCER_EMIT]


def test_a_query_shaped_dict_with_a_literal_namespace_is_not_an_emit():
    """The EMF discriminator: an entry dict carries BOTH `Namespace` and `Metrics`.

    `tests/test_oauth_alarm_coverage.py` builds an SNS alarm payload whose
    `Trigger` block is `{"MetricName": ..., "Namespace": "LifePlatform/OAuth",
    "Dimensions": ...}` — the query/notification shape, with a LITERAL
    namespace and no `Metrics` key. Drop the sibling requirement and a test
    fixture is promoted to an OAuth emitter, which would in turn keep the
    ledger row alive after the real emitters were deleted. This is the file
    that makes the rule load-bearing rather than theoretical.
    """
    src = os.path.join(_REPO, "tests", "test_oauth_alarm_coverage.py")
    tree = ast.parse(open(src, encoding="utf-8").read())
    shapes = [
        n for n in ast.walk(tree) if isinstance(n, ast.Dict) and "Namespace" in disc._dict_keys(n) and "Metrics" not in disc._dict_keys(n)
    ]
    assert shapes, "the query-shaped payload this rule exists for is gone — re-verify the discriminator has a subject"
    assert "tests/test_oauth_alarm_coverage.py" not in PRODUCERS["LifePlatform/OAuth"].get(
        disc.PRODUCER_EMIT, set()
    ), "a query/notification payload was counted as a metric emit"


def test_emit_through_a_defaulted_parameter_is_found():
    """`timeout_watchdog.arm(..., namespace=_NAMESPACE)` — the value is only in the default.

    Without parameter-default resolution the module reads as a *reader* of the
    namespace it writes, which inverts its ledger row.
    """
    assert "lambdas/common/timeout_watchdog.py" in PRODUCERS["LifePlatform/Email"][disc.PRODUCER_EMIT]


def test_log_metric_filter_namespaces_are_producers():
    """`LifePlatform/Lambda` and `LifePlatform/Privacy` have NO Python emitter at all.

    They are minted in CDK by `logs.MetricFilter` from log text. A Python-only
    sweep reports them as alarms watching a namespace nothing writes.
    """
    minted = disc.discover_cdk_log_filter_namespaces()
    for ns in ("LifePlatform/Lambda", "LifePlatform/Privacy"):
        assert "monitoring_stack.py" in minted.get(ns, set()), f"{ns}: expected a MetricFilter producer"
        assert PRODUCERS[ns].get(disc.PRODUCER_EMIT) is None, f"{ns}: has no Python emitter by construction"
        assert disc.CONSUMER_ALARM in _kinds(ns), f"{ns}: the alarm built on the filter must resolve as a consumer"


def test_a_docstring_mentioning_a_namespace_is_not_a_consumer():
    """`monitoring_stack`'s module docstring names namespaces it does not construct.

    Bare `Expr` constants are excluded so documentation cannot manufacture a
    consumer — the way a `keep` verdict would get rubber-stamped by prose.
    """
    tree = ast.parse(open(os.path.join(_REPO, "cdk", "stacks", "monitoring_stack.py"), encoding="utf-8").read())
    doc = ast.get_docstring(tree) or ""
    assert "LifePlatform/QaSmoke" in doc, "the docstring this rule exists for changed — re-verify the discriminator"
    named = disc._referenced_namespaces(tree, disc._module_str_bindings(tree))
    assert "LifePlatform/Coherence" in named, "sanity: a genuinely constructed namespace is still found"


# ── the live half's offline contract ─────────────────────────────────────────


def test_census_skips_loudly_without_credentials(monkeypatch, capsys):
    """No creds => a banner naming what was NOT checked, and exit 0. Never a silent pass."""
    monkeypatch.setattr(census, "read_live_estate", lambda: (print(census.SKIP_BANNER, file=sys.stderr), None)[1])
    assert census.main([]) == 0
    assert "NOTHING WAS CHECKED" in capsys.readouterr().err


def test_census_strict_mode_turns_the_skip_into_a_failure(monkeypatch):
    """Scheduled/attended runs DO have credentials; there the skip is the bug."""
    monkeypatch.setattr(census, "read_live_estate", lambda: None)
    assert census.main(["--strict"]) == 2


def test_census_grades_budget_unregistered_and_orphans():
    """The three failures the census exists to catch, on synthetic counters (no AWS)."""
    over = "LifePlatform/SiteAPI"
    all_14d = collections.Counter({over: LEDGER[over]["series_budget"] + 1, "LifePlatform/NeverWritten": 3})
    result = census.grade(all_14d, collections.Counter())
    assert [t[0] for t in result["over_budget"]] == [over]
    # Nothing in the tree writes it, so there is no action to grade — informational.
    assert [t[0] for t in result["live_orphans"]] == ["LifePlatform/NeverWritten"]
    assert not result["unregistered"]
    assert result["series_14d"] == LEDGER[over]["series_budget"] + 4


def test_census_fails_on_an_unregistered_namespace_this_repo_WRITES(monkeypatch):
    """The other half: unregistered + a real emitter is a failure, not an orphan."""
    monkeypatch.setattr(census, "producing_namespaces", lambda: {"LifePlatform/Invented"})
    result = census.grade(collections.Counter({"LifePlatform/Invented": 4}), collections.Counter())
    assert [t[0] for t in result["unregistered"]] == ["LifePlatform/Invented"]
    assert not result["live_orphans"]


def test_census_line_is_dated_in_pacific():
    """#2675/#3030: a UTC clock stamps tomorrow's date on every PT-evening run."""
    from common.pacific_time import pacific_today

    empty = collections.Counter()
    line = census.census_line(census.grade(empty, empty))
    assert line.startswith(f"- EMF census: {pacific_today()} —")


# ── the alarm dedupe deriver (#2891, folded) ─────────────────────────────────
#
# These use describe-alarms-shaped dicts rather than a repo file because the wire
# here IS the AWS API — there is no in-tree source of truth to read instead. The
# shapes are copied from the live 2026-08-23 response.


def _alarm(name, metric, *, dims=None, stat="Minimum", op="LessThanThreshold", threshold=1.0, ns="LifePlatform/OAuth"):
    return {
        "AlarmName": name,
        "Namespace": ns,
        "MetricName": metric,
        "Dimensions": [{"Name": k, "Value": v} for k, v in (dims or {}).items()],
        "Statistic": stat,
        "ComparisonOperator": op,
        "Threshold": threshold,
    }


def test_dedupe_proposes_only_where_a_dimensionless_guard_matches():
    """The live `ingest-auth-unhealthy-*` family: one SET guard, six per-source alarms."""
    result = census.alarm_dedupe_candidates(
        [
            _alarm("ingest-auth-unhealthy-24h", "IngestAuthHealthy"),
            _alarm("ingest-auth-unhealthy-whoop", "IngestAuthHealthy", dims={"Source": "whoop"}),
        ]
    )
    assert [c["alarm"] for c in result["candidates"]] == ["ingest-auth-unhealthy-whoop"]
    assert result["candidates"][0]["set_guard"] == "ingest-auth-unhealthy-24h"


def test_dedupe_refuses_a_guard_with_a_different_threshold():
    """The live `ai-tokens-*` pair: same metric, 150k platform-wide vs 30k for one Lambda.

    A set guard that fires five times later is not the same coverage. Proposing
    it would be exactly the trade ADR-116 forbids, dressed up as consolidation.
    """
    common = dict(ns="LifePlatform/AI", stat="Sum", op="GreaterThanOrEqualToThreshold")
    result = census.alarm_dedupe_candidates(
        [
            _alarm("ai-tokens-platform-daily-total", "AnthropicOutputTokens", threshold=150000.0, **common),
            _alarm(
                "ai-tokens-daily-brief-daily", "AnthropicOutputTokens", dims={"LambdaFunction": "daily-brief"}, threshold=30000.0, **common
            ),
        ]
    )
    assert not result["candidates"]
    assert result["not_equivalent"][0]["differs_on"] == ["Threshold"]


def test_dedupe_proposes_nothing_for_the_per_lambda_alarms_2891_targeted():
    """No dimensionless AWS/Lambda guard exists, and AWS/* is out of scope entirely.

    #2891 named the ~35 per-Lambda alarms as the prize. There are zero composite
    and zero metric-math alarms in the account, so nothing aggregates them —
    retiring one removes coverage rather than consolidating it.
    """
    lambda_alarms = [
        _alarm("site-api-errors", "Errors", dims={"FunctionName": "life-platform-site-api"}, ns="AWS/Lambda"),
        _alarm("daily-brief-errors", "Errors", dims={"FunctionName": "daily-brief"}, ns="AWS/Lambda"),
    ]
    result = census.alarm_dedupe_candidates(lambda_alarms)
    assert result == {"candidates": [], "not_equivalent": []}


# ── the ritual registration (an inventory nobody re-runs is a snapshot) ──────


def test_the_cost_close_ritual_runs_the_census():
    """The monthly series-count line is an acceptance box; a ritual can drop a step silently."""
    text = open(os.path.join(_REPO, ".claude", "commands", "cost-diligence.md"), encoding="utf-8").read()
    assert (
        "deploy/emf_series_census.py" in text
    ), "the cost-diligence ritual must invoke the census — otherwise the ledger is a one-time snapshot"


def test_the_operating_calendar_probes_the_census_log():
    """#2832's dead-man: the census advances its clock only by writing its dated line."""
    sys.path.insert(0, os.path.join(_REPO, "scripts"))
    import operating_calendar as cal

    entry = cal.CALENDAR.get("emf-series-census")
    assert entry, "the EMF census must be a calendar entry, or it silently stops running"
    kind, target, pattern = entry["probe"]
    assert kind == cal.REGEX_IN_FILE and target == "docs/PROPORTIONALITY.md"
    text = open(os.path.join(_REPO, target), encoding="utf-8").read()
    assert re.search(pattern, text, re.M), f"no line in {target} matches the calendar probe {pattern!r}"
