"""tests/test_brief_hybrid_trial_6175.py — the Morning Brief hybrid-format trial (#6175, owner ruling 2026-11-22 §2).

What is pinned, by the ruling's own terms:

  1. SWITCH OFF IS TODAY'S BRIEF, BYTE FOR BYTE — absent, "off", an unknown value and a failed switch read
     all send exactly what the handler sent before the trial, write nothing for the trial, and turning the
     switch back off after a hybrid send restores that render exactly.
  2. NEW / REPEAT — yesterday's advice is never NEW; a reworded repeat of the same action is a REPEAT;
     "day n" counts the run; only a NEW coaching recommendation becomes the day's decision.
  3. PENDING IS NOT MISSING, PROVISIONAL STAYS PROVISIONAL — a food export that has not arrived reads as
     pending data and every food ask written from it is held back; a grade without the food log says so.
  4. THE ANSWER DOOR — a GET (what a mail scanner does) writes nothing; only a POST from the page records;
     the token is opaque (no recommendation text in the URL), scoped, expiring and single-use.
  5. MEASUREMENT — one private SEND# row per send with the variant, word counts and NEW/REPEAT counts.

No AWS: every table is a hand-rolled fake; the handler runs inside test_daily_brief_behavior's harness.
"""

from __future__ import annotations

import base64
import json
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode, urlparse

import pytest
from coach import brief_recommendations as rr
from content import brief_hybrid as bh
from emails import brief_trial as bt

# ══════════════════════════════════════════════════════════════════════════════
# 2. NEW / REPEAT
# ══════════════════════════════════════════════════════════════════════════════

DAY = "2026-11-20"


def test_rewordings_of_the_same_ask_are_one_action_class():
    asks = [
        "📋 Logging went quiet two days ago — before anything else today, open the food log and enter one meal",
        "🥩 Nutrition data was completely absent yesterday — before anything else today, log your first meal in MacroFactor",
        "📊 Three days without a food log means nutrition is invisible right now — open MacroFactor before your first meal",
    ]
    assert {bh.classify(a) for a in asks} == {"food_log"}
    assert bh.classify("📊 1,152 kcal is 23% below your 1,500 target") == "intake" and "intake" in bh.FOOD_KEYS
    assert bh.classify("🚶 a deliberate 15-minute walk today") == bh.classify("one 30-minute walk closes the movement gap") == "movement"


def test_yesterdays_advice_is_never_new():
    for key in ("food_log", "movement", "readiness:red", "other:something-unclassified"):
        src = "readiness" if key.startswith("readiness") else "ai_guidance"
        r = bh.Rec(key=key, text="x", kind="coaching", source=src, evidence="e", confidence="low", basis="b")
        bh.label_recs([r], DAY, {"2026-11-19": {key}})
        assert r.status == "REPEAT" and r.day_n == 2, key


def test_day_n_counts_the_run_and_a_short_gap_does_not_end_it():
    hist = {"2026-11-19": {"movement"}, "2026-11-16": {"movement"}, "2026-11-15": {"movement"}}  # 17th, 18th absent
    assert bh.first_seen("movement", DAY, hist) == "2026-11-15"
    assert bh.day_number("2026-11-15", DAY) == 6


def test_a_gap_longer_than_the_run_gap_makes_it_new_again():
    hist = {"2026-11-16": {"movement"}}  # 17, 18, 19 absent: three days
    r = bh.Rec(key="movement", text="walk", kind="coaching", source="ai_guidance", evidence="e", confidence="low", basis="b")
    bh.label_recs([r], DAY, hist)
    assert r.status == "NEW" and r.label == "NEW"


def test_the_readiness_call_runs_only_on_consecutive_mornings():
    hist = {"2026-11-19": {"readiness:red"}, "2026-11-18": {"readiness:red"}, "2026-11-16": {"readiness:red"}}
    r = bh.readiness_rec("red", 58, [59, 57, 58], DAY)
    bh.label_recs([r], DAY, hist)
    assert r.label == "REPEAT (day 3)"
    # a different colour yesterday makes today's call new
    r2 = bh.readiness_rec("red", 58, [58], DAY)
    bh.label_recs([r2], DAY, {"2026-11-19": {"readiness:yellow"}})
    assert r2.status == "NEW"


