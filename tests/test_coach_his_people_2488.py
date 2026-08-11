"""tests/test_coach_his_people_2488.py — his-people memory (#2488).

The coaches remember the first names Matthew mentions, so one of them can ask how
someone's thing went a week later. On a PUBLIC repo that memory is the most
sensitive row the platform writes, so the pins below are weighted accordingly:

  H1  honesty + shape: a name is stored only when it is first-name shaped and
      appears in the day's transcript AS A WHOLE WORD (substring matching would
      conjure "Ana" out of "Dana"); Matthew and the coach are never "his people"
  H2  ONE eviction policy: the cap is real and it is merge_bits', not a second one
  H3  the ledger reaches the chat prompt through read_recent_summaries — and does
      it in ZERO additional DynamoDB calls (one RELATIONSHIP# query serves both
      the #2487 bits row and this one)
  H4  the two tails come off ONE model reply; a name never lands in the note or
      in the inside-references block, whatever order the model emits them in
  H5  THE PRIVACY SCREEN, widened (the deliverable): no module on the coach
      perimeter — derived from the source, not listed here — can name the people
      sk, and no perimeter module that touches DynamoDB can prefix-sweep
      RELATIONSHIP#. Proven in both directions: the real tree is clean AND the
      scanner provably flags a module that offends.
  H6  names never reach off-box logs, on the happy path OR the error path
  H7  reset semantics: the row classifies CROSS_PHASE

Every name below is synthetic. Nothing here is a real person or a real message.
"""

import ast
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from coach import coach_chat, coach_chat_summary as ccs  # noqa: E402

PK = "COACH#test_coach"


