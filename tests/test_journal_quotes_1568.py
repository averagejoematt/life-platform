"""#1568 (ADR-142) — opt-in verbatim journal pull-quotes: "from the journal, in his words".

Pins every acceptance criterion of the consent-per-line verbatim channel:

  AC1  write path: mark_journal_quote is the ONLY way a line becomes quotable —
       explicit approved=true per line, fail-closed taboo gate BEFORE any write,
       ADR-104 grounding against the day's ingested entry, the 0–2/day cap,
       revocable unmark. Nothing is ever quotable without a mark.
  AC2  public render: /api/journal_quotes serves dated verbatim quotes with a
       receipts link + the label; `featured` enforces the max-1-per-week home
       cap deterministically; absent data ⇒ honest empty (dormant surfaces).
  AC3  scanner + guard coverage: the new site surface is inside the content-policy
       scanner's scope and NEVER allowlisted; the ELENA taboo list is enforced at
       mark time in code (substances / family-specifics / age / private events /
       real names), with privacy_guard reused as the substance/name base set.
  AC4  the shared ADR: ADR-142 exists, defines the three tiers, and names #1483
       as the allude-tier implementer; the chronicle's never-quote rule is
       untouched; the command doc encodes the nomination rules.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, _REPO)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import content_policy_scan as cps  # noqa: E402
import pytest  # noqa: E402
from content import journal_quotes as jq  # noqa: E402
from experiment import phase_taxonomy as pt  # noqa: E402
from privacy import privacy_guard  # noqa: E402
from skill_paths import require_skill as _skill  # the ONE skill registry (no hard-coded .claude paths)
from web import site_api_common as sac  # noqa: E402 — reuse the real normalizer, not a copy of it

from mcp import tools_journal as tj  # noqa: E402

DECISIONS = os.path.join(_REPO, "docs", "DECISIONS.md")
COMMAND_DOC = str(_skill("journal-interview"))

CLEAN_LINE = "I used to be a main character - and I feel like an extra in my own life now."


# ── The pure taboo gate (AC3: enforced at mark time, in code) ─────────────────
def test_clean_line_is_markable():
    assert jq.find_mark_violations(CLEAN_LINE) == []
    assert jq.is_markable(CLEAN_LINE)


@pytest.mark.parametrize(
    "line,category",
    [
        ("I really wanted a fizzlewick tonight", "substances"),  # privacy_guard base set (neutral fixture vocab, #2370)
        ("two beers and I was drunk by nine", "substances"),  # the widened alcohol family
        ("my sister called about the estate", "family_specifics"),
        ("dinner with my mother-in-law went sideways", "family_specifics"),
        ("we cancelled the wedding trip", "private_event"),
        ("my therapist said the same thing", "private_event"),
        ("I'm 45 and starting over", "age"),
        ("turning 46 next month scares me", "age"),
        ("I feel every one of my 45 years old bones", "age"),
    ],
)
def test_taboo_lines_are_refused(line, category):
    cats = {c for c, _ in jq.find_mark_violations(line)}
    assert category in cats, f"{line!r} should trip {category}, got {cats}"


def test_privacy_guard_vice_set_is_the_enforced_base():
    """Reuse, not a parallel list: every privacy_guard vice keyword is refused here too."""
    for kw in privacy_guard.VICE_KEYWORDS:
        assert not jq.is_markable(f"thinking about {kw} again"), kw


def test_real_names_are_refused_at_mark_time():
    assert not jq.is_markable("huberman said to get morning light")


def test_empty_line_is_never_markable():
    assert not jq.is_markable("")
    assert not jq.is_markable("   ")


# ── Grounding + sk determinism (AC1) ─────────────────────────────────────────
def test_grounding_is_whitespace_and_case_insensitive_but_verbatim():
    body = "Long day.  I said it plainly:\n" + CLEAN_LINE + "\nThen bed."
    assert jq.grounds_in(CLEAN_LINE.upper(), body)
    assert not jq.grounds_in("I feel like the main character again", body)  # paraphrase ⇒ no


def test_quote_sk_is_deterministic_and_normalised():
    a = jq.quote_sk("2026-07-25", CLEAN_LINE)
    b = jq.quote_sk("2026-07-25", "  " + CLEAN_LINE.replace(" - ", " - ") + "  ")
    assert a == b and a.startswith("QUOTE#2026-07-25#")


# ── The weekly featured cap (AC2: max 1 featured/week, deterministic) ─────────
def _q(d, marked_at):
    return {"date": d, "quote": "x", "marked_at": marked_at}


def test_featured_is_first_marked_of_the_current_iso_week_and_stable():
    today = date(2026, 7, 24)  # Friday of ISO week 2026-W30 (Mon 2026-07-20)
    quotes = [
        _q("2026-07-21", "2026-07-21T20:00:00Z"),
        _q("2026-07-23", "2026-07-23T20:00:00Z"),  # marked later the same week
        _q("2026-07-12", "2026-07-12T20:00:00Z"),  # previous week — archive only
    ]
    f = jq.featured_for_week(quotes, today)
    assert f and f["date"] == "2026-07-21"  # first-marked wins; a later mark never rotates the slot
    assert jq.featured_for_week(quotes, today) == f  # deterministic


def test_no_quote_this_week_means_no_featured():
    assert jq.featured_for_week([_q("2026-07-12", "2026-07-12T20:00:00Z")], date(2026, 7, 24)) is None
    assert jq.featured_for_week([], date(2026, 7, 24)) is None


def test_shape_public_carries_date_label_and_receipts_link():
    shaped = jq.shape_public({"date": "2026-07-21", "quote": CLEAN_LINE, "marked_at": "2026-07-21T20:00:00Z"})
    assert shaped["date"] == "2026-07-21"
    assert shaped["label"] == "from the journal, in his words"
    assert shaped["receipts"] == "/cockpit/?date=2026-07-21"
    assert shaped["quote"] == CLEAN_LINE


# ── The MCP write path (AC1) ─────────────────────────────────────────────────
class FakeTable:
    """Minimal DDB stand-in: query by pk + sk-prefix, put/delete."""

    def __init__(self):
        self.store: dict[tuple, dict] = {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def delete_item(self, Key, ReturnValues=None):
        old = self.store.pop((Key["pk"], Key["sk"]), None)
        return {"Attributes": old} if (ReturnValues == "ALL_OLD" and old is not None) else {}

    def update_item(self, Key, UpdateExpression=None, ConditionExpression=None, ExpressionAttributeValues=None):
        # Enough for the list re-verify upgrade: SET grounding = :v IF grounding = :p
        item = self.store.get((Key["pk"], Key["sk"]))
        if item is None:
            raise Exception("ConditionalCheckFailedException")
        vals = ExpressionAttributeValues or {}
        if ConditionExpression and item.get("grounding") != vals.get(":p"):
            raise Exception("ConditionalCheckFailedException")
        item["grounding"] = vals.get(":v")

    def query(self, KeyConditionExpression=None, **kw):
        # Resolve the boto3 condition into (pk, sk_prefix) — enough for these paths.
        expr = KeyConditionExpression.get_expression()
        left, right = expr["values"]
        pk = left.get_expression()["values"][1]
        sk_prefix = right.get_expression()["values"][1]
        items = [dict(v) for (p, s), v in sorted(self.store.items()) if p == pk and s.startswith(sk_prefix)]
        return {"Items": items}


ENTRY_PK = "USER#matthew#SOURCE#notion"
QUOTES_PK = "USER#matthew#SOURCE#journal_quotes"


@pytest.fixture()
def fake_table(monkeypatch):
    ft = FakeTable()
    ft.put_item(Item={"pk": ENTRY_PK, "sk": "DATE#2026-07-25#journal#evening", "raw_text": "Rough one. " + CLEAN_LINE + " Slept early."})
    monkeypatch.setattr(tj, "table", ft)
    return ft


def test_mark_requires_explicit_per_line_approval(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE})
    assert "error" in out and "approved" in out["error"]
    assert not any(pk == QUOTES_PK for pk, _ in fake_table.store)  # nothing written

    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": "yes"})
    assert "error" in out  # truthy-but-not-True is refused — never inferred


def test_mark_refuses_taboo_lines_before_any_write(fake_table):
    fake_table.put_item(Item={"pk": ENTRY_PK, "sk": "DATE#2026-07-24#journal#evening", "raw_text": "my sister called about the estate"})
    out = tj.tool_mark_journal_quote({"date": "2026-07-24", "quote": "my sister called about the estate", "approved": True})
    assert "error" in out and out["violations"]
    assert not any(pk == QUOTES_PK for pk, _ in fake_table.store)


def test_mark_refuses_a_paraphrase_adr104(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": "I feel like a side character lately", "approved": True})
    assert "error" in out and "verbatim" in out["error"]


def test_mark_happy_path_writes_the_consent_record(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    assert out.get("status") == "marked" and out["grounding"] == "verified"
    item = fake_table.store[(QUOTES_PK, out["sk"])]
    assert item["quote"] == CLEAN_LINE and item["date"] == "2026-07-25"
    assert item["guard_version"] == privacy_guard.GUARD_VERSION


def test_mark_is_idempotent_and_capped_at_two_per_day(fake_table):
    tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})  # re-mark: overwrite
    assert len([1 for pk, _ in fake_table.store if pk == QUOTES_PK]) == 1

    fake_table.put_item(Item={"pk": ENTRY_PK, "sk": "DATE#2026-07-25#journal#morning", "raw_text": "Second line here. Third line too."})
    out2 = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": "Second line here.", "approved": True})
    assert out2.get("status") == "marked"
    out3 = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": "Third line too.", "approved": True})
    assert "error" in out3 and "cap" in out3["error"]


def test_mark_without_ingested_entry_records_pending_grounding(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-26", "quote": "A brand new day deserves a brand new sentence.", "approved": True})
    assert out.get("status") == "marked" and out["grounding"] == "pending_ingestion"


def test_unmark_revokes_consent(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    assert out.get("status") == "marked"
    out2 = tj.tool_mark_journal_quote({"action": "unmark", "date": "2026-07-25", "quote": CLEAN_LINE})
    assert out2["status"] == "revoked"
    assert not any(pk == QUOTES_PK for pk, _ in fake_table.store)


# ── The public serve path (AC2) ──────────────────────────────────────────────
@pytest.fixture()
def coach_module(monkeypatch):
    from web import site_api_coach as sc

    ft = FakeTable()
    monkeypatch.setattr(sc, "table", ft)
    return sc, ft


def _body(resp):
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


def test_endpoint_serves_honest_empty_when_nothing_is_marked(coach_module):
    sc, _ = coach_module
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["quotes"] == [] and body["count"] == 0 and body["featured"] is None


def test_endpoint_serves_dated_labeled_quotes_with_receipts(coach_module):
    sc, ft = coach_module
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk("2026-07-21", CLEAN_LINE),
            "date": "2026-07-21",
            "quote": CLEAN_LINE,
            "marked_at": "2026-07-21T20:00:00Z",
            "grounding": "verified",
        }
    )
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["count"] == 1
    q = body["quotes"][0]
    assert q["quote"] == CLEAN_LINE and q["date"] == "2026-07-21"
    assert q["label"] == "from the journal, in his words"
    assert q["receipts"] == "/cockpit/?date=2026-07-21"


def test_endpoint_withholds_a_quote_the_first_screen_flags(coach_module):
    """First-layer pin (#2203 correction — this test previously mis-claimed to pin
    the second/defense-in-depth layer, but its fixture trips jq.find_mark_violations
    (the FULL taboo vocabulary — substances/real-name/family/private-event/age)
    outright, so the handler `continue`s before `_public_decision_note` (the
    narrower #1569 all-or-nothing scrub) is ever reached. It's a real regression
    test for the wider gate, just not the one its old docstring described. See
    test_endpoint_withholds_a_quote_only_the_second_screen_would_catch below for a
    fixture that actually exercises the second layer."""
    sc, ft = coach_module
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk("2026-07-21", "zzq on my mind"),
            "date": "2026-07-21",
            "quote": "zzq on my mind",
            "marked_at": "2026-07-21T20:00:00Z",
            "grounding": "verified",
        }
    )
    # Precondition that motivates this being a first-layer (not second-layer) test:
    # the fixture trips find_mark_violations itself.
    assert jq.find_mark_violations("zzq on my mind") != []
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["quotes"] == [] and body["featured"] is None


def test_endpoint_withholds_a_quote_only_the_second_screen_would_catch(coach_module):
    """Genuine second-layer pin (#2203, the #1569/ADR-142 all-or-nothing rule via
    `_public_decision_note`).

    The wider gate (jq.find_mark_violations) matches its taboo vocabulary with
    \\b-anchored word-boundary regexes, so a term broken up with letter-spacing
    never matches — the fixture below clears find_mark_violations outright (see
    the inline assertion). The narrower gate's underlying scrub
    (site_api_common._scrub_blocked_terms) additionally normalizes the text
    (strips whitespace/punctuation, lowercases) before checking for a long,
    unambiguous vice term and — if one turns up only in that normalized form —
    refuses the WHOLE text rather than surgically excising an obfuscated span.
    That refusal makes the scrubbed text differ from the raw quote, so
    _public_decision_note (the #1569 all-or-nothing rule) returns None and the
    handler withholds the quote — this is the ONLY one of the two screens that
    catches this fixture, so a screen-2 regression genuinely reds this test.

    The vice term is pulled live from the ER-06 channel (#2370: the same
    non-committed source _scrub_blocked_terms enforces at runtime — the unit
    suite sees conftest's neutral fixture vocabulary) rather than hardcoded, so
    the fixture tracks the configured vocabulary instead of a copy of it."""
    sc, ft = coach_module
    from privacy import content_filter_channel

    keywords = content_filter_channel.blocked_keywords(require=True)
    # _scrub_blocked_terms's normalized fail-safe only fires for terms whose
    # de-spaced form is >=7 chars (see its docstring) — pick the shortest term
    # that qualifies, so the fixture stays as mild as the vocabulary allows.
    term = min(
        (kw for kw in keywords if len(sac._normalize_for_detection(kw)) >= 7),
        key=len,
    )
    obfuscated_term = " ".join(term)  # defeats the \b-anchored regex both screens' literal passes use
    quote = f"Almost reached for the {obfuscated_term} again tonight."

    # Empirically confirm the premise inline (not just asserted in the docstring):
    # screen 1 clears this fixture outright.
    assert jq.find_mark_violations(quote) == []

    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk("2026-07-22", quote),
            "date": "2026-07-22",
            "quote": quote,
            "marked_at": "2026-07-22T20:00:00Z",
            "grounding": "verified",
        }
    )
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["quotes"] == [] and body["featured"] is None


def test_endpoint_featured_respects_the_weekly_cap(coach_module):
    sc, ft = coach_module
    # The handler features by the PACIFIC week (datetime.now(PT) in site_api_coach);
    # a naive date.today() is the UTC date on CI runners, which sits one week ahead
    # every Sunday 17:00–24:00 PT — the quotes land in next week's bucket and
    # featured comes back None (first fired the night before genesis, run 30229507611).
    today = datetime.now(sc.PT).date()
    monday, _sunday = jq.week_bounds(today)
    d = monday.strftime("%Y-%m-%d")
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk(d, "This week I kept the promise."),
            "date": d,
            "quote": "This week I kept the promise.",
            "marked_at": f"{d}T08:00:00Z",
            "grounding": "verified",
        }
    )
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk(d, "A second marked line."),
            "date": d,
            "quote": "A second marked line.",
            "marked_at": f"{d}T09:00:00Z",
            "grounding": "verified",
        }
    )
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["count"] == 2  # archive carries both
    assert body["featured"]["quote"] == "This week I kept the promise."  # home gets exactly one


def test_route_is_wired_to_the_handler():
    import inspect

    from web import site_api_lambda as L

    # #2876 moved this inline branch from `lambda_handler` into `_dispatch_route`,
    # the single dispatch exit point every route now funnels through.
    src = inspect.getsource(L._dispatch_route)
    assert '"/api/journal_quotes"' in src and "handle_journal_quotes" in src
    assert callable(L.handle_journal_quotes)


# ── Scanner + guard coverage (AC3) ───────────────────────────────────────────
def test_scanner_scope_covers_the_new_surface_and_never_allowlists_it():
    assert "site" in cps.SCAN_DIRS  # journal_quotes.js + the shells live under site/
    assert not cps.is_allowlisted("site/assets/js/journal_quotes.js")
    assert not any("journal_quotes" in a for a in cps.ALLOWLIST_FILES)
    # the MCP module carrying the tool is scanned and NOT allowlisted — the taboo
    # vocabulary lives in lambdas/journal_quotes.py (outside reader surfaces), so
    # the tool file itself must stay clean.
    assert not cps.is_allowlisted("mcp/tools_journal.py")


def test_phase_taxonomy_keeps_consent_records_across_resets():
    assert pt.classify("USER#matthew#SOURCE#journal_quotes", "QUOTE#2026-07-25#abc123") == pt.RAW_TIMESERIES


def test_chronicle_never_quote_rule_is_untouched():
    src = open(os.path.join(_REPO, "lambdas", "emails", "chronicle_prompt.py"), encoding="utf-8").read()
    assert "NEVER quote the journal directly" in src


# ── AC4: the shared ADR + the command-doc nomination rules ───────────────────
def test_adr_142_defines_the_three_tiers_and_governs_1483():
    text = open(DECISIONS, encoding="utf-8").read()
    m = re.search(r"^## ADR-142: .*$", text, re.M)
    assert m, "ADR-142 heading missing from docs/DECISIONS.md"
    body = text[m.start() :]
    for needle in ("verbatim-private", "theme-referenceable", "public-delta", "#1483", "#1568", "mark_journal_quote"):
        assert needle in body, f"ADR-142 must mention {needle!r}"


def test_command_doc_encodes_the_nomination_rules():
    doc = open(COMMAND_DOC, encoding="utf-8").read()
    norm = " ".join(doc.replace("**", "").replace("`", "").split())
    assert "0–2 lines, consent per line" in norm
    assert "ELENA_PREQUEL_BRIEF.md" in norm
    assert "mark_journal_quote" in norm
    assert "approved: true" in norm
    assert "The chronicle's never-quote rule is untouched" in norm


def test_adr_index_is_current():
    import subprocess

    r = subprocess.run([sys.executable, os.path.join(_REPO, "scripts", "generate_adr_index.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ── 2026-07-26 review-fix regressions ─────────────────────────────────────────


def test_beverage_nouns_trip_the_mark_gate():
    """Review P2: the alcohol family must cover beverage phrasings, not just
    intoxication states — 'split a bottle of wine' is exactly the class of line
    the brief says never ships."""
    for line in (
        "We split a bottle of wine with dinner.",
        "Had three beers watching the game.",
        "A couple of drinks took the edge off.",
        "Felt tipsy walking home.",
    ):
        assert jq.find_mark_violations(line), line


def test_endpoint_withholds_pending_ingestion_quotes(coach_module):
    """Review P2: a mark made before the day's Notion ingestion is grounding=
    pending_ingestion — it must NOT serve until the list action re-verifies it.
    Fail-closed: absent grounding never serves either."""
    sc, ft = coach_module
    for grounding in ("pending_ingestion", None):
        item = {
            "pk": QUOTES_PK,
            "sk": jq.quote_sk("2026-07-21", CLEAN_LINE),
            "date": "2026-07-21",
            "quote": CLEAN_LINE,
            "marked_at": "2026-07-21T20:00:00Z",
        }
        if grounding:
            item["grounding"] = grounding
        ft.put_item(Item=item)
        body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
        assert body["quotes"] == [] and body["featured"] is None, f"served with grounding={grounding!r}"


def test_remark_preserves_marked_at(fake_table):
    """Review P3: an idempotent re-mark must not refresh marked_at — the home
    featured slot keys on first-marked and would rotate mid-week."""
    first = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    assert first.get("status") == "marked"
    stored = fake_table.store[(QUOTES_PK, first["sk"])]
    stored["marked_at"] = "2026-07-20T00:00:00Z"  # pin an old timestamp, then re-mark
    again = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    assert again.get("status") == "marked"
    assert fake_table.store[(QUOTES_PK, again["sk"])]["marked_at"] == "2026-07-20T00:00:00Z"


def test_list_reverifies_pending_quotes(fake_table):
    """Review P2: the list action upgrades pending_ingestion → verified once the
    entry is ingested and the line grounds; a non-grounding line is flagged
    grounding_mismatch and the stored row stays withheld."""
    ok_sk = jq.quote_sk("2026-07-25", CLEAN_LINE)
    fake_table.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": ok_sk,
            "date": "2026-07-25",
            "quote": CLEAN_LINE,
            "marked_at": "2026-07-25T20:00:00Z",
            "grounding": "pending_ingestion",
        }
    )
    bad_sk = jq.quote_sk("2026-07-25", "A line he never actually wrote.")
    fake_table.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": bad_sk,
            "date": "2026-07-25",
            "quote": "A line he never actually wrote.",
            "marked_at": "2026-07-25T20:01:00Z",
            "grounding": "pending_ingestion",
        }
    )
    out = tj.tool_mark_journal_quote({"action": "list"})
    by_sk = {q["sk"]: q for q in out["quotes"]}
    assert by_sk[ok_sk]["grounding"] == "verified"
    assert fake_table.store[(QUOTES_PK, ok_sk)]["grounding"] == "verified"  # persisted upgrade
    assert by_sk[bad_sk]["grounding"] == "grounding_mismatch"  # advisory in the response…
    assert fake_table.store[(QUOTES_PK, bad_sk)]["grounding"] == "pending_ingestion"  # …stored row stays withheld


# ── #1802: revocation is verified, never asserted ─────────────────────────────
# A DDB delete on a missing key is a successful no-op; the sk is a content hash,
# so any byte drift between the typed text and the frozen bytes silently derives
# a different key. "revoked" must mean a row actually died.


def test_1802_unmark_miss_is_honest_not_found(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    assert out.get("status") == "marked"
    drifted = CLEAN_LINE.replace(" - ", " \u2014 ")  # one punctuation drift => different hash
    out2 = tj.tool_mark_journal_quote({"action": "unmark", "date": "2026-07-25", "quote": drifted})
    assert out2["status"] == "not_found"
    assert "NOTHING was revoked" in out2["error"]
    assert out2["marked_lines_for_date"] and out2["marked_lines_for_date"][0]["quote"] == CLEAN_LINE
    assert any(pk == QUOTES_PK for pk, _ in fake_table.store)  # the row SURVIVED


def test_1802_unmark_by_sk_needs_no_quote(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    sk = out["sk"]
    out2 = tj.tool_mark_journal_quote({"action": "unmark", "sk": sk})
    assert out2["status"] == "revoked" and out2["sk"] == sk
    assert not any(pk == QUOTES_PK for pk, _ in fake_table.store)


def test_1802_mark_advertises_sk_as_the_revoke_handle(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    assert out.get("status") == "marked"
    assert f"sk='{out['sk']}'" in out["revoke"]


# ── #1804: guard_version staleness is retroactively enforced at SERVE time ────
# guard_version was stamped at mark time but nothing ever read it, so the taboo
# gate never re-applied after the vocabulary widened. handle_journal_quotes now
# re-runs jq.find_mark_violations (the FULL vocabulary) on every serve — this
# catches marks that predate a widening even though they cleared the narrower
# _scrub_blocked_terms filter, which never covered the alcohol-beverage family.


def test_1804_clean_quote_still_serves_normally(coach_module):
    """No regression: a genuinely clean, verified quote keeps serving."""
    sc, ft = coach_module
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk("2026-07-21", CLEAN_LINE),
            "date": "2026-07-21",
            "quote": CLEAN_LINE,
            "marked_at": "2026-07-21T20:00:00Z",
            "grounding": "verified",
            "guard_version": "2026-06-28",
        }
    )
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["count"] == 1
    assert body["quotes"][0]["quote"] == CLEAN_LINE


def test_1804_serve_withholds_a_verified_quote_only_the_widened_gate_catches(coach_module):
    """A stored quote clean under the OLD narrow _scrub_blocked_terms list (it
    only blocks the channel vice-family terms, never the alcohol-beverage family)
    but caught by jq.find_mark_violations (SUBSTANCE_EXTRA) must be withheld at
    serve time — proving the re-screen is retroactive, not just mark-time."""
    sc, ft = coach_module
    beer_quote = "We split a bottle of wine and just talked for hours."
    assert jq.find_mark_violations(beer_quote)  # sanity: the wide gate catches it
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk("2026-07-21", beer_quote),
            "date": "2026-07-21",
            "quote": beer_quote,
            "marked_at": "2026-07-21T20:00:00Z",
            "grounding": "verified",
            "guard_version": "2026-06-28",  # stamped BEFORE the family was widened
        }
    )
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["quotes"] == [] and body["featured"] is None


def test_1804_guard_version_bumped_and_stale_check_is_true_for_old_stamp():
    assert privacy_guard.GUARD_VERSION == "2026-07-26"
    assert privacy_guard.is_stale_draft("2026-06-28") is True
    assert privacy_guard.is_stale_draft(privacy_guard.GUARD_VERSION) is False


def test_1804_new_marks_stamp_the_current_guard_version(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True})
    assert out.get("status") == "marked"
    assert fake_table.store[(QUOTES_PK, out["sk"])]["guard_version"] == privacy_guard.GUARD_VERSION


def test_1804_list_surfaces_guard_staleness_informationally(fake_table):
    """list is Matthew's private review surface — it must show guard_stale but
    never withhold (unlike the public serve path)."""
    fake_table.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk("2026-07-20", "An old marked line from before the widening."),
            "date": "2026-07-20",
            "quote": "An old marked line from before the widening.",
            "marked_at": "2026-07-20T20:00:00Z",
            "grounding": "verified",
            "guard_version": "2026-06-28",
        }
    )
    out = tj.tool_mark_journal_quote({"action": "list"})
    assert len(out["quotes"]) == 1
    assert out["quotes"][0]["guard_stale"] is True


# ── #1806: channel is allowlisted, never free text, fail-closed to "journal" ──


def test_1806_video_diary_channel_survives_mark_and_serve_unchanged(fake_table):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True, "channel": "video_diary"})
    assert out.get("status") == "marked"
    assert fake_table.store[(QUOTES_PK, out["sk"])]["channel"] == "video_diary"
    shaped = jq.shape_public(fake_table.store[(QUOTES_PK, out["sk"])])
    assert shaped["channel"] == "video_diary"


@pytest.mark.parametrize("bad_channel", ["<script>alert(1)</script>", "beer o'clock", "  ", "SOLO_RECORDING "])
def test_1806_unknown_or_malicious_channel_coerces_to_journal(fake_table, bad_channel):
    out = tj.tool_mark_journal_quote({"date": "2026-07-25", "quote": CLEAN_LINE, "approved": True, "channel": bad_channel})
    assert out.get("status") == "marked"
    stored_channel = fake_table.store[(QUOTES_PK, out["sk"])]["channel"]
    assert stored_channel in jq.CHANNELS
    if bad_channel.strip().lower() not in jq.CHANNELS:
        assert stored_channel == "journal"


def test_1806_shape_public_coerces_legacy_out_of_enum_channel_to_journal():
    """Defense-in-depth for rows written BEFORE the mark-time allowlist fix
    (simulated pre-fix legacy data with a raw free-text channel value)."""
    shaped = jq.shape_public({"date": "2026-07-21", "quote": CLEAN_LINE, "marked_at": "x", "channel": "some-legacy-garbage"})
    assert shaped["channel"] == "journal"


def test_1806_registry_schema_enums_the_channel_property():
    from mcp import registry

    schema = registry.TOOLS["mark_journal_quote"]["schema"]["inputSchema"]
    assert schema["properties"]["channel"].get("enum") == ["journal", "video_diary", "solo_recording"]
