"""#6111 — the Site API's publication steps make the same decision for the same stored rows, whatever the container read.

THE DEFECT. Two pieces of state lived for the Lambda container and were filled by whatever earlier requests had read:
the narrative gate's taint sets (``web.narrative_publication``: a string sharing a run with any withheld graded row read
EARLIER in the container was emptied) and the public call-id map (``web.public_call_id``: only the calls a route had read
through the partition reader could be named, every other id was emptied). So ``/api/coaches`` served
``latest_checked.prediction_id: ""`` on a cold container and the id on a warm one, a coach page's learning evidence ids
came and went, and the lead's cited ``source_field`` ("whoop.recovery_score") was emptied after any request had read a
withheld call whose metric label was "WHOOP recovery score".

THE INVARIANT. A response's taint is the withheld graded rows THIS request read; the call ids come from the table's
complete partitions; a single token under a structural key is never matched by whole-value equality. Each sequence runs
in a fresh interpreter (``tests/publication_determinism_walk.py``) — a fresh interpreter is the honest cold container.
All text is synthetic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

WALK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "publication_determinism_walk.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from publication_determinism_walk import ECHO_MARK, FIELD_LABEL, FIELD_PATH  # noqa: E402
from web import narrative_publication as G, public_call_id as P  # noqa: E402

TARGETS = (
    "/api/coaches",
    "/api/coach/physical_coach",
    "/api/coach/eli_marsh",
    "/api/coach/sleep_coach",
    "/api/coach/mind_coach",
    "/api/ledger_export",
)
# Other coaches' and partitions' rows, and a different route, read first: the warm container.
WARMUP = ("/api/coach/mind_coach", "/api/predictions", "/api/coach/nutrition_coach", "/api/coach_docket", "/api/coach/glucose_coach")
WITHHELD_TAIL = "before the next weekly review"  # words only the withheld call carries


def _run(sequence, mutate=None) -> list:
    cmd = [sys.executable, WALK, "--sequence", json.dumps(list(sequence))]
    if mutate:
        cmd += ["--mutate", mutate]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)["bodies"]


@pytest.fixture(scope="module")
def runs() -> dict:
    jobs = {f"cold:{t}": ([t], None) for t in TARGETS}
    jobs["warm"] = (WARMUP + TARGETS, None)
    jobs["forward"] = (TARGETS, None)
    jobs["reverse"] = (tuple(reversed(TARGETS)), None)
    jobs.update({f"mutant-cold:{t}": ([t], "container_taint") for t in TARGETS[:4]})
    jobs["mutant-warm"] = (WARMUP + TARGETS[:4], "container_taint")
    jobs["no-wire"] = (("/api/coach/mind_coach", "/api/ledger_export", "/api/coaches"), "no_wire")
    with ThreadPoolExecutor(6) as ex:
        futs = {k: ex.submit(_run, seq, mut) for k, (seq, mut) in jobs.items()}
        return {k: f.result() for k, f in futs.items()}


def _last(bodies: list) -> dict:
    """request -> body, the LAST time each request ran in the sequence (the warm read)."""
    return {t: b for t, b in bodies}


def _cold(runs) -> dict:
    return {t: runs[f"cold:{t}"][0][1] for t in TARGETS}


def _differences(a: dict, b: dict, targets) -> list:
    return [t for t in targets if a[t] != b[t]]


def test_a_cold_and_a_warm_container_serve_byte_identical_bodies(runs):
    cold, warm = _cold(runs), _last(runs["warm"])
    assert _differences(cold, warm, TARGETS) == []
    # Non-vacuity: the fields that came and went are served, on the cold container too.
    coaches = json.loads(cold["/api/coaches"])["coaches"]
    ids = [c["latest_checked"]["prediction_id"] for c in coaches if c.get("latest_checked")]
    assert len(ids) == 7 and all(ids), ids
    learnings = json.loads(cold["/api/coach/physical_coach"])["dossier"]["learnings"]
    assert learnings and all(entry["evidence"]["prediction_id"] for entry in learnings)
    cited = json.loads(cold["/api/coach/eli_marsh"])["lead_daily"]["cited"]
    assert [c["source_field"] for c in cited] == ["whoop.recovery_score"]


def test_the_order_of_requests_changes_no_body(runs):
    forward, reverse = _last(runs["forward"]), _last(runs["reverse"])
    assert _differences(forward, reverse, TARGETS) == []
    assert _differences(forward, _cold(runs), TARGETS) == []


def test_a_withheld_rows_words_are_blanked_in_every_order(runs):
    """The privacy control. The withheld call's sentence, and a public row in its own partition that repeats a run of
    it, are on the mind coach's page and the ledger without the wire half — and emptied with it, in every order."""
    bare = _last(runs["no-wire"])
    for t in ("/api/coach/mind_coach", "/api/ledger_export", "/api/coaches"):
        assert WITHHELD_TAIL in bare[t], f"control: {t} carries the withheld words before the wire"
    assert ECHO_MARK in bare["/api/coach/mind_coach"], "control: the same-partition echo is a served field"
    for key in ("forward", "reverse", "warm"):
        served = _last(runs[key])
        for t in ("/api/coach/mind_coach", "/api/ledger_export", "/api/coaches"):
            assert WITHHELD_TAIL not in served[t], (key, t)
        assert ECHO_MARK not in served["/api/coach/mind_coach"], key
    for t in ("/api/coach/mind_coach", "/api/ledger_export", "/api/coaches"):
        assert WITHHELD_TAIL not in _cold(runs)[t], ("cold", t)


