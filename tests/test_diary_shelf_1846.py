"""#1846 — the consent-gated diary shelf on /story.

The diary is the newest station of the loop's STORY arm and had no surface on the
site it narrates. This suite pins the boundary that lets it have one:

  AC1  an entry with no explicit consent marker is INVISIBLE — no card, no
       redacted row, no ghost — but it IS counted in `withheld`; a consented
       entry renders as a card carrying only the lines Matthew separately marked
       publishable, and a line that fails ANY serve-time screen is withheld
       whole (never mangled) and counted.
  AC2  the card's day-mark is the canonical daily fingerprint (`web.fingerprint`)
       — byte-identical to the cockpit masthead / wall / studio-HUD artifact.
  AC3  reset-aware (ADR-077): each card is stamped with the CYCLE it was recorded
       in and its day number WITHIN that cycle, and the shelf is deliberately not
       phase-filtered, so a consented entry survives a reset like its quotes do.
  AC4  the page is registered in the two page registries (qa_manifest MANIFEST +
       site_review_bindings PAGE_BINDINGS) and the route is wired.

The load-bearing assertion is the leak test: not one token of an entry's private
body may appear anywhere in the payload, for any consent tier.
"""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.join(_REPO, "tests"))
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

NOTION_PK = "USER#matthew#SOURCE#notion"
QUOTES_PK = "USER#matthew#SOURCE#journal_quotes"
CLAIMS_PK = "USER#matthew#SOURCE#diary_claims"

# The private body. Every distinctive token is a canary — if one ever shows up in
# a payload, the boundary is broken.
SECRET_BODY = (
    "Sat down at the desk and admitted the whole thing out loud. The relapse last "
    "Thursday, the argument with Dana, the number on the scale I have not said to "
    "anyone. I want to stop hiding it and I keep hiding it."
)
CANARIES = ["dana", "relapse", "thursday", "hiding", "scale", "argument"]

# A line clean enough to survive every screen (no substances, no names, no ages,
# no family specifics, no PII).
CLEAN_LINE = "I keep starting over and I have stopped calling that a failure."


class FakeTable:
    """Minimal DDB stand-in: query by pk + sk-prefix, honouring ScanIndexForward."""

    def __init__(self):
        self.store: dict[tuple, dict] = {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def query(self, KeyConditionExpression=None, ScanIndexForward=True, Limit=None, ExclusiveStartKey=None, **kw):
        expr = KeyConditionExpression.get_expression()
        left, right = expr["values"]
        pk = left.get_expression()["values"][1]
        sk_prefix = right.get_expression()["values"][1]
        rows = [(s, dict(v)) for (p, s), v in self.store.items() if p == pk and s.startswith(sk_prefix)]
        rows.sort(key=lambda kv: kv[0], reverse=not ScanIndexForward)
        return {"Items": [v for _s, v in rows]}


def _entry(date="2026-07-27", channel="video_diary", suffix="1", **over):
    item = {
        "pk": NOTION_PK,
        "sk": f"DATE#{date}#journal#{channel}#{suffix}",
        "channel": channel,
        "template": "Video Diary" if channel == "video_diary" else "Solo Recording",
        "raw_text": SECRET_BODY,
        "body_text": SECRET_BODY,
        "enriched_notable_quote": "the number on the scale I have not said to anyone",
        "enriched_themes": ["relapse", "shame", "identity"],
        "date": date,
    }
    item.update(over)
    return item


def _quote(date, text, channel="video_diary", grounding="verified"):
    return {
        "pk": QUOTES_PK,
        "sk": jq.quote_sk(date, text),
        "date": date,
        "quote": text,
        "channel": channel,
        "grounding": grounding,
        "marked_at": f"{date}T20:00:00Z",
    }


@pytest.fixture()
def shelf(monkeypatch):
    """The handler module wired to a fake table and a stub metrics index."""
    from web import site_api_diary as sd

    ft = FakeTable()
    monkeypatch.setattr(sd, "table", ft)
    # Real metrics would need three source queries; the mark's geometry is what
    # matters here, and build_mark is pure, so a fixed index keeps it deterministic.
    monkeypatch.setattr(sd, "_metrics_index", lambda a, b: {"2026-07-27": {"recovery": 62.0, "sleep_hours": 7.4, "steps": 9100}})
    return sd, ft


def _body(resp):
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])["shelf"]


def _call(sd, **qs):
    return _body(sd.handle_diary_shelf({"queryStringParameters": qs or None}))


def _flatten(obj):
    """Every string anywhere in the payload, lowercased — so a canary can't hide
    in a nested value."""
    return json.dumps(obj).lower()