def test_only_a_new_coaching_recommendation_is_the_decision():
    rep = bh.Rec(key="movement", text="walk", kind="coaching", source="ai_guidance", evidence="e", confidence="low", basis="b", day_n=3)
    house = bh.export_rec(DAY, "2026-11-18")
    house.day_n = 1
    assert bh.pick_decision([rep, house]) is None  # housekeeping is never the decision
    new = bh.Rec(key="hydration", text="drink", kind="coaching", source="ai_guidance", evidence="e", confidence="low", basis="b", day_n=1)
    assert bh.pick_decision([rep, house, new]) is new
    assert bh.pick_respond([rep, house], None) is rep


def test_an_observation_is_not_a_recommendation():
    recs, held = bh.guidance_recs(["🏆 Weight hit 285.11 lbs — you are 0.1 lbs from the Sleep Threshold milestone"], DAY, False)
    assert recs == [] and held == 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. pending export, provisional grade — and the rendered block
# ══════════════════════════════════════════════════════════════════════════════


def _data(arrival_day="2026-11-18", intake=None):
    d = {"date": DAY, "brief_editorial": {"nutrition": {"last_arrival_day": arrival_day, "last_intake_day": arrival_day}}}
    if intake is not None:
        d["macrofactor"] = {"total_calories_kcal": intake, "total_protein_g": 150}
    return d


def _status(data, **over):
    s = {
        "data_day": DAY,
        "morning_day": DAY,
        "weight_lbs": 285.1,
        "weekly_rate_lbs": -3.5,
        "readiness_score": 58,
        "readiness_colour": "red",
        "recovery": 56,
        "kcal": (data.get("macrofactor") or {}).get("total_calories_kcal"),
        "arrival": bt.brief_editorial.nutrition_arrival(data),
        "last_arrival_day": data["brief_editorial"]["nutrition"]["last_arrival_day"],
        "habits_total": 7,
        "habits_done": 5,
        "grade_score": 57,
        "grade_letter": "C-",
        "grade_provisional": bt.grade_provisional(data, 57),
        "sessions": 1,
        "minutes": 90,
        "waiting": ["Week 11 chronicle draft (drafted November 17)"],
    }
    s.update(over)
    return s


GUIDANCE = [
    "📋 Logging went quiet two days ago — before anything else today, open the food log and enter one meal.",
    "🥩 Protein logged as zero — pair your first meal with a 50 g shake.",
    "🚶 Steps dropped 47% — a single 30-minute walk today is the highest-leverage move.",
]


def _view(data, hist=None, guidance=GUIDANCE):
    return bt.build_view(
        data=data,
        status=_status(data),
        readiness_score=58,
        readiness_colour="red",
        guidance_items=guidance,
        history=hist or {},
        readiness_scores=[58],
    )


def test_a_pending_export_is_pending_data_and_its_food_asks_are_held_back():
    data = _data(arrival_day="2026-11-18")  # landed before the data day ended -> not arrived for the 20th
    v = _view(data)
    text = bh.render_text(v)
    assert "export not arrived — pending data, not a missed log" in text
    assert "not logged" not in text.lower().replace("not a missed log", "")
    assert not any(r.key in bh.FOOD_KEYS for r in v.recs)  # neither "log a meal" nor the protein ask
    assert v.held_back == 2 and "2 food suggestions held back" in text
    assert any(r.source == "food_export" and r.kind == "housekeeping" for r in v.recs)
    assert any("pending data, not a missed log" in u for u in v.unknown)


def test_an_arrived_export_without_the_day_is_a_real_gap_and_the_asks_stand():
    data = _data(arrival_day="2026-11-21")
    v = _view(data)
    assert "not logged" in bh.food_line(_status(data))
    assert any(r.key == "food_log" for r in v.recs) and v.held_back == 0
    assert not any(r.source == "food_export" for r in v.recs)


def test_a_grade_without_the_food_log_stays_provisional_in_the_subject_and_the_status():
    data = _data()
    s = _status(data)
    assert s["grade_provisional"] is True
    v = _view(data)
    assert "PROVISIONAL" in bh.habits_line(s)
    assert "Grade 57 (C-, provisional)" in bh.subject(v, "Sat Nov 21", 57, "C-", True, "red")
    full = _data(intake=1480)
    assert bt.grade_provisional(full, 61) is False
    assert "provisional" not in bh.subject(v, "Sat Nov 21", 61, "C", False, "yellow")


