"""tests/test_coach_public_register_by_coach.py — #4213: the by-coach slots are served in
the PUBLIC register, or not at all.

#2972 guarded ONE coach-text slot (the door's `position_summary`). One click deeper,
on /coaching/by-coach/, four more slots were served to ~1,100 readers a week in the
owner register verbatim (read live from /api/coach/* on 2026-09-26 19:31Z):

  * `stance.headline_read`  — "You're still operating under significant structural load…"
  * `daily`                 — "You noticed the shift before the data confirmed it…"
  * `recent_outputs[].summary` — `key_recommendation`, an imperative to Matthew
  * `dossier.commitments[].text` (and the door's `open_actions[].text`) — `commitment_natural`

This file extends tests/test_public_audience_frame_2972.py's approach to those four
slots, through the REAL `/api/coach/{id}` handler over a `FakeDdbTable`. The live
Reeves specimens above are the fixtures: on the pre-#4213 code every serving test
below is red (the handler passed each of them through untouched).

The contract, per slot: the public twin (`public_ask` / a third-person text that
passes `audience_guard`) or an EMPTY slot — never the owner text.

Offline: no AWS, no network — FakeDdbTable + monkeypatched module globals.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from coach import (  # noqa: E402
    audience_guard,
    coach_derived_prose,
    coach_history_summarizer as chs,  # noqa: E402
)
from coach.coach_extraction_prompt import EXTRACTION_SYSTEM_PROMPT, build_extraction_message  # noqa: E402
from compute import coach_daily_reflection_lambda as daily  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as C  # noqa: E402

# ── The LIVE specimens (/api/coach/mind_coach, 2026-09-26 19:31Z) ───────────────────

_REEVES_HEADLINE = (
    "You're still operating under significant structural load—grief, protein intake sliding well short of what I "
    "suspect you need for cognitive clarity—yet you're showing up and engaging with genuine curiosity about your own "
    "signals. What's shifted in my read: the six-day journaling silence now feels like a more urgent signal than I "
    "initially weighted it."
)
_REEVES_DAILY = (
    "You noticed the shift before the data confirmed it—that matters. Your body knew something before your mind had "
    "words for it. So I'm curious: when you stopped writing, was it the kind of quiet that comes from being too "
    "depleted to reach for the pen?"
)
_REEVES_KEY_RECOMMENDATION = (
    "Reflect on whether you felt the recovery shift internally before checking the device, and distinguish which "
    "emotional texture the journaling silence carries — resistance or depletion — so we can understand what's "
    "actually blocking expression."
)
_REEVES_COMMITMENT = (
    "Reflect on whether you felt the recovery shift internally before checking the device on the night of "
    "2026-09-24, and report back on that sequence."
)

# The public register — first person for the coach, third person for Matthew, the ask reported.
_PUBLIC_HEADLINE = (
    "Matthew's body is recovering well, while his journal has been quiet. I've asked him one thing: before he picks "
    "up the phone in the morning, notice whether he already felt rested."
)
_PUBLIC_DAILY = "Matthew noticed the shift before the data confirmed it. I'm curious whether his quiet journal is tiredness or avoidance."
_PUBLIC_ASK = "I've asked him to notice, before he checks the device each morning, whether he already felt rested."

_COACH = "mind_coach"
_PK = f"COACH#{_COACH}"


# ══════════════════════════════════════════════════════════════════════════════
# The harness — the real /api/coach/{id} handler over a pk/sk-dispatching fake
# ══════════════════════════════════════════════════════════════════════════════


def _table(stance=None, outputs=(), commitments=()):
    def _query_hook(table, **kw):
        expr = kw["KeyConditionExpression"].get_expression()
        if expr.get("operator") != "AND":
            return {"Items": []}
        pk = expr["values"][0].get_expression()["values"][1]
        sk = expr["values"][1].get_expression()["values"][1]
        if pk != _PK:
            return {"Items": []}
        if sk == "OUTPUT#":
            return {"Items": [dict(o) for o in outputs]}
        if sk == "COMMITMENT#":
            return {"Items": [dict(c) for c in commitments]}
        if sk == "STANCE#" and stance:
            return {"Items": [dict(stance, sk="STANCE#2026-09-20")]}
        return {"Items": []}

    def _get_item_hook(table, key, **kw):
        if key.get("pk") == _PK and key.get("sk") == "STANCE#latest" and stance:
            return {"Item": dict(stance, pk=_PK, sk="STANCE#latest")}
        return {}

    return FakeDdbTable(query_hook=_query_hook, get_item_hook=_get_item_hook)


def _coach_body(monkeypatch, *, stance=None, outputs=(), commitments=(), daily_text=None):
    monkeypatch.setattr(C, "table", _table(stance, outputs, commitments))
    real_load = C._load_s3_json

    def _load(key, cache_name):
        if key == "generated/coach_daily.json":
            return {"reflections": {_COACH: {"text": daily_text, "date": "2026-09-26"}}} if daily_text else {}
        if key.startswith("generated/"):
            return {}
        return real_load(key, cache_name)

    monkeypatch.setattr(C, "_load_s3_json", _load)
    resp = C.handle_coach({"rawPath": f"/api/coach/{_COACH}"})
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body.get("persona_id") == _COACH, body
    return body


def _stance(headline, **extra):
    base = {
        "headline_read": headline,
        "focused_on_now": ["Whether you felt the recovery spike before checking the device", "His journal's silence"],
        "set_aside_for_now": [],
        "stage": {"label": "noticing", "rationale": "He is learning to read his own signals."},
        "how_my_read_changed": "",
        "confidence_note": "",
        "as_of": "2026-09-20",
    }
    base.update(extra)
    return base


def _output(**fields):
    row = {"pk": _PK, "sk": "OUTPUT#2026-09-26#daily_brief", "content": _REEVES_DAILY, "themes": ["journaling_silence"]}
    row.update(fields)
    return row


def _commitment(**fields):
    row = {
        "pk": _PK,
        "sk": "COMMITMENT#commit_20260926_reflect",
        "created_date": "2026-09-26",
        "commitment_natural": _REEVES_COMMITMENT,
        "status": "pending",
        "due_date": "2026-10-03",
    }
    row.update(fields)
    return row


# ══════════════════════════════════════════════════════════════════════════════
# 1. stance.headline_read (+ the rest of the stance's prose)
# ══════════════════════════════════════════════════════════════════════════════


def test_the_live_reeves_headline_is_not_served(monkeypatch):
    """RED before #4213: the handler served this second-person letter verbatim."""
    body = _coach_body(monkeypatch, stance=_stance(_REEVES_HEADLINE))
    assert body["stance"]["source"] == "stance"
    assert body["stance"]["headline_read"] == ""
    for snap in body["stance_history"]:
        assert snap["headline_read"] == ""