# ── AC1: consent decides visibility ──────────────────────────────────────────


def test_unconsented_entry_is_invisible_but_counted(shelf):
    """The whole point. An entry with no marker produces NO card — not a redacted
    one, not a locked one — and the reader still learns one exists."""
    sd, ft = shelf
    ft.put_item(Item=_entry())
    body = _call(sd)
    assert body["entries"] == []
    assert body["count"] == 0
    assert body["withheld"] == 1


@pytest.mark.parametrize("marker", [None, "", "public_ok", "PUBLIC", "yes", 1, "quote ", "  "])
def test_only_the_exact_opt_in_values_clear_an_entry(shelf, marker):
    """Fail-closed: consent is never inferred. Anything that is not exactly
    `quote` or `allude` (post-strip/lower) leaves the entry invisible."""
    sd, ft = shelf
    over = {} if marker is None else {"public_reaction_consent": marker}
    ft.put_item(Item=_entry(**over))
    body = _call(sd)
    if str(marker).strip().lower() in ("quote", "allude"):
        assert body["count"] == 1
    else:
        assert body["count"] == 0 and body["withheld"] == 1


def test_consented_entry_renders_a_card_with_no_quotes_when_no_line_was_marked(shelf):
    """A card can exist carrying his day and none of his words — that is the
    normal case, since the entry grant and the per-line grant are separate."""
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="allude"))
    body = _call(sd)
    assert body["count"] == 1 and body["withheld"] == 0
    card = body["entries"][0]
    assert card["date"] == "2026-07-27"
    assert card["channel"] == "video_diary" and card["format"] == "video diary"
    assert card["tier"] == "allude"
    assert card["quotes"] == [] and card["quotes_withheld"] == 0


def test_a_marked_line_appears_verbatim_on_its_entrys_card(shelf):
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="quote"))
    ft.put_item(Item=_quote("2026-07-27", CLEAN_LINE))
    card = _call(sd)["entries"][0]
    assert [q["quote"] for q in card["quotes"]] == [CLEAN_LINE]
    assert card["quotes_withheld"] == 0


def test_a_marked_line_never_appears_on_an_unconsented_entry(shelf):
    """The conservative composition: a card is a wider frame than the line it
    holds, so no card ⇒ no quote, even though the line itself carries a mark."""
    sd, ft = shelf
    ft.put_item(Item=_entry())  # no marker
    ft.put_item(Item=_quote("2026-07-27", CLEAN_LINE))
    body = _call(sd)
    assert body["entries"] == [] and body["withheld"] == 1
    assert CLEAN_LINE.lower() not in _flatten(body)


def test_a_typed_journal_quote_never_lands_on_the_diary_shelf(shelf):
    """channel=journal lines belong to /story/journal/; the shelf shows only what
    was said on tape."""
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="quote"))
    ft.put_item(Item=_quote("2026-07-27", CLEAN_LINE, channel="journal"))
    card = _call(sd)["entries"][0]
    assert card["quotes"] == [] and card["quotes_withheld"] == 0


def test_a_typed_journal_entry_is_never_a_diary_card(shelf):
    """Even WITH a consent marker, a typed entry is not a diary entry — and it is
    not counted as a withheld diary entry either."""
    sd, ft = shelf
    ft.put_item(
        Item={
            "pk": NOTION_PK,
            "sk": "DATE#2026-07-27#journal#evening",
            "channel": "journal",
            "public_reaction_consent": "quote",
            "raw_text": SECRET_BODY,
        }
    )
    body = _call(sd)
    assert body["count"] == 0 and body["withheld"] == 0


def test_a_line_the_current_taboo_vocabulary_refuses_is_withheld_and_counted(shelf):
    """#1804's lesson, applied here: the screen re-runs on every serve against
    TODAY's vocabulary, and a failing line is withheld ENTIRE — never mangled —
    with the withholding disclosed rather than silently swallowed."""
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="quote"))
    ft.put_item(Item=_quote("2026-07-27", "Two beers in and I said the quiet part out loud."))
    card = _call(sd)["entries"][0]
    assert card["quotes"] == []
    assert card["quotes_withheld"] == 1
    assert "beers" not in _flatten(card)


def test_a_line_whose_grounding_is_not_verified_is_withheld(shelf):
    """ADR-104: a mark made before the day's entry was ingested is honestly
    `pending_ingestion` and does not serve until it is re-verified."""
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="quote"))
    ft.put_item(Item=_quote("2026-07-27", CLEAN_LINE, grounding="pending_ingestion"))
    card = _call(sd)["entries"][0]
    assert card["quotes"] == [] and card["quotes_withheld"] == 1


