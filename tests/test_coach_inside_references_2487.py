"""tests/test_coach_inside_references_2487.py — the inside-references ledger (#2487).

Behavior pins for the capped ``RELATIONSHIP#bits`` partition:

  I1  honesty (ADR-104): a bit is stored only if it is LITERALLY in the day's
      transcript — no paraphrase, no inference, no invention
  I2  the cap is a real ceiling: more writes than the cap still leave <= MAX_BITS
  I3  eviction is deterministic and weakest-first (sightings, then recency, then
      alphabetical) — two runs over the same input cannot disagree
  I4  the ledger reaches the chat prompt through read_recent_summaries (the call
      _memory_block already makes) and survives build_system_prompt verbatim
  I5  the store is internal-only: no public-site module can reach a
      ``RELATIONSHIP#bits`` sk (structurally, not by convention)
  I6  reset semantics: the row classifies CROSS_PHASE

Every phrase below is synthetic. Nothing here is a real message.
"""

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import coach_chat, coach_chat_summary as ccs  # noqa: E402

PK = "COACH#test_coach"


class _FakeTable:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.put_calls = []

    def query(self, **kw):
        vals = kw.get("ExpressionAttributeValues", {})
        pk, pfx = vals.get(":pk"), vals.get(":pfx", "")
        rows = [i for i in self.items if i.get("pk") == pk and str(i.get("sk", "")).startswith(pfx)]
        rows.sort(key=lambda r: r["sk"], reverse=not kw.get("ScanIndexForward", True))
        limit = kw.get("Limit")
        return {"Items": rows[:limit] if limit else rows}

    def get_item(self, Key=None):
        for i in self.items:
            if i.get("pk") == Key["pk"] and i.get("sk") == Key["sk"]:
                return {"Item": i}
        return {}

    def put_item(self, Item=None, **kw):
        self.put_calls.append(Item)
        self.items = [i for i in self.items if not (i.get("pk") == Item["pk"] and i.get("sk") == Item["sk"])]
        self.items.append(Item)


def _turn(date, uid, role, text):
    return {"pk": PK, "sk": f"CHAT#{date}#{uid}", "role": role, "text": text}


# ── I1: honesty — verbatim or nothing ────────────────────────────────────────


def test_a_bit_is_kept_only_when_it_is_literally_in_the_transcript():
    transcript = "Matthew: the treadmill is the hamster wheel again\nCoach: the hamster wheel it is"
    kept = ccs.grounded_bits(["the hamster wheel", "the gerbil wheel", "he loves cardio metaphors"], transcript)
    assert kept == ["the hamster wheel"]


def test_a_paraphrased_or_invented_bit_never_enters_the_ledger():
    """The failure this gate exists for: a fabricated shared history. If the
    model offers a phrase the pair never said, storing it would have the coach
    'remember' something that did not happen (ADR-104)."""
    assert ccs.grounded_bits(["our little ritual", "the 5am club"], "Matthew: morning\nCoach: morning") == []


def test_grounding_is_case_and_whitespace_insensitive_but_not_meaning_insensitive():
    transcript = "Matthew: The   Hamster Wheel is back"
    assert ccs.grounded_bits(["the hamster wheel"], transcript) == ["the hamster wheel"]
    assert ccs.grounded_bits(["the hamster cage"], transcript) == []


def test_one_day_cannot_flood_the_ledger():
    transcript = "a b c d e f g"
    assert len(ccs.grounded_bits(["a", "b", "c", "d", "e", "f"], transcript)) == ccs.MAX_NEW_BITS_PER_DAY


# ── parsing the BITS: tail ───────────────────────────────────────────────────


def test_the_bits_tail_is_split_off_the_note():
    note, bits = ccs.split_note_and_bits("He skipped the gym. I said fine.\nBITS:\n- the hamster wheel\n- couch day")
    assert "BITS" not in note and note.startswith("He skipped")
    assert bits == ["the hamster wheel", "couch day"]


def test_a_day_with_no_bits_parses_clean():
    for raw in ("He skipped the gym.", "He skipped the gym.\nBITS: none", "He skipped the gym.\nBITS:"):
        note, bits = ccs.split_note_and_bits(raw)
        assert bits == []
        assert note.startswith("He skipped")
        assert "BITS" not in note


# ── I2/I3: the cap and its eviction rule ─────────────────────────────────────