class _FakeTable:
    """Records every DynamoDB call so the read path's call COUNT is assertable."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.put_calls = []
        self.calls = []

    def query(self, **kw):
        vals = kw.get("ExpressionAttributeValues", {})
        pk, pfx = vals.get(":pk"), vals.get(":pfx", "")
        self.calls.append(("query", pk, pfx))
        rows = [i for i in self.items if i.get("pk") == pk and str(i.get("sk", "")).startswith(pfx)]
        rows.sort(key=lambda r: r["sk"], reverse=not kw.get("ScanIndexForward", True))
        limit = kw.get("Limit")
        return {"Items": rows[:limit] if limit else rows}

    def get_item(self, Key=None):
        self.calls.append(("get_item", Key["pk"], Key["sk"]))
        for i in self.items:
            if i.get("pk") == Key["pk"] and i.get("sk") == Key["sk"]:
                return {"Item": i}
        return {}

    def put_item(self, Item=None, **kw):
        self.calls.append(("put_item", Item["pk"], Item["sk"]))
        self.put_calls.append(Item)
        self.items = [i for i in self.items if not (i.get("pk") == Item["pk"] and i.get("sk") == Item["sk"])]
        self.items.append(Item)


def _turn(date, uid, role, text):
    return {"pk": PK, "sk": f"CHAT#{date}#{uid}", "role": role, "text": text}


def _reply(text):
    return lambda body: {"content": [{"type": "text", "text": text}]}


# ── H1: honesty, shape, and who is never "his people" ────────────────────────


def test_a_name_is_kept_only_when_he_actually_said_it():
    transcript = "Matthew: Dana finally ran her 10k\nCoach: how did she do"
    assert ccs.grounded_people(["Dana", "Priya"], transcript) == ["Dana"]


def test_a_substring_of_a_real_name_is_not_a_person():
    """The reason people do not reuse the bits gate verbatim. 'Ana' is inside
    'Dana'; a substring match would invent a person who was never mentioned, and
    an invented person is the worst thing this store could hold (ADR-104)."""
    transcript = "Matthew: Dana finally ran her 10k"
    assert ccs.grounded_bits(["ana"], transcript) == ["ana"]  # the bits gate DOES accept it
    assert ccs.grounded_people(["Ana"], transcript) == []  # the people gate does not


def test_only_first_name_shaped_tokens_survive():
    transcript = "Matthew: Dana Okonkwo came by, so did my manager, and dana's dog"
    assert ccs.grounded_people(["Dana Okonkwo"], transcript) == []  # a full name is not a first name
    assert ccs.grounded_people(["my manager"], transcript) == []  # a phrase is not a name
    assert ccs.grounded_people(["dana"], transcript) == []  # uncapitalized -> not name-shaped
    assert ccs.grounded_people(["Dana"], transcript) == ["Dana"]


def test_matthew_and_the_coach_are_never_his_people():
    """RELATIONSHIP#state already models the pair. A ledger of 'his people' that
    contains the subject and the coach is a ledger about nothing."""
    transcript = "Matthew: hey Eli\nCoach: hey Matthew, Priya asked about you"
    assert ccs.grounded_people(["Matthew", "Eli", "Priya"], transcript, exclude=("Eli Marsh",)) == ["Priya"]


def test_one_day_cannot_rewrite_who_his_people_are():
    transcript = "Matthew: Dana Priya Reza Bex Nils all came"
    assert len(ccs.grounded_people(["Dana", "Priya", "Reza", "Bex", "Nils"], transcript)) == ccs.MAX_NEW_PEOPLE_PER_DAY


def test_the_same_name_twice_in_one_day_is_one_person():
    assert ccs.grounded_people(["Dana", "dana", "DANA"], "Matthew: Dana again") == ["Dana"]


# ── H2: ONE eviction policy, two ceilings ────────────────────────────────────


def test_the_people_cap_is_a_real_ceiling_under_far_more_writes():
    stored = []
    for n in range(40):
        stored = ccs.merge_bits(stored, [f"Name{n:02d}"], f"2026-08-{(n % 28) + 1:02d}", cap=ccs.MAX_PEOPLE)
        assert len(stored) <= ccs.MAX_PEOPLE
    assert len(stored) == ccs.MAX_PEOPLE


def test_the_people_ledger_reuses_the_bits_eviction_rule_exactly():
    """Not 'a similar rule' — the same function. A person seen many times outlives
    newer one-offs, ties break by recency then alphabetically, and re-sighting
    bumps rather than duplicates, because merge_bits does all three."""
    stored = [{"text": "Dana", "first_seen": "2026-01-01", "last_seen": "2026-01-09", "count": 9}]
    for n in range(ccs.MAX_PEOPLE * 2):
        stored = ccs.merge_bits(stored, [f"Nils{n:02d}"], f"2026-08-{(n % 28) + 1:02d}", cap=ccs.MAX_PEOPLE)
    assert [p["text"] for p in stored][0] == "Dana"
    assert len(stored) == ccs.MAX_PEOPLE
    bumped = ccs.merge_bits(ccs.merge_bits([], ["Dana"], "2026-08-01"), ["dana"], "2026-08-05", cap=ccs.MAX_PEOPLE)
    assert len(bumped) == 1 and bumped[0]["count"] == 2 and bumped[0]["first_seen"] == "2026-08-01"


def test_the_two_ledgers_have_different_ceilings_and_both_are_enforced():
    """The cap argument would be pointless if the two ceilings were the same."""
    assert ccs.MAX_PEOPLE != ccs.MAX_BITS
    many = [{"text": f"X{n:02d}", "first_seen": "2026-08-01", "last_seen": "2026-08-01", "count": 1} for n in range(40)]
    assert len(ccs.merge_bits(many, [], "2026-08-02")) == ccs.MAX_BITS
    assert len(ccs.merge_bits(many, [], "2026-08-02", cap=ccs.MAX_PEOPLE)) == ccs.MAX_PEOPLE


# ── H3: the prompt fold, and the zero-extra-reads claim ──────────────────────


def _memory_table():
    return _FakeTable(
        [
            {"pk": PK, "sk": "CHAT#summary#2026-08-08", "text": "a normal day"},
            {"pk": PK, "sk": ccs.BITS_SK, "bits": [{"text": "the hamster wheel", "first_seen": "2026-08-01", "count": 4}]},
            {
                "pk": PK,
                "sk": ccs.PEOPLE_SK,
                "people": [{"text": "Dana", "first_seen": "2026-08-01", "last_seen": "2026-08-08", "count": 3}],
            },
        ]
    )


def test_people_render_into_the_memory_block_through_read_recent_summaries():
    block = ccs.read_recent_summaries(_memory_table(), PK, today="2026-08-09")
    assert "HIS PEOPLE" in block
    assert "Dana" in block
    assert "last mentioned 2026-08-08" in block and "3x" in block
    # ordering: prose, then the pair's bits, then his people
    assert block.index("RECENT CONVERSATIONS") < block.index("INSIDE REFERENCES") < block.index("HIS PEOPLE")


def test_the_second_ledger_costs_zero_additional_dynamodb_calls():
    """The load-bearing efficiency claim, asserted as a NUMBER rather than a
    comment. The read path makes exactly three calls: the summary query, the
    time-gap turn query, and ONE RELATIONSHIP# query that returns both ledgers.
    Add a separate get_item for the people row and this goes to four."""
    table = _memory_table()
    ccs.read_recent_summaries(table, PK, today="2026-08-09")
    assert len(table.calls) == 3, table.calls
    assert [c[0] for c in table.calls].count("get_item") == 0, table.calls
    rel = [c for c in table.calls if c[0] == "query" and c[2] == "RELATIONSHIP#"]
    assert len(rel) == 1, table.calls


def test_reading_the_people_ledger_never_issues_its_own_get_item():
    """The write path reads too (a merge must see the row it overwrites). It
    reads through the SAME shared query, so the daily summarizer does not grow a
    fourth call either — give read_people its own get_item and this fails."""
    table = _memory_table()
    assert [p["text"] for p in ccs.read_people(table, PK)] == ["Dana"]
    assert table.calls == [("query", PK, "RELATIONSHIP#")], table.calls


def test_the_relationship_query_actually_matches_the_stored_rows():
    """A filter that matches nothing has shipped here before. Prove the prefix is
    real by mutating it: the true prefix finds both rows, a wrong one finds none."""
    table = _memory_table()
    bits, people = ccs.read_relationship_memory(table, PK)
    assert [b["text"] for b in bits] == ["the hamster wheel"]
    assert [p["text"] for p in people] == ["Dana"]
    assert table.query(ExpressionAttributeValues={":pk": PK, ":pfx": "RELATIONSHIP#"})["Items"] != []
    assert table.query(ExpressionAttributeValues={":pk": PK, ":pfx": "RELATIONSHIPS#"})["Items"] == []


def test_an_empty_people_ledger_says_nothing_at_all():
    assert ccs.people_block([]) == ""
    assert ccs.people_block([{"text": "  "}]) == ""
    assert ccs.read_recent_summaries(_FakeTable([]), PK, today="2026-08-09") == ""


def test_the_his_people_block_survives_the_system_prompt_verbatim():
    block = ccs.people_block([{"text": "Dana", "first_seen": "2026-08-01", "last_seen": "2026-08-08", "count": 3}])
    assert block in coach_chat.build_system_prompt("V", block, "F", "Test Coach")


# ── H4: two tails, one reply ─────────────────────────────────────────────────


def test_both_tails_split_off_one_reply():
    note, bits, people = ccs.split_note_bits_and_people(
        "He ran again.\nBITS:\n- the hamster wheel\nPEOPLE:\n- Dana\n- Priya",
    )
    assert note == "He ran again."
    assert bits == ["the hamster wheel"]
    assert people == ["Dana", "Priya"]


def test_a_reply_with_neither_tail_is_all_note():
    assert ccs.split_note_bits_and_people("He ran again.") == ("He ran again.", [], [])


def test_an_empty_or_none_people_tail_is_no_people():
    for raw in ("He ran.\nBITS: none\nPEOPLE: none", "He ran.\nPEOPLE:", "He ran.\nPEOPLE:\n- none"):
        note, _bits, people = ccs.split_note_bits_and_people(raw)
        assert people == [] and note.startswith("He ran") and "PEOPLE" not in note


def test_a_name_never_lands_in_the_bits_list_even_when_the_model_swaps_the_tails():
    """The failure this guards: a name filed as an inside reference renders into
    the INSIDE REFERENCES block, which is prose about the pair, not a gated store.
    Whatever order the model emits, neither tail may swallow the other's lines."""
    note, bits, people = ccs.split_note_bits_and_people("He ran.\nPEOPLE:\n- Dana\nBITS:\n- the hamster wheel")
    assert "Dana" not in bits and "Dana" in people
    assert "the hamster wheel" not in people
    assert "Dana" not in note


