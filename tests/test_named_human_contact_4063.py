"""tests/test_named_human_contact_4063.py — the named-human contact path (#4063).

Owner ruling (2026-09-23, box 1 = option A): disengagement only. When the owner goes
quiet on the platform the ONE named human gets a no-health-data check-in email, and a
second at four weeks. This file holds the contract:

  * the quiet definition is derived from the registry's engagement channels and its
    existing alarm threshold, not restated;
  * de-dup / cooldown / supersede / preview-vs-armed episode semantics (pure `decide`);
  * the rendered body carries NO health data — no digit, no address, no banned health
    term, no tiered field name — and passes the sensitive-content filter + PII spine;
  * the contact config fails closed, and the contact's identity never reaches a log,
    the state row, or the repo (a tree grep for the config's field shape);
  * arming lives ONLY in the private config (`"armed": true`, exactly) — the default is
    a dry run that renders to the owner; thresholds are config values inside bounds;
    the mood tripwire is never honoured (owner ruling A);
  * the host wiring, the object-scoped IAM grant, no new function/schedule, and the
    partition's taxonomy + tier classification.

Every identity here is a FAKE on the reserved `.invalid` TLD. Offline: no AWS client is
constructed and no Lambda is invoked.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from coach import named_human_contact as nhc  # noqa: E402
from common.email_identity import OWNER_SENDER, VERIFIED_SENDING_DOMAINS  # noqa: E402
from ingestion.source_registry import ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS, engagement_channels  # noqa: E402

FAKE_NAME = "Quillon Fakename"
FAKE_EMAIL = "quillon@contact.invalid"
OWNER = "owner@example.invalid"
# A SYNTHETIC in-memory config — the real object is never read by any test.
FAKE_CONFIG = {"name": FAKE_NAME, "contact": {"email": FAKE_EMAIL}, "status": "DESIGNATED"}
ARMED_CONFIG = {**FAKE_CONFIG, "armed": True}


# ── the quiet definition is derived, not restated ────────────────────────────────────
def test_quiet_threshold_is_the_registry_alarm_line():
    assert nhc.QUIET_DAYS == ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS == 7
    assert nhc.FOUR_WEEK_DAYS == 28
    assert nhc.LOOKBACK_DAYS > nhc.FOUR_WEEK_DAYS


def test_quiet_channels_are_the_engagement_channels():
    chans = set(engagement_channels())
    # the owner-named signals: food log, weigh-in, workout — all must be in the set
    assert {"macrofactor", "withings", "hevy"} <= chans


def test_lag_grace_and_anchor():
    assert nhc.quiet_days_since("2026-09-22", "2026-09-23") == 0  # yesterday → 0 (24h lag)
    assert nhc.quiet_days_since("2026-09-23", "2026-09-23") == 0
    assert nhc.quiet_days_since("2026-09-15", "2026-09-23") == 7
    assert nhc.quiet_days_since(None, "2026-09-23") == nhc.LOOKBACK_DAYS
    assert nhc.last_platform_use({"a": "2026-09-01", "b": None, "c": "2026-09-10"}) == "2026-09-10"
    assert nhc.last_platform_use({"a": None}) is None


# ── pure decision: rungs, de-dup, cooldown, supersede, preview/armed ─────────────────
ANCHOR = "2026-09-01"


def _day(offset_quiet: int) -> str:
    """The `today` at which the ANCHOR episode is `offset_quiet` lag-adjusted days quiet."""
    from datetime import date, timedelta

    return (date.fromisoformat(ANCHOR) + timedelta(days=offset_quiet + 1)).isoformat()


def _run(quiet: int, state=None, armed=True, travel=frozenset(), anchor=ANCHOR, thresholds=None):
    return nhc.decide(today=_day(quiet), anchor=anchor, state=state, armed=armed, travel_days=travel, thresholds=thresholds)


def test_not_quiet_below_seven():
    d = _run(6)
    assert d["send"] is None and d["reason"] == "not_quiet"


def test_quiet_rung_once_per_episode():
    d = _run(7)
    assert d["send"] == nhc.RUNG_QUIET
    state = nhc.state_after_send(d, _day(7))
    for q in (8, 12, 27):
        assert _run(q, state)["send"] is None, q
    assert _run(8, state)["reason"] == "quiet_already_sent"


def test_four_week_rung_once():
    s1 = nhc.state_after_send(_run(7), _day(7))
    d = _run(28, s1)
    assert d["send"] == nhc.RUNG_FOUR_WEEK
    s2 = nhc.state_after_send(d, _day(28))
    assert _run(29, s2)["send"] is None
    assert _run(60, s2)["reason"] == "four_week_already_sent"


def test_four_week_supersedes_quiet_on_the_same_run():
    d = _run(30)  # first seen already past four weeks
    assert d["send"] == nhc.RUNG_FOUR_WEEK
    s = nhc.state_after_send(d, _day(30))
    assert s["quiet_mode"].startswith("superseded")
    assert _run(31, s)["send"] is None


def test_preview_does_not_consume_the_armed_send():
    preview = _run(7, armed=False)
    assert preview["send"] == nhc.RUNG_QUIET and preview["mode"] == nhc.MODE_PREVIEW
    s = nhc.state_after_send(preview, _day(7))
    assert _run(8, s, armed=False)["send"] is None  # no daily preview spam
    armed = _run(9, s, armed=True)
    assert armed["send"] == nhc.RUNG_QUIET and armed["mode"] == nhc.MODE_ARMED
    s2 = nhc.state_after_send(armed, _day(9))
    assert _run(10, s2, armed=True)["send"] is None
    assert _run(10, s2, armed=False)["send"] is None  # an armed send blocks a later preview too


def test_a_log_ends_the_episode_and_the_cooldown_holds_the_next():
    s = nhc.state_after_send(_run(7), _day(7))  # sent on 09-09
    # He logs on 09-10, then goes quiet again: new anchor 09-10, 7 quiet days → 09-18
    d = nhc.decide(today="2026-09-18", anchor="2026-09-10", state=s, armed=True)
    assert d["send"] is None and d["reason"] == "cooldown"
    # 14 days after the first send, still quiet in the new episode → it sends
    d2 = nhc.decide(today="2026-09-23", anchor="2026-09-10", state=s, armed=True)
    assert d2["send"] == nhc.RUNG_QUIET


def test_travel_holds_the_first_rung_only():
    trip = frozenset({_day(5)})
    assert _run(7, travel=trip)["reason"] == "planned_pause_travel"
    assert _run(28, travel=frozenset({_day(26)}))["send"] == nhc.RUNG_FOUR_WEEK


def test_state_is_identity_free():
    s = nhc.state_after_send(_run(7), _day(7))
    blob = json.dumps(s)
    assert "@" not in blob and FAKE_NAME not in blob


# ── the contact config fails closed ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "x",
        {},
        {**FAKE_CONFIG, "status": "CANDIDATE"},
        {k: v for k, v in FAKE_CONFIG.items() if k != "status"},
        {**FAKE_CONFIG, "contact": {}},
        {**FAKE_CONFIG, "contact": {"email": "not-an-address"}},
        {**FAKE_CONFIG, "contact": "x@y.invalid"},
        {**FAKE_CONFIG, "name": ""},
        {**FAKE_CONFIG, "name": "Agent 007"},
    ],
)
def test_parse_contact_fails_closed(raw):
    assert nhc.parse_contact(raw) is None


def test_parse_contact_accepts_designated():
    assert nhc.parse_contact(FAKE_CONFIG) == {"name": FAKE_NAME, "email": FAKE_EMAIL}
    assert nhc.parse_contact({**FAKE_CONFIG, "status": "designated"}) is not None


@pytest.mark.parametrize("value", [None, False, "true", "True", 1, "yes", {}, [True]])
def test_arming_is_json_true_only(value):
    raw = dict(FAKE_CONFIG) if value is None else {**FAKE_CONFIG, "armed": value}
    assert nhc.parse_config(raw)["armed"] is False


def test_armed_true_arms():
    cfg = nhc.parse_config(ARMED_CONFIG)
    assert cfg["armed"] is True and cfg["thresholds"] == nhc.DEFAULT_THRESHOLDS
    assert cfg["mood_tripwire_requested"] is False


def test_unknown_keys_are_ignored():
    """The owner's own prose record (e.g. owner_stated_triggers) rides alongside, unread."""
    cfg = nhc.parse_config({**FAKE_CONFIG, "owner_stated_triggers": ["quiet for a while", "four weeks"]})
    assert cfg is not None and cfg["thresholds"] == nhc.DEFAULT_THRESHOLDS


