"""tests/test_progress_viewer_3760.py — the private progress viewer's gate (#3760, epic #3743).

WHAT IS UNDER TEST, AND WHY IT IS WORTH A FILE OF ITS OWN

`lambdas/privacy/progress_access.py` is the only thing standing between a stranger and
Matthew's body photographs. Every other property of the viewer — the layout, the weight
figures, the tape labelling — is a page that renders wrong if it breaks. This one is a lock
that opens if it breaks, and a lock that opens silently: a removed signature check produces a
page that works perfectly, for everybody.

So the rules here are the rules for a gate, not for a feature:

  * Every refusal is asserted by OUTCOME, not by message. The route answers one 401 for an
    expired link, a forged link, a replayed link and no link at all.
  * The clock is injected. Expiry is tested by passing a later `now`, never by sleeping, so
    the test measures the boundary rather than the machine it ran on.
  * There is a MUTATION CONTROL at the bottom. It deletes the signature comparison from a
    copy of the module, re-imports it, and asserts a forged token is then accepted. A gate
    whose test passes with the check removed is a green light wired to nothing (the #3562
    class), and that is the only way to know this file is doing anything at all.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from privacy import progress_access as pa  # noqa: E402

SECRET = "a-test-hmac-key-not-the-real-one"
NOW = 1_757_000_000.0  # a fixed instant; nothing here reads the wall clock


# ── a table that behaves like DynamoDB's conditional put ─────────────────────
class FakeTable:
    """`put_item` with `attribute_not_exists(pk)` — the ONE behaviour one-time-ness rests on.

    A dict would have been simpler and would have tested nothing: the property is that the
    SECOND put raises, in the shape boto3 raises it, with the code `consume_nonce` keys on.
    """

    def __init__(self, fail_with: Exception | None = None):
        self.items: dict = {}
        self.fail_with = fail_with

    def put_item(self, Item=None, ConditionExpression=None, **_):  # noqa: N803 — boto3 spelling
        if self.fail_with:
            raise self.fail_with
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and "attribute_not_exists(pk)" in ConditionExpression and key in self.items:
            err = Exception("ConditionalCheckFailedException")
            err.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
            raise err
        self.items[key] = Item
        return {}


# ── the link token ────────────────────────────────────────────────────────────
def test_a_freshly_minted_link_verifies():
    token = pa.mint_link_token(SECRET, now=NOW)
    ok, reason, nonce = pa.verify_link_token(SECRET, token, now=NOW + 60)
    assert ok and reason == "ok"
    assert nonce and len(nonce) >= 8


def test_a_link_expires_exactly_at_its_horizon():
    """24 hours, from `LINK_TTL_S` — the number the retention row in DATA_GOVERNANCE states."""
    token = pa.mint_link_token(SECRET, now=NOW)
    assert pa.verify_link_token(SECRET, token, now=NOW + pa.LINK_TTL_S - 1)[0] is True
    ok, reason, _ = pa.verify_link_token(SECRET, token, now=NOW + pa.LINK_TTL_S)
    assert ok is False and reason == "expired"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda t: t[:-1] + ("0" if t[-1] != "0" else "1"), id="signature byte flipped"),
        pytest.param(lambda t: ".".join(t.split(".")[:2] + ["deadbeefdeadbeef"] + t.split(".")[3:]), id="nonce swapped"),
        pytest.param(lambda t: ".".join([t.split(".")[0], str(int(t.split(".")[1]) + 99999)] + t.split(".")[2:]), id="expiry extended"),
        pytest.param(lambda t: t.replace("1.", "2.", 1), id="version bumped"),
        pytest.param(lambda t: t + ".extra", id="field appended"),
        pytest.param(lambda t: "", id="empty"),
    ],
)
def test_a_tampered_link_is_refused(mutate):
    """Every field is covered by the signature, including the one an attacker most wants.

    Extending the expiry is the interesting case: it is the mutation that costs nothing to
    try, and the token still carries a valid-looking timestamp afterwards.
    """
    token = pa.mint_link_token(SECRET, now=NOW)
    forged = mutate(token)
    assert forged != token or forged == ""
    assert pa.verify_link_token(SECRET, forged, now=NOW + 60)[0] is False


def test_a_link_signed_with_another_key_is_refused():
    token = pa.mint_link_token("some-other-key", now=NOW)
    ok, reason, _ = pa.verify_link_token(SECRET, token, now=NOW + 60)
    assert ok is False and reason == "bad signature"


def test_a_link_token_is_not_a_session_cookie():
    """The domain prefixes (`link:` / `sess:`) are load-bearing, not decoration.

    Without them one signature would verify as both, and 'one use, 24 hours' would silently
    become 'unlimited, forever' — with nothing observable to say so.
    """
    token = pa.mint_link_token(SECRET, now=NOW)
    exp, nonce, sig = token.split(".")[1:]
    assert pa.verify_session(SECRET, f"1.{exp}.{sig}", now=NOW + 60)[0] is False
    session = pa.sign_session(SECRET, now=NOW)
    s_exp, s_sig = session.split(".")[1:]
    assert pa.verify_link_token(SECRET, f"1.{s_exp}.{nonce}.{s_sig}", now=NOW + 60)[0] is False


# ── one-time-ness ─────────────────────────────────────────────────────────────
def test_a_link_can_be_redeemed_once_and_only_once():
    table = FakeTable()
    nonce = pa.verify_link_token(SECRET, pa.mint_link_token(SECRET, now=NOW), now=NOW)[2]
    assert pa.consume_nonce(table, nonce, now=NOW) is True
    assert pa.consume_nonce(table, nonce, now=NOW) is False
    assert pa.consume_nonce(table, nonce, now=NOW + 3600) is False


def test_the_nonce_row_carries_a_ttl_past_the_token_horizon():
    """The row must outlive every request that could still present the token, and no longer."""
    table = FakeTable()
    pa.consume_nonce(table, "cafebabecafebabe", now=NOW)
    row = list(table.items.values())[0]
    assert row["pk"].startswith(pa.LINK_PK_PREFIX)
    assert row["ttl"] > NOW + pa.LINK_TTL_S


def test_consumption_fails_closed_on_a_dynamodb_outage():
    """An auth check that cannot reach its storage refuses. The alternative is an unbounded
    replay window that nothing logs, traded for a page he could have re-requested in a minute."""
    table = FakeTable(fail_with=RuntimeError("ProvisionedThroughputExceeded"))
    assert pa.consume_nonce(table, "cafebabecafebabe", now=NOW) is False


# ── the session cookie ────────────────────────────────────────────────────────
def test_a_session_cookie_verifies_then_expires():
    value = pa.sign_session(SECRET, now=NOW)
    assert pa.verify_session(SECRET, value, now=NOW + pa.SESSION_TTL_S - 1)[0] is True
    ok, reason = pa.verify_session(SECRET, value, now=NOW + pa.SESSION_TTL_S)
    assert ok is False and reason == "expired"


def test_a_tampered_session_cookie_is_refused():
    value = pa.sign_session(SECRET, now=NOW)
    forged = ".".join([value.split(".")[0], str(int(value.split(".")[1]) + 86400), value.split(".")[2]])
    assert pa.verify_session(SECRET, forged, now=NOW)[0] is False
    assert pa.verify_session(SECRET, "", now=NOW)[0] is False
    assert pa.verify_session(SECRET, "not-a-cookie", now=NOW)[0] is False


def test_the_cookie_carries_every_flag_that_makes_it_not_a_url():
    attrs = pa.cookie_attributes(pa.sign_session(SECRET, now=NOW))
    for flag in ("HttpOnly", "Secure", "SameSite=Lax", f"Path={pa.VIEWER_PATH}"):
        assert flag in attrs, f"{flag} missing from Set-Cookie — {attrs}"


def test_one_cookie_is_read_out_of_a_crowded_header():
    header = f"other=1; {pa.COOKIE_NAME}=abc.def; __lp_auth=zzz"
    assert pa.cookie_from_header(header) == "abc.def"
    assert pa.cookie_from_header("other=1; nothing=here") is None
    assert pa.cookie_from_header("") is None


# ── the route ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def viewer(monkeypatch):
    """`site_api_progress` with the secret, the table and S3 presigning stubbed.

    Nothing is monkeypatched inside `progress_access` — the gate under test runs for real;
    only its dependencies on AWS are replaced.
    """
    from web import progress_viewer_lambda as mod

    table = FakeTable()
    monkeypatch.setattr(mod, "_signing_secret", lambda: SECRET)
    monkeypatch.setattr(mod, "table", table)
    monkeypatch.setattr(mod, "_weeks", lambda: [])
    return mod, table


def _get(path="/progress-photos/", *, query=None, cookie=None):
    event = {"rawPath": path, "rawQueryString": "", "headers": {}}
    if query:
        event["queryStringParameters"] = {"k": query}
        event["rawQueryString"] = f"k={query}"
    if cookie:
        event["headers"]["cookie"] = f"{pa.COOKIE_NAME}={cookie}"
    return event


def test_an_anonymous_request_is_refused(viewer):
    mod, _ = viewer
    resp = mod.handle(_get(), "/progress-photos/", "GET")
    assert resp["statusCode"] == 401
    assert "progress" not in resp["body"].lower() or "current link" in resp["body"]


def test_a_forged_cookie_is_refused(viewer):
    mod, _ = viewer
    resp = mod.handle(_get(cookie="1.99999999999.0123456789abcdef0123456789abcdef"), "/progress-photos/", "GET")
    assert resp["statusCode"] == 401


def test_a_valid_link_is_exchanged_for_a_cookie_then_burned(viewer):
    """The whole flow, in the order a phone does it: tap, redirect, cookie, page — and the
    second tap of the same link gets nothing."""
    mod, _ = viewer
    import time as _t

    token = pa.mint_link_token(SECRET, now=_t.time())

    first = mod.handle(_get(query=token), "/progress-photos/", "GET")
    assert first["statusCode"] == 302
    assert first["headers"]["Location"] == pa.VIEWER_PATH
    cookie_attrs = first["cookies"][0]
    assert cookie_attrs.startswith(f"{pa.COOKIE_NAME}=")

    value = cookie_attrs.split("=", 1)[1].split(";")[0]
    page = mod.handle(_get(cookie=value), "/progress-photos/", "GET")
    assert page["statusCode"] == 200
    assert "<!doctype html>" in page["body"]

    replay = mod.handle(_get(query=token), "/progress-photos/", "GET")
    assert replay["statusCode"] == 401, "a one-time link was redeemed twice"


def test_an_unreadable_signing_secret_refuses_rather_than_admits(viewer, monkeypatch):
    mod, _ = viewer
    monkeypatch.setattr(mod, "_signing_secret", lambda: None)
    assert mod.handle(_get(), "/progress-photos/", "GET")["statusCode"] == 503


def test_every_response_is_uncacheable_and_unindexable(viewer):
    mod, _ = viewer
    resp = mod.handle(_get(), "/progress-photos/", "GET")
    headers = {k.lower(): v for k, v in resp["headers"].items()}
    assert "no-store" in headers["cache-control"]
    assert "noindex" in headers["x-robots-tag"]
    # The page embeds presigned URLs and is reached with a token in the query string; a
    # default referrer policy would hand both to the next origin the browser talks to.
    assert headers["referrer-policy"] == "no-referrer"


def test_a_post_is_refused(viewer):
    mod, _ = viewer
    assert mod.handle(_get(), "/progress-photos/", "POST")["statusCode"] == 405


# ── the page, rendered offline ────────────────────────────────────────────────
def test_the_empty_state_is_a_real_state_not_a_blank_grid():
    """No photos exist yet (#3761 has not run). The page must say so, and say how to fix it."""
    from web import progress_viewer_lambda as mod

    html = mod.render_page([])
    assert "No progress photos stored yet" in html
    assert "/progress front" in html
    assert "noindex" in html


def test_a_week_with_no_weigh_in_says_so_rather_than_borrowing_a_number():
    from web import progress_viewer_lambda as mod

    html = mod.render_page(
        [
            {
                "week": 2,
                "as_of": "2026-09-19",
                "poses": {"front": "https://s3/x", "side": None, "back": None},
                "pose_dates": {"front": "2026-09-19"},
                "weight": {"lbs": None},
                "tape": {},
            }
        ]
    )
    assert "no weigh-in this week" in html
    assert "no side photo" in html, "a missing pose must render as missing, not as an empty box"


def test_a_stale_tape_session_is_labelled_with_its_own_date():
    """Tape is measured every 4-8 weeks. An unlabelled older measurement under this week's
    photo is a comparison the data cannot support (ADR-104/ADR-105)."""
    from web import progress_viewer_lambda as mod

    html = mod.render_page(
        [
            {
                "week": 3,
                "as_of": "2026-09-26",
                "poses": {p: None for p in mod.POSES},
                "pose_dates": {},
                "weight": {"lbs": 212.4, "date": "2026-09-25"},
                "tape": {"session_date": "2026-08-15", "days_back": 42, "waist_navel_in": 38.5},
            }
        ]
    )
    assert "2026-08-15" in html
    assert "42 days earlier" in html
    assert "212.4" in html


def test_the_week_number_is_the_stamp_the_bot_acked_not_a_re_derivation(monkeypatch):
    """The cross-phase trap, and the reason this module derives no week fact of its own.

    `progress_photos` is CROSS_PHASE: the photos deliberately survive experiment resets,
    because a before/after spanning attempts is the whole point. Re-deriving the week from
    the CURRENT `EXPERIMENT_START` would relabel every pre-reset set against a genesis it
    was never taken under — a silent, total corruption of the comparison, triggered by a
    constant changing in a file this module does not import.

    So a row stamped `week_n=3` in cycle 16 still reads Week 3 after the seventeenth reset.
    """
    from web import progress_viewer_lambda as mod

    rows = [
        {"sk": "DATE#2026-07-04#front", "date": "2026-07-04", "pose": "front", "s3_key": "raw/a.jpg", "week_n": 3},
        {"sk": "DATE#2026-07-04#side", "date": "2026-07-04", "pose": "side", "s3_key": "raw/b.jpg", "week_n": 3},
        {"sk": "DATE#2026-09-19#front", "date": "2026-09-19", "pose": "front", "s3_key": "raw/c.jpg", "week_n": 2},
        {"sk": "DATE#2026-08-01#back", "date": "2026-08-01", "pose": "back", "s3_key": "raw/d.jpg"},  # off-cycle, no stamp
    ]
    monkeypatch.setattr(mod, "_photo_rows", lambda: rows)
    monkeypatch.setattr(mod, "_presign", lambda key: f"https://signed/{key}")
    monkeypatch.setattr(mod, "_weight_for", lambda as_of: {"lbs": None})
    monkeypatch.setattr(mod, "_tape_for", lambda as_of: {})

    cols = mod._weeks()
    assert [c["week"] for c in cols] == [3, None, 2], "columns must order by capture date, labelled by the STORED week"
    assert cols[0]["as_of"] == "2026-07-04" and cols[0]["poses"]["front"] and cols[0]["poses"]["back"] is None
    assert cols[1]["week"] is None, "an unstamped capture is off-cycle, never folded into a week it is not in"

    html = mod.render_page(cols)
    assert "Week 3" in html and "Week 2" in html and "Off-cycle" in html


def test_a_retake_later_in_the_same_week_replaces_the_earlier_one(monkeypatch):
    from web import progress_viewer_lambda as mod

    rows = [
        {"sk": "DATE#2026-09-17#front", "date": "2026-09-17", "pose": "front", "s3_key": "raw/first.jpg", "week_n": 2},
        {"sk": "DATE#2026-09-19#front", "date": "2026-09-19", "pose": "front", "s3_key": "raw/retake.jpg", "week_n": 2},
    ]
    monkeypatch.setattr(mod, "_photo_rows", lambda: rows)
    monkeypatch.setattr(mod, "_presign", lambda key: key)
    monkeypatch.setattr(mod, "_weight_for", lambda as_of: {"lbs": None})
    monkeypatch.setattr(mod, "_tape_for", lambda as_of: {})

    cols = mod._weeks()
    assert len(cols) == 1
    assert cols[0]["poses"]["front"] == "raw/retake.jpg"


def test_the_rendered_page_escapes_what_it_interpolates():
    from web import progress_viewer_lambda as mod

    html = mod.render_page(
        [
            {
                "week": 1,
                "as_of": '"><script>alert(1)</script>',
                "poses": {p: None for p in mod.POSES},
                "pose_dates": {},
                "weight": {"lbs": None},
                "tape": {},
            }
        ]
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ── the bot command ───────────────────────────────────────────────────────────
def test_only_the_exact_view_command_mints_a_link():
    assert pa.is_view_command("/progress view") is True
    assert pa.is_view_command("  /progress   VIEW  ") is True
    for other in ("/progress front", "can I /progress view", "/progress view please", "/progress", ""):
        assert pa.is_view_command(other) is False, other


def test_the_bot_refuses_to_mint_a_link_into_a_group_or_a_stranger_s_chat():
    """A body-photo link posted into the board room cannot be unposted."""
    from coach import progress_capture as pc

    base = {"bot_key": pc.CAPTURE_BOT_KEY, "chat_id": 111}
    ok = pc.handle_view(base, chat_ids=[111], secret=SECRET, base_url="https://x.test", now=NOW)
    assert ok["ok"] and ok["reply"].startswith("Progress photos: https://x.test/progress-photos/?k=")

    group = pc.handle_view({**base, "is_group": True}, chat_ids=[111], secret=SECRET, base_url="https://x.test", now=NOW)
    assert group["ok"] is False and group["reply"] == ""

    stranger = pc.handle_view({**base, "chat_id": 999}, chat_ids=[111], secret=SECRET, base_url="https://x.test", now=NOW)
    assert stranger["ok"] is False and stranger["reply"] == "", "a stranger must learn nothing, not even that they were refused"

    wrong_bot = pc.handle_view({**base, "bot_key": "sleep"}, chat_ids=[111], secret=SECRET, base_url="https://x.test", now=NOW)
    assert wrong_bot["reply"] == ""


def test_the_link_the_bot_mints_is_the_link_the_viewer_accepts():
    """End to end across the two lambdas, with no network: mint in the worker's module,
    verify in the viewer's. They share one key and one format or the feature is dead."""
    from coach import progress_capture as pc

    reply = pc.handle_view(
        {"bot_key": pc.CAPTURE_BOT_KEY, "chat_id": 7},
        chat_ids=[7],
        secret=SECRET,
        base_url="https://averagejoematt.com",
        now=NOW,
    )["url"]
    token = reply.split("?k=")[1]
    assert pa.verify_link_token(SECRET, token, now=NOW + 3600)[0] is True


# ── the mutation control ──────────────────────────────────────────────────────
def _module_without_the_signature_check():
    """A copy of `progress_access` with the link signature comparison deleted."""
    src_path = os.path.join(_REPO, "lambdas", "privacy", "progress_access.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    anchor = '    if not hmac.compare_digest(sig, _sign(secret, f"link:{exp}:{nonce}")):\n        return (False, "bad signature", None)\n'
    assert anchor in src, "mutation anchor missing — this control no longer exercises the real shape"
    mutated = src.replace(anchor, "")
    mod = types.ModuleType("progress_access_mutated")
    mod.__file__ = src_path
    exec(compile(mutated, src_path, "exec"), mod.__dict__)  # noqa: S102 — deliberate, in-test only
    return mod


def test_the_gate_would_fail_if_the_signature_check_were_removed():
    """THE control. Without this, every assertion above could pass over a module that lets
    anybody in — which is precisely what a forged-token test looks like when the thing it is
    testing has been deleted."""
    mutated = _module_without_the_signature_check()
    forged = f"1.{int(NOW) + 3600}.deadbeefdeadbeef.{'0' * 32}"

    assert pa.verify_link_token(SECRET, forged, now=NOW)[0] is False, "the real module must refuse a forged token"
    assert mutated.verify_link_token(SECRET, forged, now=NOW)[0] is True, (
        "removing the signature comparison did NOT make a forged token verify — this control "
        "is vacuous and the tests above prove nothing"
    )


def test_the_import_of_the_real_module_is_not_the_mutated_one():
    """Paranoia with a reason: the control above execs a modified copy. If it leaked into
    `sys.modules`, every test in this file would be grading the mutant."""
    spec = importlib.util.find_spec("privacy.progress_access")
    assert spec and spec.origin and spec.origin.endswith(os.path.join("privacy", "progress_access.py"))
    assert pa.verify_link_token(SECRET, f"1.{int(NOW) + 3600}.deadbeefdeadbeef.{'0' * 32}", now=NOW)[0] is False