def test_the_2487_splitter_is_behaviourally_unchanged():
    """#2488 refactored the tail parser out of split_note_and_bits; the #2487
    contract must survive that untouched."""
    note, bits = ccs.split_note_and_bits("He skipped the gym. I said fine.\nBITS:\n- the hamster wheel\n- couch day")
    assert note.startswith("He skipped") and "BITS" not in note
    assert bits == ["the hamster wheel", "couch day"]


# ── the write path, end to end through the existing summarizer ───────────────


def test_the_daily_summarizer_stores_grounded_people_and_keeps_them_out_of_the_note():
    table = _FakeTable(
        [
            _turn("2026-08-08", "aa", "matthew", "Dana finally ran her 10k and Priya is moving"),
            _turn("2026-08-08", "ab", "coach", "big week for Dana"),
        ]
    )
    out = ccs.ensure_daily_summary(
        table,
        PK,
        "Eli Marsh",
        _reply("He talked about his week.\nBITS: none\nPEOPLE:\n- Dana\n- Priya\n- Nils\n- Eli"),
        today="2026-08-09",
        cycle=13,
    )
    assert out == "2026-08-08"
    summary = [p for p in table.put_calls if p["sk"].startswith(ccs.SUMMARY_SK_PREFIX)][0]
    assert "PEOPLE" not in summary["text"] and "Dana" not in summary["text"]
    row = [p for p in table.put_calls if p["sk"] == ccs.PEOPLE_SK][0]
    # "Nils" was never said; "Eli" is the coach. Neither lands.
    assert [p["text"] for p in row["people"]] == ["Dana", "Priya"]
    assert row["cycle"] == 13 and row["sensitivity"] == "internal_only" and row["type"] == "relationship_people"