def test_a_third_person_headline_is_served_verbatim(monkeypatch):
    body = _coach_body(monkeypatch, stance=_stance(_PUBLIC_HEADLINE))
    assert body["stance"]["headline_read"] == _PUBLIC_HEADLINE
    assert body["stance_history"][0]["headline_read"] == _PUBLIC_HEADLINE


def test_owner_directed_stance_items_are_dropped_and_public_ones_kept(monkeypatch):
    body = _coach_body(monkeypatch, stance=_stance(_PUBLIC_HEADLINE))
    assert body["stance"]["focused_on_now"] == ["His journal's silence"]
    assert body["stance"]["stage"]["rationale"] == "He is learning to read his own signals."


# ══════════════════════════════════════════════════════════════════════════════
# 2. daily ("today's read")
# ══════════════════════════════════════════════════════════════════════════════


def test_the_live_reeves_daily_read_is_not_served(monkeypatch):
    """RED before #4213: `_coach_daily` returned the artifact's text untouched."""
    body = _coach_body(monkeypatch, daily_text=_REEVES_DAILY)
    assert body["daily"] is None


def test_a_third_person_daily_read_is_served(monkeypatch):
    body = _coach_body(monkeypatch, daily_text=_PUBLIC_DAILY)
    assert body["daily"] == _PUBLIC_DAILY


def test_the_daily_producer_gate_rejects_an_owner_directed_reflection():
    """The write side: the reflection's fail-closed gate treats a second-person text as
    a violation (retried stricter, then dropped) — and the #2889 reuse path re-gates
    through the same function, so a cached second-person reflection never republishes."""
    facts = {"allowed": set(), "allowed_dates": set(), "numbers": [], "n": 21}
    ok, reasons = daily._accepts(_REEVES_DAILY, facts, "2026-09-26")
    assert not ok and "audience_violation" in reasons
    _ok, reasons = daily._accepts(_PUBLIC_DAILY, facts, "2026-09-26")
    assert "audience_violation" not in reasons
    assert "THIRD person" in daily._SYSTEM_RULES


# ══════════════════════════════════════════════════════════════════════════════
# 3. recent_outputs[].summary (the timeline)
# ══════════════════════════════════════════════════════════════════════════════


def test_the_live_key_recommendation_is_not_the_timeline_summary(monkeypatch):
    """RED before #4213: `served_summary` served `key_recommendation` (an imperative
    to Matthew), falling back to `content` (the owner narrative)."""
    body = _coach_body(monkeypatch, outputs=[_output(key_recommendation=_REEVES_KEY_RECOMMENDATION)])
    assert [o["summary"] for o in body["recent_outputs"]] == [""]


def test_the_timeline_serves_the_public_ask_first(monkeypatch):
    row = _output(key_recommendation=_REEVES_KEY_RECOMMENDATION, public_ask=_PUBLIC_ASK, public_summary=_PUBLIC_HEADLINE)
    body = _coach_body(monkeypatch, outputs=[row])
    assert body["recent_outputs"][0]["summary"] == _PUBLIC_ASK


