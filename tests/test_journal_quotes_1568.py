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

import os
import re
import sys
from datetime import date

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
import journal_quotes as jq  # noqa: E402
import phase_taxonomy as pt  # noqa: E402
import privacy_guard  # noqa: E402
import pytest  # noqa: E402

from mcp import tools_journal as tj  # noqa: E402

DECISIONS = os.path.join(_REPO, "docs", "DECISIONS.md")
COMMAND_DOC = os.path.join(_REPO, ".claude", "commands", "journal-interview.md")

CLEAN_LINE = "I used to be a main character - and I feel like an extra in my own life now."


# ── The pure taboo gate (AC3: enforced at mark time, in code) ─────────────────
def test_clean_line_is_markable():
    assert jq.find_mark_violations(CLEAN_LINE) == []
    assert jq.is_markable(CLEAN_LINE)


@pytest.mark.parametrize(
    "line,category",
    [
        ("I really wanted an edible tonight", "substances"),  # privacy_guard base set
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

    def delete_item(self, Key):
        self.store.pop((Key["pk"], Key["sk"]), None)

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
    import json

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
        }
    )
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["count"] == 1
    q = body["quotes"][0]
    assert q["quote"] == CLEAN_LINE and q["date"] == "2026-07-21"
    assert q["label"] == "from the journal, in his words"
    assert q["receipts"] == "/cockpit/?date=2026-07-21"


def test_endpoint_withholds_a_quote_the_filter_would_alter(coach_module):
    """All-or-nothing (the #1569 verbatim rule): a stored line the serve-time content
    filter would touch is dropped entirely, never served mangled. Defense in depth —
    the mark gate refuses these anyway; this pins the second layer."""
    sc, ft = coach_module
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk("2026-07-21", "weed on my mind"),
            "date": "2026-07-21",
            "quote": "weed on my mind",
            "marked_at": "2026-07-21T20:00:00Z",
        }
    )
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["quotes"] == [] and body["featured"] is None


def test_endpoint_featured_respects_the_weekly_cap(coach_module):
    sc, ft = coach_module
    today = date.today()
    monday, _sunday = jq.week_bounds(today)
    d = monday.strftime("%Y-%m-%d")
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk(d, "This week I kept the promise."),
            "date": d,
            "quote": "This week I kept the promise.",
            "marked_at": f"{d}T08:00:00Z",
        }
    )
    ft.put_item(
        Item={
            "pk": QUOTES_PK,
            "sk": jq.quote_sk(d, "A second marked line."),
            "date": d,
            "quote": "A second marked line.",
            "marked_at": f"{d}T09:00:00Z",
        }
    )
    body = _body(sc.handle_journal_quotes({"queryStringParameters": None}))
    assert body["count"] == 2  # archive carries both
    assert body["featured"]["quote"] == "This week I kept the promise."  # home gets exactly one


def test_route_is_wired_to_the_handler():
    import inspect

    from web import site_api_lambda as L

    src = inspect.getsource(L.lambda_handler)
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
