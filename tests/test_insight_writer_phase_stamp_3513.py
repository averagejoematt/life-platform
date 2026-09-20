"""tests/test_insight_writer_phase_stamp_3513.py — the insight writers stamp at the write site,
and the row-side guard is the control that would have caught them (#3513, #3599 box 2, #3877).

THE DEFECT
  `USER#matthew#SOURCE#insights` is EXPERIMENT_SCOPED. Two writers put rows on it —
  `content.insight_writer` (the daily brief's insight ledger) and the inbound email parser —
  and neither ever stamped `phase`. PHASE_FILTER_EXPRESSION admits `attribute_not_exists(phase)`
  as CURRENT, and the reset-time tagger runs before genesis, so every insight written in the
  reset->genesis countdown window (dated genesis-1) was served as this cycle's on Day 1.
  Measured live 2026-09-19: 112 unstamped rows, 10 of them pre-genesis (the issue filed 6).

WHY THE WRITER GUARD COULD NOT SEE IT
  `tests/test_coach_ensemble_writer_phase_stamp_guard_2119.py` walks `put_item` call sites and
  flags a function only when it can read a literal `COACH#` pk token. `insight_writer`'s pk is a
  module global set by `init()`, and the parser's is an f-string — runtime values, invisible to
  an AST walk. Measured 2026-09-19: the guard sees 7 of 154 `put_item` sites. #3599 box 2 asks
  for "a scratch module with table.put_item on USER#matthew#SOURCE#insights and no stamp -> red;
  wrapped in the stamp helper -> green". A scratch MODULE cannot be discriminated by that guard
  (its pk is not a literal the guard can read), so the control below is implemented against the
  ROW-side check that replaced the hand list: the unstamped row such a module writes -> the
  nightly reports it, naming the family; the same row through `experiment_stamp_for` -> clean.
  That is the box's property (unstamped write red, stamped write green) on the instrument that
  can actually see a runtime pk; the driver judges whether the wording is honoured.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402
from content import insight_writer  # noqa: E402
from experiment import phase_taxonomy as tx  # noqa: E402
from experiment.pk_census import scoped_stamp_audit  # noqa: E402

INSIGHTS_PK = "USER#matthew#SOURCE#insights"


def _day_before(iso: str) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


GENESIS = EXPERIMENT_START_DATE
GENESIS_MINUS_1 = _day_before(GENESIS)


class _RecordingTable:
    def __init__(self):
        self.puts: list[dict] = []

    def put_item(self, Item):
        self.puts.append(Item)


# ── the partition really is in the Set the guard audits ─────────────────────────


def test_the_insights_partition_is_experiment_scoped_and_stampable():
    assert tx.classify(INSIGHTS_PK, "INSIGHT#2026-09-05#daily_brief#bod") == tx.EXPERIMENT_SCOPED
    assert tx.should_phase_stamp(INSIGHTS_PK, "INSIGHT#2026-09-05#daily_brief#bod") is True


# ── writer 1: content.insight_writer ─────────────────────────────────────────────


@pytest.fixture
def writer_table():
    t = _RecordingTable()
    insight_writer.init(t, "matthew")
    yield t
    insight_writer.init(None, "matthew")


def test_a_write_dated_genesis_minus_one_lands_phase_pilot(writer_table):
    out = insight_writer.write_insight("daily_brief", "coaching", "x" * 40, date=GENESIS_MINUS_1, slug="bod")
    assert out is not None
    (item,) = writer_table.puts
    assert item["pk"] == INSIGHTS_PK
    assert item["sk"] == f"INSIGHT#{GENESIS_MINUS_1}#daily_brief#bod"
    assert item["phase"] == "pilot", item


def test_a_write_dated_genesis_day_lands_the_current_phase(writer_table):
    insight_writer.write_insight("daily_brief", "coaching", "x" * 40, date=GENESIS, slug="bod")
    (item,) = writer_table.puts
    assert item["phase"] == EXPERIMENT_PHASE_CURRENT, item
    if "cycle" in item:
        assert isinstance(item["cycle"], (int, Decimal))


def test_the_stamp_is_derived_from_the_insight_date_not_the_wall_clock(writer_table, monkeypatch):
    """A countdown-window write is made the morning AFTER the day it is about. Pin the
    wall clock to genesis day and write about genesis-1: the row must still say pilot."""
    monkeypatch.setattr(insight_writer, "pacific_today", lambda: GENESIS)
    insight_writer.write_insight("daily_brief", "coaching", "x" * 40, date=GENESIS_MINUS_1, slug="tldr")
    (item,) = writer_table.puts
    assert item["phase"] == "pilot"


def test_the_writer_stamps_through_the_class_gated_helper(writer_table, monkeypatch):
    """The stamp must come from `experiment_stamp_for(pk, sk, as_of=...)` — the gate that
    returns {} for a class that forbids provenance — and the row's own values win over it."""
    seen = {}

    def _fake(pk, sk, **kw):
        seen.update(pk=pk, sk=sk, **kw)
        return {"phase": "sentinel", "cycle": 99}

    monkeypatch.setattr(insight_writer, "experiment_stamp_for", _fake)
    insight_writer.write_insight("daily_brief", "coaching", "x" * 40, date=GENESIS_MINUS_1, slug="bod")
    (item,) = writer_table.puts
    assert seen["pk"] == INSIGHTS_PK and seen["sk"] == item["sk"] and seen["as_of"] == GENESIS_MINUS_1
    assert item["phase"] == "sentinel" and item["cycle"] == 99


