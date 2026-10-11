"""tests/test_owner_words_tuesday_4584.py — the Tuesday question, its reply on the edition, and the first-person guard
(#4584, epic #4580).

Acceptance boxes this file pins (the fourth, one real reply on the live page, is the owner's live proof):

  BOX 1  "The question arrives Tuesday evening PT"
         * the ``OwnerWordsQuestionTuesday`` rule fires at a fixed-UTC instant that is Tuesday evening Pacific in
           BOTH halves of the year (PDT and PST), targets wednesday-chronicle with ``{"tuesday_question": true}``;
         * the sender sends ONE fixed question (no model call) with the desk's ``[SQ-W<n>]`` token and Reply-To the
           inbound address, once per week (marker), and a dry run sends nothing.

  BOX 2  "A clean reply appears verbatim within an hour; a filter hit holds it (fixture + mutation)"
         * end to end through ``insight-email-parser`` → owner-words store → ``GET /api/owner_words`` →
           ``/api/edition``'s ``his_words``: a top-posted reply is served BYTE FOR BYTE with the Tuesday question;
         * a reply carrying a vocabulary hit is stored HELD and the edition reads as silence; the mutation (filter
           forced clean) serves it, so the hold is the filter's doing;
         * an unauthenticated From stores nothing (the reply route stays behind #4633's verdict);
         * "within an hour": the pickup is event-driven (SES receipt → S3 → Lambda, no schedule) and the two served
           caches stacked are well under 3600 s.

  BOX 3  "No changing first-person text on the site lacks a stored source"
         * every first-person string ``compose()`` emits — over the live wire and every upstream failing in turn —
           is carried verbatim from an upstream body, and his-voice text is carried from a STORED owner source
           (an owner-words entry or a decisions note), never composed;
         * no string literal in the edition's modules is first person (a template could not fill it with data);
         * the mutation: a compose that fabricates "I walked …" is caught by the same check.

Every vocabulary term is the suite's NEUTRAL fixture (tests/conftest.py, #2370).
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "lambdas", "emails"), os.path.dirname(__file__)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import test_edition_page_contract_4582 as edc  # noqa: E402
import test_owner_words_4584 as base  # noqa: E402
from content import (
    owner_words as ow,  # noqa: E402
    story_questions as sq,  # noqa: E402
)
from web import site_api_edition as ed  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")
EMAIL_STACK = os.path.join(ROOT, "cdk", "stacks", "email_stack.py")
RULE_ID = "OwnerWordsQuestionTuesday"

# ── BOX 1: the rule's clock ──────────────────────────────────────────────────────────────────────────────────────


def _rules(tree, rule_id):
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", None) == "Rule"
        and len(n.args) > 1
        and isinstance(n.args[1], ast.Constant)
        and n.args[1].value == rule_id
    ]


def _cron_of(rule):
    sched = next(kw.value for kw in rule.keywords if kw.arg == "schedule")
    assert getattr(sched.func, "attr", None) == "cron", "the Tuesday rule is no longer a Schedule.cron(...)"
    return {kw.arg: kw.value.value for kw in sched.keywords}


_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _fires_in_pt(cron, utc_week_of):
    """The Pacific weekday + hour of the cron's instant in the UTC week containing ``utc_week_of`` (a Monday)."""
    day = _DAYS.index(cron["week_day"])
    instant = datetime(
        utc_week_of.year, utc_week_of.month, utc_week_of.day + day, int(cron["hour"]), int(cron["minute"]), tzinfo=timezone.utc
    )
    local = instant.astimezone(PT)
    return _DAYS[local.weekday()], local.hour


def test_the_tuesday_rule_fires_tuesday_evening_pacific_in_both_halves_of_the_year():
    tree = ast.parse(open(EMAIL_STACK, encoding="utf-8").read())
    rules = _rules(tree, RULE_ID)
    assert len(rules) == 1, f"expected exactly one {RULE_ID} rule in email_stack.py, found {len(rules)}"
    cron = _cron_of(rules[0])
    summer = _fires_in_pt(cron, datetime(2026, 10, 12))  # PDT
    winter = _fires_in_pt(cron, datetime(2026, 11, 9))  # PST
    for label, (weekday, hour) in (("PDT", summer), ("PST", winter)):
        assert weekday == "TUE" and 17 <= hour <= 21, f"{RULE_ID} lands {weekday} {hour}:00 Pacific ({label}) — not Tuesday evening"
    assert summer == ("TUE", 18), "the stated clock is Tuesday 18:00 PDT"