def test_the_block_has_six_fixed_status_lines_and_states_nothing_new_exactly():
    data = _data()
    hist = {"2026-11-19": {"readiness:red", "movement"}}
    v = _view(data, hist)
    assert [k for k, _ in v.status] == list(bh.STATUS_LABELS)
    assert v.decision is None
    text = bh.render_text(v)
    assert "\nTODAY\n" + bh.NOTHING_NEW + "\n" in text
    assert "REPEAT (day 2)" in text and "Confidence: low." in text and "Unknown" in text
    html = bh.render_html(v)
    assert bh.NOTHING_NEW in html and "FULL DETAIL" in html
    # missing values say so; a line is never dropped
    empty = bh.status_lines({"data_day": DAY})
    assert len(empty) == 6 and all(v for _, v in empty)


def test_a_new_recommendation_leads_as_todays_decision():
    v = _view(_data(intake=1480), {"2026-11-19": {"readiness:red"}}, guidance=["🚶 a 30-minute walk today"])
    assert v.decision is not None and v.decision.key == "movement" and v.decision.label == "NEW"
    assert bh.render_text(v).split("TODAY\n", 1)[1].startswith("🚶 a 30-minute walk today — NEW")


# ══════════════════════════════════════════════════════════════════════════════
# 4. the token and the URL
# ══════════════════════════════════════════════════════════════════════════════


def test_the_url_carries_an_opaque_token_and_nothing_else():
    tok = rr.new_token()
    url = rr.response_url("https://averagejoematt.com/", tok)
    u = urlparse(url)
    assert u.path == "/api/brief_response" and u.query == "t=" + tok
    assert rr.token_valid_shape(tok) and len(tok) == 43
    assert rr.token_hash(tok) != tok and tok not in rr.token_hash(tok)
    assert rr.new_token() != tok


def test_the_rendered_link_has_no_recommendation_text_in_it():
    v = _view(_data(intake=1480), guidance=["🚶 a 30-minute walk today"])
    tok = "A" * 43  # fixed: a random 43-char token can legitimately contain "30" or a day fragment (CI flake, #6175)
    v.respond_url = rr.response_url("https://averagejoematt.com", tok)
    v.respond_rec = v.decision
    q = urlparse(v.respond_url).query
    assert q == "t=" + tok  # the query is the token and nothing else
    for word in ("walk", "30", "movement", DAY, "2026", "%20"):
        assert word not in q


# ══════════════════════════════════════════════════════════════════════════════
# switch + record (brief side)
# ══════════════════════════════════════════════════════════════════════════════


class _Tbl:
    def __init__(self, item=None, error=None):
        self.item, self.error, self.puts = item, error, []

    def get_item(self, Key=None, **_):
        if self.error:
            raise self.error
        return {"Item": self.item} if self.item else {}

    def put_item(self, Item=None, **kw):
        self.puts.append((Item, kw))
        return {}


@pytest.mark.parametrize(
    "item,error,expected",
    [
        (None, None, "off"),
        ({"value": "off"}, None, "off"),
        ({"value": "on"}, None, "off"),
        ({"value": ""}, None, "off"),
        ({"value": " Hybrid "}, None, "hybrid"),
        ({"value": "measure"}, None, "measure"),
        (None, RuntimeError("AccessDenied"), "off"),
    ],
)
def test_the_switch_is_off_unless_it_says_exactly_hybrid_or_measure(item, error, expected):
    assert bt.read_switch(_Tbl(item, error), "USER#matthew#SOURCE#") == expected


def _trial():
    v = _view(_data(intake=1480), guidance=["🚶 a 30-minute walk today"])
    t = bt.Trial(variant="hybrid", data_day=DAY, view=v, text=bh.render_text(v))
    t.token = rr.new_token()
    t.token_row = {"rec_id": v.decision.rec_id, "send_day": DAY, "recipient_hash": rr.recipient_hash("a@b.invalid"), "expires_at": 1}
    t.measurement = {"variant": "hybrid", "n_new": 1, "n_repeat": 1, "hybrid_words": bh.word_count(t.text), "response": rr.NOT_RECORDED}
    return t