def test_thresholds_override_in_bounds():
    cfg = nhc.parse_config({**FAKE_CONFIG, "thresholds": {"quiet_days": 10, "four_week_days": 35, "cooldown_days": 21}})
    assert cfg["thresholds"] == {"quiet_days": 10, "four_week_days": 35, "cooldown_days": 21}
    partial = nhc.parse_config({**FAKE_CONFIG, "thresholds": {"quiet_days": 5}})
    assert partial["thresholds"]["quiet_days"] == 5 and partial["thresholds"]["four_week_days"] == 28


@pytest.mark.parametrize(
    "th",
    [
        {"quiet_days": 2},  # below the floor
        {"quiet_days": 22},  # above the ceiling
        {"quiet_days": "7"},  # a string is not an int
        {"quiet_days": 7.0},
        {"quiet_days": True},
        {"quiet_days": 14, "four_week_days": 20},  # rung 2 < rung 1 + a week
        {"four_week_days": 57},
        {"cooldown_days": 3},
        {"quiet_dayz": 7},  # a typo'd key fails closed, never silently defaults
        "seven",
        [7, 28],
    ],
)
def test_a_bad_threshold_rejects_the_whole_config(th):
    assert nhc.parse_config({**ARMED_CONFIG, "thresholds": th}) is None