def test_the_timeline_falls_back_to_the_public_read_never_the_owner_text(monkeypatch):
    row = _output(key_recommendation=_REEVES_KEY_RECOMMENDATION, public_ask="Log four words each morning, you know why.")
    row["public_summary"] = _PUBLIC_HEADLINE
    body = _coach_body(monkeypatch, outputs=[row])
    assert body["recent_outputs"][0]["summary"] == _PUBLIC_HEADLINE


# ══════════════════════════════════════════════════════════════════════════════
# 4. dossier.commitments[].text (feeds /api/coaching-dashboard open_actions too)
# ══════════════════════════════════════════════════════════════════════════════


def test_the_live_commitment_imperative_is_not_served(monkeypatch):
    """RED before #4213: the dossier served `commitment_natural` verbatim."""
    body = _coach_body(monkeypatch, commitments=[_commitment()])
    commits = body["dossier"]["commitments"]
    assert len(commits) == 1, "the record itself still counts — only its text is withheld"
    assert commits[0]["text"] == ""
    assert commits[0]["date"] == "2026-09-26" and commits[0]["status"] == "pending"


def test_the_commitment_public_twin_is_served(monkeypatch):
    body = _coach_body(monkeypatch, commitments=[_commitment(public_ask=_PUBLIC_ASK)])
    assert body["dossier"]["commitments"][0]["text"] == _PUBLIC_ASK


# ══════════════════════════════════════════════════════════════════════════════
# 5. The whole page — no served slot addresses the owner
# ══════════════════════════════════════════════════════════════════════════════


def test_no_by_coach_slot_is_owner_directed_with_the_full_live_specimen_set(monkeypatch):
    """The issue's live-proof query, run offline: zero `is_owner_directed` hits across
    the four slots when every producer row is in the owner register."""
    body = _coach_body(
        monkeypatch,
        stance=_stance(_REEVES_HEADLINE),
        outputs=[_output(key_recommendation=_REEVES_KEY_RECOMMENDATION)],
        commitments=[_commitment()],
        daily_text=_REEVES_DAILY,
    )
    slots = [body["stance"]["headline_read"], body["daily"]]
    slots += [o["summary"] for o in body["recent_outputs"]]
    slots += [c["text"] for c in body["dossier"]["commitments"]]
    assert [s for s in slots if audience_guard.is_owner_directed(s)] == []


# ══════════════════════════════════════════════════════════════════════════════
# 6. public_blurb — a SENTENCE-boundary clip, never mid-sentence (§2.3)
# ══════════════════════════════════════════════════════════════════════════════


def test_clip_keeps_whole_sentences_within_the_limit():
    s1 = "Matthew logged food on all 20 days of this attempt."
    s2 = "Friday, September 25 was a good one, with 182 g of protein and 1,761 calories."
    s3 = "I've asked him to add one vegetable serving at lunch this week, because Friday's fiber was low."
    text = f"{s1} {s2} {s3}"
    assert len(f"{s1} {s2}") <= 200 < len(text)
    assert audience_guard.clip_at_sentence(text, 200) == f"{s1} {s2}"


def test_clip_returns_short_text_unchanged_and_empty_for_nothing():
    assert audience_guard.clip_at_sentence("  Matthew slept well on Friday.  ") == "Matthew slept well on Friday."
    assert audience_guard.clip_at_sentence("") == ""
    assert audience_guard.clip_at_sentence(None) == ""


def test_clip_never_cuts_a_long_first_sentence_mid_way():
    first = (
        "Matthew's recovery averaged 74 % over the last 21 days and hit 99 % on the night of Thursday, "
        + "September 24, " * 8
        + "which is the read."
    )
    assert 200 < len(first) <= 320
    clipped = audience_guard.clip_at_sentence(first + " A second sentence follows.", 200)
    assert clipped == first


def test_clip_does_not_split_on_a_decimal_point():
    text = "His HRV was 46.8 ms on the night of Friday, September 25. " * 5
    clipped = audience_guard.clip_at_sentence(text.strip(), 200)
    assert clipped.endswith("September 25.") and "46.8 ms" in clipped


def test_public_blurb_clips_at_a_sentence_boundary():
    s1 = "Matthew logged two training sessions this week, and his recovery held at 60 % on Friday, September 25."
    s2 = "I'm watching his heart-rate variability closely, because the pattern I flagged on Day 3 hasn't moved yet."
    blurb = audience_guard.public_blurb({"public_summary": f"{s1} {s2}"}, limit=200)
    assert blurb == s1


# ══════════════════════════════════════════════════════════════════════════════
# 7. public_ask — the producer plumbing (extraction task 13 + task 11, recondense, writer)
# ══════════════════════════════════════════════════════════════════════════════


