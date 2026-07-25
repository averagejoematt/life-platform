"""tests/test_horizons_retrospective.py — Horizons retrospective + public feed (#1707, S3).

The load-bearing S3 acceptance criteria, exercised offline (injected invoker + classifier,
no network, no Bedrock):

  AC1  the retrospective is GROUNDED (ADR-104) — the prompt is built ONLY from the stored
       pick's fields and the system prompt forbids claiming what Matthew did/felt.
  AC1  it is BUDGET-GATED — a reader-narrative surface, paused at budget tier 2, never
       fabricated when paused.
  AC1  it is SENSITIVITY-GATED (#1673, fail-closed) — PII / vice / a generation failure
       all HOLD; only a gate-cleared retrospective publishes.
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

import broadcast_sensitivity_gate as gate  # noqa: E402
import budget_guard  # noqa: E402
import pytest  # noqa: E402
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
    out = hr.generate(_pick(), invoker=_clean_invoker("reach me at 415-555-1212 about the weed protocol"))
    assert out["status"] == hr.STATUS_HELD
    assert "text" not in out
    assert set(out["categories"]) & {gate.CATEGORY_PII, gate.CATEGORY_MARIJUANA}


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
