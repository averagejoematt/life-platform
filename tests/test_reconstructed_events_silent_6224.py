"""tests/test_reconstructed_events_silent_6224.py — a reconstructed event is history: internal, and silent outbound (#6224).

Owner ruling 2026-11-26 23:50Z (the reconstructed historical events, approved conditionally): they "carry internal
provenance as reconstructed historical events", "avoid duplicates and be idempotent", and "avoid generating historical
notifications, artificial feed activity or subscriber emails".

Held here on the REAL consumer functions, each with a must-fail control — a reconstructed level-up dated in September
stays silent, and a genuinely new one still fires (the filter is not a blanket mute):

  * provenance never reaches a public body (``public_sheet``; the buddy page file, the one public output that
    serialises raw events) — control: the internal view carries it;
  * the milestone digest (named recipients) and the coach event trigger never pick up a re-dated level rung;
  * the milestone sweep writes a level rung the corrected chain crossed in the past unannounced;
  * the chronicle packet, the story dossier, ``character_stats.json``'s timeline and the buddy page list no reconstructed
    event as this week's / today's activity;
  * the owner's emails (the daily brief, the weekly digest) read the method-1 record, which never holds one;
  * idempotence: after an apply, a second dry run plans no write and never doubles an event.

Synthetic records only.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "sender@example.com")

import backfill_public_variant as B  # noqa: E402
import backfill_public_variant_cli as CLI  # noqa: E402
import backfill_public_variant_events as EV  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from health import character_privacy as CP, milestone_ledger as ML  # noqa: E402

V2 = CP.PUBLIC_METHOD_VERSION
U = "USER#matthew#SOURCE#"
PROV = {"event_provenance": CP.RECONSTRUCTED, "reconstructed_at": "2026-11-26", "reconstructed_method": V2}
OLD_UP = dict(PROV, type="character_level_up", old_level=4, new_level=5, redated_from="2026-09-20")  # reconstructed
NEW_UP = {"type": "level_up", "pillar": "sleep", "old_level": 30, "new_level": 33}  # genuinely new (no provenance)
TOKENS = [k.lower() for k in CP.PROVENANCE_KEYS]


@pytest.fixture(autouse=True)
def _scores_live(monkeypatch):
    """The serving once the containment switch flips after a verified recompute (the state these paths then run in)."""
    monkeypatch.setattr(CP, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", False)


def _sheet(day: str, level: int, events: list, origin: str = "recomputed") -> dict:
    return {
        "pk": U + "character_sheet",
        "sk": f"DATE#{day}",
        "date": day,
        "character_level": 99,  # the method-1 record: never what a public reader serves
        "level_events": [],  # method 1 holds no reconstructed event, ever
        B.PUBLIC: {"public_method_version": V2, "origin": origin, "character_level": level, "level_events": copy.deepcopy(events)},
    }


# ── provenance is internal ────────────────────────────────────────────────────────────────


def test_a_public_view_carries_no_provenance_and_no_reconstructed_event():
    rec = _sheet("2026-09-18", 5, [OLD_UP, NEW_UP])
    view = CP.public_sheet(rec)
    assert view["level_events"] == [NEW_UP]
    assert not any(t in json.dumps(view, default=str).lower() for t in TOKENS)
    internal = CP.public_sheet(rec, internal=True)  # control: an internal reader sees the reconstructed event and its provenance
    assert internal["level_events"] == [OLD_UP, NEW_UP]


def test_the_buddy_file_serialises_no_provenance_and_no_reconstructed_event():
    from compute import dashboard_refresh_lambda as DR
    from content import output_writers as OW

    rec = _sheet("2026-11-25", 33, [OLD_UP, NEW_UP], origin="live")
    for fn in (OW._buddy_character, DR._buddy_character):
        out = json.dumps(fn(CP.public_sheet(rec)), default=str).lower()
        assert not any(t in out for t in TOKENS) and '"new_level": 33' in out and '"new_level": 5' not in out
        leaked = json.dumps(fn(CP.public_sheet(rec, internal=True)), default=str).lower()  # control: without the strip it leaks
        assert any(t in leaked for t in TOKENS)


# ── the milestone ladder: digest and coach ────────────────────────────────────────────────


def _ledger_rows(entry_date: str, crossing_date: str) -> list:
    """A level-5 rung stored dated ``entry_date``; the corrected public chain first reaches level 5 on ``crossing_date``."""
    days = sorted({"2026-08-01", crossing_date, "2026-08-19"})
    sheets = [_sheet(d, 5 if d >= crossing_date else 4, []) for d in days]
    entry = {
        "pk": U + "milestones",
        "sk": "MILESTONE#level_5",
        "milestone_id": "level_5",
        "label": "Level 5",
        "category": "level",
        "ladder": "level",
        "description": "Reached character level 5",
        "event_date": entry_date,
        "announce": True,
        "origin": "crossing",
        "measurement": {"value": 5, "threshold": 5},
    }
    genesis = {"pk": U + "milestones", "sk": "DIGEST#genesis", "armed_date": "2026-07-01", "recorded_at": "2026-07-01"}
    return sheets + [entry, genesis]


class _Ses:
    def __init__(self):
        self.sends: list = []

    def send_email(self, **kw):
        self.sends.append(kw)
        return {"MessageId": f"m{len(self.sends)}"}


def _digest(monkeypatch, rows) -> tuple:
    import emails.milestone_digest_lambda as shell
    from coach import spiral_breaker

    monkeypatch.setattr(shell, "pacific_today", lambda: "2026-08-20")
    monkeypatch.setattr(shell, "experiment_stamp", lambda *a, **k: {"phase": "test", "cycle": 11})
    monkeypatch.setattr(
        shell, "get_secret_json", lambda *a, **k: {"reply_to": "r@example.com", "recipients": [{"name": "A", "email": "a@example.com"}]}
    )
    monkeypatch.setattr(spiral_breaker, "check_celebration_allowed", lambda *a, **k: (True, {"suppressed": False}))
    ses = _Ses()
    monkeypatch.setattr(shell, "ses", ses)
    table = FakeDdbTable(rows=rows, filter_by_pk=True)
    monkeypatch.setattr(shell, "table", table)
    return shell.lambda_handler({}, None), ses, table


def test_a_redated_level_rung_reaches_no_digest_recipient_and_no_coach(monkeypatch):
    from coach import coach_event_triggers as CT

    rows = _ledger_rows(entry_date="2026-08-19", crossing_date="2026-08-05")  # reconstructed: the chain crossed it earlier
    result, ses, table = _digest(monkeypatch, rows)
    assert ses.sends == [] and result["status"] == "quiet", result
    assert CT.detect_milestone(ML.read_announced_events(table, U), "2026-08-20") is None
    internal = ML.read_announced_events(table, U, include_reconstructed=True)  # the history is still there, internally
    assert [(e["milestone_id"], e["event_date"], e.get("redated_from")) for e in internal] == [("level_5", "2026-08-05", "2026-08-19")]


def test_must_fail_control_a_genuinely_new_level_rung_still_mails_and_triggers(monkeypatch):
    from coach import coach_event_triggers as CT

    rows = _ledger_rows(entry_date="2026-08-19", crossing_date="2026-08-19")  # crossed on the newest day: new
    result, ses, table = _digest(monkeypatch, rows)
    assert len(ses.sends) == 1, result
    assert CT.detect_milestone(ML.read_announced_events(table, U), "2026-08-20") is not None


def test_the_sweep_writes_a_historical_level_crossing_unannounced():
    entry = ML._entry(ML.RULES_BY_ID["level_5"], {"value": 5, "threshold": 5}, "2026-11-27", announce=True, origin=ML.ORIGIN_CROSSING)
    series = [("2026-09-17", 4), ("2026-09-18", 5), ("2026-11-26", 24)]
    silent = ML._historical_level_silent(entry, {"character_level_series": series}, "2026-11-27")
    assert silent["announce"] is False and silent["event_date"] == "2026-09-18" and CP.is_reconstructed(silent)
    new = ML._historical_level_silent(entry, {"character_level_series": [("2026-11-25", 4), ("2026-11-26", 5)]}, "2026-11-27")
    assert new is entry and new["announce"] is True  # control: a crossing on the newest day is announced as before
    other = dict(entry, ladder="weight", milestone_id="weight_sub_250")
    assert ML._historical_level_silent(other, {"character_level_series": series}, "2026-11-27") is other


# ── the time-ordered public outputs: this week's / today's activity ───────────────────────


def test_the_chronicle_packet_lists_no_reconstructed_event_as_this_weeks():
    import test_chronicle_data_packet as T
    from emails import chronicle_data as cd

    data = T._empty_data(start="2026-09-14", end="2026-09-20")
    data["character_sheet"] = {"2026-09-18": _sheet("2026-09-18", 5, [OLD_UP, NEW_UP])}
    text, _ = cd.build_data_packet(data)
    assert "Level 30 → 33" in text  # control: the genuine event is a story moment
    assert "Level 4 → 5" not in text


def test_the_story_dossier_lists_no_reconstructed_event(monkeypatch):
    from content import story_dossier as SD

    monkeypatch.setattr(SD, "_days", lambda *a, **k: {"2026-09-18": _sheet("2026-09-18", 5, [OLD_UP, NEW_UP])})
    out = SD._character(None, {"start": "2026-09-14", "end": "2026-09-20"})
    assert [(e["pillar"], e["type"]) for e in out["level_events"]] == [("sleep", "level_up")]


def test_character_stats_timeline_lists_no_reconstructed_event(monkeypatch):
    from compute import character_sheet_lambda as csl
    from content import site_writer

    captured = {}
    monkeypatch.setattr(site_writer, "write_character_stats", lambda **kw: captured.update(kw))
    monkeypatch.setattr(csl, "fetch_range", lambda *a, **k: [])
    csl.publish_site_stats(_sheet("2026-11-25", 33, [OLD_UP, NEW_UP], origin="live"), "2026-11-25", 80)
    assert [e["type"] for e in captured["timeline"]] == ["level_up"]
    assert not any(t in json.dumps(captured, default=str).lower() for t in TOKENS)


def test_the_owners_emails_read_method_one_which_holds_no_reconstructed_event():
    from content import html_builder
    from emails import weekly_digest_extractors as WD

    rec = _sheet("2026-09-18", 5, [OLD_UP])  # the reconstructed event lives only in the public projection
    assert WD.ex_character_sheet({"2026-09-18": rec})["events"] == []
    quiet = html_builder._brief_character(rec, [], [])
    rec["level_events"] = [dict(NEW_UP, pillar="sleep")]  # control: a method-1 event does reach both owner emails
    assert WD.ex_character_sheet({"2026-09-18": rec})["events"] and html_builder._brief_character(rec, [], []) != quiet


# ── idempotence ───────────────────────────────────────────────────────────────────────────


class _Table:
    def __init__(self, items):
        self.items = {(i["pk"], i["sk"]): copy.deepcopy(i) for i in items}

    def get_item(self, Key=None, **_kw):  # noqa: N803
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(it)} if it is not None else {}

    def update_item(
        self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **_kw
    ):  # noqa: N803
        it = self.items[(Key["pk"], Key["sk"])]
        if UpdateExpression.startswith("SET"):
            it[ExpressionAttributeNames["#p"]] = copy.deepcopy(ExpressionAttributeValues[":p"])
        else:
            it.pop(ExpressionAttributeNames["#p"], None)


def _dry_run(stored_items: dict, recomputed: dict, run_date: str) -> tuple:
    """The dry run's provenance + plan steps over ``stored_items`` ({date: item}) and freshly ``recomputed`` blocks."""
    from common.numeric import decimals_to_float

    stored = {d: decimals_to_float(i) for d, i in stored_items.items()}
    dates = sorted(stored)
    before = [stored[d] for d in dates]
    after_blocks = {d: copy.deepcopy(recomputed[d]) for d in dates}
    after = [dict(stored[d], **{B.PUBLIC: after_blocks[d]}) for d in dates]
    comp = EV.compare(EV.served_events(before, old_rule=True), EV.served_events(after, old_rule=False), EV.per_date_values(after))
    marked = EV.annotate_provenance(after_blocks, stored, comp, run_date, V2)
    plan = [{"pk": B.SHEET_PK, "sk": f"DATE#{d}", "value": B.as_stored(after_blocks[d]), "precision": 4} for d in dates]
    writes, _skipped = CLI.narrow_plan(plan, {(B.SHEET_PK, f"DATE#{d}"): stored[d] for d in dates})
    return writes, marked, after_blocks


