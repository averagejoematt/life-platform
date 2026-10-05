"""tests/test_edition_latency_4607.py — /api/edition reads its upstreams at once, narrowly, under a budget (#4607).

Measured 2026-10-04: the route took ~4.8 s uncached (p50 in the Lambda) because
``read_bodies`` read eighteen upstreams one after another, and two of them —
``/api/predictions`` and ``/api/calibration`` — were 7.8 MB of the 10.0 MB of DynamoDB JSON
one request parsed, for five numbers.

What this file holds:

  * the reads OVERLAP (an in-flight count, never a wall-clock budget — #3849);
  * a raising upstream and a HUNG upstream each blank their own block and no other, and a
    hung one cannot hold the response past the deadline;
  * the narrow record reader returns the same record block as the two whole routes over one
    fake table, and its projection stays inside theirs;
  * the dashboard composed for the edition serves the same ``moves`` and ``coaches`` without
    reading a single dossier, and says the asks were not read (``null``, never ``[]``);
  * the latency budget: every upstream has a reviewed cost, and their sum stays under a
    ceiling that is pinned here as well as in the module — so adding an upstream is a
    two-place, same-PR edit, never a silent one.

Offline: fake tables and the edition's wire fixtures only.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

from coach import persona_registry  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as coach_api, site_api_coach_ledger as ledger, site_api_edition as ed  # noqa: E402
from web.prediction_reason import metric_words  # noqa: E402

_WIRE_DIR = os.path.join(_REPO, "tests", "fixtures", "edition_wire_4582")
_DAY = "2026-10-03"
_INSTANT = datetime(2026, 10, 4, 2, 29, tzinfo=timezone.utc)

# Which blocks (and nested parts) each upstream feeds — the same map
# tests/test_site_api_routes.py::test_edition_one_upstream_failing_leaves_only_its_block_unavailable holds.
_FEEDS = {
    "dashboard": {"coach_lines"},
    "training": {"week.training"},
    "predictions": {"record"},
    "calibration": {"record"},
}


def _wire():
    out = {}
    for key in ed.SOURCES:
        with open(os.path.join(_WIRE_DIR, f"{key}.json"), encoding="utf-8") as fh:
            out[key] = json.load(fh)
    return out


def _compose(bodies):
    return ed.compose(
        bodies,
        today=_DAY,
        now=_INSTANT,
        start_date="2026-09-06",
        persona_of=persona_registry.resolve,
        persona_of_short=lambda sid: persona_registry.by_short_id(sid)[1],
        metric_words=metric_words,
    )


def _parts(doc):
    blocks = doc["blocks"]
    yield from blocks.items()
    for k, part in ((blocks.get("week") or {}).get("data") or {}).get("measures", {}).items():
        yield f"week.{k}", part


def _key_of(path):
    return next(k for k, p in ed.SOURCES.items() if p == path)


def _s3_of(wire):
    return lambda s3_key: wire[next(k for k, v in ed._S3_KEYS.items() if v == s3_key)]


def _route_of(wire, on_read=None):
    def read(path, qs):
        key = _key_of(path)
        if on_read is not None:
            on_read(key)
        return {"statusCode": 200, "body": json.dumps(wire[key])}

    return read


# ── the reads overlap ────────────────────────────────────────────────────────────


class _InFlight:
    """Counts upstream reads open at the same instant. A sequential walk can only ever
    reach a peak of 1, on any machine at any speed; no clock is asserted (#3849)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.now = self.peak = self.calls = 0

    def __call__(self, key):
        with self._lock:
            self.calls += 1
            self.now += 1
            self.peak = max(self.peak, self.now)
        try:
            time.sleep(0.02)  # holds the read open so overlap is observable; not an assertion
        finally:
            with self._lock:
                self.now -= 1


def test_the_upstreams_are_read_at_the_same_time_and_the_document_is_unchanged():
    wire = _wire()
    probe = _InFlight()
    bodies = ed.read_bodies(_route_of(wire, probe), read_s3=_s3_of(wire))
    assert list(bodies) == list(ed.SOURCES)
    assert probe.calls == len(ed.SOURCES) - len(ed._S3_KEYS), "an upstream route was not read, or was read twice"
    assert probe.peak > 1, f"read_bodies is sequential again: {probe.calls} reads, never more than {probe.peak} in flight"
    assert probe.peak <= ed.MAX_WORKERS
    # Same inputs, same bytes: the document from the concurrent read is the document composed
    # straight from the wire bodies.
    assert json.dumps(_compose(bodies)) == json.dumps(_compose(wire))


def test_MUST_FAIL_a_sequential_read_is_caught_by_the_in_flight_count(monkeypatch):
    """The control: with one worker the same probe reads a peak of exactly 1."""
    wire = _wire()
    probe = _InFlight()
    monkeypatch.setattr(ed, "MAX_WORKERS", 1)
    ed.read_bodies(_route_of(wire, probe), read_s3=_s3_of(wire))
    assert probe.calls == len(ed.SOURCES) - len(ed._S3_KEYS) and probe.peak == 1


# ── isolation under the new execution model ──────────────────────────────────────


def _assert_only_its_blocks_changed(key, bodies, wire):
    baseline = _compose(wire)
    assert bodies[key] is None, f"{key} was not blanked"
    assert [k for k in ed.SOURCES if k != key and bodies[k] is None] == [], "another upstream was blanked with it"
    doc = _compose(bodies)
    parts = dict(_parts(doc))
    fed = _FEEDS[key]
    for name in fed:
        p = parts[name]
        assert p["state"] == "unavailable" and p["data"] is None and p["absent_text"].endswith("is not served right now."), (name, p)
    for name in doc["blocks"]:
        if name in fed or any(f.startswith(name + ".") for f in fed):
            continue
        assert doc["blocks"][name] == baseline["blocks"][name], f"{key} failing changed the unrelated block {name}"


def test_an_upstream_that_raises_blanks_only_its_own_block():
    wire = _wire()
    for key in ("dashboard", "training"):

        def boom(k, key=key):
            if k == key:
                raise RuntimeError("upstream blew up")

        bodies = ed.read_bodies(_route_of(wire, boom), read_s3=_s3_of(wire))
        _assert_only_its_blocks_changed(key, bodies, wire)


def test_a_hung_upstream_blanks_only_its_own_block_and_cannot_hold_the_response():
    """The upstream never answers. ``read_bodies`` returns anyway — while that read is
    STILL blocked — with every other body present. The proof that it did not wait is the
    event, not a stopwatch: the hung read is released only after ``read_bodies`` returned."""
    wire = _wire()
    release = threading.Event()
    entered = threading.Event()

    def hang(k):
        if k == "training":
            entered.set()
            release.wait(60)

    try:
        # Three seconds is this test's whole runtime, and room for seventeen in-memory reads
        # on a starved runner (#3849 measured a starved pool at 2.7 s for nine reads that sleep).
        bodies = ed.read_bodies(_route_of(wire, hang), read_s3=_s3_of(wire), deadline=3.0)
        assert entered.is_set(), "the hung upstream was never started"
        assert not release.is_set(), "read_bodies returned only because the hung read was released"
        _assert_only_its_blocks_changed("training", bodies, wire)
    finally:
        release.set()


def test_a_narrow_reader_that_raises_blanks_exactly_the_keys_it_serves():
    wire = _wire()

    def boom():
        raise RuntimeError("every partition read failed")

    bodies = ed.read_bodies(_route_of(wire), read_s3=_s3_of(wire), narrow={"record": boom})
    assert [k for k in ed.SOURCES if bodies[k] is None] == ["predictions", "calibration"]
    doc = _compose(bodies)
    assert doc["blocks"]["record"]["state"] == "unavailable" and doc["blocks"]["record"]["data"] is None
    baseline = _compose(wire)
    assert all(doc["blocks"][n] == baseline["blocks"][n] for n in doc["blocks"] if n != "record")


def test_a_narrow_reader_replaces_its_routes_and_nothing_else():
    wire = _wire()
    seen = []
    narrow_body = {"predictions": wire["predictions"], "calibration": wire["calibration"]}
    bodies = ed.read_bodies(_route_of(wire, seen.append), read_s3=_s3_of(wire), narrow={"record": lambda: narrow_body})
    assert sorted(seen) == sorted(k for k in ed.SOURCES if k not in ed._S3_KEYS and k not in ("predictions", "calibration"))
    assert json.dumps(_compose(bodies)) == json.dumps(_compose(wire))
    for job, keys in ed.NARROW_JOBS.items():
        assert set(keys) <= set(ed.SOURCES), f"{job} serves a key SOURCES does not have"


# ── the narrow record reader is the two routes' record, not a second one ──────────

_GENESIS = "2026-09-06"


def _pred(pid, status, confidence, outcome_date=None, **extra):
    row = {
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "status": status,
        "confidence": confidence,
        "phase": "experiment",
        "claim_natural": f"claim {pid}",
        "created_date": "2026-09-10",
        "evaluation": {"metric": "sleep_duration_hours", "type": "threshold", "threshold": 7},
        "outcome_notes": "graded",
        "subdomain": "recovery",
    }
    if outcome_date:
        row["outcome_date"] = outcome_date
    row.update(extra)
    return row


def _ledger_rows():
    """Per coach partition: this cycle's graded calls, a re-written docket row (one
    prediction, three rows — #4216), an archived cycle's call, a call resolved before
    genesis, a pending call, an observation and a graded row with no confidence."""
    return {
        "COACH#sleep_coach": [
            _pred("s1", "confirmed", 0.8, "2026-09-20"),
            _pred("s2", "refuted", 0.7, "2026-09-22"),
            _pred("s3", "confirmed", 0.6, "2026-09-25"),
            _pred("s4", "pending", 0.6),
            _pred("s-old", "confirmed", 0.9, "2026-08-01", phase="pilot"),
            _pred("s-tomb", "refuted", 0.9, "2026-09-21", tombstone=True),
        ],
        "COACH#nutrition_coach": [
            _pred("docket-1", "refuted", 0.9, "2026-09-18"),
            {**_pred("docket-1", "refuted", 0.9, "2026-09-19"), "sk": "PREDICTION#docket-1-2"},
            {**_pred("docket-1", "refuted", 0.9, "2026-09-20"), "sk": "PREDICTION#docket-1-3"},
            _pred("n2", "confirmed", 0.55, "2026-09-30"),
            _pred("n-pre", "confirmed", 0.7, "2026-09-01"),
            _pred("n-obs", "observation", 0.5),
        ],
        "COACH#mind_coach": [
            _pred("m1", "refuted", 0.85, "2026-09-12"),
            _pred("m2", "confirmed", None, "2026-09-14"),
            _pred("m3", "confirmed", 0.65, "2026-09-28"),
            {k: v for k, v in _pred("m4", "inconclusive", 0.5).items() if k != "status"}
            | {"outcome": "confirmed", "outcome_date": "2026-09-29"},
        ],
    }


def _projected_table(rows_by_pk, projections):
    """A table that honours ProjectionExpression, so a field the narrow projection drops is
    really absent from what the reader sees — the property under test."""

    def hook(table, **kw):
        expr = kw["KeyConditionExpression"].get_expression()
        pk = expr["values"][0].get_expression()["values"][1]
        sk_prefix = expr["values"][1].get_expression()["values"][1]
        rows = rows_by_pk.get(pk, []) if sk_prefix == "PREDICTION#" else []
        names = kw.get("ExpressionAttributeNames")
        if kw.get("ProjectionExpression"):
            fields = [names[n.strip()] for n in kw["ProjectionExpression"].split(",")]
            projections.append(tuple(fields))
            rows = [{f: r[f] for f in fields if f in r} for r in rows]
        return {"Items": [dict(r) for r in rows]}

    return FakeDdbTable(query_hook=hook)


def _record_block(predictions, calibration):
    return ed._record(predictions, calibration, _DAY)


def test_the_narrow_record_reader_serves_the_same_record_as_the_two_whole_routes(monkeypatch):
    monkeypatch.setattr(coach_api, "EXPERIMENT_START", _GENESIS)
    projections = []
    monkeypatch.setattr(coach_api, "table", _projected_table(_ledger_rows(), projections))

    whole_predictions = ed.body_of(coach_api.handle_predictions({"queryStringParameters": {"limit": "1"}}))
    whole_calibration = ed.body_of(coach_api.handle_calibration({}))
    assert whole_predictions is not None and whole_calibration is not None
    whole = _record_block(whole_predictions, whole_calibration)

    del projections[:]
    narrow = coach_api.edition_record()
    assert set(projections) == {ledger._RECORD_PROJECTION_FIELDS}, "the narrow reader did not ask for its narrow projection"
    assert set(narrow) == set(ed.NARROW_JOBS["record"])

    # The fixture exercises the record: 5 right of 8 decided this cycle (the docket's three
    # rows are one call; the archived, tombstoned and pre-genesis calls are not this cycle's).
    assert whole["state"] == "ok" and (whole["data"]["right"], whole["data"]["decided"]) == (5, 8), whole
    # The skill is scored over NINE pairs: one row carries its grade in `outcome` with no
    # `status`, which the Brier pairs read and the routes' status tally does not. That is the
    # two routes' own behaviour; the narrow reader has to reproduce both numbers, not tidy them.
    assert isinstance(whole["data"]["brier_skill"], float) and whole["data"]["skill_n"] == 9
    assert json.dumps(_record_block(narrow["predictions"], narrow["calibration"])) == json.dumps(whole)
    # Field for field, the subset the narrow reader serves is the routes' own.
    assert narrow["calibration"]["platform"]["strata"]["coaches"] == whole_calibration["platform"]["strata"]["coaches"]
    for field in ("confirmed", "refuted", "decided"):
        assert narrow["predictions"]["overall"][field] == whole_predictions["overall"][field], field
    assert narrow["predictions"]["overall"]["due"]["as_of"] == whole_predictions["overall"]["due"]["as_of"]
    assert narrow["calibration"]["as_of"] == whole_calibration["as_of"]


def test_the_narrow_projection_stays_inside_the_routes_projection():
    assert set(ledger._RECORD_PROJECTION_FIELDS) < set(ledger._PREDICTION_PROJECTION_FIELDS)


def test_the_narrow_record_reader_raises_when_every_partition_read_fails(monkeypatch):
    """A total outage is a failure, never five zeros (#2658) — the edition then serves the
    record unavailable."""

    def down(table, **kw):
        raise RuntimeError("dynamodb is down")

    monkeypatch.setattr(coach_api, "table", FakeDdbTable(query_hook=down))
    try:
        coach_api.edition_record()
    except RuntimeError as e:
        assert "partition reads failed" in str(e)
    else:
        raise AssertionError("a total read failure was served as a record")


# ── the dashboard, composed for the edition ──────────────────────────────────────


def test_the_dashboard_composed_for_the_edition_reads_no_dossier_and_serves_the_same_lines(monkeypatch):
    from ai import budget_guard
    from web import site_api_lambda as L

    output = {
        "pk": "COACH#sleep_coach",
        "sk": "OUTPUT#2026-10-03#daily",
        "public_summary": "Sleep held at seven hours for a third night.",
        "generated_at": "2026-10-03T17:05:00+00:00",
        "data_through": "2026-10-02",
        "phase": "experiment",
    }

    def hook(table, **kw):
        expr = kw["KeyConditionExpression"].get_expression()
        if expr.get("operator") == "AND":
            pk = expr["values"][0].get_expression()["values"][1]
            sk = expr["values"][1].get_expression()["values"][1]
            if pk == "COACH#sleep_coach" and sk == "OUTPUT#":
                return {"Items": [dict(output)]}
        return {"Items": []}

    dossier_reads = []

    def dossier(coach_id):
        dossier_reads.append(coach_id)
        return {"commitments": [{"status": "pending", "text": "Lights out by eleven.", "date": "2026-10-01", "due_date": "2026-10-05"}]}

    monkeypatch.setattr(L, "table", FakeDdbTable(query_hook=hook))
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(L, "_dossier_block", dossier)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

    def read(event_extra):
        event = {"rawPath": "/api/coaching-dashboard", "queryStringParameters": {}, "headers": {}, **event_extra}
        return ed.body_of(L._dispatch_route(event, "/api/coaching-dashboard", "GET"))

    whole = read({})
    assert whole is not None and dossier_reads, "the fixture does not exercise the dossier read at all"
    assert whole["open_actions"] and whole["open_actions"][0]["text"] == "Lights out by eleven."

    del dossier_reads[:]
    lean = read({"composed_for": "edition"})
    assert dossier_reads == [], f"composed for the edition, the dashboard still read {len(dossier_reads)} dossiers"
    assert lean["open_actions"] is None, "asks that were not read must be null, never an empty list"
    # A caller cannot ask for the lean body: the flag is an event key, not a query parameter.
    assert read({"queryStringParameters": {"composed_for": "edition"}})["open_actions"] == whole["open_actions"]

    strip = lambda body: {k: v for k, v in body.items() if k not in ("open_actions", "_meta")}  # noqa: E731
    assert json.dumps(strip(lean)) == json.dumps(strip(whole))
    assert any(c.get("position_summary") for c in lean["coaches"]), "the fixture serves no coach line to compare"
    assert ed._coach_lines(lean, _DAY, lambda sid: persona_registry.by_short_id(sid)[1], persona_registry.resolve) == ed._coach_lines(
        whole, _DAY, lambda sid: persona_registry.by_short_id(sid)[1], persona_registry.resolve
    )


def test_the_edition_marks_every_read_it_makes(monkeypatch):
    """``handle_edition``'s dispatcher is the one that sets the flag — the wiring itself."""
    with open(os.path.join(_REPO, "lambdas", "web", "site_api_lambda.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert '_ed_event = {"headers": {}, "composed_for": "edition"}' in src
    assert 'handle_edition(lambda p, qs: _dispatch_route({**_ed_event, "rawPath": p, "queryStringParameters": qs}, p, "GET"))' in src
    assert 'event.get("composed_for") == "edition"' in src


# ── the latency budget ───────────────────────────────────────────────────────────

# The second place the ceiling lives. Raising SOURCE_COST_CEILING_MS in the module without
# changing this line is red; changing both is the explicit, reviewed budget change (#4607).
REVIEWED_CEILING_MS = 2160


def test_every_upstream_has_a_reviewed_cost_and_the_sum_is_under_the_reviewed_ceiling():
    assert len(ed.SOURCES) >= 18, "the upstream set shrank below what this guard was written over"
    assert ed.latency_budget_offences() == [], ed.latency_budget_offences()
    assert ed.SOURCE_COST_CEILING_MS == REVIEWED_CEILING_MS, (
        f"the edition's cost ceiling moved to {ed.SOURCE_COST_CEILING_MS} ms without the reviewed pin "
        f"({REVIEWED_CEILING_MS} ms) moving with it — change REVIEWED_CEILING_MS here in the same PR, and say why"
    )
    # The ceiling only comes down toward the target; it is never a licence to grow.
    assert ed.LATENCY_TARGET_MS == 1500


def test_MUST_FAIL_an_upstream_added_without_a_budget_change_is_refused():
    """The mutations, run against the decision function over the module's real tables."""
    grown = {**ed.SOURCES, "glucose": "/api/glucose_overview"}
    # 1. A new upstream with no cost at all.
    assert ed.latency_budget_offences(sources=grown) == ["glucose: an upstream with no reviewed cost in SOURCE_COST_MS"]
    # 2. A new upstream with an honest cost: over the ceiling, by name.
    costed = {**ed.SOURCE_COST_MS, "glucose": 300}
    (offence,) = ed.latency_budget_offences(sources=grown, costs=costed)
    assert "over the reviewed ceiling" in offence
    # 3. A zero or missing-number cost is not a way in.
    assert ed.latency_budget_offences(sources=grown, costs={**ed.SOURCE_COST_MS, "glucose": 0}) == [
        "glucose: cost 0 is not a whole number of milliseconds above zero"
    ]
    # 4. A cost left behind by a removed upstream is named too.
    assert ed.latency_budget_offences(costs={**ed.SOURCE_COST_MS, "gone": 5}) == ["gone: a cost for an upstream SOURCES no longer reads"]
    # 5. Only an explicit ceiling change lets the costed upstream through.
    assert ed.latency_budget_offences(sources=grown, costs=costed, ceiling=ed.SOURCE_COST_CEILING_MS + 300) == []