def test_the_tuesday_rule_targets_the_chronicle_sender_with_its_own_payload():
    src = open(EMAIL_STACK, encoding="utf-8").read()
    tree = ast.parse(src)
    payloads = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "tuesday_question" for k in n.keys)
    ]
    assert len(payloads) == 1, "the rule no longer sends the {tuesday_question: true} event the sender keys on"
    seg = src[src.index(f'"{RULE_ID}"') :]
    assert "targets.LambdaFunction(wednesday_chronicle" in seg.split("create_platform_lambda(")[0]
    # The comment the triage required: the UTC cron and the DST caveat are stated beside the rule.
    head = src[: src.index(f'"{RULE_ID}"')]
    comment = head[head.rindex("# #4584") :]
    assert "cron(0 1 ? * WED *)" in comment and "PDT" in comment and "PST" in comment


def test_the_tuesday_question_is_fixed_rotates_and_passes_the_desks_own_screens():
    seen = [sq.tuesday_question(w) for w in range(1, len(sq.TUESDAY_QUESTIONS) + 1)]
    assert seen == list(sq.TUESDAY_QUESTIONS) and sq.tuesday_question(1) == sq.tuesday_question(1 + len(sq.TUESDAY_QUESTIONS))
    assert sq.tuesday_question(5) != sq.tuesday_question(6), "two weeks running never ask the same thing"
    for q in sq.TUESDAY_QUESTIONS:
        assert not sq._forbidden(q) and not sq._ABSOLUTE.search(q), q
        verdict, kinds = ow.screen(q, vocabulary=base.NEUTRAL_VOCAB)
        assert verdict == ow.VERDICT_CLEAN, (q, kinds)  # it is served beside his reply as its prompt


def test_the_tuesday_email_routes_through_the_desk_and_states_what_happens_to_a_reply():
    e = sq.render_tuesday_email(6, sq.tuesday_question(6))
    assert sq.week_from_subject(e["subject"]) == 6, "the reply must take the desk's ONE authenticated route"
    assert e["body"].count("\nQ") + e["body"].startswith("Q") == 1 and f"Q1: {sq.tuesday_question(6)}" in e["body"]
    for told in ("word for word", "privacy filter holds", '"off record"', "No reply is fine"):
        assert told in e["body"], told


class _SES:
    def __init__(self):
        self.sent = []

    def send_email(self, **kw):
        self.sent.append(kw)
        return {"MessageId": f"m{len(self.sent)}"}


def test_the_sender_sends_one_question_once_per_week_and_never_calls_a_model(monkeypatch):
    import wednesday_chronicle_lambda as wc
    from ai import bedrock_client

    def no_model(*a, **kw):
        raise AssertionError("the Tuesday question must never call a model")

    monkeypatch.setattr(bedrock_client, "invoke_with_retry", no_model)
    monkeypatch.setattr(bedrock_client, "invoke", no_model, raising=False)
    t, ses = base.FakeTable(), _SES()
    monkeypatch.setattr(wc, "table", t)
    monkeypatch.setattr(wc, "ses", ses)
    monkeypatch.setattr("common.pacific_time.pacific_today", lambda: "2026-10-13")  # a Tuesday, week 6
    monkeypatch.setattr("experiment.phase_taxonomy.experiment_stamp_for", lambda pk, sk: {})

    dry = json.loads(wc.lambda_handler({"tuesday_question": True, "dry_run": True}, None)["body"])
    assert dry["status"] == "dry_run" and dry["week"] == 6 and not ses.sent and not t.puts

    sent = json.loads(wc.lambda_handler({"tuesday_question": True}, None)["body"])
    assert sent == {"status": "sent", "week": 6, "questions": 1}
    assert len(ses.sent) == 1 and ses.sent[0]["ReplyToAddresses"] == [sq.REPLY_TO]
    assert "[SQ-W6]" in ses.sent[0]["Content"]["Simple"]["Subject"]["Data"]
    marker = t.items[("USER#matthew#SOURCE#chronicle", "STORYQ#W006#TUE")]
    assert json.loads(marker["questions_json"]) == [sq.tuesday_question(6)]

    again = json.loads(wc.lambda_handler({"tuesday_question": True}, None)["body"])
    assert again["status"] == "already_sent" and len(ses.sent) == 1
    # Monday's dead-man matches its marker EXACTLY, so Tuesday's never stands in for a missed Monday send.
    assert ("USER#matthew#SOURCE#chronicle", "STORYQ#W006") not in t.items