def test_decide_honours_configured_thresholds():
    th = {"quiet_days": 10, "four_week_days": 35, "cooldown_days": 14}
    assert _run(9, thresholds=th)["reason"] == "not_quiet"
    assert _run(10, thresholds=th)["send"] == nhc.RUNG_QUIET
    s = nhc.state_after_send(_run(10, thresholds=th), _day(10))
    assert _run(34, s, thresholds=th)["send"] is None
    assert _run(35, s, thresholds=th)["send"] == nhc.RUNG_FOUR_WEEK


def test_every_allowed_four_week_line_fits_the_lookback():
    assert nhc.LOOKBACK_DAYS > nhc.FOUR_WEEK_DAYS_CEIL


# ── the rendered body carries NO health data ────────────────────────────────────────
ALL_RENDERS = [(rung, armed) for rung in nhc.RUNGS for armed in (True, False)]


@pytest.mark.parametrize("rung,armed", ALL_RENDERS)
def test_body_has_no_digit_address_or_health_term(rung, armed):
    body = nhc.render_body_text(rung, FAKE_NAME)
    assert nhc.body_violations(body) == []
    email = nhc.render_email(rung, FAKE_NAME, armed=armed)
    contact_facing = body  # the preview wraps this same text; the banner is owner-facing
    assert contact_facing in email["text"]
    assert not re.search(r"\d", contact_facing)
    assert "@" not in email["text"] and "@" not in email["html"]


