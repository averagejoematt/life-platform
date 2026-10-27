"""tests/test_og_front_frame_4646.py — the front page's year-frame share card (#4646).

The owner ruled drawing C, "the year frame", on 2026-10-23; the card is ``og-front`` in
``og_image_lambda.PAGES``. ``og_image_lambda`` imports Pillow at module scope and Pillow is
absent from the CI runner (tests/test_og_card_coverage.py), so the geometry, the words and
the fail-safe live in the pure-stdlib ``web.og_front_frame`` and are driven here; the
structural half AST-reads the lambda to prove the builder and the handler use them.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import sys
import urllib.error

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import og_front_frame as off  # noqa: E402

_OG_LAMBDA_SRC = os.path.join(_REPO, "lambdas", "web", "og_image_lambda.py")

START, GOAL, START_ISO = 327.3, 185.0, "2026-09-06"

# /api/edition on 2026-10-23 (read live), trimmed to what the card reads.
LIVE_EDITION = {
    "as_of": "2026-10-23",
    "blocks": {
        "today": {
            "state": "ok",
            "data": {
                "weight_lbs": 298.4,
                "date": "2026-10-23",
                "start_weight_lbs": 327.3,
                "start_date": "2026-09-06",
                "goal_weight_lbs": 185.0,
            },
        },
        "week": {
            "state": "ok",
            "data": {
                "weight_series": [
                    {"date": "2026-09-06", "lbs": 327.3},
                    {"date": "2026-09-12", "lbs": 319.7},
                    {"date": "2026-09-15", "lbs": 318.9},
                    {"date": "2026-10-21", "lbs": 299.2},
                    {"date": "2026-10-22", "lbs": 299.4},
                    {"date": "2026-10-23", "lbs": 298.4},
                ]
            },
        },
    },
}


def _frame(series, today="2026-10-23", start=START, goal=GOAL, start_iso=START_ISO):
    return off.year_frame(series, today, start, goal, start_iso)


# ── geometry ──────────────────────────────────────────────────────────────────


def test_heights_are_the_weight_still_above_the_goal_on_the_start_to_goal_scale():
    f = _frame(
        [
            {"date": "2026-09-06", "lbs": 327.3},  # the start: full height
            {"date": "2026-09-07", "lbs": 256.15},  # half way
            {"date": "2026-09-08", "lbs": 185.0},  # the goal: zero
            {"date": "2026-09-09", "lbs": 340.0},  # above the start: clamps to the top
            {"date": "2026-09-10", "lbs": 180.0},  # below the goal: clamps to the floor
        ]
    )
    assert f is not None and f["from"] == START_ISO
    assert [c["height"] for c in f["cols"]] == pytest.approx([1.0, 0.5, 0.0, 1.0, 0.0])
    assert [c["day"] for c in f["cols"]] == [0, 1, 2, 3, 4]


def test_day_index_counts_from_the_experiment_start_and_absent_days_draw_nothing():
    f = _frame(LIVE_EDITION["blocks"]["week"]["data"]["weight_series"])
    assert f is not None
    assert [(c["date"], c["day"]) for c in f["cols"]] == [
        ("2026-09-06", 0),
        ("2026-09-12", 6),
        ("2026-09-15", 9),
        ("2026-10-21", 45),
        ("2026-10-22", 46),
        ("2026-10-23", 47),
    ]


def test_future_pre_start_and_unusable_weigh_ins_are_dropped():
    f = _frame(
        [
            {"date": "2026-09-01", "lbs": 330.0},  # before the frame
            {"date": "2026-09-06", "lbs": 327.3},
            {"date": "2026-10-24", "lbs": 297.0},  # after today
            {"date": "2026-09-07", "lbs": None},
            {"date": "not-a-day", "lbs": 300.0},
            {"date": "2026-09-08", "lbs": True},
            "junk",
        ]
    )
    assert f is not None
    assert [c["date"] for c in f["cols"]] == ["2026-09-06"]


def test_past_a_year_the_frame_is_the_365_days_ending_today():
    today = "2027-10-11"  # 400 days after the start
    f = _frame([{"date": "2026-09-06", "lbs": 327.3}, {"date": "2026-10-12", "lbs": 300.0}, {"date": today, "lbs": 200.0}], today=today)
    assert f is not None
    assert f["from"] == "2026-10-12"  # today - 364
    assert [(c["date"], c["day"]) for c in f["cols"]] == [("2026-10-12", 0), (today, 364)]


def test_exactly_one_year_in_does_not_roll():
    f = _frame([{"date": "2027-09-05", "lbs": 250.0}], today="2027-09-05")  # day 364
    assert f is not None and f["from"] == START_ISO and f["cols"][0]["day"] == 364
    f = _frame([{"date": "2027-09-06", "lbs": 250.0}], today="2027-09-06")  # day 365 → rolls one day
    assert f is not None and f["from"] == "2026-09-07" and f["cols"][0]["day"] == 364


def test_no_frame_without_the_numbers_it_needs():
    s = [{"date": "2026-09-06", "lbs": 327.3}]
    assert _frame([]) is None
    assert _frame(None) is None
    assert _frame(s, start=None) is None
    assert _frame(s, goal=None) is None
    assert _frame(s, start=185.0, goal=185.0) is None  # no distance to draw
    assert _frame(s, today="") is None
    assert _frame([{"date": "2026-10-24", "lbs": 300.0}]) is None  # only a future weigh-in


def test_without_a_start_day_the_frame_opens_on_the_first_weigh_in():
    f = _frame([{"date": "2026-09-10", "lbs": 320.0}, {"date": "2026-09-12", "lbs": 319.0}], start_iso=None)
    assert f is not None and f["from"] == "2026-09-10" and [c["day"] for c in f["cols"]] == [0, 2]


def test_column_rects_place_each_day_on_the_floor():
    f = _frame(
        [{"date": "2026-09-06", "lbs": 327.3}, {"date": "2026-09-08", "lbs": 185.0}, {"date": "2027-09-05", "lbs": 256.15}],
        today="2027-09-05",
    )
    assert f is not None
    rects = off.column_rects(f, x0=100.0, y0=50.0, width=730.0, height=200.0)  # 2 px a day
    (l0, t0, r0, b0), (l1, t1, r1, b1), (l2, t2, r2, b2) = rects
    assert (l0, t0, r0, b0) == pytest.approx((100.0, 50.0, 101.6, 250.0))  # full height, 80% of a day wide
    assert (l1, b1) == pytest.approx((104.0, 250.0)) and b1 - t1 == pytest.approx(1.0)  # at the goal: 1 px, never invisible
    assert l2 == pytest.approx(100.0 + 364 * 2.0) and b2 - t2 == pytest.approx(100.0)
    assert all(b == pytest.approx(250.0) for _, _, _, b in rects)
    assert max(r for _, _, r, _ in rects) <= 830.0  # inside the frame


# ── words ─────────────────────────────────────────────────────────────────────


def test_card_lines_carry_served_numbers_and_no_iso_date():
    f = _frame(LIVE_EDITION["blocks"]["week"]["data"]["weight_series"])
    premise, names = off.front_card_lines(f, START, GOAL)
    assert premise == "327.3 to 185, in public. Every coach call checked."
    assert names == "One year from September 6. One column per weigh-in, as tall as the weight still above 185."
    # the numbers follow the inputs, not a literal
    p2, n2 = off.front_card_lines(f, 330.0, 190.5)
    assert p2.startswith("330.0 to 190.5,") and n2.endswith("above 190.5.")
    for text in (premise, names, p2, n2):
        assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
        assert not re.search(r"\b(cycle|reset|attempt|restart)", text, re.I)


# ── the edition payload + fail-safe ───────────────────────────────────────────


def test_parse_edition_reads_the_live_shape():
    got = off.parse_edition(LIVE_EDITION)
    assert got is not None
    assert (got["start"], got["goal"], got["start_iso"], len(got["series"])) == (327.3, 185.0, "2026-09-06", 6)
    assert off.parse_edition({"data": LIVE_EDITION}) == got  # an enveloped payload reads the same


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["blocks"]["today"].update(state="absent"),
        lambda d: d["blocks"]["week"].update(state="error"),
        lambda d: d["blocks"]["today"].update(data=None),
        lambda d: d["blocks"]["today"]["data"].update(goal_weight_lbs=None),
        lambda d: d["blocks"]["today"]["data"].update(start_weight_lbs="327"),
        lambda d: d["blocks"]["today"]["data"].update(start_date=None),
        lambda d: d["blocks"]["week"]["data"].pop("weight_series"),
        lambda d: d.pop("blocks"),
    ],
)
def test_parse_edition_refuses_a_partial_payload(mutate):
    d = json.loads(json.dumps(LIVE_EDITION))
    mutate(d)
    assert off.parse_edition(d) is None


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_edition_returns_the_payload_with_a_bounded_timeout():
    seen = {}

    def opener(req, timeout):
        seen["url"], seen["timeout"] = req.full_url, timeout
        return _Resp(json.dumps(LIVE_EDITION).encode())

    assert off.fetch_edition(opener=opener) == LIVE_EDITION
    assert seen["url"] == "https://averagejoematt.com/api/edition"
    assert 0 < seen["timeout"] <= 15  # well under the Lambda's 60 s


@pytest.mark.parametrize(
    "opener",
    [
        lambda req, timeout: (_ for _ in ()).throw(urllib.error.URLError("no route")),
        lambda req, timeout: (_ for _ in ()).throw(TimeoutError("timed out")),
        lambda req, timeout: _Resp(b"{}", status=503),
        lambda req, timeout: _Resp(b"<html>not json"),
    ],
)
def test_fetch_failure_is_none_and_logged(opener, capsys):
    assert off.fetch_edition(opener=opener) is None
    assert "[og-front]" in capsys.readouterr().out


def test_load_front_inputs_fails_safe_and_succeeds_on_the_live_shape(capsys):
    assert off.load_front_inputs("2026-10-23", fetch=lambda: None) is None
    assert off.load_front_inputs("2026-10-23", fetch=lambda: {"blocks": {}}) is None
    assert "[og-front]" in capsys.readouterr().out
    got = off.load_front_inputs("2026-10-23", fetch=lambda: LIVE_EDITION)
    assert got is not None
    assert got["frame"]["from"] == "2026-09-06" and len(got["frame"]["cols"]) == 6
    assert got["premise"].startswith("327.3 to 185")


# ── structural: the lambda uses all of the above ─────────────────────────────


def _lambda_tree():
    return ast.parse(open(_OG_LAMBDA_SRC, encoding="utf-8").read())


def _fn(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_og_front_is_in_pages_and_its_builder_draws_from_og_front_frame():
    tree = _lambda_tree()
    pages = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "PAGES" for t in n.targets))
    entries = {e.elts[0].value: e.elts[1].id for e in pages.value.elts}
    assert entries.get("og-front") == "build_front"
    src = ast.unparse(_fn(tree, "build_front"))
    assert "og_front_frame.load_front_inputs(pacific_today())" in src
    assert "if inputs is None:\n        return None" in src
    assert "og_front_frame.column_rects(" in src


def test_the_columns_are_neutral_ink_never_the_accent():
    loop = next(n for n in ast.walk(_fn(_lambda_tree(), "build_front")) if isinstance(n, ast.For) and "column_rects" in ast.unparse(n.iter))
    body = ast.unparse(loop)
    assert "KIT_SOFT" in body
    assert not re.search(r"ACCENT|GREEN|AMBER", body)


def test_handler_writes_nothing_when_a_builder_returns_none():
    handler = _fn(_lambda_tree(), "render_cards")  # #5421: the PAGES loop moved out of lambda_handler into render_cards
    loop = next(n for n in ast.walk(handler) if isinstance(n, ast.For) and ast.unparse(n.iter) == "PAGES")
    src = ast.unparse(loop)
    skip = src.index("if img is None:")
    assert "continue" in src[skip : skip + 200]
    assert skip < src.index("put_object")