@pytest.mark.parametrize("tier", ["quote", "allude"])
def test_no_private_body_token_ever_reaches_the_payload(shelf, tier):
    """The leak assertion. `raw_text`, `body_text`, the enrichment tags and
    `enriched_notable_quote` are never read by this module — for ANY tier."""
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent=tier))
    ft.put_item(Item=_quote("2026-07-27", CLEAN_LINE))
    blob = _flatten(_call(sd))
    for canary in CANARIES:
        assert canary not in blob, f"private token {canary!r} leaked into the shelf payload"
    assert "notable_quote" not in blob


def test_the_theme_is_the_coarse_laundered_category_not_the_raw_tag(shelf):
    """Raw enrichment tags ("relapse", "shame") are private vocabulary; only the
    8-way public category may cross."""
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="allude"))
    card = _call(sd)["entries"][0]
    assert card["theme"] in (
        "anxiety_stress",
        "health_body",
        "relationships",
        "work_ambition",
        "gratitude",
        "personal_growth",
        "reflection",
        "other",
    )


# ── ADR-104: absence is absence ──────────────────────────────────────────────


def test_duration_is_omitted_entirely_when_no_transcript_measured_one(shelf):
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="allude"))
    assert "duration" not in _call(sd)["entries"][0]


def test_duration_is_reported_when_the_transcript_measured_one(shelf):
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="allude", vocal_duration_s=401))
    duration = _call(sd)["entries"][0]["duration"]
    assert duration == {"seconds": 401, "label": "6:41"}


@pytest.mark.parametrize("bad", [0, -12, "", None, "not-a-number"])
def test_a_zero_or_unparseable_duration_is_absence_not_zero(shelf, bad):
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="allude", vocal_duration_s=bad))
    assert "duration" not in _call(sd)["entries"][0]


def test_an_empty_shelf_is_honest_not_padded(shelf):
    sd, _ft = shelf
    body = _call(sd)
    assert body == {
        "entries": [],
        "count": 0,
        "withheld": 0,
        "label": sd.PUBLIC_LABEL,
        "note": sd.SHELF_NOTE,
    }


# ── AC2: one visual system ───────────────────────────────────────────────────


def test_the_day_mark_is_the_canonical_daily_fingerprint(shelf):
    """Not a bespoke glyph: the same artifact web.fingerprint renders for the
    cockpit masthead, the wall and the studio HUD, for that date's real metrics."""
    from web.fingerprint import build_mark, mark_to_svg

    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="allude"))
    card = _call(sd)["entries"][0]
    expected = mark_to_svg(build_mark("2026-07-27", {"recovery": 62.0, "sleep_hours": 7.4, "steps": 9100}), size=sd._MARK_PX)
    assert card["day_mark"]["svg"] == expected
    assert card["day_mark"]["warming_up"] is False


def test_a_thin_day_yields_a_warming_up_mark_not_a_faked_one(shelf, monkeypatch):
    sd, ft = shelf
    monkeypatch.setattr(sd, "_metrics_index", lambda a, b: {})
    ft.put_item(Item=_entry(public_reaction_consent="allude"))
    assert _call(sd)["entries"][0]["day_mark"]["warming_up"] is True


# ── AC3: reset-aware (ADR-077) ───────────────────────────────────────────────


def test_each_card_is_stamped_with_its_own_cycle_and_day_within_it(shelf, monkeypatch):
    """A reset re-anchors the counting rather than orphaning or renumbering the
    archive: an entry recorded in cycle 10 keeps saying cycle 10, day 3."""
    from web import site_api_data as sad

    sd, ft = shelf
    monkeypatch.setattr(sad, "CYCLE_GENESES", {10: "2026-07-22", 11: "2026-07-27"})
    monkeypatch.setattr(sd, "_metrics_index", lambda a, b: {})
    ft.put_item(Item=_entry(date="2026-07-24", public_reaction_consent="allude", suffix="1"))
    ft.put_item(Item=_entry(date="2026-07-27", public_reaction_consent="allude", suffix="2"))
    by_date = {e["date"]: e for e in _call(sd)["entries"]}
    assert (by_date["2026-07-24"]["cycle"], by_date["2026-07-24"]["day_number"]) == (10, 3)
    assert (by_date["2026-07-27"]["cycle"], by_date["2026-07-27"]["day_number"]) == (11, 1)