# ── BOX 2: the reply, verbatim, on the edition ───────────────────────────────────────────────────────────────────

QUESTION = sq.tuesday_question(6)
# How a phone answers a one-question email: typed ABOVE the quote, no "Q1:" label, the client's own lines after it.
REPLY_CLEAN = "honestly?  the week went better than the numbers say,,\n\nslept badly tues but kept walking"
REPLY_HELD = "Skipped the fizzlewick all week and it was hard."


def _top_posted(reply, signature="Sent from my iPhone\n\n"):
    return (
        f"{reply}\n\n{signature}"
        "On Tue, Oct 13, 2026 at 6:00 PM The Measured Life <\nlifeplatform@example.invalid> wrote:\n\n"
        f"> One question for Wednesday, Week 6.\n>\n> Q1: {QUESTION}\n>\n> —\n> Your reply goes on the site word for word.\n"
    )


def _wire_email(body, *, authenticated=True):
    auth = (
        "Authentication-Results: amazonses.com; spf=pass smtp.mailfrom=example.invalid; dkim=pass header.i=@example.invalid;"
        " dmarc=pass header.from=example.invalid;\r\n"
        if authenticated
        else ""
    )
    return (
        auth + "From: Matthew <matthew@example.invalid>\r\n"
        "To: insight@aws.example.invalid\r\n"
        "Subject: Re: The Measured Life · Week 6 · one question for Wednesday [SQ-W6]\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body.replace("\n", "\r\n")
    ).encode("utf-8")