def test_public_ask_is_in_the_extraction_contract():
    assert "13. **public_ask**" in EXTRACTION_SYSTEM_PROMPT
    assert "   - public_ask:" in EXTRACTION_SYSTEM_PROMPT, "each commitment carries its own reported twin (task 11)"
    assert "public_ask." in build_extraction_message("mind_coach", "text", "daily_brief", {})


def test_public_ask_joins_the_derived_prose_set_and_the_recondense():
    assert "public_ask" in coach_derived_prose.DERIVED_PROSE_FIELDS
    assert "public_ask" not in coach_derived_prose.SERVED_SUMMARY_PREFERENCE
    assert '"public_ask"' in coach_derived_prose.RECONDENSE_SYSTEM_PROMPT
    assert coach_derived_prose.hold({"public_ask": _PUBLIC_ASK})["public_ask"] is None

    def _model(**kw):
        return {"public_ask": f"  {_PUBLIC_ASK}  ", "public_summary": _PUBLIC_HEADLINE}

    out = coach_derived_prose.recondense("mind_coach", "narrative", {"themes": ["a"]}, "fix it", _model)
    assert out["public_ask"] == _PUBLIC_ASK and out["themes"] == ["a"]


def test_public_ask_reader_seam_rejects_an_imperative_to_matthew():
    assert audience_guard.public_ask({"public_ask": _PUBLIC_ASK}) == _PUBLIC_ASK
    assert audience_guard.public_ask({"public_ask": "Log your mood before you check the app."}) is None
    assert audience_guard.public_ask({"key_recommendation": _PUBLIC_ASK}) is None, "only public_ask is ever read"
    assert audience_guard.public_ask(None) is None


