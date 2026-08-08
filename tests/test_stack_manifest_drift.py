"""tests/test_stack_manifest_drift.py — site/data/stack.json can never drift (#1401).

stack.json is the public "fork the architecture, not the data" manifest. A manifest is
worth exactly as much as the guarantee that it still describes reality, and this repo has
been bitten seven times by the same failure: a list restated somewhere it isn't derived,
which quietly stops matching the thing it claims to describe. So nothing here trusts the
file — every section is re-derived from its origin and compared.

The guards, in the order they'd catch a real regression:

  1. REGENERATION. The whole file must equal the generator's output (modulo the date
     stamp). This is the guard that fires when the source registry gains a source and
     nobody re-ran the build.
  2. DERIVATION. The source id set must equal the public data-source catalogue's id set —
     including the `catalog: False` exclusion, so a wired-but-unannounced source cannot
     leak into a public artifact through this door.
  3. SCHEMA. The manifest validates against the schema it publishes alongside itself.
  4. PRIVACY. No account identifiers, no bucket or resource names, no subject-level
     results; the supplement projection is exactly the published catalogue at exactly the
     published field granularity, never one item or one column wider.
  5. COST HONESTY. Every figure is re-derived from its stated origin: the run-rate from
     the constant the live cost page serves, the ceilings from the governor, the actuals
     from the cost tracker, the supplement totals from this file's own rows.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "t@example.com")
os.environ.setdefault("EMAIL_SENDER", "t@example.com")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import pytest  # noqa: E402

from scripts import v4_build_stack_manifest as gen  # noqa: E402

MANIFEST_PATH = os.path.join(ROOT, "site", "data", "stack.json")
SCHEMA_PATH = os.path.join(ROOT, "site", "data", "stack.schema.json")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def manifest():
    return _load(MANIFEST_PATH)


@pytest.fixture(scope="module")
def built():
    return gen.build()


# ─────────────────────────────── 1. regeneration ────────────────────────────────


def test_manifest_equals_generator_output(manifest, built):
    """THE guard. If the source registry gains a source, a protocol is added, a supplement
    is paused, or a cost constant moves, the on-disk file no longer equals the generator's
    output and this fails — naming the exact command that fixes it."""
    expected = json.loads(json.dumps(built))
    expected["_meta"]["updated"] = manifest["_meta"]["updated"]  # the date stamp alone may lag
    assert manifest == expected, "site/data/stack.json is stale — run: python3 scripts/v4_build_stack_manifest.py"


def test_manifest_declares_itself_generated(manifest):
    assert "never hand-edit" in manifest["_meta"]["generated_by"]
    assert "v4_build_stack_manifest.py" in manifest["_meta"]["generated_by"]


# ─────────────────────────────── 2. derivation ──────────────────────────────────


def test_source_ids_are_exactly_the_public_catalogue(manifest):
    """Proves the sources section is a projection of the public data-source catalogue and
    not an independent list. Same entry point as /data/data_sources.json, so the two can
    never disagree about which sources exist."""
    from scripts.v4_build_data_sources import build as build_catalogue

    assert [s["id"] for s in manifest["sources"]] == [s["id"] for s in build_catalogue()["sources"]]


def test_unannounced_sources_never_reach_the_manifest(manifest):
    """The registry's `catalog: False` gate (#1669) marks sources that are wired but that
    the owner has not chosen to advertise. The manifest inherits that gate by construction;
    assert it actually holds, because this is the door a privacy leak would come through."""
    from ingestion.source_registry import SOURCE_REGISTRY

    unannounced = {k for k, v in SOURCE_REGISTRY.items() if v.get("catalog") is False}
    assert unannounced, "no catalog:False sources left — if that is real, delete this guard deliberately"
    assert unannounced.isdisjoint({s["id"] for s in manifest["sources"]})


def test_registry_facets_are_reflected_not_restated(manifest):
    """Each source's behavioral/paused/raw-scheme facets must match the registry entry —
    the manifest reflects the registry, it does not carry a second opinion about it."""
    from ingestion.source_registry import SOURCE_REGISTRY

    for row in manifest["sources"]:
        entry = SOURCE_REGISTRY.get(row["id"])
        if entry is None:
            continue  # clinical/archive rows have no ingestion pipe to classify
        assert row["behavioral"] is bool(entry.get("behavioral")), row["id"]
        assert row["paused"] is bool(entry.get("paused")), row["id"]
        if entry.get("raw_layout"):
            assert row["raw_scheme"] == entry["raw_layout"]["scheme"], row["id"]
        else:
            assert "raw_scheme" not in row, row["id"]


def test_devices_are_the_public_gear_catalogue(manifest):
    from v4_build_gear import GEAR

    for row in manifest["sources"]:
        gear = GEAR.get(row["id"])
        if gear is None:
            assert "device" not in row, row["id"]
            continue
        assert row["device"]["product"] == gear["product"]
        assert row["device"]["vendor"] == gear["vendor"]
        assert row["device"]["purchasable"] is (gear["kind"] == "gear")


def test_every_ingest_pattern_is_in_the_closed_vocabulary(manifest):
    """A new source whose method string matches no rule must fail the BUILD loudly rather
    than land in a catch-all bucket, so the vocabulary stays meaningful."""
    schema_enum = set(_load(SCHEMA_PATH)["$defs"]["ingestPattern"]["enum"])
    assert schema_enum == set(gen.INGEST_PATTERNS), "schema enum and generator vocabulary diverged"
    for row in manifest["sources"]:
        assert row["ingest_pattern"] in schema_enum, row["id"]
    assert manifest["architecture"]["ingest_patterns"] == sorted({r["ingest_pattern"] for r in manifest["sources"]})


def test_an_unclassifiable_source_fails_the_build():
    """Prove guard 6's mechanism rather than asserting it exists: a source whose method
    matches no rule raises instead of being silently filed as manual_entry."""
    with pytest.raises(SystemExit):
        gen._ingest_pattern("some_new_source_with_no_registry_entry", "beamed down by satellite")


# ──────────────────────────────── 3. schema ─────────────────────────────────────


def _validate(node, schema, root, path="$"):
    """A deliberately small JSON-Schema subset checker — enough for the constructs this
    schema actually uses. Pulling in a validator dependency for one file would cost more
    rent than it pays (ADR-103)."""
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/$defs/"), ref
        return _validate(node, root["$defs"][ref.split("/")[-1]], root, path)

    types = schema.get("type")
    if types:
        allowed = types if isinstance(types, list) else [types]
        ok = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None,
        }
        assert any(ok[t](node) for t in allowed), f"{path}: expected {allowed}, got {type(node).__name__}"

    if "enum" in schema:
        assert node in schema["enum"], f"{path}: {node!r} not in {schema['enum']}"
    if "pattern" in schema and isinstance(node, str):
        assert re.match(schema["pattern"], node), f"{path}: {node!r} fails {schema['pattern']}"
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema:
            assert node >= schema["minimum"], path
        if "maximum" in schema:
            assert node <= schema["maximum"], path

    if isinstance(node, dict):
        for key in schema.get("required", []):
            assert key in node, f"{path}: missing required {key!r}"
        for key, sub in schema.get("properties", {}).items():
            if key in node:
                _validate(node[key], sub, root, f"{path}.{key}")
    if isinstance(node, list):
        if "minItems" in schema:
            assert len(node) >= schema["minItems"], path
        if "maxItems" in schema:
            assert len(node) <= schema["maxItems"], path
        if "items" in schema:
            for i, item in enumerate(node):
                _validate(item, schema["items"], root, f"{path}[{i}]")


def test_manifest_validates_against_its_published_schema(manifest):
    schema = _load(SCHEMA_PATH)
    _validate(manifest, schema, schema)


def test_schema_is_published_next_to_the_manifest(manifest):
    """The manifest points at a schema URL that must resolve on the live site — a
    documented schema nobody can fetch isn't documented."""
    assert manifest["$schema"] == "/data/stack.schema.json"
    assert os.path.exists(SCHEMA_PATH)