def test_only_one_model_call_is_made_for_both_tails():
    """A third Bedrock call per turn would be a regression (#2554). The people
    extraction must ride the summarizer call, not add one."""
    calls = []

    def _counting(body):
        calls.append(body)
        return {"content": [{"type": "text", "text": "Note.\nBITS: none\nPEOPLE:\n- Dana"}]}

    table = _FakeTable([_turn("2026-08-08", "aa", "matthew", "Dana came over")])
    ccs.ensure_daily_summary(table, PK, "T", _counting, today="2026-08-09")
    assert len(calls) == 1
    assert [p["text"] for p in [q for q in table.put_calls if q["sk"] == ccs.PEOPLE_SK][0]["people"]] == ["Dana"]


def test_no_people_row_is_written_on_a_day_with_no_grounded_names():
    table = _FakeTable([_turn("2026-08-08", "aa", "matthew", "hey"), _turn("2026-08-08", "ab", "coach", "hey")])
    ccs.ensure_daily_summary(table, PK, "T", _reply("Short.\nBITS: none\nPEOPLE: none"), today="2026-08-09")
    assert [p for p in table.put_calls if p["sk"] == ccs.PEOPLE_SK] == []


def test_a_failing_people_write_never_breaks_the_summary():
    class _Boom(_FakeTable):
        def put_item(self, Item=None, **kw):
            if Item["sk"] == ccs.PEOPLE_SK:
                raise RuntimeError("ddb down")
            return super().put_item(Item=Item, **kw)

    table = _Boom([_turn("2026-08-08", "aa", "matthew", "Dana came over")])
    assert ccs.ensure_daily_summary(table, PK, "T", _reply("Note.\nPEOPLE:\n- Dana"), today="2026-08-09") == "2026-08-08"