# ── writer 2: the inbound email parser ───────────────────────────────────────────


@pytest.fixture
def parser():
    from emails import insight_email_parser_lambda as mod

    return mod


def test_the_email_parser_stamps_pilot_before_genesis_and_current_from_genesis(parser, monkeypatch):
    for day, expected in ((GENESIS_MINUS_1, "pilot"), (GENESIS, EXPERIMENT_PHASE_CURRENT)):
        t = _RecordingTable()
        monkeypatch.setattr(parser, "table", t)
        monkeypatch.setattr(parser, "pacific_today", lambda d=day: d)
        parser.save_insight("an insight from a reply", "Re: Daily Brief")
        (item,) = t.puts
        assert item["pk"] == INSIGHTS_PK
        assert item["phase"] == expected, (day, item)


def test_the_email_parser_dry_run_still_writes_nothing(parser, monkeypatch):
    t = _RecordingTable()
    monkeypatch.setattr(parser, "table", t)
    parser.save_insight("an insight", "Re: Daily Brief", dry_run=True)
    assert t.puts == []


# ── the #3599 box-2 control, on the ROW-side guard ───────────────────────────────


def _audit(rows):
    return scoped_stamp_audit([rows])


def test_an_unstamped_insights_row_is_reported_by_the_row_audit_naming_the_family():
    """The scratch-module direction 1: a bare put_item on USER#matthew#SOURCE#insights with
    no stamp — the row it leaves is a finding, and the family is named."""
    row = {"pk": INSIGHTS_PK, "sk": f"INSIGHT#{GENESIS_MINUS_1}#daily_brief#bod"}
    out = _audit([row])
    assert out["unstamped"] == {"SOURCE#insights": [f"{INSIGHTS_PK}/{row['sk']}"]}
    assert "SOURCE#insights" in out["families_audited"]


def test_the_same_row_through_the_stamp_helper_is_clean():
    """Direction 2: the identical write wrapped in `experiment_stamp_for` leaves no finding."""
    sk = f"INSIGHT#{GENESIS_MINUS_1}#daily_brief#bod"
    row = {**tx.experiment_stamp_for(INSIGHTS_PK, sk, as_of=GENESIS_MINUS_1), "pk": INSIGHTS_PK, "sk": sk}
    assert row["phase"] == "pilot"
    out = _audit([row])
    assert out["unstamped"] == {}
    assert "SOURCE#insights" in out["families_audited"]  # audited AND clean — not merely absent