# ──────────────────────────────── 4. privacy ────────────────────────────────────

# The manifest describes the instrument. These are the shapes that would mean it had
# started describing the subject, or the deployment, instead.
_FORBIDDEN_PATTERNS = [
    (r"\b\d{12}\b", "a 12-digit AWS account id"),
    (r"arn:aws", "an ARN"),
    (r"matthew-life-platform", "the S3 bucket name"),
    (r"USER#", "a DynamoDB partition key"),
    (r"life-platform/", "a Secrets Manager path"),
    (r"\bE[A-Z0-9]{12,}\b", "a CloudFront distribution id"),
    (r"\.amazonaws\.com", "an AWS endpoint hostname"),
    (r"\b\d{2,3}\.\d\s*(lbs|lb|kg)\b", "a body weight"),
    # A lab READING is subject data; a lab THRESHOLD is part of a protocol's definition
    # and belongs here ("time-in-range (<140 mg/dL)" is what the instrument watches for,
    # not what it found). So the rule fires on a bare figure and not on a compared one.
    (r"(?<![<>≤≥])(?<![<>≤≥]\s)\b\d{2,3}(?:\.\d+)?\s*mg/dL", "a lab reading"),
]


def test_manifest_carries_no_identifiers_or_subject_data(manifest):
    blob = json.dumps(manifest)
    for pattern, what in _FORBIDDEN_PATTERNS:
        hit = re.search(pattern, blob)
        assert hit is None, f"stack.json contains {what}: {hit.group(0)!r}"


