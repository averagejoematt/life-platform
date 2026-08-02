"""tests/test_oauth_alarm_coverage.py — #1960: the OAuth alarm-inventory guard.

THE INCIDENT
  `ingest-auth-unhealthy-24h` (URGENT topic) was acked by the remediation agent as
  "duplicate, covered by source-specific alarms". Per-source
  `ingest-consecutive-failures-*` alarms existed for exactly five sources
  (whoop, withings, strava, eightsleep, hevy) — so a garmin / notion / todoist auth
  death fired ONLY the aggregate alarm the ack dismissed, and because the
  IngestAuthHealthy metric was emitted without dimensions, that aggregate could not
  name which source had died either. The ack was still being renewed a week later.

WHAT THIS GUARDS
  The SET, not the instance (the 4x-recurring lesson): the OAuth-capable source set
  is DERIVED from `source_registry.oauth_source_ids()`, and the alarm set is
  AST-scanned out of `cdk/stacks/monitoring_stack.py`. A new credentialed source
  added to the registry with no per-source alarm FAILS here — it does not wait to be
  noticed during the next outage.

  Routing is guarded too: `oauth_digest_only_source_ids()` (paused / best_effort /
  unmonitored) must route to the daily digest, everything else must page. That is
  what keeps ADR-074's de-paging of the accepted, unfixable Garmin 429 state intact
  while still restoring coverage.

  `test_uncovered_source_is_detected` is the prove-it-fires negative: it feeds the
  checker a synthetic registry with an unalarmed OAuth source and asserts the
  checker reports it. A coverage guard that has never been seen to fail is a guard
  whose parser might be silently returning the empty set.
"""

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from ingestion import source_registry as reg  # noqa: E402

_MONITORING = os.path.join(_REPO, "cdk", "stacks", "monitoring_stack.py")

# The two alarm families that constitute per-source auth coverage. A breaker trip on
# a SIMP-2 framework source also records a failed run (ingestion_framework records
# attempted=True/succeeded=False, error_class="auth" on the short-circuit), so a
# consecutive-failures alarm is genuine coverage for the sources that have one; the
# auth-unhealthy family covers the rest off the newly-dimensioned metric.
_COVERAGE_PREFIXES = ("ingest-consecutive-failures-", "ingest-auth-unhealthy-")