def test_the_nightly_check_itself_names_the_insights_family(monkeypatch):
    """End to end through qa_smoke_lambda's check — the instrument that runs at 18:30Z —
    so the control is on the shipped check, not only on the reducer under it."""
    import qa_smoke_lambda as qa

    class _T:
        def scan(self, **kw):
            return {"Items": [{"pk": INSIGHTS_PK, "sk": f"INSIGHT#{GENESIS_MINUS_1}#daily_brief#bod"}]}

    monkeypatch.setattr(qa, "table", _T())
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None and c.chronic is True
    assert "SOURCE#insights 1" in c.message
    assert f"{INSIGHTS_PK}/INSIGHT#{GENESIS_MINUS_1}#daily_brief#bod" in c.message


def test_the_row_audit_derives_its_families_and_never_reports_a_cross_phase_row():
    """Guard the SET: one unstamped row on every EXPERIMENT_SCOPED source in the registry,
    one on a CROSS_PHASE source and one on a SYSTEM_STATE source. The scoped ones are all
    findings, the other two never are, and `families_audited` is the registry's own size."""
    scoped = sorted(s for s, c in tx.SOURCE_CLASS.items() if c == tx.EXPERIMENT_SCOPED)
    # Dated BEFORE genesis: SOURCE# pks are tagger-reachable, so only a pre-genesis unstamped
    # row is a finding there (#3877 split); an in-cycle one is `deferred` to the next reset's tagger.
    rows = [{"pk": f"USER#matthew#SOURCE#{s}", "sk": "X#2020-01-01"} for s in scoped]
    rows += [
        {"pk": f"USER#matthew#SOURCE#{tx.CROSS_PHASE_SOURCES[0]}", "sk": "X#2020-01-01"},
        {"pk": f"USER#matthew#SOURCE#{tx.SYSTEM_STATE_SOURCES[0]}", "sk": "X#2020-01-01"},
        {"pk": f"USER#matthew#SOURCE#{scoped[0]}", "sk": "X#2099-01-01"},  # in-cycle: deferred, not a finding
    ]
    out = _audit(rows)
    assert sorted(out["unstamped"]) == [f"SOURCE#{s}" for s in scoped]
    assert sorted(out["deferred"]) == [f"SOURCE#{scoped[0]}"]
    assert len(out["families_audited"]) == len(scoped)
    assert out["rows"] == len(rows)


def test_the_row_audit_refuses_an_empty_scan():
    from experiment.pk_census import CensusPreflightError

    with pytest.raises(CensusPreflightError):
        _audit([])


def test_an_unclassifiable_row_is_counted_not_guessed_and_does_not_stop_the_audit(monkeypatch):
    rows = [{"pk": "NEWTIER#x", "sk": "A#1"}, {"pk": INSIGHTS_PK, "sk": "INSIGHT#2026-09-05#daily_brief#bod"}]
    out = _audit(rows)
    assert out["unclassified"] == 1
    assert out["unstamped"] == {"SOURCE#insights": [f"{INSIGHTS_PK}/INSIGHT#2026-09-05#daily_brief#bod"]}


# ── the backfill covers the insights partition, per-row, and leaves cross-phase alone ─


def _load_backfill():
    spec = importlib.util.spec_from_file_location("backfill_3513", REPO_ROOT / "deploy/backfill_coach_ensemble_phase_stamps.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_3513"] = mod
    spec.loader.exec_module(mod)
    return mod


class _QueryTable:
    def __init__(self, items_by_pk):
        self.items_by_pk = items_by_pk
        self.updates = []

    def query(self, **kwargs):
        cond = kwargs["KeyConditionExpression"].get_expression()
        if cond["operator"] == "AND":  # #3900: a prefixed family (pk & begins_with(sk))
            pk, prefix = cond["values"][0].get_expression()["values"][1], cond["values"][1].get_expression()["values"][1]
        else:
            pk, prefix = cond["values"][1], None
        return {
            "Items": [
                it for it in self.items_by_pk.get(pk, []) if "phase" not in it and (not prefix or str(it.get("sk", "")).startswith(prefix))
            ]
        }

    def update_item(self, **kwargs):
        self.updates.append(kwargs)


def test_backfill_targets_the_insights_partition():
    bf = _load_backfill()
    assert INSIGHTS_PK in bf.target_pks()


