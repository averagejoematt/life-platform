"""tests/test_measurement_columns_3663.py — #3663: a measured value is stored or NAMED.

Three groups, one per acceptance box:

1. **The six sites are modelled.** `MEASUREMENT_FIELDS` carries the six sites the
   2026-09-06 session measured with nowhere to put them, they round-trip from a
   real fixture CSV into the written DDB item, and `docs/SCHEMA.md`'s own table
   lists every field the writer stores (the doc match is asserted, not claimed).

2. **An unmodelled column is a named failure.** Two real fixture files that differ
   by exactly one column: `session_surplus_column.csv` reds the handler (422, the
   offending header named in the body, NOTHING written) and `session_clean.csv`
   passes (200, every site stored). Before #3663 both returned 200 and the surplus
   value vanished.

3. **The limb enumerations state their sites.** `LIMB_AVG_SITES` and
   `BILATERAL_SYMMETRY_PAIRS` are the contract `_compute_derived` reads, every name
   in them is a field actually stored, and — the load-bearing case for this very
   change — adding the four new limb sites does NOT move `limb_avg_in`, which stays
   the four-site mean the stored 2026-03-29 and 2026-09-06 rows already carry.
"""

import io
import json
import os
import re
import sys
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "measurements_3663")
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import measurements_ingestion_lambda as mi  # noqa: E402

# The six sites measured on 2026-09-06 that the 13-field schema could not hold.
# Values verbatim from that DDB row's own `notes` string.
SURVIVED_IN_NOTES = {
    "waist_iliac_crest_in": Decimal("56.00"),
    "shoulder_width_in": Decimal("21.00"),
    "forearm_max_left_in": Decimal("13.00"),
    "forearm_max_right_in": Decimal("13.25"),
    "thigh_upper_left_in": Decimal("34.00"),
    "thigh_upper_right_in": Decimal("34.00"),
}


class FakeTable:
    def __init__(self):
        self.items = {}
        self.puts = []

    def put_item(self, Item):  # noqa: N803
        self.puts.append(Item)
        self.items[(Item.get("pk"), Item.get("sk"))] = Item

    def get_item(self, Key):  # noqa: N803
        item = self.items.get((Key.get("pk"), Key.get("sk")))
        return {"Item": item} if item else {}

    def query(self, **kwargs):
        out = [v for (p, s), v in self.items.items() if p == mi.PK and s.startswith("DATE#")]
        return {"Items": [{"sk": it["sk"]} for it in out]}


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


class FakeS3:
    def __init__(self, payload=b""):
        self.payload = payload

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": _Body(self.payload)}