def test_a_pre_genesis_entry_reports_no_cycle_rather_than_a_fabricated_day_one(shelf, monkeypatch):
    """The #1824 lesson: never clamp a pre-genesis date to Day 1."""
    from web import site_api_data as sad

    sd, ft = shelf
    monkeypatch.setattr(sad, "CYCLE_GENESES", {11: "2026-07-27"})
    monkeypatch.setattr(sd, "_metrics_index", lambda a, b: {})
    ft.put_item(Item=_entry(date="2026-07-20", public_reaction_consent="allude"))
    card = _call(sd)["entries"][0]
    assert card["cycle"] is None and card["day_number"] is None


def test_the_shelf_is_not_phase_filtered(shelf):
    """Like the journal_quotes channel it composes with, the shelf is cross-phase
    by design — a consented entry leaves it only by an explicit unmark, never by
    a reset. Pinned structurally so a later 'tidy-up' can't quietly add one."""
    import inspect

    from web import site_api_diary as sd

    src = inspect.getsource(sd)
    assert "with_phase_filter" not in src


# ── #1841: on-tape claims stay private unless separately marked ──────────────


def test_claims_are_counted_but_never_quoted_without_their_own_marker(shelf):
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="allude"))
    ft.put_item(
        Item={
            "pk": CLAIMS_PK,
            "sk": "PREDICTION#2026-07-27#coast-on-the-habits",
            "source_sk": "DATE#2026-07-27#journal#video_diary#1",
            "claim_natural": "If I get through sixty days I coast on the habits after that.",
            "visibility": "private",
        }
    )
    card = _call(sd)["entries"][0]
    assert card["claims_on_record"] == 1
    assert card["claims"] == []
    assert "coast on the habits" not in _flatten(card)


def test_a_publicly_marked_claim_is_projected_from_the_allowlist_only(shelf):
    sd, ft = shelf
    ft.put_item(Item=_entry(public_reaction_consent="quote"))
    ft.put_item(
        Item={
            "pk": CLAIMS_PK,
            "sk": "PREDICTION#2026-07-27#sixty-days",
            "source_sk": "DATE#2026-07-27#journal#video_diary#1",
            "claim_id": "2026-07-27#sixty-days",
            "claim_natural": "I will still be logging every day in sixty days.",
            "metric": "adherence",
            "grade_by": "2026-09-25",
            "status": "pending",
            "visibility": "public",
            # Fields OUTSIDE the allowlist must not ride along.
            "criterion": "internal grading criterion text",
            "source_pk": NOTION_PK,
        }
    )
    card = _call(sd)["entries"][0]
    assert card["claims_on_record"] == 1
    claim = card["claims"][0]
    assert claim["claim_natural"] == "I will still be logging every day in sixty days."
    assert claim["grade_by"] == "2026-09-25"
    assert set(claim) <= set(sd.CLAIM_PUBLIC_FIELDS)
    assert "internal grading criterion" not in _flatten(card)


# ── AC4: wiring + registration ───────────────────────────────────────────────


def test_route_is_wired_to_the_handler():
    import inspect

    from web import site_api_lambda as L

    src = inspect.getsource(L.lambda_handler)
    assert '"/api/diary_shelf"' in src and "handle_diary_shelf" in src
    assert callable(L.handle_diary_shelf)


def test_the_page_is_registered_in_both_page_registries():
    import qa_manifest
    import site_review_bindings

    page = next((p for p in qa_manifest.MANIFEST if p["path"] == "/story/diary/"), None)
    assert page is not None, "/story/diary/ missing from tests/qa_manifest.py"
    assert page["api_deps"] == ["/api/diary_shelf"]
    assert "diary_shelf.js" in page["js_modules"]

    binding = next((b for b in site_review_bindings.PAGE_BINDINGS if b["path"] == "/story/diary/"), None)
    assert binding is not None, "/story/diary/ missing from PAGE_BINDINGS"
    assert binding["door"] == "story"
    assert binding["endpoints"][0]["url"] == "/api/diary_shelf"


def test_the_page_shell_mounts_the_shelf_module():
    path = os.path.join(_REPO, "site", "story", "diary", "index.html")
    html = open(path, encoding="utf-8").read()
    assert "data-diary-shelf" in html
    assert "/assets/js/diary_shelf.js" in html
    assert 'href="https://averagejoematt.com/story/diary/"' in html


def test_the_new_site_surface_is_scanned_and_never_allowlisted():
    """The content-policy scanner must cover the new JS + shell (the #1568 AC3
    pattern) — a public surface outside the scanner's scope is how leaks ship."""
    assert "site" in cps.SCAN_DIRS
    assert not cps.is_allowlisted("site/assets/js/diary_shelf.js")
    assert not cps.is_allowlisted("site/story/diary/index.html")
