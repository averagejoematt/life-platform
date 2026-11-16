"""tests/test_horizons_retrospective.py — Horizons retrospective + public feed (#1707, S3).

The load-bearing S3 acceptance criteria, exercised offline (injected invoker + classifier,
no network, no Bedrock):

  AC1  the retrospective is GROUNDED (ADR-104) — the prompt is built ONLY from the stored
       pick's fields and the system prompt forbids claiming what Matthew did/felt.
  AC1  it is BUDGET-GATED — a reader-narrative surface, paused at budget tier 2, never
       fabricated when paused.
  AC1  it is SENSITIVITY-GATED (#1673, fail-closed) — PII / vice / a generation failure
       all HOLD; only a gate-cleared retrospective publishes.
  #1830 it is DETERMINISTICALLY GROUNDING-GATED (ADR-104) — the output's numbers and
       dates must appear in what the model was actually given, with one regen_once
       corrective rewrite; anything still ungrounded HOLDS. Prompt text is no longer
       the only factual defense.
  AC2  the /api/horizons feed projects public-safe cards reverse-chron and shows the
       retrospective ONLY when it published (honest empty/"note coming" state otherwise).
  AC3  storage: set_horizon_retrospective attaches a published verdict's prose to the pick
       and NEVER stores prose for a held/paused verdict (fail-closed by storage).
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from ai import budget_guard  # noqa: E402
from privacy import broadcast_sensitivity_gate as gate  # noqa: E402
from reading import horizons_retrospective as hr, reading_store as rs  # noqa: E402
from reading_fakes import FakeTable  # noqa: E402
from web import site_api_reading as sar  # noqa: E402


def _pick(week="2026-W30", title="On Rest as a Skill", **over):
    p = {
        "week": week,
        "format": "essay",
        "url": "https://themarginalian.org/rest",
        "title": title,
        "source": "The Marginalian",
        "pitch": "a reframe of rest as active recovery, not idleness",
        "pitchStatus": "published",  # #5947: the curate-time publication stamp
        "rationale_tag": "experiment-relevant",
        "curator": "mind",
        "verification": {"verified": True, "status": 200},
    }
    p.update(over)
    return p


def _clean_invoker(
    text="I sent this because your training block leans hard on volume; I hoped a reframe of rest as a skill would give you permission to bank recovery without guilt.",
):
    return lambda body: {"content": [{"type": "text", "text": text}]}


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — GROUNDED (ADR-104): prompt built only from the stored pick
# ══════════════════════════════════════════════════════════════════════════════
def test_prompt_is_grounded_in_the_stored_pick_only():
    body = hr.build_body(_pick())
    user = body["messages"][0]["content"]
    # every stored fact the coach may use is present …
    for fact in ("On Rest as a Skill", "essay", "The Marginalian", "experiment-relevant", "2026-W30"):
        assert fact in user, fact
    # … and the system prompt forbids inventing Matthew's reaction / outside facts.
    sysmsg = body["system"].lower()
    assert "never claim he" in sysmsg
    assert "no fabricated" in sysmsg or "fabricated" in sysmsg


def test_absent_optional_fields_are_omitted_not_guessed():
    body = hr.build_body(_pick(source=None, pitch=None))
    user = body["messages"][0]["content"]
    assert "Source:" not in user and "pitch" not in user.lower()


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — BUDGET-GATED (ADR-062/125): reader-narrative band 2
# ══════════════════════════════════════════════════════════════════════════════
def test_feature_is_registered_in_the_reader_narrative_band():
    assert budget_guard._FEATURE_CUTOFF[hr.BUDGET_FEATURE] == 2


def test_paused_at_tier2_returns_no_fabricated_text(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    out = hr.generate(_pick(), invoker=_clean_invoker())
    assert out["status"] == hr.STATUS_PAUSED
    assert "text" not in out  # nothing fabricated when the budget pauses


def test_runs_below_tier2(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)
    out = hr.generate(_pick(), invoker=_clean_invoker())
    assert out["status"] == hr.STATUS_PUBLISHED


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — SENSITIVITY-GATED (#1673, fail-closed)
# ══════════════════════════════════════════════════════════════════════════════
def test_clean_retrospective_publishes(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    out = hr.generate(_pick(), invoker=_clean_invoker())
    assert out["status"] == hr.STATUS_PUBLISHED
    assert out["curator"] == "mind"
    assert out["sensitivity_status"] == gate.SENSITIVITY_CLEARED
    assert out["text"]


def test_pii_or_vice_in_generation_is_held_fail_closed(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    out = hr.generate(_pick(), invoker=_clean_invoker("reach me at 415-555-1212 about the zzq protocol"))
    assert out["status"] == hr.STATUS_HELD
    assert "text" not in out
    assert set(out["categories"]) & {gate.CATEGORY_PII, gate.CATEGORY_VICE}


def test_generation_failure_is_held_not_raised(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

    def _boom(_body):
        raise RuntimeError("bedrock down")

    out = hr.generate(_pick(), invoker=_boom)
    assert out["status"] == hr.STATUS_HELD and "text" not in out


def test_empty_generation_is_held(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    out = hr.generate(_pick(), invoker=lambda b: {"content": [{"type": "text", "text": "   "}]})
    assert out["status"] == hr.STATUS_HELD


# ══════════════════════════════════════════════════════════════════════════════
# #1830 — DETERMINISTIC GROUNDING GATE (ADR-104), fail-closed
#
# The filed repro: a generation citing "47-minute runtime and 3,200 citations" —
# two numbers absent from the pick — used to return status=published, verbatim.
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture()
def tier0(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)


def test_the_filed_repro_is_now_held_not_published(tier0):
    out = hr.generate(
        _pick(),
        invoker=_clean_invoker("I picked this for its 47-minute runtime and 3,200 citations — the definitive case for rest."),
    )
    assert out["status"] == hr.STATUS_HELD
    assert "text" not in out  # nothing ungrounded ever carries prose forward
    assert out["categories"] == [hr.CATEGORY_UNGROUNDED]
    assert any("47" in f for f in out["grounding_findings"])
    assert any("3200" in f or "3,200" in f for f in out["grounding_findings"])


def test_a_number_present_in_the_pick_is_grounded_and_publishes(tier0):
    pick = _pick(pitch="a 12-week reframe of rest as active recovery")
    out = hr.generate(pick, invoker=_clean_invoker("I sent this because the 12-week arc matches your training block."))
    assert out["status"] == hr.STATUS_PUBLISHED
    assert out["grounded"] is True


def test_an_invented_calendar_date_is_held(tier0):
    out = hr.generate(_pick(), invoker=_clean_invoker("I sent it on 2019-03-04, right when rest became the theme."))
    assert out["status"] == hr.STATUS_HELD
    assert out["categories"] == [hr.CATEGORY_UNGROUNDED]


def test_regen_once_rescues_a_fixable_draft(tier0):
    """One corrective rewrite, kept only because it is strictly better (the house harness)."""
    calls = {"n": 0}
    fabricated = "I picked this for its 47-minute runtime and 3,200 citations."
    corrected = "I picked this because it makes the case for rest as a skill, not a reward."

    def _invoker(body):
        calls["n"] += 1
        return {"content": [{"type": "text", "text": fabricated if calls["n"] == 1 else corrected}]}

    out = hr.generate(_pick(), invoker=_invoker)
    assert calls["n"] == 2, "the gate must attempt exactly one corrective rewrite"
    assert out["status"] == hr.STATUS_PUBLISHED
    assert out["text"] == corrected


def test_a_rewrite_that_does_not_improve_still_holds(tier0):
    """regen_once never regresses — and an un-fixed draft must not publish."""
    out = hr.generate(_pick(), invoker=_clean_invoker("Its 47-minute runtime and 3,200 citations are the point."))
    assert out["status"] == hr.STATUS_HELD


def test_the_allow_list_is_what_the_model_saw_not_the_whole_pick_record(tier0):
    """A number living only in an unrendered field was never shown to the model —
    counting it as grounded would quietly widen the gate."""
    pick = _pick(verification={"verified": True, "status": 200, "checked_bytes": 8675309})
    assert "8675309" not in hr._grounding_facts(pick)
    out = hr.generate(pick, invoker=_clean_invoker("This piece runs to 8675309 words of argument."))
    assert out["status"] == hr.STATUS_HELD


def test_a_broken_grounding_gate_withholds_rather_than_publishes_ungated(tier0, monkeypatch):
    """Fail-closed: this is a public reader surface, so an unavailable gate HOLDS."""
    monkeypatch.setattr(hr, "_gg", None)
    out = hr.generate(_pick(), invoker=_clean_invoker())
    assert out["status"] == hr.STATUS_HELD
    assert "text" not in out
    assert out["categories"] == [hr.CATEGORY_UNGROUNDED]


def test_a_raising_grounding_gate_withholds(tier0, monkeypatch):
    from ai import grounded_generation

    def _boom(*_a, **_kw):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(grounded_generation, "allowed_numbers", _boom)
    out = hr.generate(_pick(), invoker=_clean_invoker())
    assert out["status"] == hr.STATUS_HELD and "text" not in out


def test_a_corrective_rewrite_is_re_screened_by_the_sensitivity_gate(tier0):
    """The grounding gate can REWRITE the text; the sensitivity stamp must describe the
    bytes that actually publish, never the discarded draft."""
    calls = {"n": 0}

    def _invoker(body):
        calls["n"] += 1
        # draft 1: ungrounded but clean · rewrite: numerically grounded but leaks an email
        text = "Its 47-minute runtime is the point." if calls["n"] == 1 else "Reach the author at ada@example.com about rest as a skill."
        return {"content": [{"type": "text", "text": text}]}

    out = hr.generate(_pick(), invoker=_invoker)
    assert calls["n"] == 2
    assert out["status"] == hr.STATUS_HELD
    assert gate.CATEGORY_PII in out["categories"], "the rewritten text must be re-screened"


def test_a_privacy_hold_is_reported_as_privacy_not_masked_as_ungrounded(tier0):
    """A leaking draft carries ungrounded digits too (415/555/1212). The verdict must
    name the privacy category — a PII hold reported as 'ungrounded' would be triaged
    as a quality bug."""
    out = hr.generate(_pick(), invoker=_clean_invoker("reach me at 415-555-1212 about the zzq protocol"))
    assert out["status"] == hr.STATUS_HELD
    assert set(out["categories"]) & {gate.CATEGORY_PII, gate.CATEGORY_VICE}
    assert hr.CATEGORY_UNGROUNDED not in out["categories"]


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — storage: published prose attaches; held/paused stores NO prose
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture()
def fake_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(rs, "table", t)
    monkeypatch.setattr(sar.reading_store, "table", t)
    return t


def test_store_published_retrospective_attaches_prose(fake_table):
    rs.put_horizon_pick(_pick())
    updated = rs.set_horizon_retrospective(
        "2026-W30", {"status": "published", "text": "why I sent it", "curator": "mind", "generatedAt": "2026-07-30T00:00:00+00:00"}
    )
    assert updated["retrospectiveStatus"] == "published"
    assert updated["retrospective"] == "why I sent it"


def test_store_held_retrospective_never_persists_prose(fake_table):
    rs.put_horizon_pick(_pick())
    updated = rs.set_horizon_retrospective("2026-W30", {"status": "held", "reason": "flagged: pii", "text": "leaky text"})
    assert updated["retrospectiveStatus"] == "held"
    assert "retrospective" not in updated  # fail-closed: no prose on a held verdict
    assert updated["retrospectiveReason"] == "flagged: pii"


def test_store_missing_week_returns_none(fake_table):
    assert rs.set_horizon_retrospective("2026-W99", {"status": "published", "text": "x"}) is None


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — the public /api/horizons feed
# ══════════════════════════════════════════════════════════════════════════════
def _parse(resp):
    import json

    return json.loads(resp["body"])


def test_feed_empty_state_is_honest(fake_table):
    body = _parse(sar.handle_horizons())
    assert body["items"] == [] and body["count"] == 0
    assert body["note"]


def test_feed_is_reverse_chron_and_public_safe(fake_table):
    rs.put_horizon_pick(_pick("2026-W28", title="Older"))
    rs.put_horizon_pick(_pick("2026-W30", title="Newest"))
    rs.set_horizon_retrospective(
        "2026-W30",
        {"status": "published", "text": "the coach's grounded note", "curator": "mind", "generatedAt": "2026-08-01T00:00:00+00:00"},
    )
    body = _parse(sar.handle_horizons())
    assert [i["week"] for i in body["items"]] == ["2026-W30", "2026-W28"]  # newest first
    newest, older = body["items"]
    # published retrospective is surfaced …
    assert newest["retrospective"] == "the coach's grounded note"
    # … the un-retrospected pick shows none (client renders "note coming")
    assert "retrospective" not in older
    # public allowlist — the verification block never leaks to the feed
    assert "verification" not in newest


def test_held_retrospective_is_never_public(fake_table):
    rs.put_horizon_pick(_pick("2026-W30"))
    rs.set_horizon_retrospective("2026-W30", {"status": "held", "reason": "flagged", "text": "secret leaky prose"})
    body = _parse(sar.handle_horizons())
    assert "retrospective" not in body["items"][0]
    assert "secret leaky prose" not in resp_text(body)


def resp_text(body):
    import json

    return json.dumps(body)


# ══════════════════════════════════════════════════════════════════════════════
# #5947 — coach-written text on the feed is public by POSITIVE stamp, fail closed
# (synthetic vocabulary only: the real one lives in the off-repo channel)
# ══════════════════════════════════════════════════════════════════════════════
import datetime as _dt  # noqa: E402
import json as _json  # noqa: E402

from privacy import content_filter_channel as _channel  # noqa: E402
from reading import horizons_publication as hp  # noqa: E402

_SYNTHETIC_CLINICAL = "snorbleitis"  # a conftest NEUTRAL_CONTENT_FILTER clinical term, never a real one
_SYNTHETIC_PHRASE = "quibbled-wumpus"  # the fixture's two-word term, written with a hyphen


@pytest.fixture()
def unarmed_clinical_channel(monkeypatch):
    """A channel armed BEFORE the clinical list existed: the blocked vocabulary, no clinical key."""
    monkeypatch.setenv("CONTENT_FILTER_JSON", _json.dumps({"blocked_vice_keywords": ["fizzlewick"]}))
    _channel.reset_cache()
    yield
    _channel.reset_cache()


def test_a_pitch_with_no_publication_stamp_is_never_served(fake_table):
    """The must-fail control: the row shape every pick had before the stamp existed. Its pitch was served
    verbatim; now the card is served without it — and with the stamp, the same clean text is served."""
    legacy = _pick("2026-W28", pitch="words nobody screened")
    del legacy["pitchStatus"]
    rs.put_horizon_pick(legacy)
    rs.put_horizon_pick(_pick("2026-W30", pitch="words that cleared the screen"))
    body = _parse(sar.handle_horizons())
    newest, older = body["items"]
    assert older["title"] and older["pitch"] is None
    assert "words nobody screened" not in resp_text(body)
    assert newest["pitch"] == "words that cleared the screen"


def test_a_stamped_pitch_is_rescreened_at_the_read_and_a_held_stamp_never_serves(fake_table):
    rs.put_horizon_pick(_pick("2026-W29", pitch=f"a week after the {_SYNTHETIC_CLINICAL} finding"))  # stamped, vocabulary widened since
    rs.put_horizon_pick(_pick("2026-W30", pitch="clean words, held stamp", pitchStatus="held"))
    body = _parse(sar.handle_horizons())
    assert [i["pitch"] for i in body["items"]] == [None, None]
    assert _SYNTHETIC_CLINICAL not in resp_text(body)


def test_a_published_retrospective_is_rescreened_and_a_flagged_title_drops_the_card(fake_table):
    rs.put_horizon_pick(_pick("2026-W29", title=f"Living with {_SYNTHETIC_PHRASE}"))
    rs.put_horizon_pick(_pick("2026-W30"))
    rs.set_horizon_retrospective(
        "2026-W30", {"status": "published", "text": f"I sent it the week {_SYNTHETIC_CLINICAL} arrived.", "curator": "mind"}
    )
    body = _parse(sar.handle_horizons())
    assert [i["week"] for i in body["items"]] == ["2026-W30"] and body["count"] == 1
    assert "retrospective" not in body["items"][0]
    assert _SYNTHETIC_CLINICAL not in resp_text(body) and "wumpus" not in resp_text(body)


def test_the_screen_fails_closed_when_the_clinical_vocabulary_is_not_armed(fake_table, unarmed_clinical_channel):
    """An unarmed screen vouches for nothing: nothing new is stamped published and nothing stamped is served."""
    assert hp.screen("perfectly ordinary words") == (hp.STATUS_HELD, [hp.CATEGORY_SCREEN_UNAVAILABLE])
    assert hp.stamp({"pitch": "perfectly ordinary words", "title": "A Piece"})[hp.STATUS_ATTR] == hp.STATUS_HELD
    rs.put_horizon_pick(_pick("2026-W30"))
    card = _parse(sar.handle_horizons())["items"][0]
    assert card["title"] == "On Rest as a Skill", "an unavailable screen is not a finding: the verified title still shows"
    assert card["pitch"] is None


def test_the_stamp_names_a_neutral_category_and_never_the_term():
    attrs = hp.stamp({"pitch": f"since the {_SYNTHETIC_CLINICAL} news", "title": "A Piece", "source": "Somewhere"})
    assert attrs == {hp.STATUS_ATTR: hp.STATUS_HELD, hp.CATEGORIES_ATTR: [hp.CATEGORY_CLINICAL]}
    assert hp.stamp({"pitch": "about the piece itself", "title": "A Piece"}) == {hp.STATUS_ATTR: hp.STATUS_PUBLISHED}


def test_a_retrospective_is_never_written_from_an_unpublished_pitch_and_a_clinical_draft_is_held(tier0):
    held_pitch = _pick(pitch="words the screen held", pitchStatus="held")
    assert "words the screen held" not in hr.build_body(held_pitch)["messages"][0]["content"]
    assert "a reframe of rest" in hr.build_body(_pick())["messages"][0]["content"]
    out = hr.generate(_pick(), invoker=_clean_invoker(f"I sent this the week the {_SYNTHETIC_CLINICAL} result came back."))
    assert out["status"] == hr.STATUS_HELD and "text" not in out
    assert out["categories"] == [hp.CATEGORY_CLINICAL]


def test_the_pending_line_is_promised_only_inside_the_retrospective_window(fake_table, monkeypatch):
    """A pick's "retrospective is coming" flag is true for this ISO week and the one before, and false after —
    the page no longer promises a note that is weeks overdue. The clock is pinned (#4848)."""
    today = _dt.date(2026, 7, 29)  # ISO 2026-W31
    assert sar._retrospective_window_open("2026-W31", today) and sar._retrospective_window_open("2026-W30", today)
    assert not sar._retrospective_window_open("2026-W29", today) and not sar._retrospective_window_open(None, today)
    monkeypatch.setattr(sar, "_retrospective_window_open", lambda week, today=None: week == "2026-W30")
    rs.put_horizon_pick(_pick("2026-W28"))
    rs.put_horizon_pick(_pick("2026-W29"))
    rs.put_horizon_pick(_pick("2026-W30"))
    rs.set_horizon_retrospective("2026-W29", {"status": "published", "text": "the coach's grounded note", "curator": "mind"})
    flags = {i["week"]: i["retrospective_pending"] for i in _parse(sar.handle_horizons())["items"]}
    assert flags == {"2026-W30": True, "2026-W29": False, "2026-W28": False}


import sys as _sys  # noqa: E402


def test_the_feed_is_in_the_live_privacy_sweep_and_a_planted_clinical_term_reds_it(unarmed_clinical_channel, monkeypatch):
    """The nightly sweep (deploy/pii_surface_guard.py --endpoints) fetches this feed's route and reads its
    payload against the clinical vocabulary. Must-fail control: a planted synthetic term in a card's pitch is
    a violation that names the JSON path and never the term; the same payload without it is clean; and an
    unarmed channel raises instead of reporting a surface it could not screen."""
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
    import pii_surface_guard as guard  # noqa: PLC0415

    def sweep(feed_payload):
        def fetch(fetch_path):
            return 200, (feed_payload if fetch_path.split("?")[0] == feed_route else {"ok": True}), None

        return guard.scan_endpoints("https://unit-test.invalid", fetcher=fetch)

    feed_route = "/api/" + sar.handle_horizons.__name__.removeprefix("handle_")

    with pytest.raises(_channel.ContentFilterUnavailable):
        sweep({"items": []})

    monkeypatch.setenv(
        "CONTENT_FILTER_JSON", _json.dumps({"blocked_vice_keywords": ["fizzlewick"], "blocked_clinical_keywords": ["Snorbleitis"]})
    )
    _channel.reset_cache()
    planted = sweep({"items": [{"title": "A Piece", "pitch": f"a week after the {_SYNTHETIC_CLINICAL} finding"}], "count": 1})
    assert feed_route in planted["scanned"], "the feed's route must be in the live sweep's scan set"
    assert [(w, a) for w, a, _ in planted["violations"]] == [(feed_route, "clinical-record")]
    detail = planted["violations"][0][2]
    assert detail.startswith("$.items[].pitch ") and _SYNTHETIC_CLINICAL not in detail.lower()
    assert sweep({"items": [{"title": "A Piece", "pitch": "about the piece itself"}], "count": 1})["violations"] == []