# ── H5: THE PRIVACY SCREEN, widened and derived from the source ──────────────
#
# #2487 pinned "no public surface reads the bits row" over `lambdas/web/` only.
# Five more modules touch the COACH# partition and reach reader-facing output —
# the chronicle, the podcast, the nudge mail, the diary-claims record builder —
# so the screen below covers a set DERIVED from the tree instead of a path list
# that goes stale the day someone adds the sixth.

_LAMBDAS = os.path.join(ROOT, "lambdas")
_FORBIDDEN_SUBSTRINGS = (ccs.PEOPLE_SK, "relationship_people")
_DDB_CALLS = {"query", "get_item", "batch_get_item", "scan", "put_item", "update_item", "delete_item"}


def _tree(path):
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=path)


def _modules():
    for dirpath, _dirs, names in os.walk(_LAMBDAS):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(names):
            if name.endswith(".py"):
                full = os.path.join(dirpath, name)
                yield os.path.relpath(full, _LAMBDAS), full


def _prose_ids(tree):
    """Docstring Constant nodes, by identity — prose ABOUT a key is not a key."""
    out = set()
    for scope in ast.walk(tree):
        if isinstance(scope, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = (getattr(scope, "body", None) or [None])[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def _string_constants(tree, *, include_prose):
    skip = set() if include_prose else _prose_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield getattr(node, "lineno", 0), node.value


def _touches_dynamodb(tree):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _DDB_CALLS for n in ast.walk(tree))


def _is_key_shaped(value):
    """A DynamoDB sk literal: starts with the prefix and has no whitespace. Keeps
    log/prose strings that merely MENTION a key out of the sweep screen, while
    still catching an f-string's `RELATIONSHIP#` fragment."""
    return value.startswith("RELATIONSHIP#") and not any(c.isspace() for c in value)


def _perimeter():
    """The derived coach perimeter: every module under the public serving package
    plus every module that mentions the COACH# partition ANYWHERE — code or
    prose. Deliberately over-inclusive: for a privacy screen, a module that talks
    about the partition is close enough to it to be worth screening, and
    over-inclusion costs nothing while an omission is the whole failure mode."""
    out = {}
    for rel, full in _modules():
        tree = _tree(full)
        if rel.startswith("web" + os.sep) or any("COACH#" in v for _ln, v in _string_constants(tree, include_prose=True)):
            out[rel] = tree
    return out


def _store_owners(perimeter):
    """The module(s) that DEFINE the people sk — the store's owner, derived by
    assignment rather than named, so a move re-derives instead of silently
    exempting the wrong file."""
    owners = set()
    for rel, tree in perimeter.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.BinOp):
                if any(isinstance(t, ast.Name) and t.id == "PEOPLE_SK" for t in node.targets):
                    owners.add(rel)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if any(isinstance(t, ast.Name) and t.id == "PEOPLE_SK" for t in node.targets):
                    owners.add(rel)
    return owners


def _name_offenders(rel, tree):
    return [f"{rel}:{ln}: {v!r}" for ln, v in _string_constants(tree, include_prose=False) if any(s in v for s in _FORBIDDEN_SUBSTRINGS)]


def _sweep_offenders(rel, tree):
    return [
        f"{rel}:{ln}: {v!r}" for ln, v in _string_constants(tree, include_prose=False) if _is_key_shaped(v) and v != "RELATIONSHIP#state"
    ]


# The five modules the widening was filed for. They are a CANARY on the
# derivation, not the screen itself: if the derivation ever silently returns a
# smaller set, these fail loudly instead of the screen passing vacuously.
_KNOWN_PERIMETER = (
    os.path.join("emails", "between_chronicle_lambda.py"),
    os.path.join("emails", "chronicle_data.py"),
    os.path.join("emails", "coach_panel_podcast_lambda.py"),
    os.path.join("emails", "coach_nudge_lambda.py"),
    os.path.join("privacy", "diary_claims.py"),
)


