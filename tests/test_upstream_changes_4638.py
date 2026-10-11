"""tests/test_upstream_changes_4638.py — #4638: what an upstream edit or delete does to the store.

Three contracts:

  * Every member of `source_registry.UPSTREAM_CHANGES_REQUIRED` states its behaviour on
    its registry entry (`upstream_changes`), from the facet's closed vocabulary, and the
    windows of the two framework re-fetchers (strava, whoop) match their configs.
  * Apple Health: the stated behaviour is `not_propagated` for edits AND deletes, and it
    stays true only while the rebuild-a-day path (`merge_day_to_dynamo(...,
    monotonic_guard=False)`) has no caller outside tests. A new operator caller fails
    here until the facet is re-stated. (The guard itself — a lower corrected total is
    never written — is pinned in tests/test_hae_ingestion_behavior.py.)
  * MacroFactor: on a diary import the file's date range is authoritative — a stored
    day inside it with no rows gets an explicit empty, tombstoned record. The fixture
    takes its header list and cell shapes from a real archived export (read-only S3,
    2026-10-09); food names are placeholders.
"""

import ast
import csv
import io
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import macrofactor_lambda as mf  # noqa: E402
from ingestion import source_registry as sr  # noqa: E402

# ── registry facet ──────────────────────────────────────────────────────────────


def _facet(source):
    return sr.SOURCE_REGISTRY.get(source, {}).get("upstream_changes")


def test_every_required_source_states_its_upstream_change_behaviour():
    offenders = []
    for key in sr.UPSTREAM_CHANGES_REQUIRED:
        facet = _facet(key)
        if key not in sr.SOURCE_REGISTRY:
            offenders.append(f"{key}: not a registry source")
            continue
        if not facet:
            offenders.append(f"{key}: no upstream_changes facet")
            continue
        for side in ("edits", "deletes"):
            if facet.get(side) not in sr.UPSTREAM_CHANGE_BEHAVIOURS:
                offenders.append(f"{key}.{side}={facet.get(side)!r}")
        if facet.get("standing") not in sr.UPSTREAM_CHANGE_STANDINGS:
            offenders.append(f"{key}.standing={facet.get('standing')!r}")
        windowed = "inside_window" in (facet.get("edits"), facet.get("deletes"))
        if windowed != isinstance(facet.get("window_days"), int):
            offenders.append(f"{key}: window_days={facet.get('window_days')!r} disagrees with an inside_window behaviour")
        if not str(facet.get("note") or "").strip():
            offenders.append(f"{key}: no note")
    assert not offenders, "upstream_changes facet offenders:\n  " + "\n  ".join(offenders)


def test_framework_refetch_windows_match_the_stated_windows():
    """strava and whoop's window IS their refresh_trailing_days — a config change re-states the facet."""
    offenders = []
    for key, path in (("strava", "lambdas/ingestion/strava_lambda.py"), ("whoop", "lambdas/ingestion/whoop_lambda.py")):
        m = re.search(r"refresh_trailing_days=(\d+)", (ROOT / path).read_text())
        stated = (_facet(key) or {}).get("window_days")
        if not m or int(m.group(1)) != stated:
            offenders.append(f"{key}: config {m and m.group(1)} vs stated {stated}")
    assert not offenders, offenders


def _is_true(node):
    return isinstance(node, ast.Constant) and node.value is True


def test_apple_health_rebuild_path_has_no_operator_caller_so_nothing_propagates():
    facet = _facet("apple_health") or {}
    assert (facet.get("edits"), facet.get("deletes")) == ("not_propagated", "not_propagated")
    callers = []
    for top in ("lambdas", "scripts", "deploy", "mcp"):
        for path in sorted((ROOT / top).rglob("*.py")):
            text = path.read_text(errors="ignore")
            # Prefilter on the CALLEE, never on the keyword: a positional caller
            # merge_day_to_dynamo(d, f, None, False) never spells "monotonic_guard" (#4638 verifier).
            if "merge_day_to_dynamo" not in text:
                continue
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                rebuild = (len(node.args) >= 4 and not _is_true(node.args[3])) or any(
                    k.arg == "monotonic_guard" and not _is_true(k.value) for k in node.keywords
                )
                if name == "merge_day_to_dynamo" and rebuild:
                    callers.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not callers, (
        f"a rebuild-a-day caller now exists ({callers}) — Apple Health edits/deletes can propagate; "
        "re-state source_registry apple_health.upstream_changes (#4638)"
    )


# ── MacroFactor: the diary file's date range is authoritative ────────────────────

# The header row of a real diary export (raw/matthew/macrofactor/2026/10/, 2026-10-05), verbatim.
REAL_HEADERS = (
    "Date,Time,Food Name,Serving Size,Serving Qty,Serving Weight (g),Calories (kcal),Fat (g),Carbs (g),Protein (g),"
    'Alcohol (g),"B12, Cobalamin (mcg)","B1, Thiamine (mg)","B2, Riboflavin (mg)","B3, Niacin (mg)",'
    '"B5, Pantothenic Acid (mg)","B6, Pyridoxine (mg)",Caffeine (mg),Calcium (mg),Cholesterol (mg),Choline (mg),'
    "Copper (mg),Cysteine (g),Monounsaturated Fat (g),Polyunsaturated Fat (g),Saturated Fat (g),Trans Fat (g),Fiber (g),"
    "Folate (mcg),Histidine (g),Iron (mg),Isoleucine (g),Leucine (g),Lysine (g),Magnesium (mg),Manganese (mg),"
    "Methionine (g),Omega-3 ALA (g),Omega-3 DHA (g),Omega-3 EPA (g),Omega-3 (g),Omega-6 (g),Phenylalanine (g),"
    "Phosphorus (mg),Potassium (mg),Selenium (mcg),Sodium (mg),Starch (g),Sugars (g),Sugars Added (g),Threonine (g),"
    "Tryptophan (g),Tyrosine (g),Valine (g),Vitamin A (mcg),Vitamin C (mg),Vitamin D (mcg),Vitamin E (mg),"
    "Vitamin K (mcg),Water (g),Zinc (mg)"
)
HEADERS = next(csv.reader(io.StringIO(REAL_HEADERS)))