def fixture_bytes(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def invoke(monkeypatch, payload, key="imports/measurements/session.csv"):
    table = FakeTable()
    monkeypatch.setattr(mi, "table", table)
    monkeypatch.setattr(mi, "s3", FakeS3(payload))
    response = mi.lambda_handler({"bucket": "test-bucket", "key": key}, None)
    return response, table


# ──────────────────────────────────────────────────────────────────────────────
# 1. The six sites are modelled, stored, and documented
# ──────────────────────────────────────────────────────────────────────────────


def test_measurement_fields_carries_the_six_sites():
    missing = [f for f in SURVIVED_IN_NOTES if f not in mi.MEASUREMENT_FIELDS]
    assert not missing, f"sites measured on 2026-09-06 still have nowhere to go: {missing}"


def test_measurement_fields_have_no_duplicates():
    assert len(mi.MEASUREMENT_FIELDS) == len(set(mi.MEASUREMENT_FIELDS))


def test_upper_thigh_is_a_distinct_field_from_mid_thigh():
    """Two thigh sites, two fields — the protocol was measuring both into one field's space."""
    for side in ("left", "right"):
        assert f"thigh_{side}_in" in mi.MEASUREMENT_FIELDS
        assert f"thigh_upper_{side}_in" in mi.MEASUREMENT_FIELDS


def test_clean_fixture_stores_every_one_of_the_six_notes_values(monkeypatch):
    """The real 2026-09-06 numbers, as a CSV, land as queryable fields."""
    response, table = invoke(monkeypatch, fixture_bytes("session_clean.csv"))
    assert response["statusCode"] == 200
    item = table.items[(mi.PK, "DATE#2026-09-06")]
    for field, value in SURVIVED_IN_NOTES.items():
        assert field in item, f"{field} was dropped by the ingest"
        assert Decimal(str(item[field])) == value


def _schema_measurements_table():
    with open(os.path.join(ROOT, "docs", "SCHEMA.md"), encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("### measurements (body tape measurements)")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def test_schema_md_documents_every_stored_measurement_field():
    """docs/SCHEMA.md's table matches MEASUREMENT_FIELDS — asserted, not asserted-in-prose."""
    section = _schema_measurements_table()
    documented = set(re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|", section, re.M))
    missing = sorted(f for f in mi.MEASUREMENT_FIELDS if f not in documented)
    assert not missing, f"stored but undocumented in docs/SCHEMA.md: {missing}"


def test_schema_md_documents_the_derived_fields_too():
    section = _schema_measurements_table()
    documented = set(re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|", section, re.M))
    for derived in ("limb_avg_in", "limb_avg_sites", *mi.BILATERAL_SYMMETRY_PAIRS):
        assert derived in documented, f"{derived} is written but not in docs/SCHEMA.md"


# ──────────────────────────────────────────────────────────────────────────────
# 2. An unmodelled column is a NAMED failure, not a silent drop
# ──────────────────────────────────────────────────────────────────────────────


def test_the_two_fixtures_differ_by_exactly_the_surplus_column():
    """Guards the pair itself: if the fixtures drift apart, the red/green contrast below
    stops being about the surplus column and the test silently changes meaning."""
    import csv

    clean = next(csv.reader(io.StringIO(fixture_bytes("session_clean.csv").decode())))
    surplus = next(csv.reader(io.StringIO(fixture_bytes("session_surplus_column.csv").decode())))
    assert set(surplus) - set(clean) == {"ankle_left_in"}
    assert set(clean) - set(surplus) == set()


def test_surplus_column_fixture_reds_the_handler_and_names_it(monkeypatch):
    response, table = invoke(monkeypatch, fixture_bytes("session_surplus_column.csv"))
    assert response["statusCode"] != 200, "a measured-but-unstorable column reported a clean success"
    assert response["statusCode"] == 422
    body = json.loads(response["body"])
    assert body["unmodelled_columns"] == ["ankle_left_in"]
    assert "ankle_left_in" in body["message"]
    assert body["sessions_written"] == 0
    assert table.puts == [], "a refused file still wrote to DynamoDB"


def test_the_same_fixture_without_the_surplus_column_passes(monkeypatch):
    response, table = invoke(monkeypatch, fixture_bytes("session_clean.csv"))
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["sessions_written"] == 1
    assert len(table.puts) == 1


def test_every_unrecognised_header_is_named_not_just_the_first():
    headers = ["date", "neck_in", "ankle_left_in", "notes", "wingspan_in", "measured_by"]
    assert mi._unmodelled_columns(headers) == ["ankle_left_in", "wingspan_in"]


def test_non_measurement_columns_are_not_reported():
    assert mi._unmodelled_columns(["date", "notes", "measured_by"]) == []


def test_blank_header_cells_are_not_reported():
    """A trailing comma or an empty spreadsheet column carries no measured value."""
    assert mi._unmodelled_columns(["date", "", None, "   ", "neck_in"]) == []


def test_a_header_the_row_parser_could_not_key_is_named_not_normalised():
    """`Neck_in` is unstorable — `_row_to_session` does an exact `row_dict.get()`.
    Normalising it into a match here would re-create the silent drop one layer down."""
    assert mi._unmodelled_columns(["Neck_in", "neck_in "]) == ["Neck_in", "neck_in "]


def test_parse_csv_raises_the_named_error():
    with pytest.raises(mi.UnmodelledColumnsError) as excinfo:
        mi._parse_csv("date,neck_in,ankle_left_in\n2026-09-06,17.0,9.5\n")
    assert excinfo.value.columns == ["ankle_left_in"]


def test_xlsx_headers_go_through_the_same_check():
    """The spreadsheet path lower-cases its headers first, then uses the one checker."""
    headers = [str(h).strip().lower() for h in ["Date", "Neck_in", "Ankle_Left_in"]]
    assert mi._unmodelled_columns(headers) == ["ankle_left_in"]


# ──────────────────────────────────────────────────────────────────────────────
# 3. The limb enumerations state their sites — and adding one cannot move a number
# ──────────────────────────────────────────────────────────────────────────────


def test_limb_avg_sites_are_all_fields_actually_stored():
    unstored = [f for f in mi.LIMB_AVG_SITES if f not in mi.MEASUREMENT_FIELDS]
    assert not unstored, f"limb_avg_in claims to average fields that are never stored: {unstored}"


def test_bilateral_symmetry_pairs_are_all_fields_actually_stored():
    for out_field, pair in mi.BILATERAL_SYMMETRY_PAIRS.items():
        for f in pair:
            assert f in mi.MEASUREMENT_FIELDS, f"{out_field} names {f}, which is not a stored field"


def test_limb_avg_is_exactly_the_mean_of_its_enumerated_sites():
    """Independent arithmetic over the enumeration — not a re-run of the writer's own loop."""
    measurements = {f: Decimal(str(10 + i)) for i, f in enumerate(mi.MEASUREMENT_FIELDS)}
    derived = mi._compute_derived(measurements, 69)
    expected = sum(float(measurements[f]) for f in mi.LIMB_AVG_SITES) / len(mi.LIMB_AVG_SITES)
    assert float(derived["limb_avg_in"]) == pytest.approx(expected)


def test_adding_the_new_limb_sites_does_not_move_limb_avg():
    """The load-bearing case for #3663's OWN change.

    Same body, measured twice: once with the 13 fields the schema used to hold,
    once with all 19. `limb_avg_in` must be identical — otherwise the number
    stored on 2026-03-29 and 2026-09-06 silently stops meaning what it meant.
    """
    old_fields = [
        "neck_in",
        "chest_in",
        "waist_narrowest_in",
        "waist_navel_in",
        "hips_in",
        "bicep_relaxed_left_in",
        "bicep_relaxed_right_in",
        "bicep_flexed_left_in",
        "bicep_flexed_right_in",
        "calf_left_in",
        "calf_right_in",
        "thigh_left_in",
        "thigh_right_in",
    ]
    values = {
        "neck_in": "17.0",
        "shoulder_width_in": "21.0",
        "chest_in": "51.0",
        "waist_narrowest_in": "49.0",
        "waist_navel_in": "55.5",
        "waist_iliac_crest_in": "56.0",
        "hips_in": "57.0",
        "bicep_relaxed_left_in": "17.5",
        "bicep_relaxed_right_in": "17.75",
        "bicep_flexed_left_in": "18.25",
        "bicep_flexed_right_in": "18.5",
        "forearm_max_left_in": "13.0",
        "forearm_max_right_in": "13.25",
        "calf_left_in": "19.0",
        "calf_right_in": "19.0",
        "thigh_left_in": "29.0",
        "thigh_right_in": "29.0",
        "thigh_upper_left_in": "34.0",
        "thigh_upper_right_in": "34.0",
    }
    narrow = {k: Decimal(v) for k, v in values.items() if k in old_fields}
    wide = {k: Decimal(v) for k, v in values.items()}

    derived_narrow = mi._compute_derived(narrow, 69)
    derived_wide = mi._compute_derived(wide, 69)

    assert derived_wide["limb_avg_in"] == derived_narrow["limb_avg_in"]
    # and it is still the number the live 2026-09-06 row carries
    assert derived_wide["limb_avg_in"] == Decimal("23.312")
    assert derived_wide["bilateral_symmetry_thigh_in"] == derived_narrow["bilateral_symmetry_thigh_in"]
    assert derived_wide["bilateral_symmetry_bicep_in"] == derived_narrow["bilateral_symmetry_bicep_in"]


def test_a_site_outside_the_enumeration_cannot_move_a_derived_number():
    base = {f: Decimal("20") for f in mi.MEASUREMENT_FIELDS}
    baseline = mi._compute_derived(base, 69)
    outside = [f for f in mi.MEASUREMENT_FIELDS if f not in mi.LIMB_AVG_SITES and f not in ("waist_navel_in", "waist_narrowest_in")]
    assert outside, "no field outside the enumeration — this control proves nothing"
    for field in outside:
        moved = dict(base, **{field: Decimal("99")})
        derived = mi._compute_derived(moved, 69)
        assert derived["limb_avg_in"] == baseline["limb_avg_in"], f"{field} moved limb_avg_in without being in LIMB_AVG_SITES"


def test_the_written_row_stamps_which_sites_it_averaged(monkeypatch):
    """`limb_avg_sites` on the item — the enumeration matches the fields stored ON THAT ROW."""
    response, table = invoke(monkeypatch, fixture_bytes("session_clean.csv"))
    assert response["statusCode"] == 200
    item = table.items[(mi.PK, "DATE#2026-09-06")]
    assert item["limb_avg_sites"] == list(mi.LIMB_AVG_SITES)
    for site in item["limb_avg_sites"]:
        assert site in item, f"limb_avg_in says it averaged {site}, which this row does not store"
    mean = sum(float(item[s]) for s in item["limb_avg_sites"]) / len(item["limb_avg_sites"])
    assert float(item["limb_avg_in"]) == pytest.approx(mean, abs=0.001)


def test_limb_avg_sites_omits_a_site_the_row_did_not_measure():
    """A partial session's stamp names what it ACTUALLY averaged, not the full enumeration."""
    measurements = {
        "waist_navel_in": Decimal("55.5"),
        "waist_narrowest_in": Decimal("49.0"),
        "bicep_relaxed_left_in": Decimal("17.5"),
        "bicep_relaxed_right_in": Decimal("17.75"),
    }
    derived = mi._compute_derived(measurements, 69)
    assert derived["limb_avg_sites"] == ["bicep_relaxed_left_in", "bicep_relaxed_right_in"]
    assert float(derived["limb_avg_in"]) == pytest.approx((17.5 + 17.75) / 2)


# ──────────────────────────────────────────────────────────────────────────────
# The backfill script's notes parser (deploy/backfill_measurements_3663.py)
# ──────────────────────────────────────────────────────────────────────────────

# The 2026-09-06 row's `notes` string, verbatim from DynamoDB (read 2026-09-17).
LIVE_NOTES_2026_09_06 = (
    "SELF-MEASURED (not partner-measured as session 1 was — measured_by is hardcoded 'partner' by the "
    "ingestion Lambda; corrected post-write). Cycle-17 Day-1 experiment baseline; session 2 lifetime. "
    "Six sites measured that have no schema field, recorded here so they are not lost: "
    "waist_iliac_crest_in=56.00; shoulder_width_in=21.00; forearm_max_left_in=13.00; "
    "forearm_max_right_in=13.25; thigh_upper_left_in=34.00; thigh_upper_right_in=34.00. "
    "Bodyweight not taken at the tape session (Withings same-day: 327.34 lb)."
)


def _load_backfill_module():
    import importlib.util

    path = os.path.join(ROOT, "deploy", "backfill_measurements_3663.py")
    spec = importlib.util.spec_from_file_location("backfill_measurements_3663", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backfill_parses_exactly_the_six_values_out_of_the_live_notes():
    """The script reads the numbers out of the notes text — it does not carry a value table."""
    backfill = _load_backfill_module()
    found, unknown = backfill.parse_notes_pairs(LIVE_NOTES_2026_09_06)
    assert found == SURVIVED_IN_NOTES
    assert unknown == []


def test_backfill_reports_a_notes_name_the_schema_does_not_model():
    backfill = _load_backfill_module()
    found, unknown = backfill.parse_notes_pairs("ankle_left_in=9.5; neck_in=17.0")
    assert found == {"neck_in": Decimal("17.0")}
    assert unknown == ["ankle_left_in"]


def test_backfill_invents_nothing_from_prose():
    backfill = _load_backfill_module()
    found, unknown = backfill.parse_notes_pairs("Six sites measured that have no schema field. Withings same-day: 327.34 lb.")
    assert found == {}