def alarm_names_by_prefix(path=_MONITORING):
    """{prefix: {source: routing}} for every f-string alarm name built over a
    constant loop variable in the monitoring stack.

    Deliberately AST-based, not regex: the names are built as
    `f"ingest-auth-unhealthy-{_auth_src}"` inside `for _auth_src in (...)` loops, and
    resolving them means binding the loop variable — the same shape
    deploy/sync_doc_metadata.py resolves for docs/MONITORING.md. `routing` is
    "digest" when the call passes `to_digest=True`, else "urgent".
    """
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    found = {prefix: {} for prefix in _COVERAGE_PREFIXES}
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        var = node.target.id
        if not isinstance(node.iter, (ast.Tuple, ast.List)):
            continue
        values = [e.value for e in node.iter.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if not values:
            continue
        for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
            for arg in list(call.args) + [kw.value for kw in call.keywords]:
                if not isinstance(arg, ast.JoinedStr):
                    continue
                for bound in values:
                    name = _render_fstring(arg, {var: bound})
                    if name is None:
                        continue
                    for prefix in _COVERAGE_PREFIXES:
                        if name == prefix + bound:
                            found[prefix][bound] = _routing(call)
    return found


def _render_fstring(node, bindings):
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
            if value.value.id not in bindings:
                return None
            parts.append(bindings[value.value.id])
        else:
            return None
    return "".join(parts)


def _routing(call):
    for kw in call.keywords:
        if kw.arg == "to_digest":
            return "digest" if (isinstance(kw.value, ast.Constant) and kw.value.value) else "urgent"
    return "urgent"


def uncovered_oauth_sources(oauth_ids, covered):
    """OAuth sources with no per-source alarm of any covering family.

    Pure function over already-extracted data so the negative test can drive it
    with a synthetic registry — no AWS, no CDK synth."""
    return sorted(set(oauth_ids) - set(covered))


def _covered_map():
    families = alarm_names_by_prefix()
    covered = {}
    for prefix in _COVERAGE_PREFIXES:
        for src, routing in families[prefix].items():
            # auth-unhealthy is the authoritative routing signal when both exist.
            if src not in covered or prefix == "ingest-auth-unhealthy-":
                covered[src] = routing
    return families, covered


def test_parser_finds_the_known_alarm_families():
    """Guard the guard: if the AST walk silently returned nothing, every coverage
    assertion below would pass vacuously."""
    families, _ = _covered_map()
    assert "whoop" in families["ingest-consecutive-failures-"], "consecutive-failures loop not parsed — parser broke"
    assert "garmin" in families["ingest-auth-unhealthy-"], "per-source auth loop not parsed — parser broke"


def test_every_oauth_source_has_a_per_source_alarm():
    """The acceptance criterion: an auth death on ANY credentialed source produces a
    page/digest line that NAMES the source."""
    _, covered = _covered_map()
    oauth_ids = reg.oauth_source_ids()
    assert oauth_ids, "registry reports no OAuth sources — the `oauth` facet vanished"
    missing = uncovered_oauth_sources(oauth_ids, covered)
    assert not missing, (
        "OAuth-capable sources with no per-source alarm — an auth death on these fires only the "
        f"aggregate `ingest-auth-unhealthy-24h`, which is exactly the #1960 gap: {missing}. "
        "Add them to the per-source auth loop in cdk/stacks/monitoring_stack.py."
    )


def test_uncovered_source_is_detected():
    """PROVE IT FIRES. A synthetic new OAuth source with no alarm must be reported."""
    covered = {"whoop": "urgent", "garmin": "digest"}
    assert uncovered_oauth_sources(["whoop", "garmin", "brand_new_oauth_source"], covered) == ["brand_new_oauth_source"]
    assert uncovered_oauth_sources(["whoop", "garmin"], covered) == []


def test_digest_only_sources_do_not_page():
    """ADR-074: garmin's auth death is an ACCEPTED, unfixable upstream state (the
    datacenter-IP 429 block). Restoring coverage must not restore the permanent-red
    page that de-paged it — and notion is monitored:False, operator view only."""
    _, covered = _covered_map()
    digest_only = reg.oauth_digest_only_source_ids()
    assert "garmin" in digest_only, "garmin lost its paused/best_effort facets — re-check the routing rule"
    wrong = sorted(s for s in digest_only if covered.get(s) == "urgent")
    assert not wrong, f"digest-only OAuth sources routed to the URGENT page: {wrong}"


def test_live_monitored_oauth_sources_page():
    """The converse: a dead credential on a live, monitored source is actionable
    within the hour and must NOT be buried in the daily digest."""
    _, covered = _covered_map()
    digest_only = reg.oauth_digest_only_source_ids()
    should_page = [s for s in reg.oauth_source_ids() if s not in digest_only]
    assert should_page, "no OAuth source pages at all — the routing rule inverted"
    buried = sorted(s for s in should_page if covered.get(s) == "digest")
    assert not buried, f"live monitored OAuth sources routed to digest instead of paging: {buried}"


def test_oauth_facet_excludes_keyless_and_manual_sources():
    """The facet means 'has a credential that can die'. A keyless pull or a webhook
    source can never emit IngestAuthHealthy=0, so alarming on it would be a sensor
    that structurally cannot fire — the dishonest-green class."""
    oauth_ids = set(reg.oauth_source_ids())
    for keyless in ("weather", "youtube", "apple_health", "measurements", "food_delivery", "supplements"):
        assert keyless not in oauth_ids, f"{keyless} has no outbound credential — it must not carry the oauth facet"
    for credentialed in ("whoop", "withings", "strava", "eightsleep", "todoist", "habitify", "hevy", "garmin", "notion", "dropbox"):
        assert credentialed in oauth_ids, f"{credentialed} is a credentialed pull — it must carry the oauth facet"


def test_aggregate_alarm_still_reads_the_dimensionless_stream():
    """The design constraint that makes the Source dimension safe: CloudWatch treats
    the dimensioned metric as a SEPARATE metric, so the fleet-wide alarm must keep
    reading a dimensionless IngestAuthHealthy — if someone 'tidies' it by adding
    dimensions_map here, the aggregate goes blind and nothing else notices."""
    tree = ast.parse(open(_MONITORING, encoding="utf-8").read(), filename=_MONITORING)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name_kw = next((kw.value for kw in node.keywords if kw.arg == "alarm_name"), None)
        if not (isinstance(name_kw, ast.Constant) and name_kw.value == "ingest-auth-unhealthy-24h"):
            continue
        metric = next((kw.value for kw in node.keywords if kw.arg == "metric"), None)
        assert isinstance(metric, ast.Call), "aggregate alarm's metric= is no longer an inline Metric(...)"
        dims = next((kw.arg for kw in metric.keywords if kw.arg == "dimensions_map"), None)
        assert dims is None, "the fleet aggregate must stay DIMENSIONLESS — a dimensions_map here blinds it"
        return
    raise AssertionError("ingest-auth-unhealthy-24h not found in monitoring_stack.py")


# ── The page payload actually names the source (#1960) ──────────────────────
# The acceptance criterion is operator-facing, not structural: "an auth death on ANY
# OAuth source produces a page that NAMES the source". So drive the real urgent
# dispatcher with a synthetic CloudWatch alarm notification and read what the
# operator would receive.


def _sns_event(alarm_name, dimensions):
    import json

    message = {
        "AlarmName": alarm_name,
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold Crossed: 1 datapoint [0.0] was less than the threshold (1.0).",
        "StateChangeTime": "2026-08-02T12:00:00.000+0000",
        "Trigger": {
            "MetricName": "IngestAuthHealthy",
            "Namespace": "LifePlatform/OAuth",
            "Dimensions": [{"name": k, "value": v} for k, v in dimensions.items()],
        },
    }
    return {"Records": [{"Sns": {"Message": json.dumps(message)}}]}


def _drive_dispatcher(monkeypatch, event):
    sys.path.insert(0, os.path.join(_REPO, "lambdas"))
    from operational import remediation_dispatcher_lambda as disp

    sent = []
    monkeypatch.setattr(disp, "_dispatch", lambda payload: sent.append(payload))
    monkeypatch.setattr(disp, "_seen", lambda key: False)
    monkeypatch.setattr(disp, "_mark", lambda key, payload: None)
    disp.lambda_handler(event, None)
    return sent


def test_per_source_page_payload_names_the_dead_source(monkeypatch):
    """A todoist auth death now pages with the SOURCE IN THE ALARM NAME — the
    operator knows which credential to rotate before opening a console."""
    sent = _drive_dispatcher(monkeypatch, _sns_event("ingest-auth-unhealthy-todoist", {"Source": "todoist"}))
    assert len(sent) == 1, "the per-source auth alarm must still match an URGENT pattern and dispatch"
    assert "todoist" in sent[0]["alarm_name"]
    assert sent[0]["metric"] == "IngestAuthHealthy"


def test_aggregate_page_payload_still_cannot_name_a_source(monkeypatch):
    """The control that makes the test above non-vacuous: the aggregate alarm — the
    ONLY thing that fired for garmin/notion/todoist before #1960 — carries no source
    anywhere in the payload. This is the defect, reproduced."""
    sent = _drive_dispatcher(monkeypatch, _sns_event("ingest-auth-unhealthy-24h", {}))
    assert len(sent) == 1
    blob = " ".join(str(v) for v in sent[0].values())
    for src in reg.oauth_source_ids():
        assert src not in blob, "the aggregate payload unexpectedly names a source — re-derive this control"