def _row(date, name="item", time="09:00"):
    # The real cell shapes: ISO date, HH:MM time, '1.0'/'100.0' servings, integer macros,
    # one-decimal micros, and blank for every untracked nutrient.
    return {
        "Date": date,
        "Time": time,
        "Food Name": name,
        "Serving Size": "serving",
        "Serving Qty": "1.0",
        "Serving Weight (g)": "100.0",
        "Calories (kcal)": "80",
        "Fat (g)": "0",
        "Carbs (g)": "4",
        "Protein (g)": "15",
        "Sodium (mg)": "1060.0",
    }


def _export(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADERS)
    w.writeheader()
    for r in rows:
        w.writerow({h: r.get(h, "") for h in HEADERS})
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")  # the real file carries a BOM


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


class _S3:
    def __init__(self, payload):
        self.payload = payload

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": _Body(self.payload)}

    def put_object(self, **kw):
        return {}


class _Table:
    """Bounded DynamoDB stand-in: `stored` answers the range query (in two pages, so
    pagination is exercised); every put is recorded."""

    def __init__(self, stored=(), query_error=None):
        self.stored = list(stored)
        self.query_error = query_error
        self.queries = []
        self.puts = {}

    def query(self, **kw):
        self.queries.append(kw)
        if self.query_error:
            raise self.query_error
        half = len(self.stored) // 2
        if "ExclusiveStartKey" not in kw:
            return {"Items": self.stored[:half], "LastEvaluatedKey": {"sk": "page"}}
        return {"Items": self.stored[half:]}

    def put_item(self, Item):  # noqa: N803
        self.puts[Item["date"]] = Item


def _stored(date, **extra):
    return {"sk": f"DATE#{date}", "date": date, "entries_count": 3, **extra}


def _run(monkeypatch, rows, table):
    monkeypatch.setattr(mf, "s3_client", _S3(_export(rows)))
    monkeypatch.setattr(mf, "table", table)
    monkeypatch.setattr(mf, "archive_raw", lambda *a, **k: None)
    return mf.lambda_handler({"bucket": "test-bucket", "key": "uploads/macrofactor/MacroFactor-x.csv"}, None)


# The rolling window: 09-29 .. 10-05, with 09-30 emptied in the app since the last upload.
WINDOW = ["2026-09-29", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"]


def test_a_stored_day_inside_the_range_with_no_rows_gets_an_explicit_empty_record(monkeypatch):
    rows = [_row(d, f"item-{i}") for i, d in enumerate(WINDOW)]
    table = _Table(
        stored=[
            _stored("2026-09-29"),
            _stored("2026-09-30"),  # deleted in the app — absent from this export
            _stored("2026-10-01"),
            _stored("2026-10-02"),
        ]
    )
    resp = _run(monkeypatch, rows, table)

    empty = table.puts["2026-09-30"]
    assert empty["entries_count"] == 0 and empty["food_log"] == []
    assert empty["tombstone"] is True and empty["tombstoned_reason"] == mf.EMPTY_DAY_REASON
    assert not [k for k in empty if k.startswith("total_")], "an emptied day must carry no totals (absence, never 0)"
    assert '"days_emptied": 1' in resp["body"]
    # the logged days still write normally, and the query read the file's own range, paginated
    assert set(table.puts) == set(WINDOW) | {"2026-09-30"}
    assert all(not table.puts[d].get("tombstone") for d in WINDOW)
    assert len(table.queries) == 2 and table.queries[1]["ExclusiveStartKey"] == {"sk": "page"}


def test_what_the_empty_record_never_touches(monkeypatch):
    rows = [_row(d) for d in WINDOW] + [_row("2026-09-27", name="")]  # 09-27: a dated row that parses to no entry
    table = _Table(
        stored=[
            _stored("2026-09-20"),  # outside the file's range — older than the export window
            _stored("2026-09-27"),  # present in the file (a dated row), even though no entry parsed
            _stored("2026-09-28", _format="daily_summary"),  # the other export channel's record
            _stored("2026-09-30", tombstone=True, entries_count=0),  # already empty — idempotent
        ]
    )
    resp = _run(monkeypatch, rows, table)
    assert not ({"2026-09-20", "2026-09-27", "2026-09-28", "2026-09-30"} & set(table.puts)), sorted(table.puts)
    assert '"days_emptied": 0' in resp["body"]


def test_a_never_stored_gap_stays_absent(monkeypatch):
    """09-30 has no row in the file AND none in the store: no row is invented for it."""
    table = _Table(stored=[_stored("2026-09-29")])
    _run(monkeypatch, [_row(d) for d in WINDOW], table)
    assert "2026-09-30" not in table.puts


def test_a_failed_range_read_never_costs_the_import(monkeypatch):
    table = _Table(stored=[_stored("2026-09-30")], query_error=RuntimeError("throttled"))
    resp = _run(monkeypatch, [_row(d) for d in WINDOW], table)
    assert set(table.puts) == set(WINDOW)
    assert '"days_emptied": 0' in resp["body"]