@pytest.mark.parametrize("rung", nhc.RUNGS)
def test_body_names_no_tiered_field(rung):
    """No metric/mood/intake/note FIELD of any tiered source may appear, in any casing."""
    from privacy.field_tiers import FIELD_TIERS

    body = nhc.render_body_text(rung, FAKE_NAME).lower()
    fields = {f for per in FIELD_TIERS.values() for f in per}
    extra = {"mood", "mood_valence", "intake", "intake_count", "note", "notes", "journal", "calories", "weight", "sleep"}
    leaked = sorted(f for f in fields | extra if re.search(rf"\b{re.escape(f.lower())}\b", body))
    assert leaked == []


@pytest.mark.parametrize("rung,armed", ALL_RENDERS)
def test_body_passes_the_sensitive_content_filter(rung, armed):
    from privacy import broadcast_sensitivity_gate, privacy_guard

    email = nhc.render_email(rung, FAKE_NAME, armed=armed)
    for text in (email["subject"], email["text"]):
        assert privacy_guard.find_violations(text) == []
        assert broadcast_sensitivity_gate.deterministic_findings(text) == []


def test_the_sensitive_content_filter_is_live_in_this_test(monkeypatch):
    """Non-vacuity: the filter above is the suite's neutral off-repo vocabulary (conftest,
    #2370), and it DOES catch a planted term in this very body — so a clean pass means
    something."""
    from privacy import privacy_guard

    privacy_guard.reset_vocabulary_cache()
    planted = "fizzlewick"  # a conftest NEUTRAL_CONTENT_FILTER keyword, never the real list
    monkeypatch.setitem(nhc._SPAN_WORDS, nhc.RUNG_QUIET, f"about a week of {planted}")
    body = nhc.render_body_text(nhc.RUNG_QUIET, FAKE_NAME)
    assert privacy_guard.find_violations(body), "the neutral vocabulary did not load — the clean pass above is vacuous"


def test_render_refuses_a_body_that_leaks(monkeypatch):
    """Non-vacuity: a template edit that puts a number or a health word in refuses to render."""
    monkeypatch.setitem(nhc._SPAN_WORDS, nhc.RUNG_QUIET, "7 days, and his weight is up")
    with pytest.raises(ValueError):
        nhc.render_email(nhc.RUNG_QUIET, FAKE_NAME, armed=True)


def test_preview_is_marked_and_names_the_arming_step():
    email = nhc.render_email(nhc.RUNG_QUIET, FAKE_NAME, armed=False)
    assert email["subject"].startswith("[Preview, not sent]")
    assert '"armed": true' in email["text"] and "config/coaching/named_human.json" in email["text"]