def test_backfill_derives_the_insights_stamp_from_each_rows_own_date(monkeypatch):
    """10 of the 112 live rows are dated before genesis. A constant stamp would mark them
    as this cycle's — the #3513 defect, made permanent under attribute_not_exists(phase)."""
    bf = _load_backfill()
    rows = [
        {"sk": f"INSIGHT#{GENESIS_MINUS_1}#daily_brief#bod", "date": GENESIS_MINUS_1},
        {"sk": f"INSIGHT#{GENESIS}#daily_brief#bod", "date": GENESIS},
        {"sk": "INSIGHT#2026-09-19T15:14:03", "date_saved": "2026-09-19"},  # the legacy ts sk: date in the sk
        {"sk": "INSIGHT#undated"},  # no date dimension at all: refused, never guessed
    ]
    table = _QueryTable({INSIGHTS_PK: rows})
    monkeypatch.setattr(bf.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda self, n: table})())
    calls = []

    def _stamp(as_of=None, **kw):
        calls.append(as_of)
        return {"phase": "pilot" if (as_of and as_of < GENESIS) else EXPERIMENT_PHASE_CURRENT, "cycle": 17}

    monkeypatch.setattr(bf, "experiment_stamp", _stamp)
    monkeypatch.setattr(sys, "argv", ["backfill", "--apply"])

    assert bf.main() == 0

    by_sk = {u["Key"]["sk"]: u["ExpressionAttributeValues"][":phase"] for u in table.updates}
    assert by_sk == {
        f"INSIGHT#{GENESIS_MINUS_1}#daily_brief#bod": "pilot",
        f"INSIGHT#{GENESIS}#daily_brief#bod": EXPERIMENT_PHASE_CURRENT,
        "INSIGHT#2026-09-19T15:14:03": EXPERIMENT_PHASE_CURRENT,
    }
    assert "INSIGHT#undated" not in by_sk
    assert set(calls) >= {GENESIS_MINUS_1, GENESIS, "2026-09-19"}
    for u in table.updates:
        assert u["ConditionExpression"] == "attribute_not_exists(#phase)"
        assert isinstance(u["ExpressionAttributeValues"][":cycle"], Decimal)


def test_backfill_dry_run_counts_insights_rows_and_writes_nothing(monkeypatch, capsys):
    bf = _load_backfill()
    table = _QueryTable({INSIGHTS_PK: [{"sk": f"INSIGHT#{GENESIS_MINUS_1}#daily_brief#bod"}]})
    monkeypatch.setattr(bf.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda self, n: table})())
    monkeypatch.setattr(bf, "experiment_stamp", lambda as_of=None, **kw: {"phase": "pilot", "cycle": 16})
    monkeypatch.setattr(sys, "argv", ["backfill"])
    assert bf.main() == 0
    assert table.updates == []
    out = capsys.readouterr().out
    assert "1 unstamped experiment-scoped row(s) found" in out and "DRY RUN" in out


def test_backfill_still_leaves_every_cross_phase_row_on_a_coach_partition_untouched(monkeypatch):
    """#3514 running backwards is the risk of any widening: CHAT#/RELATIONSHIP# on COACH#
    must receive no update_item while the insights row beside them is stamped."""
    bf = _load_backfill()
    coach_pk = bf.target_pks()[0]
    table = _QueryTable(
        {
            coach_pk: [{"sk": "CHAT#2026-09-10#m1"}, {"sk": "RELATIONSHIP#state"}],
            INSIGHTS_PK: [{"sk": f"INSIGHT#{GENESIS}#daily_brief#bod"}],
        }
    )
    monkeypatch.setattr(bf.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda self, n: table})())
    monkeypatch.setattr(bf, "experiment_stamp", lambda as_of=None, **kw: {"phase": EXPERIMENT_PHASE_CURRENT, "cycle": 17})
    monkeypatch.setattr(sys, "argv", ["backfill", "--apply"])
    assert bf.main() == 0
    assert [u["Key"] for u in table.updates] == [{"pk": INSIGHTS_PK, "sk": f"INSIGHT#{GENESIS}#daily_brief#bod"}]
