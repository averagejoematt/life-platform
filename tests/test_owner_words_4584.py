"""tests/test_owner_words_4584.py — his own words: one store, two inlets, one outlet (#4584, epic #4580).

What is pinned here:
  * the store — the text is kept EXACTLY as given (whitespace, punctuation, casing), with the Pacific date, the
    received-at instant, the channel, the optional prompt and the verdict; a replay writes nothing twice;
  * the filter — a vocabulary hit, a display name, PII, the off-record marker or flag, tool-call residue, an
    over-long entry and an unloadable vocabulary each HOLD; the hold names a kind, never the term;
  * the serve — newest first, at most SERVE_LIMIT entries, the stored text untouched; a held entry is
    indistinguishable from silence; a vocabulary grown since the write still applies; a failed read is never
    silence (the route answers 503);
  * the mutations — the filter replaced by always-clean SERVES the held fixture, and replaced by always-hold
    WITHHOLDS the clean one, so both paths are load-bearing;
  * inlet A — ``log_owner_note`` is registered, classified as a write, declares its replay semantics, stores
    verbatim and answers in plain words without echoing the vocabulary;
  * inlet B — a Story Desk reply writes one entry per ANSWERED question (none for an unanswered one), with the
    question as the prompt and the answer as typed, and the chronicle's ``STORYQA#`` row is unchanged;
  * nothing here can generate words in his voice: neither module imports a model client.

Every vocabulary term below is the suite's NEUTRAL fixture (tests/conftest.py, #2370) — never a real category.
"""

from __future__ import annotations

import ast
import io
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

from content import (
    owner_words as ow,  # noqa: E402
    story_questions as sq,  # noqa: E402
)

NEUTRAL_VOCAB = {"blocked_vices": ["No fizzlewick", "No grumbleflax"], "blocked_vice_keywords": ["fizzlewick", "grumbleflax", "zzq"]}

CLEAN = "Honestly the second walk was easier than I expected, and I slept like a rock."
HELD_VOCAB = "Skipped the fizzlewick all week and it was hard."
WEIRD = "  lowercase, no fixes,,  and two  spaces —  ALSO caps!!\n\nsecond line…  "


class ConditionalCheckFailedException(Exception):
    pass


def _key_conditions(expr):
    pk, pfx = None, ""
    stack = [expr]
    while stack:
        e = stack.pop().get_expression()
        if e["operator"] == "AND":
            stack.extend(e["values"])
        elif e["operator"] == "=":
            pk = e["values"][1]
        elif e["operator"] == "begins_with":
            pfx = e["values"][1]
    return pk, pfx


class FakeTable:
    def __init__(self, items=None):
        self.items = {(i["pk"], i["sk"]): dict(i) for i in (items or [])}
        self.puts = []

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None, **_):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.items:
            raise ConditionalCheckFailedException()
        self.items[key] = dict(Item)
        self.puts.append(dict(Item))
        return {}

    def query(self, KeyConditionExpression, ScanIndexForward=True, Limit=None, **_):
        pk, pfx = _key_conditions(KeyConditionExpression)
        rows = sorted((v for (p, s), v in self.items.items() if p == pk and s.startswith(pfx)), key=lambda r: r["sk"])
        if not ScanIndexForward:
            rows.reverse()
        return {"Items": [dict(r) for r in (rows[:Limit] if Limit else rows)]}


def _entry(text, day="2026-10-02", at="2026-10-02T18:00:00Z", **kw):
    return ow.make_entry(text, channel=kw.pop("channel", ow.CHANNEL_CHAT), day=day, received_at=at, vocabulary=NEUTRAL_VOCAB, **kw)


def _store(table, *entries):
    for e in entries:
        ow.record(table, e)
    return table


# ── the store ─────────────────────────────────────────────────────────────────


def test_an_entry_is_stored_byte_for_byte_with_its_date_instant_channel_prompt_and_verdict():
    t = FakeTable()
    stored, created = ow.record(t, _entry(WEIRD, prompt="How did the week feel?"))
    row = t.items[(ow.PK, stored["sk"])]
    assert created and row["text"] == WEIRD, "no trim, no copyedit, no case change"
    assert row["date"] == "2026-10-02" and row["received_at"] == "2026-10-02T18:00:00Z"
    assert row["channel"] == "chat" and row["prompt"] == "How did the week feel?"
    assert row["verdict"] == ow.VERDICT_CLEAN and row["hold_kinds"] == [] and row["off_record"] is False
    assert row["sk"].startswith("WORDS#2026-10-02#")