# ── the leg, end to end on fakes ────────────────────────────────────────────────────
class FakeTable:
    def __init__(self, latest: dict[str, str | None], *, fail: bool = False, state: dict | None = None):
        self.latest = latest
        self.fail = fail
        self.puts: list[dict] = []
        self.state = state

    def query(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        pk = kw["ExpressionAttributeValues"][":pk"]
        source = pk.split("#SOURCE#", 1)[1]
        day = self.latest.get(source)
        if not day:
            return {"Items": []}
        vals = kw["ExpressionAttributeValues"]
        sk = f"DATE#{day}"
        if ":lo" in vals and not (vals[":lo"] <= sk <= vals[":hi"]):
            return {"Items": []}
        return {"Items": [{"sk": sk, "total_completed": 1}]}

    def get_item(self, Key):
        return {"Item": dict(self.state)} if self.state else {}

    def put_item(self, Item):
        self.puts.append(Item)


class FakeSes:
    def __init__(self):
        self.sent: list[dict] = []

    def send_email(self, **kw):
        self.sent.append(kw)
        return {"MessageId": "m"}


class FakeS3:
    def __init__(self, payload: Any = FAKE_CONFIG, fail: bool = False):
        self.payload = payload
        self.fail = fail
        self.reads: list[tuple[str, str]] = []

    def get_object(self, Bucket, Key):
        self.reads.append((Bucket, Key))
        if self.fail:
            raise RuntimeError("NoSuchKey")

        class _B:
            def __init__(self, b):
                self.b = b

            def read(self):
                return self.b

        return {"Body": _B(json.dumps(self.payload).encode())}


QUIET_LATEST = {"macrofactor": "2026-09-10", "withings": "2026-09-08", "hevy": "2026-09-05"}
TODAY = "2026-09-20"  # 9 lag-adjusted days since 09-10


def _leg(table, *, armed, s3=None, dry=False, today=TODAY):
    ses, logs = FakeSes(), []
    s3 = s3 or FakeS3(ARMED_CONFIG if armed else FAKE_CONFIG)
    out = nhc.run_leg(
        table=table,
        ses_client=ses,
        today=today,
        user_id="matthew",
        owner_recipient=OWNER,
        event_dry_run=dry,
        log=logs.append,
        s3_client_factory=lambda: s3,
        bucket="bucket",
    )
    return out, ses, logs, s3


def _no_identity_leak(logs, out, table):
    blob = "\n".join(logs) + json.dumps(out, default=str) + json.dumps(table.puts, default=str)
    assert FAKE_EMAIL not in blob and FAKE_NAME not in blob and "Quillon" not in blob
    assert "@" not in blob


def test_unarmed_previews_to_the_owner():
    t = FakeTable(QUIET_LATEST)
    out, ses, logs, s3 = _leg(t, armed=False)
    assert out["sent"] and out["rung"] == nhc.RUNG_QUIET
    assert ses.sent[0]["Destination"]["ToAddresses"] == [OWNER]
    assert ses.sent[0]["FromEmailAddress"] == OWNER_SENDER
    assert ses.sent[0]["Content"]["Simple"]["Subject"]["Data"].startswith("[Preview")
    assert s3.reads == [("bucket", "config/coaching/named_human.json")]
    assert t.puts and t.puts[0]["quiet_mode"] == nhc.MODE_PREVIEW
    _no_identity_leak(logs, out, t)


def test_armed_sends_to_the_contact_once():
    t = FakeTable(QUIET_LATEST)
    out, ses, logs, _ = _leg(t, armed=True)
    assert ses.sent[0]["Destination"]["ToAddresses"] == [FAKE_EMAIL]
    _no_identity_leak(logs, out, t)
    t2 = FakeTable(QUIET_LATEST, state=t.puts[0])
    out2, ses2, _, s3b = _leg(t2, armed=True)
    assert not out2["sent"] and ses2.sent == [] and out2["reason"] == "quiet_already_sent"


def test_not_quiet_never_reads_the_contact():
    t = FakeTable({**QUIET_LATEST, "notion": "2026-09-19"})
    out, ses, _, s3 = _leg(t, armed=True)
    assert out["reason"] == "not_quiet" and ses.sent == [] and s3.reads == []


def test_below_the_floor_never_reads_the_config():
    t = FakeTable({"macrofactor": "2026-09-17"})  # 2 lag-adjusted quiet days on 09-20
    out, ses, _, s3 = _leg(t, armed=True)
    assert out["quiet_days"] == 2 < nhc.QUIET_DAYS_FLOOR and s3.reads == [] and ses.sent == []


def test_quiet_but_not_yet_due_reads_config_and_sends_nothing():
    t = FakeTable({"macrofactor": "2026-09-15"})  # 4 quiet days — past the floor, under 7
    out, ses, _, s3 = _leg(t, armed=True)
    assert s3.reads and out["reason"] == "not_quiet" and ses.sent == []


def test_an_armed_config_with_a_lower_threshold_sends_earlier():
    t = FakeTable({"macrofactor": "2026-09-15"})
    s3 = FakeS3({**ARMED_CONFIG, "thresholds": {"quiet_days": 4}})
    out, ses, logs, _ = _leg(t, armed=True, s3=s3)
    assert out["sent"] and ses.sent[0]["Destination"]["ToAddresses"] == [FAKE_EMAIL]
    _no_identity_leak(logs, out, t)


@pytest.mark.parametrize(
    "s3",
    [
        FakeS3(fail=True),
        FakeS3(payload={**ARMED_CONFIG, "status": "REVOKED"}),
        FakeS3(payload={}),
        FakeS3(payload={**ARMED_CONFIG, "thresholds": {"quiet_days": 1}}),
    ],
)
def test_absent_undesignated_or_malformed_config_fails_closed(s3):
    t = FakeTable(QUIET_LATEST)
    out, ses, logs, _ = _leg(t, armed=True, s3=s3)
    assert not out["sent"] and ses.sent == [] and t.puts == [] and out["armed"] is False
    assert out["reason"].startswith("config_")
    assert any(nhc.CONTACT_LEG_FAILED_TOKEN in line for line in logs)
    _no_identity_leak(logs, out, t)


def test_an_absent_config_is_quiet_inert_when_no_rung_is_due():
    """Not wired yet + not due at the defaults = inert, NOT a nightly failure page."""
    t = FakeTable({"macrofactor": "2026-09-15"})  # 4 quiet days
    out, ses, logs, _ = _leg(t, armed=True, s3=FakeS3(fail=True))
    assert out["reason"] == "config_unavailable" and ses.sent == []
    assert not any(nhc.CONTACT_LEG_FAILED_TOKEN in line for line in logs)


def test_the_default_config_is_a_dry_run_to_the_owner_never_the_contact():
    """No `armed` key at all — the shape the owner writes first — mails only the owner."""
    t = FakeTable(QUIET_LATEST)
    out, ses, logs, _ = _leg(t, armed=False, s3=FakeS3(FAKE_CONFIG))
    assert out["armed"] is False and out["sent"]
    assert [m["Destination"]["ToAddresses"] for m in ses.sent] == [[OWNER]]
    assert FAKE_EMAIL not in json.dumps(ses.sent)


def test_a_mood_tripwire_request_is_ignored_under_ruling_a():
    t = FakeTable({**QUIET_LATEST, "notion": "2026-09-19"})  # not quiet by disengagement
    s3 = FakeS3({**ARMED_CONFIG, "mood_tripwire": True})
    out, ses, logs, _ = _leg(t, armed=True, s3=s3)
    assert ses.sent == []
    t2 = FakeTable({"macrofactor": "2026-09-15"})
    out2, ses2, logs2, _ = _leg(t2, armed=True, s3=s3)
    assert ses2.sent == [] and any("IGNORED" in line for line in logs2)


def test_no_mood_signal_is_read():
    src = (ROOT / "lambdas" / "coach" / "named_human_contact.py").read_text(encoding="utf-8")
    code = src[src.index("from __future__") :]
    for partition in ("state_of_mind", "mood_valence", "evening_intake"):
        assert partition not in code


def test_read_failure_fails_closed_before_the_config():
    t = FakeTable(QUIET_LATEST, fail=True)
    out, ses, logs, s3 = _leg(t, armed=True)
    assert out["reason"] == "read_failed" and ses.sent == [] and s3.reads == []


def test_no_rows_at_all_is_a_broken_read_not_four_weeks():
    t = FakeTable({})
    out, ses, _, s3 = _leg(t, armed=True)
    assert out["reason"] == "no_history" and ses.sent == [] and s3.reads == []


def test_event_dry_run_sends_nothing_and_writes_nothing():
    t = FakeTable(QUIET_LATEST)
    out, ses, logs, _ = _leg(t, armed=True, dry=True)
    assert out["reason"] == "event_dry_run" and ses.sent == [] and t.puts == []
    _no_identity_leak(logs, out, t)


# ── the host, the CDK flag, the IAM grant, the classification ───────────────────────
def test_the_leg_rides_the_evening_nudge_before_its_early_returns():
    src = (ROOT / "lambdas" / "emails" / "evening_nudge_lambda.py").read_text(encoding="utf-8")
    handler = src[src.index("def lambda_handler(") :]
    leg = handler.index("_run_named_human_contact_leg(today, dry_run)")
    assert leg < handler.index("should_skip_replay"), "the leg must run before the nudge's replay guard"
    assert leg < handler.index('return {"statusCode": 200, "body": "All complete')


def test_no_new_function_schedule_or_deploy_time_arming():
    stack = (ROOT / "cdk" / "stacks" / "email_stack.py").read_text(encoding="utf-8")
    assert "named_human" not in stack.replace("named-human", ""), "no new function for this path — it rides evening-nudge"
    assert "ARMED" not in stack, "arming is the owner's private-config act, never a deploy-time env flag"


def test_iam_grant_is_object_scoped():
    src = (ROOT / "cdk" / "stacks" / "role_policies_email.py").read_text(encoding="utf-8")
    assert '_s3("config/coaching/named_human.json")' in src
    assert 'config/coaching/*"' not in src


def test_partition_is_classified():
    from experiment import phase_taxonomy
    from privacy import field_tiers

    assert phase_taxonomy.classify("USER#matthew#SOURCE#named_human_contact", "STATE#current") == phase_taxonomy.SYSTEM_STATE
    assert field_tiers.source_tier_of("named_human_contact") == field_tiers.TIER_OWNER_ONLY


# ── the repo never carries the contact (box 4: grep for the field shape) ───────────
_ADDR = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b")  # alphabetic TLD: `pkg@1.3.0` is a version, not an address
_CONTACT_SHAPE = re.compile(r'"contact"\s*:\s*\{[^{}]*?"email"\s*:\s*"([^"]*)"', re.S)
_RESERVED = ("example.com", "example.org", "example.net")
_RESERVED_TLDS = (".invalid", ".test", ".example", ".localhost")


def _allowed_domain(domain: str) -> bool:
    d = domain.lower().rstrip(".")
    return d in VERIFIED_SENDING_DOMAINS or d in _RESERVED or d.endswith(_RESERVED_TLDS)


def contact_leaks(text: str) -> list[str]:
    """Addresses in `text` that could be a real named contact (redacted to their domain)."""
    found = []
    for m in _CONTACT_SHAPE.finditer(text):
        am = _ADDR.search(m.group(1))
        if am and not _allowed_domain(am.group(1)):
            found.append(f"contact-shape @{am.group(1)}")
    if re.search(r"named[_ -]human", text, re.I):
        for am in _ADDR.finditer(text):
            if not _allowed_domain(am.group(1)):
                found.append(f"named-human file @{am.group(1)}")
    return found


# Built at runtime so this file's own source never carries a contact-shaped address.
_PLANT_DOMAIN = "realmail" + ".net"


def test_the_leak_scan_catches_a_planted_contact():
    planted = json.dumps({"name": "X", "contact": {"email": "someone@" + _PLANT_DOMAIN}, "status": "DESIGNATED"})
    assert contact_leaks(planted)
    assert contact_leaks("the named_human is someone@" + _PLANT_DOMAIN)
    assert contact_leaks(json.dumps(FAKE_CONFIG)) == []


def test_no_tracked_file_carries_a_named_contact():
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
    leaks = []
    for rel in filter(None, files):
        path = ROOT / rel
        if path.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".ico",
            ".woff",
            ".woff2",
            ".pdf",
            ".zip",
            ".gz",
            ".mp3",
            ".mp4",
        }:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if '"contact"' not in text and not re.search(r"named[_ -]human", text, re.I):
            continue
        leaks += [f"{rel}: {hit}" for hit in contact_leaks(text)]
    assert leaks == [], f"a contact-shaped address is tracked in the PUBLIC repo: {leaks}"


def test_no_real_identity_in_this_file():
    """This file's own fake must stay on a reserved TLD."""
    assert FAKE_EMAIL.endswith(".invalid") and OWNER.endswith(".invalid")
    assert os.path.basename(__file__) == "test_named_human_contact_4063.py"