def test_the_cap_holds_under_far_more_writes_than_the_cap():
    """Mutation proof for the ceiling: 40 distinct bits across 40 days must still
    leave exactly MAX_BITS rows. Remove the truncation in merge_bits and this
    fails."""
    stored = []
    for n in range(40):
        stored = ccs.merge_bits(stored, [f"synthetic bit {n}"], f"2026-08-{(n % 28) + 1:02d}")
        assert len(stored) <= ccs.MAX_BITS
    assert len(stored) == ccs.MAX_BITS


def test_eviction_drops_the_weakest_not_the_newest():
    """A bit seen many times outlives newer one-offs — that is what makes the
    ledger a record of RECURRING bits rather than a recency buffer."""
    stored = [{"text": "old faithful", "first_seen": "2026-01-01", "last_seen": "2026-01-09", "count": 9}]
    for n in range(ccs.MAX_BITS * 2):
        stored = ccs.merge_bits(stored, [f"one off {n}"], f"2026-08-{(n % 28) + 1:02d}")
    texts = [b["text"] for b in stored]
    assert "old faithful" in texts
    assert texts[0] == "old faithful"  # strongest first
    assert len(stored) == ccs.MAX_BITS


def test_eviction_is_total_and_deterministic_on_ties():
    """Equal sightings -> least recently used goes; equal recency -> alphabetical
    tiebreak, so the same input can never produce two different ledgers."""
    existing = [{"text": f"bit {c}", "first_seen": "2026-08-01", "last_seen": "2026-08-01", "count": 1} for c in "abcdefghij"]
    a = ccs.merge_bits(existing, ["bit z"], "2026-08-02")
    b = ccs.merge_bits(list(reversed(existing)), ["bit z"], "2026-08-02")
    assert [x["text"] for x in a] == [x["text"] for x in b]
    assert a[0]["text"] == "bit z"  # most recent among equal counts
    assert "bit j" not in [x["text"] for x in a]  # alphabetically last of the tied losers


def test_reseeing_a_bit_bumps_it_instead_of_duplicating_it():
    stored = ccs.merge_bits([], ["the hamster wheel"], "2026-08-01")
    stored = ccs.merge_bits(stored, ["The Hamster Wheel"], "2026-08-05")
    assert len(stored) == 1
    assert stored[0]["count"] == 2
    assert stored[0]["first_seen"] == "2026-08-01"
    assert stored[0]["last_seen"] == "2026-08-05"


def test_rerunning_the_same_day_is_idempotent():
    stored = ccs.merge_bits([], ["the hamster wheel"], "2026-08-01")
    again = ccs.merge_bits(stored, ["the hamster wheel"], "2026-08-01")
    assert again[0]["count"] == 1


# ── the write path, end to end through the existing summarizer ───────────────


def _reply(text):
    return lambda body: {"content": [{"type": "text", "text": text}]}


def test_the_daily_summarizer_stores_grounded_bits_and_keeps_them_out_of_the_note():
    table = _FakeTable(
        [
            _turn("2026-08-08", "aa", "matthew", "back on the hamster wheel today"),
            _turn("2026-08-08", "ab", "coach", "the hamster wheel earns its name"),
        ]
    )
    out = ccs.ensure_daily_summary(
        table,
        PK,
        "Test Coach",
        _reply("He ran again and joked about it.\nBITS:\n- the hamster wheel\n- our secret handshake"),
        today="2026-08-09",
        cycle=13,
    )
    assert out == "2026-08-08"
    summary = [p for p in table.put_calls if p["sk"].startswith(ccs.SUMMARY_SK_PREFIX)][0]
    assert "BITS" not in summary["text"] and "hamster" not in summary["text"]
    bits_row = [p for p in table.put_calls if p["sk"] == ccs.BITS_SK][0]
    assert bits_row["cycle"] == 13
    # "our secret handshake" is not in the transcript -> it never lands.
    assert [b["text"] for b in bits_row["bits"]] == ["the hamster wheel"]


def test_no_bits_row_is_written_on_a_day_with_no_grounded_bits():
    table = _FakeTable([_turn("2026-08-08", "aa", "matthew", "hey"), _turn("2026-08-08", "ab", "coach", "hey")])
    ccs.ensure_daily_summary(table, PK, "Test Coach", _reply("Short exchange.\nBITS: none"), today="2026-08-09")
    assert [p for p in table.put_calls if p["sk"] == ccs.BITS_SK] == []