def test_must_fail_control_the_container_lived_state_makes_cold_and_warm_differ(runs):
    """With the taint and the id map living for the container again, the same table serves different bodies."""
    cold = {t: runs[f"mutant-cold:{t}"][0][1] for t in TARGETS[:4]}
    warm = _last(runs["mutant-warm"])
    differ = _differences(cold, warm, TARGETS[:4])
    assert {"/api/coaches", "/api/coach/physical_coach", "/api/coach/sleep_coach"} <= set(differ), differ
    assert json.loads(cold["/api/coaches"])["coaches"][1]["latest_checked"]["prediction_id"] == "", "the defect, reproduced"


def test_no_handler_cache_carries_a_withheld_rows_words_past_its_request():
    """The taint is this request's reads, which is only complete if no handler serves a graded row read by an EARLIER
    request. Every GET route runs with the withheld call in the table, the call is deleted, and every route runs again:
    a cache that kept its row would serve its words untainted in the second pass."""
    bodies = _run(["*", "!drop-withheld", "*"])
    half = len(bodies) // 2
    assert half > 100, half
    assert [t for t, b in bodies if WITHHELD_TAIL in b] == []
    second = dict(bodies[half:])
    assert ECHO_MARK in second["/api/coach/mind_coach"], "after the delete, the public echo is no withheld row's words"
    # Must-fail control: one handler that keeps its graded rows across requests serves the deleted call's words.
    cached = _run(["*", "!drop-withheld", "*"], mutate="handler_cache")
    assert [t for t, b in cached[half:] if WITHHELD_TAIL in b], "the cache mutation went undetected"


# ── the rule pieces, in process ─────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh():
    G.reset_taint()
    G.begin_request()
    P.reset()
    yield
    G.reset_taint()
    G.begin_request()
    P.reset()


def test_begin_request_forgets_the_previous_requests_taint(fresh):
    G._taint_text("A synthetic withheld sentence that names seven quiet evenings of reading.")
    assert G.is_tainted("a synthetic withheld sentence that names seven quiet evenings")
    G.begin_request()
    assert not G.is_tainted("a synthetic withheld sentence that names seven quiet evenings"), "an earlier request's reads"


