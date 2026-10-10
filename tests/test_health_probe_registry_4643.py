"""tests/test_health_probe_registry_4643.py — the boot-probe list is the registry (#4643).

`pipeline_health_check_lambda.PIPELINES` was a hand-written literal: it omitted the Hevy
poller and all three enrichment functions (activity / journal / social) and listed paused
Garmin with nothing tying it to the `paused` facet. The ingestion rows are now derived from
the registry's `probe_functions` facet. Pinned here:

  * the probe list EQUALS the registry facet (recomputed independently of the helper);
  * the registry facet covers every SCHEDULED function in cdk/stacks/ingestion_stack.py,
    and the only probed-but-unscheduled functions are a paused source's and the HAE
    webhook's — so a new scheduled ingestion function with no facet fails here;
  * a paused source is skipped by its facet (never invoked, reported `paused`) while
    every other registry function is invoked;
  * every probed ingestion handler short-circuits {"healthcheck": true} — a probe must
    never trigger a real walk or a model call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from ingestion import source_registry as reg
from operational import pipeline_health_check_lambda as phc

ROOT = Path(__file__).resolve().parent.parent
INGESTION_STACK = ROOT / "cdk" / "stacks" / "ingestion_stack.py"

# The one probed function with no cron by design: a webhook has nothing scheduled to
# go stale, but its boot check still proves the bundle imports (apple_health's facet).
UNSCHEDULED_BY_DESIGN = {"health-auto-export-webhook"}


def _registry_probe_rows() -> list[tuple[str, str, str]]:
    """Independent recomputation of the facet — not via health_probe_targets()."""
    rows, seen = [], set()
    for key, entry in reg.SOURCE_REGISTRY.items():
        for fn_name, display in entry.get("probe_functions") or ():
            if fn_name not in seen:
                seen.add(fn_name)
                rows.append((fn_name, display, key))
    return rows


def _ingestion_stack_functions() -> dict[str, dict]:
    """{function_name: {"scheduled": bool, "source_file": str}} for each
    create_platform_lambda(...) call in the ingestion stack (balanced-paren scan)."""
    text = INGESTION_STACK.read_text()
    out: dict[str, dict] = {}
    for m in re.finditer(r"create_platform_lambda\(", text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        call = text[m.end() : i]
        name = re.search(r'function_name="([^"]+)"', call)
        if not name:
            continue
        src = re.search(r'source_file="([^"]+)"', call)
        code_lines = [ln for ln in call.splitlines() if not ln.strip().startswith("#")]
        out[name.group(1)] = {
            "scheduled": any(re.match(r"\s*schedule=", ln) for ln in code_lines),
            "source_file": src.group(1) if src else "",
        }
    return out


def _paused_fns() -> set[str]:
    return {fn for fn, _d, src in _registry_probe_rows() if reg.SOURCE_REGISTRY[src].get("paused")}


def test_probe_list_equals_the_registry():
    assert phc.INGESTION_PROBES == _registry_probe_rows()
    assert phc.INGESTION_PROBES == reg.health_probe_targets()
    assert phc.PIPELINES == phc.INGESTION_PROBES + phc.COMPUTE_PROBES
    compute_fns = {fn for fn, _d, _s in phc.COMPUTE_PROBES}
    assert not compute_fns & {fn for fn, _d, _s in phc.INGESTION_PROBES}, "an ingestion function is named twice"
    fns = [fn for fn, _d, _s in phc.PIPELINES]
    assert len(fns) == len(set(fns)), "a function would be probed twice in one run"


def test_the_functions_the_issue_named_are_probed():
    fns = {fn for fn, _d, _s in phc.PIPELINES}
    for fn in ("hevy-backfill", "activity-enrichment", "journal-enrichment", "social-enrichment"):
        assert fn in fns, f"{fn} has a schedule and no boot probe"


def test_registry_covers_every_scheduled_ingestion_function():
    stack = _ingestion_stack_functions()
    assert len(stack) >= 15, f"the CDK scan found too few functions to be trusted: {sorted(stack)}"
    scheduled = {fn for fn, info in stack.items() if info["scheduled"]}
    probed = {fn for fn, _d, _s in phc.INGESTION_PROBES}
    unprobed = scheduled - probed
    assert not unprobed, f"scheduled ingestion functions with no `probe_functions` facet: {sorted(unprobed)}"
    unknown = probed - set(stack)
    assert not unknown, f"facet names a function the ingestion stack does not define: {sorted(unknown)}"
    extra = probed - scheduled - _paused_fns() - UNSCHEDULED_BY_DESIGN
    assert not extra, f"probed but unscheduled, and neither paused nor a webhook: {sorted(extra)}"
    assert _paused_fns(), "the registry has a paused source today (garmin) — the facet must reach it"
    assert _paused_fns() <= probed - scheduled, "a paused source still has a schedule in CDK"


def test_every_probed_ingestion_handler_short_circuits_the_healthcheck():
    stack = _ingestion_stack_functions()
    missing = []
    for fn, _d, _s in phc.INGESTION_PROBES:
        src = (ROOT / stack[fn]["source_file"]).read_text()
        if not re.search(r"""get\(\s*["']healthcheck["']\s*\)""", src):
            missing.append(fn)
    assert not missing, f"a probe would run these for real (no healthcheck short-circuit): {missing}"


# ── the handler, on the REAL derived list and the REAL paused facet ─────────────────


class _FakeLambda:
    def __init__(self):
        self.invoked: list[str] = []

    def invoke(self, FunctionName, InvocationType=None, Payload=None):
        assert Payload == b'{"healthcheck": true}'
        self.invoked.append(FunctionName)
        return {"StatusCode": 200}


class _FakeTable:
    def __init__(self):
        self.puts: list[dict] = []

    def put_item(self, Item):
        self.puts.append(Item)


class _FakeAws:
    def describe_secret(self, SecretId):
        return {}


@pytest.fixture()
def probe_run(monkeypatch):
    lam, tbl = _FakeLambda(), _FakeTable()
    monkeypatch.setattr(phc, "lambda_client", lam)
    monkeypatch.setattr(phc, "table", tbl)
    monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: _FakeAws())
    body = json.loads(phc.lambda_handler({}, None)["body"])
    return lam, tbl, body


def test_a_paused_source_is_skipped_by_its_facet_and_everything_else_is_probed(probe_run):
    lam, tbl, body = probe_run
    paused = _paused_fns()
    assert not paused & set(lam.invoked), f"a paused source was invoked: {sorted(paused & set(lam.invoked))}"
    expected = {fn for fn, _d, _s in phc.PIPELINES} - paused
    assert set(lam.invoked) == expected
    stored = {r["function_name"]: r for r in json.loads(tbl.puts[0]["results"])}
    for fn in paused:
        assert stored[fn]["state"] == "paused", fn
    assert body["paused"] == len(paused)
    assert body["passed"] + body["failed"] + body["paused"] == body["total"] == len(phc.PIPELINES)


def test_an_enrichment_probe_is_recorded_under_its_own_id_not_its_parents(probe_run):
    """#4761: the stored row's source_id is what the status page matches against a source;
    an enrichment function must never carry its parent source's bare id."""
    _lam, tbl, _body = probe_run
    stored = {r["function_name"]: r for r in json.loads(tbl.puts[0]["results"])}
    for fn, _d, src in phc.INGESTION_PROBES:
        if fn.endswith("-enrichment"):
            assert stored[fn]["source_id"] == f"{src}:enrichment", fn
        else:
            assert stored[fn]["source_id"] == src, fn
