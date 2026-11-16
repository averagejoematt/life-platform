"""web.public_call_id — a call's public identity is opaque, stable and never made of its words (owner ruling 2026-11-14).

The stored identity of a call is a slug of its sentence; served as ``prediction_id`` it put withheld words into public
addresses, and the narrative gate's taint match emptied ~250 of them on the wire. These pin the replacement: the id is
the first filing instant (no text, no hash of text, no secret), a re-write never moves it, ties are broken the same way
from any read, and on the wire every stored key is replaced or — when it cannot be placed — emptied.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import public_call_id as P  # noqa: E402

SLUG = "pred_20261109_recovery_score_tomorrow_will_fall_betwee"


@pytest.fixture(autouse=True)
def _fresh():
    P.reset()
    yield
    P.reset()


def _row(key, at, sk_only=False):
    r = {"sk": f"PREDICTION#{key}", "created_at": at}
    if not sk_only:
        r["prediction_id"] = key
    return r


def test_the_id_is_the_filing_instant_and_carries_no_word_of_the_call():
    pid = P.public_id("2026-11-09T17:08:33.679712+00:00")
    assert P.PUBLIC_ID.match(pid) and pid.startswith("20261109-")
    assert P.public_id("2026-11-09T17:08:33.679712+00:00") == pid, "deterministic"
    assert P.public_id("2026-11-09T17:08:33.679713+00:00") != pid, "microsecond resolution"
    for word in ("recovery", "score", "tomorrow", "fall"):
        assert word not in pid
    assert P.public_id("not a time") is None and P.public_id(None) is None


def test_the_earliest_filing_wins_so_a_rewrite_never_moves_the_address():
    P.remember("sleep", [_row(SLUG, "2026-11-10T09:00:00+00:00")])  # a re-write read first
    later = P.of("sleep", SLUG)
    P.remember("sleep", [_row(SLUG, "2026-11-09T17:08:33.679712+00:00"), _row(SLUG + "-2", "2026-11-10T09:00:00+00:00")])
    assert P.of("sleep", SLUG) == P.public_id("2026-11-09T17:08:33.679712+00:00") != later


def test_ties_are_broken_by_stored_key_whatever_the_read_order():
    at = "2026-10-20T12:00:00+00:00"
    P.remember("mind", [_row("pred_b", at), _row("pred_a", at)])
    first = (P.of("mind", "pred_a"), P.of("mind", "pred_b"))
    P.reset()
    P.remember("mind", [_row("pred_a", at)])
    P.remember("mind", [_row("pred_b", at)])
    assert (P.of("mind", "pred_a"), P.of("mind", "pred_b")) == first
    assert first[1] == first[0] + "-2"


def test_the_wire_replaces_every_identity_and_empties_what_it_cannot_place():
    P.remember("sleep", [_row(SLUG, "2026-11-09T17:08:33.679712+00:00")])
    pub = P.of("sleep", SLUG)
    body = {
        "items": [
            {"coach_id": "sleep", "prediction_id": SLUG, "item_id": f"sleep:{SLUG}"},
            {"coach_id": "sleep_coach", "prediction_id": "pred_20261101_never_read_words_here"},
        ],
        "verification_summary": {"counted_calls": [f"sleep-{SLUG}", "mind-pred_20261101_unknown_words"]},
        "records": [
            {"record_id": f"PREDICTION#{SLUG}", "predictions": [SLUG]},
            {"record_id": "COMMITMENT#commit_20261020_the_words_of_an_ask"},
        ],
    }
    out = json.loads(P.publicize_response({"statusCode": 200, "body": json.dumps({"coach_id": "sleep", **body})})["body"])
    assert out["items"][0]["prediction_id"] == pub and out["items"][0]["item_id"] == f"sleep:{pub}"
    assert out["items"][1]["prediction_id"] == "", "an unplaced stored key is emptied, never served"
    assert out["verification_summary"]["counted_calls"] == [f"sleep-{pub}", ""]
    assert out["records"][0] == {"record_id": f"PREDICTION#{pub}", "predictions": [pub]}
    assert out["records"][1]["record_id"] == ""
    blob = json.dumps(out)
    for word in ("recovery_score", "never_read_words", "unknown_words", "the_words_of_an_ask"):
        assert word not in blob


def test_must_fail_control_without_the_wire_step_the_words_are_served():
    P.remember("sleep", [_row(SLUG, "2026-11-09T17:08:33.679712+00:00")])
    raw = {"statusCode": 200, "body": json.dumps({"items": [{"coach_id": "sleep", "prediction_id": SLUG}]})}
    assert "recovery_score_tomorrow" in raw["body"], "the defect this module closes"
    assert "recovery_score_tomorrow" not in P.publicize_response(raw)["body"]


def test_a_public_id_already_on_a_payload_passes_by_membership_never_by_shape():
    P.remember("sleep", [_row(SLUG, "2026-11-09T17:08:33.679712+00:00")])
    pub = P.of("sleep", SLUG)
    assert P.of(None, pub) == pub
    assert P.of(None, "20261102-abc") is None, "a stored key shaped like a public id is not trusted"


def test_the_partition_reader_registers_every_prediction_read():
    from web import site_api_coach_ledger as L

    class _T:
        def query(self, **_kw):
            return {"Items": [_row(SLUG, "2026-11-09T17:08:33.679712+00:00")]}

    L._query_partition("COACH#sleep_coach", "PREDICTION#", ("prediction_id",), _g={"table": _T()})
    assert P.of("sleep", SLUG) == P.public_id("2026-11-09T17:08:33.679712+00:00")
    assert "created_at" in L._PREDICTION_PROJECTION_FIELDS


def test_the_lambda_publicizes_before_the_guards():
    import inspect

    from web import site_api_lambda as SL

    src = inspect.getsource(SL)
    assert "public_call_id.publicize_response(result)" in src
    assert src.index("public_call_id.publicize_response(result)") < src.index(
        "narrative_publication.annotate(result)", src.index("public_call_id.publicize_response(result)")
    )