def test_a_dry_run_or_demo_writes_nothing_for_the_trial():
    tbl = _Tbl()
    bt.record(tbl, "USER#matthew#SOURCE#", _trial(), 27, persist=False, logger=_Log())
    bt.record(tbl, "USER#matthew#SOURCE#", None, 13, persist=True, logger=_Log())
    assert tbl.puts == []


def test_the_send_records_the_token_hash_never_the_token_and_the_measurement_row():
    tbl, t = _Tbl(), _trial()
    bt.record(tbl, "USER#matthew#SOURCE#", t, 41, persist=True, logger=_Log())
    (tok_row, tok_kw), (send_row, _) = tbl.puts
    assert tok_row["sk"] == "TOKEN#" + rr.token_hash(t.token) and t.token not in json.dumps(tok_row, default=str)
    assert tok_kw["ConditionExpression"] == "attribute_not_exists(sk)"
    assert send_row["sk"] == "SEND#" + DAY and send_row["variant"] == "hybrid" and send_row["total_html_chars"] == 41
    assert send_row["n_new"] == 1 and send_row["response"] == "not_recorded" and send_row["hybrid_words"] > 0


class _Log:
    def warning(self, *a, **k):
        pass

    info = error = warning


# ══════════════════════════════════════════════════════════════════════════════
# 1. switch off == today's brief, byte for byte (through the real handler)
# ══════════════════════════════════════════════════════════════════════════════

import test_daily_brief_behavior as _dbb  # noqa: E402 — the handler harness (fakes only, no AWS)

brief, computed_row = _dbb.brief, _dbb.computed_row
# the harness's fixtures, bound here so pytest finds them (two are autouse: the frozen clock, every day a narrative day)
frozen_clock, _every_day_is_a_narrative_day = _dbb.frozen_clock, _dbb._every_day_is_a_narrative_day
handler_env, ses, table = _dbb.handler_env, _dbb.ses, _dbb.table

SWITCH_KEY = (brief.USER_PREFIX + "brief_trial", "SWITCH#format")


def _run(env, switch=None, event=None):
    env["ses"].sent.clear()
    store = env["table"].store
    store.pop(SWITCH_KEY, None)
    if switch is not None:
        store[SWITCH_KEY] = {"pk": SWITCH_KEY[0], "sk": SWITCH_KEY[1], "value": switch}
    # force_send: the DIL-025 replay guard would otherwise refuse every run after the first
    brief.lambda_handler({"force_send": True, **(event or {})}, None)
    if not env["ses"].sent:
        return None, None
    simple = env["ses"].sent[-1]["Content"]["Simple"]
    return simple["Subject"]["Data"], simple["Body"]["Html"]["Data"]


def _trial_writes(env):
    return [p for p in env["table"].puts if str(p.get("pk", "")).endswith("#brief_trial")]


@pytest.fixture
def env(handler_env):
    r = computed_row()
    handler_env["table"].store[(r["pk"], r["sk"])] = r
    return handler_env


def test_switch_off_in_every_spelling_sends_the_current_brief_byte_for_byte(env, monkeypatch):
    baseline = _run(env)
    assert baseline[1] is not None and "THE BRIEF" in baseline[1] and "S:hybrid_brief" not in baseline[1]
    assert baseline[0].startswith("Morning Brief | ") and "Grade: 84 (B)" in baseline[0]
    for spelling in ("off", "OFF-ish", "on", "", "true"):
        assert _run(env, spelling) == baseline, spelling
    monkeypatch.setattr(env["table"], "get_error", None)
    real_get = env["table"].get_item

    def failing_switch(Key=None, **kw):
        if (Key["pk"], Key["sk"]) == SWITCH_KEY:
            raise RuntimeError("AccessDeniedException")
        return real_get(Key=Key, **kw)

    monkeypatch.setattr(env["table"], "get_item", failing_switch)
    assert _run(env, "hybrid") == baseline  # an unreadable switch is off
    assert _trial_writes(env) == []


def test_hybrid_then_off_restores_the_current_render_exactly(env):
    baseline = _run(env)
    subj, html = _run(env, "hybrid")
    assert html != baseline[1] and "<!-- S:hybrid_brief -->" in html
    assert html.index("S:hybrid_brief") < html.index("THE BRIEF")  # decision first, the full brief after
    assert html.replace(html[html.index("<!-- S:hybrid_brief -->") : html.index("<!-- /S:hybrid_brief -->") + 24], "") == baseline[1]
    assert subj.startswith("Morning Brief | ") and subj != baseline[0]
    assert {p["sk"].split("#")[0] for p in _trial_writes(env)} >= {"SEND"}
    assert _run(env, "off") == baseline