def test_a_second_dry_run_after_an_apply_plans_no_write_and_doubles_no_event():
    from common.numeric import floats_to_decimal

    v1 = CP.PUBLIC_METHOD_V1
    old = {
        "2026-09-17": {
            "pk": B.SHEET_PK,
            "sk": "DATE#2026-09-17",
            "date": "2026-09-17",
            "character_level": 4,
            B.PUBLIC: {"public_method_version": v1, "origin": "live", "character_level": 4, "level_events": []},
        },
        "2026-09-18": {
            "pk": B.SHEET_PK,
            "sk": "DATE#2026-09-18",
            "date": "2026-09-18",
            "character_level": 6,
            B.PUBLIC: {
                "public_method_version": v1,
                "origin": "live",
                "character_level": 6,
                "level_events": [{"type": "character_level_up", "old_level": 5, "new_level": 6}],
            },
        },
    }
    recomputed = {
        "2026-09-17": {"public_method_version": V2, "origin": "recomputed", "character_level": 4, "level_events": []},
        "2026-09-18": {
            "public_method_version": V2,
            "origin": "recomputed",
            "character_level": 5,
            "level_events": [{"type": "character_level_up", "old_level": 4, "new_level": 5}],
        },
    }
    table = _Table([floats_to_decimal(i) for i in old.values()])
    writes, marked, blocks = _dry_run(
        {d: table.get_item(Key={"pk": B.SHEET_PK, "sk": f"DATE#{d}"})["Item"] for d in old}, recomputed, "2026-11-26"
    )
    assert len(writes) == 2 and marked == 1 and CP.is_reconstructed(blocks["2026-09-18"]["level_events"][0])
    export = B.build_export(lambda key: table.get_item(Key=key).get("Item"), writes, "2026-11-26T00:00:00Z")
    assert B.apply_plan(table, writes, export)["written"] == 2
    # the second dry run, a day later, against the applied table
    stored = {d: table.get_item(Key={"pk": B.SHEET_PK, "sk": f"DATE#{d}"})["Item"] for d in old}
    writes2, marked2, blocks2 = _dry_run(stored, recomputed, "2026-11-27")
    assert writes2 == [] and marked2 == 1
    assert blocks2["2026-09-18"]["level_events"] == blocks["2026-09-18"]["level_events"]  # one event, the first run's stamp
    assert len(blocks2["2026-09-18"]["level_events"]) == 1


def test_no_public_route_carries_reconstructed_provenance():
    """Every public GET route, with the stored character row a corrected-chain variant whose events carry internal
    provenance (``--provenance``), scores live: no provenance key on any body (the walk's leak tokens include them). No
    public route serialises raw event dicts today; the must-fail control for the strip is the buddy-file test above."""
    import subprocess
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "restraint_route_walk.py"), "--state", "low", "--now", now, "--provenance", "--scores-live"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["answered"] >= 140 and out["raised"] == {} and out["leaks"] == {}, (out["answered"], out["raised"], out["leaks"])