def test_the_writer_persists_public_ask_through_the_guard():
    with open(os.path.join(_REPO, "lambdas", "coach", "coach_state_updater.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert 'audience_guard.reader_safe(extraction.get("public_ask")' in src, "OUTPUT# public_ask is written unguarded"
    assert 'audience_guard.reader_safe(c.get("public_ask")' in src, "COMMITMENT# public_ask is written unguarded"


# ══════════════════════════════════════════════════════════════════════════════
# 8. The stance producer — third person by prompt, guarded at write
# ══════════════════════════════════════════════════════════════════════════════


def test_the_stance_prompt_serves_visitors_in_the_third_person():
    assert "SERVED TO SITE VISITORS" in chs.STANCE_SYSTEM_PROMPT
    assert "Address him as 'you'" not in chs.STANCE_SYSTEM_PROMPT
    assert "my current read of you" not in chs.STANCE_SYSTEM_PROMPT


def test_write_stance_holds_an_owner_directed_headline_empty(monkeypatch):
    written = []
    monkeypatch.setattr(chs, "_put_item", lambda item: written.append(item) or True)
    assert chs._write_stance(_COACH, {"as_of": "2026-09-26", "headline_read": _REEVES_HEADLINE, "stage": {}})
    assert [w["headline_read"] for w in written] == ["", ""]
    written.clear()
    assert chs._write_stance(_COACH, {"as_of": "2026-09-26", "headline_read": _PUBLIC_HEADLINE, "stage": {}})
    assert [w["headline_read"] for w in written] == [_PUBLIC_HEADLINE, _PUBLIC_HEADLINE]


# ══════════════════════════════════════════════════════════════════════════════
# #4217 — a coach with a dark instrument is ABSENT on /api/coach/<id>, /api/coaches
# and in the stance writer. Fixture = the live 2026-09-26 sentinel (cgm dark since
# 2026-08-27); mutation control = the same rows with the checker's verdict flipped.
# ══════════════════════════════════════════════════════════════════════════════

from instrument_presence_fixture import (  # noqa: E402
    ABSENT_REASON,
    GLUCOSE_HEADLINE,
    NOW,
    dispatching_query_hook,
    fresh_instrument_rows,
    glucose_output_row,
    sentinel_item,
)

_GLUCOSE = "glucose_coach"
_GPK = f"COACH#{_GLUCOSE}"


def _glucose_stance():
    return {
        "pk": _GPK,
        "sk": "STANCE#latest",
        "as_of": "2026-09-21",
        "headline_read": GLUCOSE_HEADLINE,
        "focused_on_now": ["Whether the sensor is accumulating usable data"],
        "set_aside_for_now": [],
        "stage": {"label": "Data gate: awaiting synchronization", "rationale": "He has the sensors in place but not the context."},
        "how_my_read_changed": "",
        "confidence_note": "",
    }


def _glucose_table(cgm_dark):
    rows = [
        sentinel_item(cgm_dark=cgm_dark),
        *fresh_instrument_rows(),
        _glucose_stance(),
        dict(_glucose_stance(), sk="STANCE#2026-09-21"),
        glucose_output_row(),
    ]
    return FakeDdbTable(rows=rows, query_hook=dispatching_query_hook)


def _pin_presence_clock(monkeypatch):
    """The SAME derivation the board runs, pinned to the corpus's instant."""
    from health import instrument_presence
    from web import site_api_coach_profile as P

    monkeypatch.setattr(P, "_absent_coaches", lambda _g: instrument_presence.absent_coaches(_g["table"], now=NOW))


def _glucose_body(monkeypatch, cgm_dark):
    monkeypatch.setattr(C, "table", _glucose_table(cgm_dark))
    real_load = C._load_s3_json
    monkeypatch.setattr(C, "_load_s3_json", lambda key, cache_name: {} if key.startswith("generated/") else real_load(key, cache_name))
    _pin_presence_clock(monkeypatch)
    resp = C.handle_coach({"rawPath": f"/api/coach/{_GLUCOSE}"})
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body.get("persona_id") == _GLUCOSE, body
    return body


def test_the_glucose_coach_is_absent_with_the_sensor_dark(monkeypatch):
    """RED before #4217: the handler served the CGM headline as today's stance."""
    body = _glucose_body(monkeypatch, cgm_dark=True)
    assert body["absent"] is True
    assert body["reason"] == ABSENT_REASON
    assert body["instrument"] == {"source": "apple_health", "datatype": "cgm"}
    assert body["stance"] == {"source": "absent", "headline_read": "", "stage": {}}
    assert body["daily"] == ""
    assert "CGM" not in json.dumps({k: body[k] for k in ("stance", "daily", "reason")})


def test_mutation_control_the_glucose_stance_serves_when_the_cgm_is_not_dark(monkeypatch):
    body = _glucose_body(monkeypatch, cgm_dark=False)
    assert body["absent"] is False and body["reason"] is None
    assert body["stance"]["source"] == "stance"
    assert body["stance"]["headline_read"] == GLUCOSE_HEADLINE
    assert body["instrument"] == {"source": "apple_health", "datatype": "cgm"}


def test_history_stays_while_the_coach_is_absent(monkeypatch):
    """Dated records are history, not today's argument — only the live slots go quiet."""
    body = _glucose_body(monkeypatch, cgm_dark=True)
    assert body["stance_history"], "the dated STANCE# history was withheld — that is a record, not a read"
    assert body["recent_outputs"], "the dated OUTPUT# timeline was withheld"


def test_the_roster_serves_the_instrument_map_and_the_absence(monkeypatch):
    """/api/coaches carries {source, datatype} per coach — the renderer reads THIS instead of
    its own table — and the same absence verdict as the profile."""
    from ingestion.source_registry import coach_instruments

    monkeypatch.setattr(C, "table", _glucose_table(cgm_dark=True))
    _pin_presence_clock(monkeypatch)
    body = json.loads(C.handle_coaches({})["body"])
    by_id = {c["persona_id"]: c for c in body["coaches"]}
    assert by_id[_GLUCOSE]["absent"] is True and by_id[_GLUCOSE]["reason"] == ABSENT_REASON
    for cid, row in coach_instruments().items():
        assert by_id[cid]["instrument"] == {"source": row["source"], "datatype": row["datatype"]}, cid
    for cid in ("mind_coach", "explorer_coach", "eli_marsh"):
        assert by_id[cid]["instrument"] is None and by_id[cid]["absent"] is False, cid
    assert sum(1 for c in body["coaches"] if c["absent"]) == 1, "only the coach with the dark sensor is absent"


# ── the stance writer: no STANCE# while the instrument is dark ─────────────────


def _stance_run(monkeypatch, cgm_dark, event=None):
    from health import instrument_presence

    table = _glucose_table(cgm_dark)
    monkeypatch.setattr(chs, "table", table)
    monkeypatch.setattr(chs, "_absent_coaches", lambda: instrument_presence.absent_coaches(table, now=NOW))
    monkeypatch.setattr(chs, "_presence_signal", lambda: None)
    monkeypatch.setattr(
        chs,
        "_gather_coach_state",
        lambda cid: {"outputs": [{"x": 1}], "open_threads": [], "active_predictions": [], "confidence_records": []},
    )
    monkeypatch.setattr(chs, "_compress_coach", lambda cid, state, presence_signal=None: {"summary": "compressed"})
    monkeypatch.setattr(chs, "_write_compressed_state", lambda cid, compressed: True)
    monkeypatch.setattr(chs, "_get_item", lambda pk, sk: {"summary": "compressed history"})
    monkeypatch.setattr(chs, "_query_begins_with", lambda pk, prefix, **kw: [])
    from ai import budget_guard

    monkeypatch.setattr(budget_guard, "allow", lambda feature: True)
    ran = []
    monkeypatch.setattr(chs, "_run_stance", lambda coach_id, *a, **kw: ran.append(coach_id) or {"written": True})
    out = chs.lambda_handler(event or {"coach_ids": [_GLUCOSE, "sleep_coach"]}, None)
    return ran, out


def test_the_weekly_batch_writes_no_glucose_stance_while_the_cgm_is_dark(monkeypatch):
    ran, out = _stance_run(monkeypatch, cgm_dark=True)
    assert ran == ["sleep_coach"], ran
    assert out["results"][_GLUCOSE]["stance"] == {"written": False, "reason": "instrument_dark", "instrument_reason": ABSENT_REASON}
    assert out["results"][_GLUCOSE]["status"] == "success", "compression (his private memory) still runs"


def test_mutation_control_the_weekly_batch_writes_the_glucose_stance_when_not_dark(monkeypatch):
    ran, _out = _stance_run(monkeypatch, cgm_dark=False)
    assert ran == [_GLUCOSE, "sleep_coach"]


def test_an_event_refresh_for_an_absent_coach_is_skipped(monkeypatch):
    ran, out = _stance_run(
        monkeypatch, cgm_dark=True, event={"mode": "event_stance_refresh", "coach_id": _GLUCOSE, "trigger_event": {"type": "refuted"}}
    )
    assert ran == [] and out["skipped"] == "instrument_dark" and out["reason"] == ABSENT_REASON


# ══════════════════════════════════════════════════════════════════════════════
# #4213 live read (2026-09-27 16:07Z) — the LADDER fallback slots. Five of eight
# coaches serve the authored weight-band ladder (no STANCE#latest yet), and the page
# prints its stage headline (`cs-headline`) and graduation gate. The authored configs
# are written TO Matthew: /coaching/by-coach/ showed nutrition's headline "First, I just
# need to see what you eat." and sleep's gate "Hitting your duration target…" — and the
# raw `rung` (sleep's "showing up for sleep the way you show up for the gym") rode the
# payload whole. Fixture = the repo's own stance configs through the real handler.
# ══════════════════════════════════════════════════════════════════════════════


class _NoS3:
    def get_object(self, **kw):  # force coach_stance.load_stance onto the repo config file
        raise RuntimeError("offline")


def _ladder_body(monkeypatch, coach_id):
    from coach import coach_stance

    coach_stance._cache.clear()
    monkeypatch.setattr(C, "table", FakeDdbTable(query_hook=lambda t, **kw: {"Items": []}, get_item_hook=lambda t, k, **kw: {}))
    monkeypatch.setattr(C, "_S3", _NoS3())
    monkeypatch.setattr(C, "_load_s3_json", lambda key, name: {})
    resp = C.handle_coach({"rawPath": f"/api/coach/{coach_id}"})
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body["stance"]["source"] == "ladder", body["stance"]
    return body["stance"]


def _stance_strings(stance):
    for key in ("headline_read", "graduation_gate"):
        yield key, stance.get(key) or ""
    for key in ("label", "rationale"):
        yield f"stage.{key}", (stance.get("stage") or {}).get(key) or ""
    for key in ("focused_on_now", "set_aside_for_now"):
        for v in stance.get(key) or []:
            yield key, v
    for key, v in (stance.get("rung") or {}).items():
        for x in v if isinstance(v, list) else [v]:
            if isinstance(x, str):
                yield f"rung.{key}", x
    for s in stance.get("ladder") or []:
        yield "ladder.headline", s.get("headline") or ""


def test_the_live_nutrition_ladder_headline_is_not_served(monkeypatch):
    """RED before this fix: stage.label == "First, I just need to see what you eat."."""
    st = _ladder_body(monkeypatch, "nutrition_coach")
    assert st["rung"]["stage_id"] == "visibility"  # ids survive the guard
    assert st["stage"]["label"] == ""
    assert all(not audience_guard.is_owner_directed(v) for _, v in _stance_strings(st))


def test_the_live_sleep_graduation_gate_and_rung_are_not_served(monkeypatch):
    """RED before this fix: graduation_gate "Hitting your duration target…" and the raw
    rung's cares_most "…the way you show up for the gym" were both served."""
    st = _ladder_body(monkeypatch, "sleep_coach")
    assert st["graduation_gate"] == ""
    assert st["stage"]["label"] == "Get enough hours, regularly."  # a third-person headline is kept
    assert st["rung"]["stage_id"] == "foundation"
    assert [k for k, v in _stance_strings(st) if audience_guard.is_owner_directed(v)] == []


def test_no_ladder_slot_is_owner_directed_for_any_operational_coach(monkeypatch):
    """The live-proof query over every coach that can fall back to the authored ladder."""
    from coach import persona_registry

    hits, covered = [], []
    for cid in persona_registry.OPERATIONAL_COACH_IDS:
        try:
            st = _ladder_body(monkeypatch, cid)
        except AssertionError:
            continue  # no ladder / absent coach — nothing served from the scaffold
        covered.append(cid)
        hits += [(cid, k, v) for k, v in _stance_strings(st) if audience_guard.is_owner_directed(v)]
    # the four configs that carried owner-directed ladder text (glucose, mind, nutrition, sleep) must be exercised
    assert {"glucose_coach", "mind_coach", "nutrition_coach", "sleep_coach"} <= set(covered), covered
    assert hits == []


def test_an_evidence_stance_label_addressed_to_him_is_blanked(monkeypatch):
    body = _coach_body(monkeypatch, stance=_stance(_PUBLIC_HEADLINE, stage={"label": "This is just who you are now.", "rationale": ""}))
    assert body["stance"]["stage"]["label"] == ""
    assert body["stance_history"][0]["stage"]["label"] == ""
    body = _coach_body(monkeypatch, stance=_stance(_PUBLIC_HEADLINE))
    assert body["stance"]["stage"]["label"] == "noticing"


# ══════════════════════════════════════════════════════════════════════════════
# /api/coach_analysis — the by-coach READ and "the one thing" (#4213), and the absent
# coach on that endpoint (#4217). Found live by the Session AX proof lane at
# 2026-09-28T00:04Z: 16 owner-directed blocks on /coaching/by-coach/ came from this
# endpoint, and the glucose coach (CGM dark) still served its stale "your CGM is
# generating traces" read. The fixture is the WIRE: every domain's served prose slots,
# captured read-only from the live endpoint (tests/fixtures/coach_analysis_live_4213.json).
# ══════════════════════════════════════════════════════════════════════════════

from coach import coach_presence_gate  # noqa: E402
from web import site_api_coach_narrative as N  # noqa: E402

_WIRE = json.load(open(os.path.join(_REPO, "tests", "fixtures", "coach_analysis_live_4213.json")))["domains"]
_PROSE = ("analysis", "key_recommendation", "elena_quote", "journaling_prompt", "thread_reference", "cross_domain_note", "weekly_priority")


def _pin_absence_clock(monkeypatch):
    """`coach_presence_gate.coach_absence` runs the one derivation; pin its clock to the corpus."""
    from health import instrument_presence

    real = instrument_presence.absent_coaches
    monkeypatch.setattr(
        instrument_presence, "absent_coaches", lambda table, now=None, instruments=None: real(table, now=NOW, instruments=instruments)
    )


def _wire_rows(domain, wire):
    """The stored rows the live payload was served from, rebuilt from the wire: the OUTPUT#
    row (`observatory_summary` is what `analysis` serves, `public_summary` the twin), the
    mind coach's EXPERT# journaling prompt, and every instrument fresh (no one absent)."""
    cid = wire["coach_id"]
    out = {"pk": f"COACH#{cid}", "sk": "OUTPUT#2026-09-26#daily_brief", "created_at": wire["generated_at"]}
    for src, dst in (("analysis", "observatory_summary"), ("key_recommendation", "key_recommendation"), ("elena_quote", "elena_quote")):
        if wire.get(src):
            out[dst] = wire[src]
    if wire.get("public_read"):
        out["public_summary"] = wire["public_read"]
    rows = [sentinel_item(cgm_dark=False), *fresh_instrument_rows(), out]
    if wire.get("journaling_prompt"):
        rows.append({"pk": "USER#matthew#SOURCE#ai_analysis", "sk": f"EXPERT#{domain}", "journaling_prompt": wire["journaling_prompt"]})
    return rows


def _analysis_body(monkeypatch, domain, rows, integrator=None):
    monkeypatch.setattr(C, "table", FakeDdbTable(rows=rows, query_hook=dispatching_query_hook))
    monkeypatch.setattr(C, "_integrator_digest", lambda: integrator)
    monkeypatch.setattr(C, "_latest_cycle_digest", lambda: None)
    monkeypatch.setattr(C, "_regeneration_paused", lambda feature: False)
    _pin_absence_clock(monkeypatch)
    resp = C.handle_coach_analysis({"queryStringParameters": {"domain": domain}})
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _wire_hits(monkeypatch):
    hits = []
    for domain, wire in _WIRE.items():
        integ = {"cross_domain_notes": {domain: wire.get("cross_domain_note")}, "analysis": wire.get("weekly_priority")}
        body = _analysis_body(monkeypatch, domain, _wire_rows(domain, wire), integ)
        assert body.get("absent") is not True, f"{domain}: no instrument is dark in this corpus"
        hits += [(domain, k, body[k]) for k in _PROSE if isinstance(body.get(k), str) and audience_guard.is_owner_directed(body[k])]
    return hits


def test_the_live_wire_carries_owner_directed_reads():
    """The corpus is the defect: the live payload DID address Matthew (else the guard test is vacuous)."""
    hits = [(d, k) for d, w in _WIRE.items() for k in _PROSE if isinstance(w.get(k), str) and audience_guard.is_owner_directed(w[k])]
    assert len(hits) >= 10, hits
    assert ("sleep", "analysis") in hits and ("glucose", "key_recommendation") in hits


def test_no_coach_analysis_prose_slot_is_owner_directed_for_any_domain(monkeypatch):
    """RED before #4213's serve seam: 13 slots across 7 domains passed through verbatim."""
    assert _wire_hits(monkeypatch) == []


def test_mutation_control_without_the_reader_register_the_wire_leaks(monkeypatch):
    monkeypatch.setattr(N, "_reader_register", lambda resp, output: None)
    assert len(_wire_hits(monkeypatch)) >= 10


def test_an_owner_directed_read_serves_its_public_twin_or_nothing(monkeypatch):
    g = _WIRE["glucose"]
    body = _analysis_body(monkeypatch, "glucose", _wire_rows("glucose", g))
    assert body["analysis"] == g["public_read"], "the owner read must yield to the stored public twin"
    assert "key_recommendation" not in body, "no public_ask on the row: the one thing is withheld, not served to him"
    s = _WIRE["sleep"]  # no public_summary on the live sleep row → no read at all
    body = _analysis_body(monkeypatch, "sleep", _wire_rows("sleep", s))
    assert "analysis" not in body
    assert body["key_recommendation"] == s["key_recommendation"], "a reader-safe value passes untouched"


def test_the_one_thing_prefers_the_public_ask(monkeypatch):
    rows = _wire_rows("mind", _WIRE["mind"])
    rows[-2]["public_ask"] = _PUBLIC_ASK
    assert _analysis_body(monkeypatch, "mind", rows)["key_recommendation"] == _PUBLIC_ASK


def _absent_glucose_body(monkeypatch, cgm_dark, domain="glucose"):
    live = dict(glucose_output_row(), observatory_summary=_WIRE["glucose"]["analysis"], public_summary=_WIRE["glucose"]["public_read"])
    rows = [sentinel_item(cgm_dark=cgm_dark), *fresh_instrument_rows(), live]
    return _analysis_body(monkeypatch, domain, rows)


def test_the_absent_glucose_coach_serves_no_read_on_coach_analysis(monkeypatch):
    """#4217, RED before: the 09-26 CGM read was served while the CGM was dark."""
    for domain in ("glucose", "metabolic"):  # the cockpit asks by pillar name
        body = _absent_glucose_body(monkeypatch, cgm_dark=True, domain=domain)
        assert body["absent"] is True and body["reason"] == ABSENT_REASON
        assert body["analysis"] is None, "the endpoint's honest-empty shape: analysis null, as for a coach with no read"
        assert "key_recommendation" not in body and "public_read" not in body
        assert "CGM" not in json.dumps(body)


def test_mutation_control_the_glucose_read_serves_when_the_cgm_is_not_dark(monkeypatch):
    body = _absent_glucose_body(monkeypatch, cgm_dark=False)
    assert "absent" not in body
    assert body["analysis"] == _WIRE["glucose"]["public_read"]


def test_a_failed_presence_read_keeps_the_read_fail_open(monkeypatch):
    from health import instrument_presence

    def boom(*a, **k):
        raise RuntimeError("sentinel unreadable")

    monkeypatch.setattr(
        C, "table", FakeDdbTable(rows=[sentinel_item(cgm_dark=True), glucose_output_row()], query_hook=dispatching_query_hook)
    )
    monkeypatch.setattr(instrument_presence, "absent_coaches", boom)
    assert coach_presence_gate.coach_absence("glucose_coach", N.logger, "[t]", table=C.table) is None


# ── the daily-brief coach loop: an absent coach is not asked (#4217) ──────────────


def _brief_run(monkeypatch, cgm_dark):
    import boto3
    from ai import ai_calls

    table = FakeDdbTable(rows=[sentinel_item(cgm_dark=cgm_dark), *fresh_instrument_rows()], query_hook=dispatching_query_hook)
    clients = []

    class _Res:
        def Table(self, name):
            return table

    def _client(name, **kw):
        clients.append(name)
        raise RuntimeError("the pipeline went past the absence gate")  # → caught, returns None

    monkeypatch.setattr(boto3, "resource", lambda *a, **k: _Res())
    monkeypatch.setattr(boto3, "client", _client)
    monkeypatch.setattr(ai_calls.boto3, "client", _client)
    _pin_absence_clock(monkeypatch)
    return ai_calls._run_coach_v2_pipeline("glucose_coach", {}, "glucose", {}, ""), clients, ai_calls


def test_the_brief_does_not_ask_an_absent_coach(monkeypatch, capsys):
    """RED before: 09-27 17:07Z `[COACH-V2:glucose_coach] Output: 2647 chars` with the CGM dark."""
    out, clients, ai_calls = _brief_run(monkeypatch, cgm_dark=True)
    assert isinstance(out, ai_calls.CoachHold) and out.reason == "instrument_absent"
    assert clients == [], "the computation engine / orchestrator was invoked for an absent coach"
    assert "skipped_absent" in capsys.readouterr().out


def test_mutation_control_the_brief_asks_the_glucose_coach_when_the_cgm_is_live(monkeypatch):
    out, clients, ai_calls = _brief_run(monkeypatch, cgm_dark=False)
    assert not isinstance(out, ai_calls.CoachHold)
    assert clients, "the pipeline never started for a present coach"