def test_a_replay_writes_nothing_twice_and_returns_the_stored_entry():
    t = FakeTable()
    first, created = ow.record(t, _entry(CLEAN))
    again, created_again = ow.record(t, _entry(CLEAN, at="2026-10-02T18:05:00Z"))
    assert created and not created_again and len(t.puts) == 1 and again["received_at"] == first["received_at"]
    other, created_other = ow.record(t, _entry(CLEAN, prompt="A different question?"))
    assert created_other and other["sk"] != first["sk"], "the same words under a different prompt are a different entry"


def test_an_entry_needs_words_and_a_known_channel():
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            ow.make_entry(bad, channel="chat", day="2026-10-02", received_at="x")
    with pytest.raises(ValueError):
        ow.make_entry("hi", channel="telegram", day="2026-10-02", received_at="x")


# ── the filter ────────────────────────────────────────────────────────────────

HITS = [
    (HELD_VOCAB, "vice"),
    ("I said No Grumbleflax, mostly", "vice"),
    ("call me on 206-555-0142 about it", "pii"),
    ("off record: the knee is worse than I let on", ow.HOLD_OFF_RECORD),
    ("OTR the knee is worse", ow.HOLD_OFF_RECORD),
    ("fine week</parameter>", ow.HOLD_RESIDUE),
    ("x" * (ow.MAX_CHARS + 1), ow.HOLD_TOO_LONG),
]


def test_every_filter_hit_holds_and_names_a_kind_never_the_term():
    misses = []
    for text, kind in HITS:
        verdict, kinds = ow.screen(text)
        if verdict != ow.VERDICT_HELD or kind not in kinds or any("fizzlewick" in k or "grumbleflax" in k for k in kinds):
            misses.append((text[:40], verdict, kinds))
    assert not misses, f"a hit that did not hold (or a hold kind that names the term): {misses}"


def test_a_clean_entry_passes_and_the_off_record_flag_holds_it():
    assert ow.screen(CLEAN) == (ow.VERDICT_CLEAN, [])
    assert ow.screen(CLEAN, off_record=True) == (ow.VERDICT_HELD, [ow.HOLD_OFF_RECORD])


def test_a_held_prompt_holds_the_entry_it_sits_beside():
    e = _entry(CLEAN, prompt="Did the fizzlewick come up?")
    assert e["verdict"] == ow.VERDICT_HELD and "vice" in e["hold_kinds"]


def test_an_unavailable_vocabulary_holds(monkeypatch):
    from privacy import content_filter_channel, privacy_guard

    monkeypatch.delenv("CONTENT_FILTER_JSON", raising=False)
    monkeypatch.setattr(content_filter_channel, "_from_local_file", lambda: None)
    monkeypatch.setattr(content_filter_channel, "_from_s3_boto", lambda b: None)
    monkeypatch.setattr(content_filter_channel, "_from_s3_cli", lambda b: None)
    content_filter_channel.reset_cache()
    privacy_guard.reset_vocabulary_cache()
    try:
        assert ow.screen(CLEAN) == (ow.VERDICT_HELD, [ow.HOLD_FILTER_UNAVAILABLE])
        e = ow.make_entry(CLEAN, channel="email", day="2026-10-02", received_at="2026-10-02T18:00:00Z")
        assert e["verdict"] == ow.VERDICT_HELD and ow.verdict_in_words(e) == ow.SAID_UNAVAILABLE
    finally:
        content_filter_channel.reset_cache()
        privacy_guard.reset_vocabulary_cache()


def test_the_verdict_in_words_never_echoes_the_vocabulary():
    for text in (HELD_VOCAB, "I said No Grumbleflax, mostly", CLEAN):
        said = ow.verdict_in_words(_entry(text))
        assert "fizzlewick" not in said.lower() and "grumbleflax" not in said.lower()
    assert ow.verdict_in_words(_entry(CLEAN)) == ow.SAID_PUBLISHED
    assert ow.verdict_in_words(_entry(HELD_VOCAB)) == ow.SAID_HELD
    assert ow.verdict_in_words(_entry(CLEAN, off_record=True)) == ow.SAID_OFF_RECORD


# ── the serve ─────────────────────────────────────────────────────────────────