def _deliver(monkeypatch, raw_bytes):
    from emails import insight_email_parser_lambda as iep

    class S3:
        def get_object(self, **kw):
            return {"Body": io.BytesIO(raw_bytes)}

        def put_object(self, **kw):
            pass

    class CW:
        def put_metric_data(self, **kw):
            pass

    t = base.FakeTable()
    monkeypatch.setattr(iep, "table", t)
    monkeypatch.setattr(iep, "s3", S3())
    monkeypatch.setattr(iep, "cloudwatch", CW())
    monkeypatch.setattr(iep, "ALLOWED_SENDERS", {"matthew@example.invalid"})
    monkeypatch.setattr(iep, "experiment_stamp_for", lambda pk, sk: {})
    resp = iep.lambda_handler({"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "raw/inbound_email/tue1"}}}]}, None)
    assert resp["statusCode"] == 200
    return t


def _edition_his_words(table):
    """The stored rows → the real route → the real compose(), with every other upstream from the live wire."""
    from web import site_api_thirdwall as tw

    g = {"table": table, "_error": lambda c, m: {"statusCode": c, "body": "{}"}, "_public_decision_note": tw._public_decision_note}
    route = tw.handle_owner_words({}, _g=g)
    body = ed.body_of(route)
    assert body is not None, route
    rows = ow.recent(table)
    today = max([str(r["date"]) for r in rows] or [edc.CAPTURE_DAY])
    wire = {**edc._wire(), "owner_words": body, "decisions": {"decisions": []}}
    doc = ed.compose(
        wire,
        today=today,
        now=datetime.now(timezone.utc),
        start_date=edc.START_DATE,
        persona_of=edc._personas.resolve,
        persona_of_short=lambda sid: edc._personas.by_short_id(sid)[1],
        metric_words=edc._metric_words,
    )
    return route, doc["blocks"]["his_words"]


def test_a_one_question_top_post_pairs_with_q1_and_keeps_his_lines_exactly():
    a = sq.parse_reply(_top_posted(REPLY_CLEAN), keep_raw=True)
    assert [(x["q"], x["question"]) for x in a] == [(1, QUESTION)]
    assert a[0]["raw"] == REPLY_CLEAN, "his lines as typed — the signature and the wrapped attribution are not his"
    # Without a signature line the client's WRAPPED attribution ("On Tue, … <" / "…> wrote:") is the only end
    # marker, and it never matches the one-line header pattern whole.
    bare = sq.parse_reply(_top_posted(REPLY_CLEAN, signature=""), keep_raw=True)
    assert [x["raw"] for x in bare] == [REPLY_CLEAN]
    for sig in ("--\nMatt\n\n", "Get Outlook for iOS\n\n", "________________________________\nFrom: Matthew <m@example.invalid>\n"):
        assert [x["raw"] for x in sq.parse_reply(_top_posted(REPLY_CLEAN, signature=sig), keep_raw=True)] == [REPLY_CLEAN], sig


def test_mutation_several_questions_keep_an_unlabelled_top_post_unpaired():
    """Monday's multi-question behaviour is unchanged: with more than one question, a top-post with no labels cannot
    be paired, and pairing it with Q1 anyway would put words under a question he did not answer."""
    body = "Felt fine.\n\nOn Mon, Oct 12, 2026 at 9:00 AM wrote:\n> Q1: first?\n> Q2: second?\n"
    assert sq.parse_reply(body) == []
    assert [x["q"] for x in sq.parse_reply(body.replace("> Q2: second?\n", ""))] == [1]


def test_a_clean_tuesday_reply_leads_the_edition_byte_for_byte_with_its_question(monkeypatch):
    t = _deliver(monkeypatch, _wire_email(_top_posted(REPLY_CLEAN)))
    qa = [r for (pk, sk), r in t.items.items() if sk.startswith(sq.QA_SK_PREFIX)]
    assert len(qa) == 1, "the chronicle's STORYQA row for the week is written too"
    _route, his = _edition_his_words(t)
    assert his["state"] == "ok" and his["source"] == ed.SOURCES["owner_words"]
    assert his["data"]["text"] == REPLY_CLEAN and his["data"]["prompt"] == QUESTION and his["data"]["channel"] == "email"


def test_a_filter_hit_is_stored_held_and_the_edition_reads_as_silence(monkeypatch):
    t = _deliver(monkeypatch, _wire_email(_top_posted(REPLY_HELD)))
    words = [r for (pk, sk), r in t.items.items() if pk == ow.PK]
    assert len(words) == 1 and words[0]["text"] == REPLY_HELD and words[0]["verdict"] == ow.VERDICT_HELD
    route, his = _edition_his_words(t)
    assert "fizzlewick" not in route["body"].lower() and "fizzlewick" not in json.dumps(his).lower()
    assert his["state"] == "absent" and his["data"] is None and his["absent_text"] == ow.SILENCE_SENTENCE


def test_mutation_a_filter_forced_clean_would_put_the_held_reply_on_the_edition(monkeypatch):
    """Negative control: the same delivery with the screen mutated to always pass serves the held fixture, so the
    test above is the filter's doing. (The serve-time verbatim rule is neutralised too — it is the second screen.)"""
    monkeypatch.setattr(ow, "screen", lambda text, **kw: (ow.VERDICT_CLEAN, []))
    t = _deliver(monkeypatch, _wire_email(_top_posted(REPLY_HELD)))
    from web import site_api_thirdwall as tw

    monkeypatch.setattr(tw, "_public_decision_note", lambda text: text)
    _route, his = _edition_his_words(t)
    assert his["state"] == "ok" and his["data"]["text"] == REPLY_HELD


def test_an_unauthenticated_reply_stores_nothing(monkeypatch):
    t = _deliver(monkeypatch, _wire_email(_top_posted(REPLY_CLEAN), authenticated=False))
    assert not [k for k in t.items if k[0] == ow.PK] and not [k for k in t.items if k[1].startswith(sq.QA_SK_PREFIX)]


def test_within_an_hour_the_pickup_is_event_driven_and_the_served_caches_stack_well_under_it():
    from emails import insight_email_parser_lambda as iep
    from web import site_api_thirdwall as tw

    assert iep.SES_EXEMPT_EVENT_DRIVEN, "the parser runs on SES receipt, not on a schedule"
    ops = open(os.path.join(ROOT, "cdk", "stacks", "operational_stack.py"), encoding="utf-8").read()
    block = ops[ops.index('function_name="insight-email-parser"') :][:1500]
    assert "schedule=" not in block.split("create_platform_lambda(")[0], "a polled parser would add its interval to the wait"
    t = base._store(base.FakeTable(), base._entry(base.CLEAN))
    g = {"table": t, "_error": lambda c, m: None, "_public_decision_note": tw._public_decision_note}
    headers = tw.handle_owner_words({}, _g=g).get("headers") or {}
    max_age = int(re.search(r"max-age=(\d+)", headers.get("Cache-Control", "")).group(1))
    assert max_age + ed.CACHE_SECONDS <= 3600 // 2, f"owner_words {max_age}s + edition {ed.CACHE_SECONDS}s"


# ── BOX 3: no changing first-person text without a stored source ─────────────────────────────────────────────────

_FIRST_PERSON = re.compile(r"(?<!Part )\b(?:I|I'm|I've|I'd|I'll|me|my|mine|myself)\b", re.IGNORECASE)
EDITION_MODULES = ("lambdas/web/site_api_edition.py", "lambdas/web/edition_scorecard.py", "lambdas/web/edition_page_reads.py")


def _strings(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, path + (str(i),))
    elif isinstance(obj, str):
        yield ".".join(path), obj


def _owner_sources(bodies):
    """His STORED words in the inputs: owner-words entries and the decisions notes."""
    out = [e.get("text") for e in ((bodies.get("owner_words") or {}).get("entries") or [])]
    out += [d.get("note") for d in ((bodies.get("decisions") or {}).get("decisions") or [])]
    return [s for s in out if isinstance(s, str) and s.strip()]


def unsourced_first_person(doc, bodies):
    """Every first-person string in an edition that no upstream body carries verbatim, plus every his-voice text
    not carried from a stored owner source. Empty = the guard holds."""
    upstream = [s for _p, s in _strings({k: v for k, v in bodies.items() if v is not None})]
    owner = _owner_sources(bodies)
    bad = []
    for path, s in _strings(doc):
        if _FIRST_PERSON.search(s) and not any(s.strip() and s.strip() in u for u in upstream):
            bad.append((path, s))
    his = (doc.get("blocks") or {}).get("his_words") or {}
    text = (his.get("data") or {}).get("text")
    if text is not None and not any(text.strip() and text.strip() in o for o in owner):
        bad.append(("blocks.his_words.data.text", text))
    return bad


def _cases():
    wire = edc._wire()
    fresh = {
        "state": "ok",
        "entries": [{"text": REPLY_CLEAN, "date": "2026-10-03", "date_text": "October 3", "channel": "email", "prompt": QUESTION}],
        "count": 1,
        "sentence": None,
    }
    yield "wire", wire
    yield "fresh-owner-words", {**wire, "owner_words": fresh}
    yield "all-failed", {k: None for k in ed.SOURCES}
    for key in ed.SOURCES:
        yield f"{key}-failed", {**wire, key: None}


def test_every_first_person_string_on_the_edition_is_carried_from_a_stored_source():
    offenders = {}
    for name, bodies in _cases():
        bad = unsourced_first_person(edc._compose(bodies), bodies)
        if bad:
            offenders[name] = bad
    assert not offenders, offenders


def test_the_wire_does_exercise_the_guard():
    """Vacuity control: the wire edition carries first-person text (his decisions note) for the check to inspect."""
    doc = edc._compose(edc._wire())
    assert any(_FIRST_PERSON.search(s) for _p, s in _strings(doc))


def test_no_literal_in_the_edition_modules_is_first_person():
    """A first-person template in compose() is changing first-person text with no stored source the moment data
    fills it. Docstrings are prose about the code, not served text."""
    offenders = []
    for rel in EDITION_MODULES:
        tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings and _FIRST_PERSON.search(n.value):
                offenders.append(f"{rel}:{n.lineno}: {n.value[:80]!r}")
    assert not offenders, offenders


def test_mutation_a_composed_first_person_line_is_caught(monkeypatch):
    """Negative control: a compose that fills his words from a template ("I walked …") — and one that dresses a
    coach line as his — both fail the same check the real compose passes."""
    wire = edc._wire()
    real = ed._his_words

    def templated(decisions, owner_words, today):
        block = real(decisions, owner_words, today)
        return {**block, "state": "ok", "data": {**(block.get("data") or {}), "text": "I walked 9 miles today and I feel great."}}

    monkeypatch.setattr(ed, "_his_words", templated)
    bad = unsourced_first_person(edc._compose(wire), wire)
    assert ("blocks.his_words.data.text", "I walked 9 miles today and I feel great.") in bad

    monkeypatch.setattr(ed, "_his_words", lambda d, o, t: {**real(d, o, t), "data": {"text": "Steady week."}})
    bad = unsourced_first_person(edc._compose(wire), wire)
    assert ("blocks.his_words.data.text", "Steady week.") in bad, "his voice must come from HIS stored words"