def test_the_derived_perimeter_is_not_vacuous():
    perimeter = _perimeter()
    assert len(perimeter) >= 60, len(perimeter)
    web = [r for r in perimeter if r.startswith("web" + os.sep)]
    assert len(web) >= 40, web  # the whole public serving package, as #2487 had
    missing = [m for m in _KNOWN_PERIMETER if m not in perimeter]
    assert missing == [], f"the widening's own targets fell out of the derived set: {missing}"
    assert os.path.join("coach", "coach_chat_summary.py") in perimeter


def test_the_store_has_exactly_one_owner():
    owners = _store_owners(_perimeter())
    assert owners == {os.path.join("coach", "coach_chat_summary.py")}, owners


def test_no_module_on_the_coach_perimeter_can_name_the_people_row():
    """AC2, the wide half: the sk of the his-people store appears in exactly one
    file in the tree — the one that owns it. Name it anywhere else and this
    fails, whether that module reads, writes, logs, or merely mentions it."""
    perimeter = _perimeter()
    owners = _store_owners(perimeter)
    offenders = []
    for rel, tree in sorted(perimeter.items()):
        if rel in owners:
            continue
        offenders += _name_offenders(rel, tree)
    assert offenders == [], "the his-people sk is named outside its owner: " + "; ".join(offenders)


def test_no_perimeter_module_that_reads_dynamodb_can_sweep_the_relationship_prefix():
    """AC2, the sharp half: naming the sk is the obvious leak; a
    ``begins_with(sk, "RELATIONSHIP#")`` query is the quiet one — it would pull
    the people row into a reader-facing payload without ever spelling it. Every
    RELATIONSHIP# key literal on a DynamoDB-touching perimeter module must be
    the one public-safe singleton, ``RELATIONSHIP#state``."""
    perimeter = _perimeter()
    owners = _store_owners(perimeter)
    screened = {r: t for r, t in perimeter.items() if r not in owners and _touches_dynamodb(t)}
    assert len(screened) >= 40, len(screened)
    for known in _KNOWN_PERIMETER:
        tree = perimeter[known]
        assert (known in screened) == _touches_dynamodb(tree), known
    offenders = []
    for rel, tree in sorted(screened.items()):
        offenders += _sweep_offenders(rel, tree)
    assert offenders == [], "a perimeter reader sweeps the RELATIONSHIP# prefix: " + "; ".join(offenders)


def test_the_sweep_exclusion_is_derived_not_convenient():
    """The screen above skips perimeter modules that touch no DynamoDB API at
    all (the phase-taxonomy classifier is the live example: it matches on the
    RELATIONSHIP# prefix but cannot read a byte). That exclusion is only honest
    if every excluded module really has zero DynamoDB call sites."""
    perimeter = _perimeter()
    owners = _store_owners(perimeter)
    excluded = {r: t for r, t in perimeter.items() if r not in owners and not _touches_dynamodb(t)}
    assert excluded, "the exclusion rule excludes nothing — it is untested as written"
    for rel, tree in sorted(excluded.items()):
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert not (calls & _DDB_CALLS), rel


@pytest.mark.parametrize(
    "source,scanner,label",
    [
        ('SK = "RELATIONSHIP#people"\n', _name_offenders, "names the sk"),
        ('def go(t):\n    return t.get_item(Key={"pk": p, "sk": "RELATIONSHIP#people"})\n', _name_offenders, "reads the sk"),
        ('ROW_TYPE = "relationship_people"\n', _name_offenders, "names the row type"),
        ('def go(t):\n    return t.query(KeyConditionExpression=Key("sk").begins_with("RELATIONSHIP#"))\n', _sweep_offenders, "sweeps"),
        ('def go(t, kind):\n    return t.get_item(Key={"sk": f"RELATIONSHIP#{kind}"})\n', _sweep_offenders, "builds the sk"),
    ],
)
def test_the_screen_provably_catches_an_offending_module(source, scanner, label):
    """THE MUTATION CLINCHER (#2487's technique, applied to both halves). A screen
    that passes over a clean tree proves nothing on its own — it would also pass
    if the scanner were broken and returned [] for everything. Each source below
    is a module that DOES what the screen forbids, and each must be flagged."""
    assert scanner("synthetic.py", ast.parse(source)) != [], label