def test_clean_entries_are_served_newest_first_word_for_word_with_date_channel_and_prompt():
    t = _store(
        FakeTable(),
        _entry("first", day="2026-09-30", at="2026-09-30T18:00:00Z"),
        _entry(WEIRD, day="2026-10-02", at="2026-10-02T18:00:00Z", prompt="How did the week feel?"),
        _entry("same day, later", day="2026-10-02", at="2026-10-02T20:00:00Z", channel="email"),
    )
    view = ow.public_view(ow.recent(t), vocabulary=NEUTRAL_VOCAB)
    assert view["state"] == ow.STATE_OK and view["sentence"] is None and view["count"] == 3
    assert [e["text"] for e in view["entries"]] == ["same day, later", WEIRD, "first"]
    second = view["entries"][1]
    assert second == {
        "text": WEIRD,
        "date": "2026-10-02",
        "date_text": "Friday, October 2",
        "channel": "chat",
        "prompt": "How did the week feel?",
    }
    assert set(json.dumps(view)) and "verdict" not in json.dumps(view) and "received_at" not in json.dumps(view)


def test_at_most_serve_limit_entries_are_served():
    entries = [_entry(f"note {i}", day=f"2026-09-{10 + i:02d}", at=f"2026-09-{10 + i:02d}T18:00:00Z") for i in range(ow.SERVE_LIMIT + 3)]
    view = ow.public_view(ow.recent(_store(FakeTable(), *entries)), vocabulary=NEUTRAL_VOCAB)
    assert view["count"] == ow.SERVE_LIMIT and view["entries"][0]["text"] == f"note {ow.SERVE_LIMIT + 2}"


def test_silence_is_a_plain_sentence_never_generated_text():
    view = ow.public_view([])
    assert view == {"state": ow.STATE_ABSENT, "entries": [], "count": 0, "sentence": ow.SILENCE_SENTENCE}


def test_a_held_or_off_record_entry_reads_exactly_like_silence_and_never_leaks():
    for held in (_entry(HELD_VOCAB), _entry(CLEAN, off_record=True), _entry("off the record: knee is bad")):
        view = ow.public_view(ow.recent(_store(FakeTable(), held)), vocabulary=NEUTRAL_VOCAB)
        assert view == ow.public_view([]), "the public payload must not reveal that words were held"
        assert "fizzlewick" not in json.dumps(view).lower() and "knee" not in json.dumps(view)


def test_the_serve_screens_again_so_a_grown_vocabulary_still_applies():
    stored_clean = _entry("The plorptangle was the hard part.")
    assert stored_clean["verdict"] == ow.VERDICT_CLEAN
    grown = {"blocked_vices": [], "blocked_vice_keywords": ["fizzlewick", "plorptangle"]}
    assert ow.public_view([stored_clean], vocabulary=grown)["state"] == ow.STATE_ABSENT


def test_a_failed_read_is_never_shown_as_silence():
    class Boom:
        def query(self, **kw):
            raise RuntimeError("throttled")

    assert ow.read_public(Boom())["state"] == ow.STATE_READ_FAILED


def test_the_route_serves_the_stored_text_untouched_and_503s_a_failed_read(monkeypatch):
    from web import site_api_thirdwall as tw

    monkeypatch.setattr(tw, "_ok", lambda body, cache_seconds=300: {"statusCode": 200, "body": json.dumps(body)})

    def _error(code, msg):
        return {"statusCode": code, "body": json.dumps({"error": msg})}

    t = _store(FakeTable(), _entry(WEIRD, prompt="How did the week feel?"), _entry(HELD_VOCAB, day="2026-10-03", at="2026-10-03T18:00:00Z"))
    g = {"table": t, "_error": _error, "_public_decision_note": tw._public_decision_note}
    body = json.loads(tw.handle_owner_words({}, _g=g)["body"])
    assert body["state"] == "ok" and [e["text"] for e in body["entries"]] == [WEIRD], "stored text, not the stripped screen output"
    assert "fizzlewick" not in json.dumps(body).lower()

    class Boom:
        def query(self, **kw):
            raise RuntimeError("x")

    assert tw.handle_owner_words({}, _g={**g, "table": Boom()})["statusCode"] == 503
    # The serve-time all-or-nothing rule is the second screen: an entry it would alter is withheld.
    g2 = {**g, "_public_decision_note": lambda text: None}
    assert json.loads(tw.handle_owner_words({}, _g=g2)["body"])["sentence"] == ow.SILENCE_SENTENCE


# ── the mutations: both filter paths are load-bearing ─────────────────────────


def test_mutation_an_always_clean_filter_would_serve_the_held_fixture(monkeypatch):
    """Negative control for the HOLD path: with the screen mutated to always pass, the held fixture is stored as
    clean and SERVED. That the real screen keeps it off the page (above) is therefore the screen's doing."""
    monkeypatch.setattr(ow, "screen", lambda text, off_record=False, vocabulary=None: (ow.VERDICT_CLEAN, []))
    view = ow.public_view(ow.recent(_store(FakeTable(), _entry(HELD_VOCAB))))
    assert view["state"] == ow.STATE_OK and view["entries"][0]["text"] == HELD_VOCAB