def test_measure_arm_sends_the_current_brief_and_records_the_send(env):
    baseline = _run(env)
    assert _run(env, "measure") == baseline
    sends = [p for p in _trial_writes(env) if p["sk"].startswith("SEND#")]
    assert sends and sends[-1]["variant"] == "measure" and sends[-1]["total_html_chars"] > 0
    assert not any(p["sk"].startswith("TOKEN#") for p in _trial_writes(env))  # no link in the current render


def test_a_hybrid_dry_run_writes_nothing_for_the_trial(env):
    _run(env, "hybrid", {"dry_run": True})
    assert _trial_writes(env) == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. the answer door (site-api)
# ══════════════════════════════════════════════════════════════════════════════


class _DoorTable:
    """Keyed store with the two conditional updates the door makes."""

    class _CCF(Exception):
        pass

    def __init__(self):
        self.store, self.writes, self.reads = {}, [], []

    def get_item(self, Key=None, **_):
        self.reads.append(Key)
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, **kw):  # pragma: no cover — the door never puts
        self.writes.append(("put", kw))
        raise AssertionError("the door must not put_item")

    def update_item(self, Key=None, ConditionExpression="", ExpressionAttributeValues=None, **kw):
        self.writes.append(("update", Key))
        k = (Key["pk"], Key["sk"])
        it = self.store.get(k)
        v = ExpressionAttributeValues or {}
        if it is None:
            raise self._CCF("ConditionalCheckFailedException")
        if Key["sk"].startswith("TOKEN#") and (it.get("used_at") or int(it["expires_at"]) <= v[":now"]):
            raise self._CCF("ConditionalCheckFailedException")
        if Key["sk"].startswith("TOKEN#"):
            it.update(used_at=v[":u"], response=v[":r"], response_status=v[":s"])
        else:
            it.update(response=v[":s"], response_word=v[":r"], response_at=v[":u"], response_rec_id=v[":id"])
        return {"Attributes": dict(it)}


PK = "USER#matthew#SOURCE#brief_trial"


@pytest.fixture
def door(monkeypatch):
    from web import site_api_brief_response as sb

    t = _DoorTable()
    metered = []
    monkeypatch.setattr(sb, "_deps", lambda: (t, _Log()))
    monkeypatch.setattr(sb, "salted_ip_hash", lambda ip, logger=None: "iphash")
    monkeypatch.setattr(sb, "_meter", lambda _tbl, ip_hash: (metered.append(ip_hash), (True, 10, 0))[1])
    tok = rr.new_token()
    t.store[(PK, "TOKEN#" + rr.token_hash(tok))] = {
        "pk": PK,
        "sk": "TOKEN#" + rr.token_hash(tok),
        "rec_id": "2026-11-20#movement",
        "send_day": DAY,
        "recipient_hash": rr.recipient_hash("owner@example.invalid"),
        "expires_at": Decimal(int(time.time()) + 3600),
    }
    t.store[(PK, "SEND#" + DAY)] = {"pk": PK, "sk": "SEND#" + DAY, "response": "not_recorded"}
    return _Door(sb, metered), t, tok


class _Door:
    def __init__(self, sb, metered):
        self.sb, self.metered = sb, metered

    def _handle_brief_response(self, event):
        return self.sb.handle_brief_response(event)


def _get(tok):
    return {
        "queryStringParameters": {"t": tok},
        "headers": {"cloudfront-viewer-address": "203.0.113.7:1"},
        "requestContext": {"http": {"method": "GET"}},
    }


def _post(tok, response, b64=False):
    body = urlencode({"t": tok, "response": response})
    if b64:
        body = base64.b64encode(body.encode()).decode()
    return {
        "body": body,
        "isBase64Encoded": b64,
        "headers": {"cloudfront-viewer-address": "203.0.113.7:1", "content-type": "application/x-www-form-urlencoded"},
        "requestContext": {"http": {"method": "POST"}},
    }


