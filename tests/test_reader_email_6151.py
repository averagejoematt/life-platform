"""#6151 — reader mail: no invented attribution, no ungated insight text, List-Unsubscribe, a text part.

Pins, through the real builders and handlers (SES, DynamoDB and S3 replaced by in-memory fakes — nothing
is sent, nothing reaches AWS):

  * The Weekly Signal no longer carries "The Board Says" — no fixed sentence under a rotating board name.
  * "What Worked This Week" renders ONLY a row the Site API's public narrative gate passes
    (web.narrative_publication.gate_item); an owner-only / unrecorded row never reaches the rendered email,
    in its HTML part or its text part; a public row is HTML-escaped.
  * Every reader send carries a text part and List-Unsubscribe; List-Unsubscribe-Post rides only on the signed
    one-click endpoint (the /privacy/ fallback is a page and gets the plain header only).
  * The reader templates declare color-scheme, carry a preheader, and their footer colour meets 4.5:1.
"""

import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

from common import (
    narrative_provenance as NP,  # noqa: E402
    reader_email as RE,  # noqa: E402
)

SITE = "https://averagejoematt.com"
CANARY = "OWNERONLYCANARY guidance sentence that must never reach a reader"
SECRET = "unit-test-unsub-secret-0123456789abcdef"


@pytest.fixture(autouse=True)
def _unsub_secret(monkeypatch):
    monkeypatch.setenv("UNSUB_TOKEN_SECRET", SECRET)


def _family(cls):
    return next(f for f, c in sorted(NP.SOURCE_FAMILIES.items()) if c == cls)


def _insight_row(text, provenance=None, field="top_insight"):
    row = {"pk": "USER#matthew#SOURCE#computed_insights", "sk": "DATE#2026-11-20", field: text}
    if provenance is not None:
        row[NP.PROVENANCE_KEY] = provenance
    return row


# ── the shared envelope ─────────────────────────────────────────────────────────────────────