def test_mutation_an_always_hold_filter_would_withhold_the_clean_fixture(monkeypatch):
    """Negative control for the CLEAN path: with the screen mutated to always hold, the clean fixture never serves."""
    monkeypatch.setattr(ow, "screen", lambda text, off_record=False, vocabulary=None: (ow.VERDICT_HELD, ["vice"]))
    assert ow.public_view(ow.recent(_store(FakeTable(), _entry(CLEAN))))["state"] == ow.STATE_ABSENT


# ── inlet A: his Claude chat (MCP) ────────────────────────────────────────────


@pytest.fixture
def chat(monkeypatch):
    from mcp import tools_owner_words as tow

    t = FakeTable()
    monkeypatch.setattr(tow, "_table_ref", t)
    monkeypatch.setattr(tow, "experiment_stamp_for", lambda pk, sk: {})
    monkeypatch.setattr(tow, "pacific_today", lambda: "2026-10-04")
    return tow, t


def test_the_tool_is_wired_as_a_write_with_declared_replay_semantics():
    from mcp import audit, idempotency, registry

    entry = registry.TOOLS["log_owner_note"]
    assert entry["schema"]["name"] == "log_owner_note" and entry["schema"]["inputSchema"]["required"] == ["text"]
    assert set(entry["schema"]["inputSchema"]["properties"]) == {"text", "prompt", "off_record", "date"}
    assert audit.is_write_tool("log_owner_note")
    assert idempotency.REPLAY_SEMANTICS["log_owner_note"][0] == idempotency.CONTENT_KEY
    assert "VERBATIM" in entry["schema"]["description"] and "never write words for him" in entry["schema"]["description"]


def test_the_tool_stores_his_words_verbatim_and_says_what_happened(chat):
    tow, t = chat
    out = tow.tool_log_owner_note({"text": WEIRD, "prompt": "How did the week feel?"})
    assert out["stored"] and out["published"] and out["verdict"] == ow.SAID_PUBLISHED and out["date"] == "2026-10-04"
    (row,) = t.items.values()
    assert row["text"] == WEIRD and row["channel"] == "chat" and row["prompt"] == "How did the week feel?"
    again = tow.tool_log_owner_note({"text": WEIRD, "prompt": "How did the week feel?"})
    assert again["duplicate"] and len(t.puts) == 1


def test_the_tool_holds_off_record_and_filtered_words_without_naming_the_term(chat):
    tow, t = chat
    off = tow.tool_log_owner_note({"text": CLEAN, "off_record": True, "date": "2026-10-01"})
    held = tow.tool_log_owner_note({"text": HELD_VOCAB})
    assert not off["published"] and off["verdict"] == ow.SAID_OFF_RECORD and off["date"] == "2026-10-01"
    assert not held["published"] and held["verdict"] == ow.SAID_HELD and "fizzlewick" not in json.dumps(held).lower()
    assert ow.public_view(ow.recent(t), vocabulary=NEUTRAL_VOCAB)["state"] == ow.STATE_ABSENT


def test_the_tool_refuses_bad_arguments_and_stores_nothing(chat):
    tow, t = chat
    for args in (
        {},
        {"text": "  "},
        {"text": "hi", "date": "Oct 1"},
        {"text": "hi", "date": "2026-10-05"},
        {"text": "hi", "off_record": "yes"},
    ):
        assert "error" in tow.tool_log_owner_note(args) and not t.puts, args


# ── inlet B: email (the Story Desk reply) ─────────────────────────────────────

QS = ["Did you take the rest day Max suggested?", "What did Sunday's 8-mile walk feel like?", "Which coach was most wrong about you?"]

INLINE = """Mostly yes.

On Mon, Oct 5, 2026 at 9:00 AM The Measured Life <lifeplatform@mattsusername.com> wrote:
> A few quick ones for Week 5.
>
> Q1: Did you take the rest day Max suggested?
No.  Felt like I'd lose the thread if I stopped,,
honestly.

>
> Q2: What did Sunday's 8-mile walk feel like?
Honestly the best part of the week. off record: my knee was sore after.
>
> Q3: Which coach was most wrong about you?
"""