def test_protocols_publish_definitions_not_results(manifest):
    """A protocol's findings, adherence and signal strength are results about a person.
    They exist in the catalogue this section derives from, and must be dropped here."""
    allowed = {"id", "name", "domain", "category", "tier", "status", "definition", "mechanism", "tracked_by", "key_metrics"}
    for p in manifest["protocols"]:
        assert set(p) == allowed, f"protocol {p['id']} field set drifted: {set(p) ^ allowed}"
    blob = json.dumps(manifest["protocols"])
    for leaked in ("key_finding", "signal_note", "signal_status", "adherence_target", "start_date"):
        assert leaked not in blob


def test_protocol_ids_match_the_public_catalogue(manifest):
    catalogue = _load(os.path.join(ROOT, "site", "config", "protocols.json"))
    assert {p["id"] for p in manifest["protocols"]} == {p["id"] for p in catalogue["protocols"]}


def test_supplements_are_the_published_catalogue_exactly(manifest):
    """Not a subset and not a superset: the manifest must publish the same items the site
    already renders. A narrower list would be dishonest; a wider one would be a leak."""
    catalogue = _load(os.path.join(ROOT, "site", "config", "supplement_registry.json"))
    published = {item["key"] for group in catalogue["groups"].values() for item in group["items"]}
    assert {s["key"] for s in manifest["supplements"]} == published


def test_supplement_projection_never_widens_a_column(manifest):
    """The field allowlist IS the privacy decision. Adding a key to this set widens what
    is public about the stack, so it has to be changed here, deliberately, in a diff."""
    allowed = {"key", "name", "group", "group_name", "dose", "timing", "evidence", "cost_monthly_usd", "paused"}
    for s in manifest["supplements"]:
        assert set(s) == allowed, f"supplement {s['key']} field set drifted: {set(s) ^ allowed}"
        assert set(s["evidence"]) == {"grade", "confidence_pct"}
    # the narrative fields in the catalogue stay out: they are the owner's reasoning,
    # published on his page in his voice, not payload for a machine-readable manifest
    blob = json.dumps(manifest["supplements"])
    for leaked in ("science", "sources", "why", "board", "rationale", "hoped_outcome", "questionReason", "pausedReason"):
        assert leaked not in blob


def test_source_rows_expose_shape_never_location(manifest):
    """raw_scheme says how the archive is laid out; nothing may say WHERE it is."""
    allowed = {"id", "name", "category", "measures", "method", "posture", "ingest_pattern", "behavioral", "paused", "raw_scheme", "device"}
    for row in manifest["sources"]:
        assert set(row) <= allowed, f"source {row['id']} grew a field: {set(row) - allowed}"
        assert "prefix" not in json.dumps(row)


# ────────────────────────────── 5. cost honesty ─────────────────────────────────


def test_run_rate_is_the_same_number_the_live_cost_page_serves(manifest):
    """/method/cost/ renders PLATFORM_STATS['monthly_cost'] via /api/platform_stats. The
    manifest must read that same constant, not a second opinion that can age separately."""
    from web.site_api_common import PLATFORM_STATS

    assert manifest["cost_of_ownership"]["aws"]["monthly_usd_typical"] == PLATFORM_STATS["monthly_cost"]