def _contrast(fg, bg):
    def lum(h):
        c = [int(h.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_footer_colours_meet_aa_on_their_backgrounds():
    from emails import between_chronicle_lambda as bc

    for bg in ("#0D1117", "#161b22"):
        assert _contrast(RE.FOOTER_TEXT, bg) >= 4.5, bg
    assert _contrast(bc.FOOTER_TEXT, "#0b0f0d") >= 4.5


def test_list_unsubscribe_one_click_only_on_the_signed_endpoint():
    from common.unsubscribe_token import build_unsub_url

    signed = build_unsub_url("reader@example.org", SITE, secret=SECRET)
    h = {x["Name"]: x["Value"] for x in RE.list_unsubscribe_headers(signed)}
    assert h == {"List-Unsubscribe": f"<{signed}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    fallback = f"{SITE}/privacy/#unsubscribe"
    h = {x["Name"]: x["Value"] for x in RE.list_unsubscribe_headers(fallback)}
    assert h == {"List-Unsubscribe": f"<{fallback}>"}
    assert RE.list_unsubscribe_headers("") == []


def test_one_click_post_reaches_the_token_unsubscribe(monkeypatch):
    """RFC 8058: the POST to the List-Unsubscribe URL must perform the unsubscribe. The handler routes
    action=unsubscribe before it reads the method, so a POST runs the same token-verified path as the GET."""
    from urllib.parse import parse_qs, urlparse

    from common.unsubscribe_token import build_unsub_url, subscriber_email_hash
    from web import email_subscriber_lambda as es

    monkeypatch.setattr(es, "SITE_API_ORIGIN_SECRET", "")
    seen = []
    monkeypatch.setattr(es, "handle_unsubscribe", lambda h, dry_run=False: seen.append(h) or {"statusCode": 302})
    url = build_unsub_url("reader@example.org", SITE, secret=SECRET)
    qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    event = {"requestContext": {"http": {"method": "POST"}}, "queryStringParameters": qs, "body": "List-Unsubscribe=One-Click"}
    assert es.lambda_handler(event, None)["statusCode"] == 302
    assert seen == [subscriber_email_hash("reader@example.org")]


def test_text_part_drops_hidden_markup_and_keeps_links():
    html = (
        f"<html><head>{RE.head_meta()}<title>T</title></head><body>{RE.preheader_html('preview line')}"
        '<div><p>Hello &amp; welcome.</p><a href="https://x.example/u">Unsubscribe</a></div></body></html>'
    )
    text = RE.html_to_text(html)
    assert "Hello & welcome." in text
    assert "Unsubscribe (https://x.example/u)" in text
    assert "preview line" not in text and "color-scheme" not in text and "T\n" not in text


def test_simple_content_shape():
    c = RE.simple_content("S", html="<p>Body</p>", unsub_url=f"{SITE}/privacy/#unsubscribe")["Simple"]
    assert c["Body"]["Html"]["Data"] == "<p>Body</p>" and c["Body"]["Text"]["Data"].strip() == "Body"
    assert c["Headers"][0]["Name"] == "List-Unsubscribe"
    t = RE.simple_content("S", text="plain")["Simple"]
    assert "Html" not in t["Body"] and "Headers" not in t


# ── the Weekly Signal ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def ws():
    from compute import weekly_signal_lambda

    return weekly_signal_lambda


def test_board_says_is_gone(ws):
    assert not hasattr(ws, "BOARD_ROTATION") and not hasattr(ws, "_build_board_quote")
    _, html = ws._build_email({}, None, None, 3, f"{SITE}/privacy/#unsubscribe", "Week 3")
    assert "The Board Says" not in html
    assert "Check the data, not the mirror" not in html


def test_withheld_insight_never_renders(ws):
    cases = {
        "unrecorded": None,
        "private-family": NP.stamp([_family(NP.PRIVATE)], producer="test"),
        "unknown-family": NP.stamp(["not-a-family"], producer="test"),
        "malformed": {"v": "x", "families": "nope"},
    }
    leaked = [name for name, prov in cases.items() if ws._public_insight(_insight_row(CANARY, prov)) is not None]
    assert leaked == []


def test_public_insight_renders_escaped(ws):
    row = _insight_row("Protein <b>held</b> & sleep followed", NP.stamp([_family(NP.PUBLIC)], producer="test"))
    text = ws._public_insight(row)
    assert text == "Protein <b>held</b> & sleep followed"
    _, html = ws._build_email({}, None, text, 3, f"{SITE}/privacy/#unsubscribe", "Week 3")
    assert "Protein &lt;b&gt;held&lt;/b&gt; &amp; sleep followed" in html and "<b>held</b>" not in html


def test_guidance_given_json_list_reads_first_sentence(ws):
    row = _insight_row(json.dumps(["First line.", "Second."]), NP.stamp([_family(NP.PUBLIC)], producer="test"), field="guidance_given")
    assert ws._public_insight(row) == "First line."


class _SignalTable:
    def __init__(self, insight_rows):
        self.insight_rows = insight_rows

    def query(self, **kw):
        pk = kw["ExpressionAttributeValues"][":pk"]
        if pk.endswith("#computed_insights"):
            return {"Items": list(self.insight_rows)}
        if pk.endswith("#subscribers"):
            return {"Items": [{"email": "reader@example.org", "status": "confirmed"}]}
        return {"Items": []}


def test_signal_send_owner_only_insight_never_reaches_the_reader(ws, monkeypatch):
    """End to end through lambda_handler: an owner-only computed_insights row in the window, one subscriber —
    the mail on the wire carries neither its words (HTML or text part) nor the section, and carries the headers."""
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    private = NP.stamp([_family(NP.PRIVATE)], producer="test")
    monkeypatch.setattr(ws, "table", _SignalTable([_insight_row(CANARY, private), _insight_row(CANARY + " two")]))
    monkeypatch.setattr(ws, "_s3_json", lambda key: None)
    monkeypatch.setattr(ws, "_emit_sent_metric", lambda *a, **k: None)
    monkeypatch.setattr(ws.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(ws.send_ledger, "record_sent", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(ws.ses, "send_email", lambda **kw: sent.append(kw) or {"MessageId": "m"})

    out = ws.lambda_handler({}, None)
    assert out["sent"] == 1 and len(sent) == 1
    simple = sent[0]["Content"]["Simple"]
    html, text = simple["Body"]["Html"]["Data"], simple["Body"]["Text"]["Data"]
    for part in (html, text):
        assert "OWNERONLYCANARY" not in part and "What Worked This Week" not in part
    names = {h["Name"] for h in simple["Headers"]}
    assert names == {"List-Unsubscribe", "List-Unsubscribe-Post"}
    assert 'name="color-scheme"' in html and "data-preheader" in html


# ── the other reader templates ──────────────────────────────────────────────────────────────


def _assert_template(html):
    assert 'name="color-scheme" content="dark"' in html
    assert "data-preheader" in html
    for faint in ("color:#30363d", "color:#484f58;text-decoration", 'color:#5a7565;">No open'):
        assert faint not in html


def test_chronicle_installment_template():
    from emails import chronicle_email_sender_lambda as ce

    inst = {"title": "A Fixture Week", "week_number": 4, "date": "2026-11-18", "content_html": "<p>Fixture opening paragraph.</p>"}
    _, html = ce._build_subscriber_email(inst, {"email": "reader@example.org"})
    _assert_template(html)
    assert "Fixture opening paragraph." in RE.html_to_text(html)


def test_between_chronicle_send_carries_text_and_headers(monkeypatch):
    from emails import between_chronicle_lambda as bc

    d = {"deltas": [], "unlocked": [{"interpretation": "Fixture correlation", "r": 0.5}], "decided": [], "stance_shifts": []}
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    monkeypatch.setattr(bc, "gather_digest", lambda: d)
    monkeypatch.setattr(bc.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(bc.send_ledger, "record_sent", lambda *a, **k: None)
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)

    class _T:
        def get_item(self, Key):
            return {}

        def put_item(self, Item):
            return {}

        def query(self, **kw):
            return {"Items": [{"email": "reader@example.org", "status": "confirmed"}]}

    monkeypatch.setattr(bc, "table", _T())
    sent = []
    monkeypatch.setattr(bc.ses, "send_email", lambda **kw: sent.append(kw) or {"MessageId": "m"})
    assert bc.lambda_handler({}, None)["sent"] == 1
    simple = sent[0]["Content"]["Simple"]
    _assert_template(simple["Body"]["Html"]["Data"])
    assert "Fixture correlation" in simple["Body"]["Text"]["Data"]
    assert {h["Name"] for h in simple["Headers"]} == {"List-Unsubscribe", "List-Unsubscribe-Post"}


def test_onboarding_template(monkeypatch):
    from web import subscriber_onboarding_lambda as so

    monkeypatch.setattr(so, "_get_published_posts", lambda max_posts=3: so.FALLBACK_PAGES)
    _, html = so._build_onboarding_email("reader@example.org")
    _assert_template(html)


def test_confirmation_and_welcome(monkeypatch):
    from web import email_subscriber_lambda as es

    _, html = es._confirmation_email_content(f"{SITE}/api/subscribe?action=confirm&token=abc&h=def")
    _assert_template(html)
    sent = []
    monkeypatch.setattr(es.ses, "send_email", lambda **kw: sent.append(kw) or {"MessageId": "m"})
    es._send_confirmation_email("reader@example.org", f"{SITE}/x")
    es._send_welcome_email("reader@example.org")
    confirm, welcome = (s["Content"]["Simple"] for s in sent)
    assert "Text" in confirm["Body"] and "Html" in confirm["Body"]
    assert "Headers" not in confirm  # deliberately: a pending row is not on the list (see the sender's comment)
    assert "Html" not in welcome["Body"] and {h["Name"] for h in welcome["Headers"]} == {"List-Unsubscribe", "List-Unsubscribe-Post"}