def test_keep_raw_adds_his_lines_as_typed_and_leaves_the_default_output_unchanged():
    plain = sq.parse_reply(INLINE)
    raw = sq.parse_reply(INLINE, keep_raw=True)
    assert all("raw" not in a for a in plain), "the chronicle's owner_voice input must not change"
    assert [{k: v for k, v in a.items() if k != "raw"} for a in raw] == plain
    assert raw[0]["raw"] == "No.  Felt like I'd lose the thread if I stopped,,\nhonestly."


def test_a_reply_writes_one_entry_per_answered_question_and_none_for_an_unanswered_one():
    answers = sq.parse_reply(INLINE, keep_raw=True)
    entries = ow.entries_from_story_reply(answers, week=5, received_at="2026-10-06T03:10:00Z", source_key="raw/inbound_email/m1")
    assert [(e["q"], e["channel"], e["date"]) for e in entries] == [(1, "email", "2026-10-05"), (2, "email", "2026-10-05")]
    assert entries[0]["text"] == "No.  Felt like I'd lose the thread if I stopped,,\nhonestly." and entries[0]["prompt"] == QS[0]
    assert entries[0]["verdict"] == ow.VERDICT_CLEAN
    assert entries[1]["off_record"] is True and entries[1]["verdict"] == ow.VERDICT_HELD and "off record" in entries[1]["text"]


def _sq_email(body):
    return (
        "From: Matthew <matthew@example.invalid>\r\n"
        "To: insight@aws.example.invalid\r\n"
        "Subject: Re: The Measured Life · Week 5 · 3 quick questions [SQ-W5]\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body.replace("\n", "\r\n")
    ).encode("utf-8")


def test_the_parser_lands_the_answers_in_both_stores_and_the_chronicle_row_is_unchanged(monkeypatch):
    from emails import insight_email_parser_lambda as iep

    class S3:
        puts = []

        def get_object(self, **kw):
            return {"Body": io.BytesIO(_sq_email(INLINE))}

        def put_object(self, **kw):
            self.puts.append(kw)

    class CW:
        calls = []

        def put_metric_data(self, **kw):
            self.calls.append(kw)

    t = FakeTable()
    monkeypatch.setattr(iep, "table", t)
    monkeypatch.setattr(iep, "s3", S3())
    monkeypatch.setattr(iep, "cloudwatch", CW())
    monkeypatch.setattr(iep, "ALLOWED_SENDERS", {"matthew@example.invalid"})
    monkeypatch.setattr(iep, "experiment_stamp_for", lambda pk, sk: {})
    resp = iep.lambda_handler({"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "raw/inbound_email/m1"}}}]}, None)
    assert resp["statusCode"] == 200

    qa = [r for (pk, sk), r in t.items.items() if sk.startswith(sq.QA_SK_PREFIX)]
    assert len(qa) == 1 and json.loads(qa[0]["answers_json"]) == sq.parse_reply(_sq_email(INLINE).decode().split("\r\n\r\n", 1)[1])
    words = sorted((r for (pk, sk), r in t.items.items() if pk == ow.PK), key=lambda r: r["q"])
    assert [(r["q"], r["channel"], r["week"], r["source_key"]) for r in words] == [
        (1, "email", 5, "raw/inbound_email/m1"),
        (2, "email", 5, "raw/inbound_email/m1"),
    ]
    assert words[1]["verdict"] == ow.VERDICT_HELD, "the off-record answer is stored and never served"
    assert ow.public_view(ow.recent(t))["count"] == 1


def test_a_failed_owner_words_write_never_undoes_the_chronicle_row(monkeypatch):
    from emails import insight_email_parser_lambda as iep

    def boom(*a, **kw):
        raise RuntimeError("throttled")

    archived = []
    monkeypatch.setattr(ow, "record", boom)
    monkeypatch.setattr(iep, "_persist_failure_envelope", lambda ident, reason, payload: archived.append(reason) or "")
    assert iep._store_owner_words(INLINE, 5, "2026-10-06T03:10:00Z", "raw/inbound_email/m1") == 0
    assert archived == ["owner_words_write_failed"]


# ── nothing here writes in his voice ──────────────────────────────────────────


def test_no_module_on_the_path_imports_a_model_client():
    offenders = {}
    for rel in ("lambdas/content/owner_words.py", "mcp/tools_owner_words.py"):
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom):
                mods.add(node.module or "")
                mods |= {f"{node.module}.{a.name}" for a in node.names}
            elif isinstance(node, ast.Import):
                mods |= {a.name for a in node.names}
        bad = {m for m in mods if m.startswith("ai") or "bedrock" in m}
        if bad:
            offenders[rel] = bad
    assert not offenders, offenders