def test_a_single_token_under_a_structural_key_is_matched_only_by_a_run(fresh):
    G._taint_text(FIELD_LABEL)
    G._taint_text("Synthetic: the subject will log seven quiet evenings of reading.")
    out = G.scrub_payload(
        {
            "source_field": FIELD_PATH,  # an engine field path: the same three words, never compared whole
            "cited": [{"source_field": FIELD_PATH}],
            "label": FIELD_PATH,  # a PROSE_KEYS value is free text, whatever its shape
            "note": FIELD_LABEL.lower(),  # free text: equality still blanks it
            "thread_id": "2026-11-02#the_subject_will_log_seven_quiet_evenings",  # a slug carrying a six-word run
            "coach_ids": ["sleep_coach", "will_log_seven_quiet_evenings_of_reading"],  # elements judged under the list key
        }
    )
    assert out["source_field"] == FIELD_PATH and out["cited"][0]["source_field"] == FIELD_PATH
    assert out["label"] == "" and out["note"] == ""
    assert out["thread_id"] == "", "a slug built from a withheld sentence stays blanked"
    assert out["coach_ids"] == ["sleep_coach", ""], "a structural list keeps its ids and loses a run-carrying slug"


class _Partitions:
    """A raw table of call rows answering a query by its partition key (the loader filters the sort-key prefix)."""

    def __init__(self, rows):
        self.rows, self.queries = list(rows), 0

    def query(self, **kw):
        self.queries += 1
        pk = G._requested_pk(kw.get("KeyConditionExpression"), kw.get("ExpressionAttributeValues"), kw.get("ExpressionAttributeNames"))
        return {"Items": [dict(r) for r in self.rows if r["pk"] == pk]}

    def get_item(self, **kw):
        key = kw.get("Key") or {}
        hit = [dict(r) for r in self.rows if r["pk"] == key.get("pk") and r["sk"] == key.get("sk")]
        return {"Item": hit[0]} if hit else {}


def _filed(coach, slug, at):
    return {"pk": f"COACH#{coach}_coach", "sk": f"PREDICTION#{slug}", "prediction_id": slug, "created_at": at, "claim_natural": "x y z"}


def test_the_id_map_is_the_complete_partition_never_what_a_route_happened_to_read(fresh):
    from call_publication_fixtures import registered

    rows = [_filed("sleep", "pred_20261020_synthetic_sleep_call", "2026-10-20T12:00:00.000001+00:00")]
    rows += [_filed("mind", "pred_20261021_synthetic_mind_call", "2026-10-21T12:00:00.000002+00:00")]
    late = _filed("mind", "pred_20261101_synthetic_late_call", "2026-11-01T12:00:00.000003+00:00")
    table = _Partitions(rows)
    with registered(rows + [late]):
        P.begin_request(table)
        assert P.of(None, "pred_20261021_synthetic_mind_call") == P.public_id("2026-10-21T12:00:00.000002+00:00"), "no read needed"
        first = table.queries
        P.begin_request(table)
        assert P.of("sleep", "pred_20261020_synthetic_sleep_call") and table.queries == first, "a kept map reads nothing"
        table.rows.append(late)  # a call filed after the map was read
        assert P.of("mind", late["prediction_id"]) == P.public_id(late["created_at"]), "one re-read places it"
        before = table.queries
        assert P.of("mind", "pred_20261102_never_filed") is None
        assert P.of("mind", "pred_20261103_never_filed") is None
        assert table.queries - before <= len(P.all_coaches()), "an unplaceable key re-reads each coach at most once a request"


def test_a_map_read_from_one_table_never_answers_for_another(fresh):
    from call_publication_fixtures import registered

    a = _filed("sleep", "pred_20261020_synthetic_shared_key", "2026-10-20T12:00:00.000001+00:00")
    b = dict(a, created_at="2026-10-22T12:00:00.000009+00:00")
    with registered([a, b]):
        P.begin_request(_Partitions([a]))
        assert P.of("sleep", a["prediction_id"]) == P.public_id(a["created_at"])
        P.begin_request(_Partitions([b]))
        assert P.of("sleep", a["prediction_id"]) == P.public_id(b["created_at"])