def test_ceilings_are_the_governor_constants(manifest):
    from operational.cost_governor_lambda import MONTHLY_CEILING, SURGE_CEILING_USD, SURGE_UNIQUES_THRESHOLD

    aws = manifest["cost_of_ownership"]["aws"]
    assert aws["ceiling_usd"] == MONTHLY_CEILING
    assert aws["surge_ceiling_usd"] == SURGE_CEILING_USD
    assert aws["surge_trigger_trailing_7d_uniques"] == SURGE_UNIQUES_THRESHOLD


def test_actuals_are_pinned_to_the_cost_tracker(manifest):
    """Each published month must appear with that exact figure in the Monthly Actuals
    table of docs/COST_TRACKER.md, which is itself re-read from Cost Explorer on a
    freshness contract. This is what stops the series becoming folklore."""
    with open(os.path.join(ROOT, "docs", "COST_TRACKER.md"), encoding="utf-8") as fh:
        tracker = fh.read()
    actuals = manifest["cost_of_ownership"]["aws"]["actuals"]
    assert actuals, "the actuals series must not be empty"
    for row in actuals:
        line = next((ln for ln in tracker.splitlines() if ln.startswith(f"| {row['label']} |")), None)
        assert line, f"{row['label']} has no Monthly Actuals row in docs/COST_TRACKER.md"
        assert f"${row['usd']:.2f}" in line, f"{row['label']}: manifest says ${row['usd']:.2f}, COST_TRACKER row says {line!r}"


def test_actuals_exclude_incomplete_months(manifest):
    """A partial month is not a run-rate. The tracker marks in-progress months 'MTD'."""
    with open(os.path.join(ROOT, "docs", "COST_TRACKER.md"), encoding="utf-8") as fh:
        tracker = fh.read()
    for row in manifest["cost_of_ownership"]["aws"]["actuals"]:
        line = next(ln for ln in tracker.splitlines() if ln.startswith(f"| {row['label']} |"))
        assert "MTD" not in line, f"{row['label']} is still an in-progress month"


def test_supplement_totals_are_the_sum_of_the_published_rows(manifest):
    """A reader can add up the rows in this same file and must get the headline number."""
    rows = manifest["supplements"]
    block = manifest["cost_of_ownership"]["supplements"]
    assert block["active_monthly_usd"] == sum(s["cost_monthly_usd"] for s in rows if not s["paused"])
    assert block["including_paused_monthly_usd"] == sum(s["cost_monthly_usd"] for s in rows)
    assert block["item_count"] == len(rows)
    assert block["paused_count"] == sum(1 for s in rows if s["paused"])


def test_unmeasured_costs_are_null_with_a_stated_reason(manifest):
    """ADR-104/105. Device prices and human hours are genuinely not measured here, so they
    must be null AND explain themselves — never a plausible-looking invented figure."""
    cost = manifest["cost_of_ownership"]
    assert cost["devices"]["monthly_usd"] is None
    assert cost["devices"]["one_time_usd"] is None
    assert cost["time"]["hours_to_build"] is None
    assert cost["time"]["hours_per_week_to_operate"] is None
    for block in (cost["devices"], cost["time"]):
        assert len(block["basis"]) > 80, "a null figure needs a real explanation, not a shrug"
        assert "no figure asserted" in block["confidence"]


def test_every_cost_figure_states_its_basis(manifest):
    """No bare number anywhere in the cost block: each sub-block carries a basis."""
    cost = manifest["cost_of_ownership"]
    assert cost["aws"]["monthly_usd_typical_basis"]
    assert cost["aws"]["ceiling_basis"]
    assert cost["aws"]["actuals_basis"]
    assert cost["aws"]["composition"]["basis"]
    assert cost["supplements"]["basis"]
    assert cost["time"]["recurring_manual_touchpoints"]["basis"]
    assert "_description" not in cost, "the build-side provenance note must not ship to readers"


def test_manual_touchpoint_counts_are_derived_from_the_source_rows(manifest):
    rows = manifest["sources"]
    tp = manifest["cost_of_ownership"]["time"]["recurring_manual_touchpoints"]
    assert tp["credentialed_sources_that_can_need_reauth"] == sum(
        1 for s in rows if s["ingest_pattern"] == "scheduled_credentialed_pull" and not s["paused"]
    )
    assert tp["sources_whose_records_require_typing"] == sum(1 for s in rows if s["ingest_pattern"] == "manual_entry")