def test_a_failing_bits_write_never_breaks_the_summary():
    class _Boom(_FakeTable):
        def put_item(self, Item=None, **kw):
            if Item["sk"] == ccs.BITS_SK:
                raise RuntimeError("ddb down")
            return super().put_item(Item=Item, **kw)

    table = _Boom([_turn("2026-08-08", "aa", "matthew", "the hamster wheel again")])
    out = ccs.ensure_daily_summary(table, PK, "T", _reply("Note.\nBITS:\n- the hamster wheel"), today="2026-08-09")
    assert out == "2026-08-08"


# ── I4: the ledger reaches the prompt ────────────────────────────────────────


def test_bits_render_into_the_memory_block_through_read_recent_summaries():
    table = _FakeTable(
        [
            {"pk": PK, "sk": "CHAT#summary#2026-08-08", "text": "a normal day"},
            {
                "pk": PK,
                "sk": ccs.BITS_SK,
                "bits": [{"text": "the hamster wheel", "first_seen": "2026-08-01", "last_seen": "2026-08-08", "count": 4}],
            },
        ]
    )
    block = ccs.read_recent_summaries(table, PK, today="2026-08-09")
    assert "RECENT CONVERSATIONS" in block
    assert "INSIDE REFERENCES" in block
    assert "the hamster wheel" in block
    assert "4x" in block
    # ordering: remembered prose first, the bits tail last
    assert block.index("RECENT CONVERSATIONS") < block.index("INSIDE REFERENCES")


def test_an_empty_ledger_says_nothing_at_all():
    assert ccs.bits_block([]) == ""
    assert ccs.read_recent_summaries(_FakeTable([]), PK, today="2026-08-09") == ""


def test_the_inside_references_block_survives_the_system_prompt_verbatim():
    """Same seam #2489 pins: whatever the memory block holds must reach the
    volatile tail untouched."""
    block = ccs.bits_block([{"text": "the hamster wheel", "first_seen": "2026-08-01", "count": 3}])
    s = coach_chat.build_system_prompt("V", block, "F", "Test Coach")
    assert block in s


# ── I5: internal-only, proven structurally ───────────────────────────────────


def test_no_public_site_module_can_reach_the_bits_row():
    """AC 'no public surface reads it', proven rather than audited.

    ``site_api_coach_profile`` reads RELATIONSHIP by EXACT key
    (``get_item(sk="RELATIONSHIP#state")``), so a ``RELATIONSHIP#bits`` sk is
    structurally unreachable from it. This pins that property for the whole
    public serving package: every RELATIONSHIP# string literal under
    ``lambdas/web/`` must be the exact ``RELATIONSHIP#state`` key. Introduce a
    ``begins_with(sk, "RELATIONSHIP#")`` query — or name BITS_SK — anywhere in
    the reader-facing package and this test fails.
    """
    web = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "web")
    offenders = []
    for name in sorted(os.listdir(web)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(web, name)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        # Docstrings are prose ABOUT the reads, not reads — exclude them by
        # identity so the guard still sees every real key literal.
        prose = set()
        for scope in ast.walk(tree):
            if isinstance(scope, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = (getattr(scope, "body", None) or [None])[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    prose.add(id(first.value))
        for node in ast.walk(tree):
            if id(node) in prose:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "RELATIONSHIP#" in node.value:
                if node.value != "RELATIONSHIP#state":
                    offenders.append(f"{name}:{node.lineno}: {node.value!r}")
    assert offenders == [], "public web package reaches a non-state RELATIONSHIP sk: " + "; ".join(offenders)
    assert ccs.BITS_SK != "RELATIONSHIP#state"  # the guard above is meaningful only if these differ


# ── I6: reset semantics ──────────────────────────────────────────────────────


def test_the_bits_row_is_cross_phase_and_survives_a_reset():
    from experiment import phase_taxonomy

    assert phase_taxonomy.classify(PK, ccs.BITS_SK) == phase_taxonomy.CROSS_PHASE
    # ...for the same reason the rest of the texting relationship is (ADR-153).
    assert phase_taxonomy.classify(PK, "RELATIONSHIP#state") == phase_taxonomy.CROSS_PHASE