def test_opening_the_link_shows_a_confirmation_page_and_writes_nothing(door):
    social, t, tok = door
    for _ in range(3):  # a scanner, a preview, the owner
        resp = social._handle_brief_response(_get(tok))
        assert resp["statusCode"] == 200
    assert t.writes == []
    assert t.store[(PK, "TOKEN#" + rr.token_hash(tok))].get("used_at") is None
    page = resp["body"]
    assert 'method="post"' in page and page.count("<form") == 3 and "Opening this page recorded nothing" in page
    assert "walk" not in page.lower() and "movement" not in page  # the page names no recommendation
    h = resp["headers"]
    assert h["Cache-Control"].startswith("no-store") and "noindex" in h["X-Robots-Tag"] and h["Referrer-Policy"] == "no-referrer"


def test_only_the_explicit_post_records_and_the_token_is_single_use(door):
    social, t, tok = door
    resp = social._handle_brief_response(_post(tok, "done"))
    assert resp["statusCode"] == 200 and "Recorded" in resp["body"]
    row = t.store[(PK, "TOKEN#" + rr.token_hash(tok))]
    assert row["response"] == "done" and row["response_status"] == "accepted" and row["used_at"]
    send = t.store[(PK, "SEND#" + DAY)]
    assert send["response"] == "accepted" and send["response_rec_id"] == "2026-11-20#movement"
    again = social._handle_brief_response(_post(tok, "not_doing", b64=True))
    assert again["statusCode"] == 410 and "already recorded" in again["body"]
    assert row["response"] == "done"  # the second answer changed nothing
    assert social._handle_brief_response(_get(tok))["statusCode"] == 410  # the page says so, too


def test_an_expired_token_records_nothing(door):
    social, t, tok = door
    t.store[(PK, "TOKEN#" + rr.token_hash(tok))]["expires_at"] = Decimal(int(time.time()) - 1)
    assert social._handle_brief_response(_get(tok))["statusCode"] == 410
    assert social._handle_brief_response(_post(tok, "done"))["statusCode"] == 410
    assert "used_at" not in t.store[(PK, "TOKEN#" + rr.token_hash(tok))]
    assert t.store[(PK, "SEND#" + DAY)]["response"] == "not_recorded"


def test_a_token_is_scoped_to_its_own_row_and_nothing_else_is_accepted(door):
    social, t, tok = door
    other = rr.new_token()  # well-formed, never minted
    assert social._handle_brief_response(_get(other))["statusCode"] == 404
    assert social._handle_brief_response(_post(other, "done"))["statusCode"] == 404
    for bad in ("", "short", tok + "x", "../" + tok[3:]):
        assert social._handle_brief_response(_get(bad))["statusCode"] == 404
    assert social._handle_brief_response(_post(tok, "everything"))["statusCode"] == 404  # unknown answer
    # extra fields cannot retarget the answer: the row's rec id is the only one recorded
    ev = _post(tok, "still_deciding")
    ev["body"] += "&rec_id=2026-11-01%23food_log"
    assert social._handle_brief_response(ev)["statusCode"] == 200
    assert t.store[(PK, "SEND#" + DAY)]["response_rec_id"] == "2026-11-20#movement"
    # the unminted token's conditional write found no row: nothing was created, nothing else was spent
    assert set(t.store) == {(PK, "TOKEN#" + rr.token_hash(tok)), (PK, "SEND#" + DAY)}


def test_the_door_is_routed_for_get_and_post_only():
    from web import site_api_lambda as api

    methods, fn = api._SIMPLE_ROUTES["/api/brief_response"]
    assert methods == {"GET", "POST"} and fn.__name__ == "handle_brief_response"


def test_both_verbs_are_metered_and_the_meter_fails_closed(door, monkeypatch):
    social, t, tok = door
    social._handle_brief_response(_get(tok))
    social._handle_brief_response(_post(tok, "done"))
    assert social.metered == ["iphash", "iphash"]
    from web import site_api_brief_response as sb

    monkeypatch.setattr(sb, "_meter", lambda _tbl, ip_hash: (False, 0, 60))
    refused = sb.handle_brief_response(_post(rr.new_token(), "done"))
    assert refused["statusCode"] == 429 and refused["headers"]["Retry-After"] == "60"
    src = Path(sb.__file__).read_text()
    meter = src[src.index("def _meter") : src.index("def handle_brief_response")]
    assert "fail_open=False" in meter  # a limiter outage refuses (#6088)