@pytest.mark.parametrize(
    "source",
    [
        'REL = "RELATIONSHIP#state"\n',
        '"""A docstring about RELATIONSHIP#people and relationship_people rows."""\n',
        'def f():\n    """Reads RELATIONSHIP#bits, never RELATIONSHIP#people."""\n    return 1\n',
        'logger.warning("RELATIONSHIP#state update failed for %s", pk)\n',
    ],
)
def test_the_screen_does_not_flag_what_it_should_not(source):
    """The other direction: a screen that flags everything is equally useless, and
    would force the next author to weaken it. Legitimate state reads and prose
    ABOUT the store must pass."""
    tree = ast.parse(source)
    assert _name_offenders("synthetic.py", tree) == []
    assert _sweep_offenders("synthetic.py", tree) == []


def test_the_screen_is_meaningful_only_because_the_keys_differ():
    assert ccs.PEOPLE_SK not in ("RELATIONSHIP#state", ccs.BITS_SK)
    assert ccs.PEOPLE_SK.startswith("RELATIONSHIP#")


# ── H6: names never reach an off-box log ─────────────────────────────────────


def _logged(caplog):
    return "\n".join([r.getMessage() for r in caplog.records] + [str(r.msg) for r in caplog.records])


def test_the_happy_path_logs_a_count_and_never_a_name(caplog):
    caplog.set_level(logging.DEBUG)
    table = _FakeTable([_turn("2026-08-08", "aa", "matthew", "Dana came over")])
    ccs.ensure_daily_summary(table, PK, "T", _reply("Note.\nPEOPLE:\n- Dana"), today="2026-08-09")
    assert [p for p in table.put_calls if p["sk"] == ccs.PEOPLE_SK], "nothing was stored — the assertion below would be vacuous"
    text = _logged(caplog)
    assert "Dana" not in text and "dana" not in text.lower(), text
    assert "1 remembered people" in text  # the count DOES ship


def test_the_error_path_logs_the_exception_class_not_its_message(caplog):
    """CloudWatch is off-box and a DynamoDB error can quote the item it rejected.
    'Names never appear in off-box logs' has to hold on the failure path too."""
    caplog.set_level(logging.DEBUG)

    class _Leaky(_FakeTable):
        def put_item(self, Item=None, **kw):
            if Item["sk"] == ccs.PEOPLE_SK:
                raise RuntimeError("ValidationException on item {'people': [{'text': 'Dana'}]}")
            return super().put_item(Item=Item, **kw)

    table = _Leaky([_turn("2026-08-08", "aa", "matthew", "Dana came over")])
    assert ccs.ensure_daily_summary(table, PK, "T", _reply("Note.\nPEOPLE:\n- Dana"), today="2026-08-09") == "2026-08-08"
    text = _logged(caplog)
    assert "people write failed" in text, text
    assert "Dana" not in text, text


def test_a_failing_relationship_read_logs_no_payload(caplog):
    caplog.set_level(logging.DEBUG)

    class _Boom:
        def query(self, **kw):
            raise RuntimeError("row was {'people': [{'text': 'Dana'}]}")

    assert ccs.read_relationship_memory(_Boom(), PK) == ([], [])
    assert "Dana" not in _logged(caplog), _logged(caplog)


# ── H7: reset semantics ──────────────────────────────────────────────────────


def test_the_people_row_is_cross_phase_and_survives_a_reset():
    """A reset re-anchors the experiment; it does not un-introduce his sister."""
    from experiment import phase_taxonomy

    assert phase_taxonomy.classify(PK, ccs.PEOPLE_SK) == phase_taxonomy.CROSS_PHASE
    assert phase_taxonomy.classify(PK, ccs.BITS_SK) == phase_taxonomy.CROSS_PHASE
