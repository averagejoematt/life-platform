"""tests/test_provenance_reconcile_2026_09.py — contract for the one-shot live
provenance reconcile (#3511, #3513, #3514).

The script mutates LIVE rows, so the two properties that make that safe are
pinned here against a fake table, offline:

  CLASSIFICATION — every row is routed by ``phase_taxonomy.classify()``, once.
    A CROSS_PHASE row is only ever STRIPPED (group A), an EXPERIMENT_SCOPED row
    is only ever STAMPED (groups B/C), and a row the taxonomy cannot classify
    stops the whole run (exit 2, nothing written) rather than taking a default.
    The negative controls are the point: the clean row of each class must NOT be
    selected, or "85 rows planned" would be a number with no meaning.

  IDEMPOTENCY — the planned writes are applied to the fake store through a
    mini-interpreter of the exact UpdateExpressions the script emits, and the
    plan is recomputed. Every group must come back empty. A reconcile that is
    not idempotent cannot be re-run to PROVE it landed, which is the only way
    the live apply is verifiable at all.

Plus the one-line #3514 sweep fix this reconcile depends on: the countdown-gap
sweep passed no ``pk`` to ``wipe.should_tombstone``, so the ADR-153 carve-out
protecting CROSS_PHASE CHAT#/RELATIONSHIP# rows could not fire and the sweep
reported them as tombstone-able escapees. Without that fix the very next
``reconcile_countdown_gap.py --apply`` would undo group A.

All dates derive from the live ``EXPERIMENT_START_DATE`` so a re-anchor cannot
turn these into wall-clock time bombs.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import countdown_gap_sweep as sweep  # noqa: E402
import reconcile_provenance_2026_09 as recon  # noqa: E402
import restart_intelligence_wipe as wipe  # noqa: E402
from experiment import phase_taxonomy as taxonomy  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

GENESIS = wipe.EXPERIMENT_START_DATE
BOUNDARY = sweep.genesis_boundary_utc(GENESIS)
WIPE_TS = BOUNDARY - timedelta(hours=15)  # a future-genesis countdown window
IN_WINDOW = BOUNDARY - timedelta(hours=14)  # the 17:00 UTC daily run, post-wipe
POST_GENESIS = BOUNDARY + timedelta(hours=10)
CLOSING_CYCLE = 15
NOW_ISO = POST_GENESIS.isoformat()

COACH_PK = wipe.COACH_PARTITIONS[0][0]  # derived from the wipe registry, never typed
INSIGHTS_PK = recon.INSIGHTS_PK
DAY_BEFORE_GENESIS = (BOUNDARY.date() - timedelta(days=1)).isoformat()


# ── the fake: FakeDdbTable + an interpreter for the script's own writes ───────


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are NOT inside parentheses — ``if_not_exists(#c, :v)``
    is one clause, not two."""
    parts, depth, current = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _apply_update(table: FakeDdbTable, **kwargs) -> dict:
    """update_item_hook: apply the script's UpdateExpression to the store.

    Deliberately a MINI-interpreter of only the grammar this script emits
    (``REMOVE #a, #b`` / ``SET x = :v`` / ``SET x = if_not_exists(x, :v)``) —
    enough to make the idempotency assertion real, and narrow enough that an
    expression shape it does not understand raises here instead of silently
    passing.
    """
    key = kwargs["Key"]
    item = table.store.setdefault((key["pk"], key["sk"]), dict(key))
    expr = kwargs["UpdateExpression"].strip()
    names = kwargs.get("ExpressionAttributeNames", {})
    values = kwargs.get("ExpressionAttributeValues", {})

    def attr(token: str) -> str:
        return names[token] if token.startswith("#") else token

    if expr.startswith("REMOVE "):
        for token in _split_top_level(expr[len("REMOVE ") :]):
            item.pop(attr(token), None)
        return {}
    if expr.startswith("SET "):
        for clause in _split_top_level(expr[len("SET ") :]):
            lhs, rhs = clause.split("=", 1)
            name, rhs = attr(lhs.strip()), rhs.strip()
            if rhs.startswith("if_not_exists("):
                existing, placeholder = [p.strip() for p in rhs[len("if_not_exists(") : -1].split(",")]
                if attr(existing) in item:
                    continue
                item[name] = values[placeholder]
            else:
                item[name] = values[rhs]
        return {}
    raise AssertionError(f"unsupported UpdateExpression shape: {expr!r}")


def make_table(rows: list[dict]) -> FakeDdbTable:
    return FakeDdbTable(rows=rows, filter_by_pk=True, update_item_hook=_apply_update)


def wipe_evidence_row() -> dict:
    """A row the wipe archived — the evidence run_sweep derives its window from."""
    return {
        "pk": INSIGHTS_PK,
        "sk": "INSIGHT#pre-wipe",
        "tombstone": True,
        "phase": "pilot",
        "tombstoned_at": WIPE_TS.isoformat(),
        "tombstoned_reason": wipe.TOMBSTONE_REASON,
    }


def plan(table, **kw):
    return recon.plan(table, NOW_ISO, CLOSING_CYCLE, **kw)


def actions_of(result, group):
    return [a for a in result["actions"] if a.group == group]


# ── group A (#3514): a CROSS_PHASE row may carry no scoped provenance ─────────


def test_cross_phase_chat_row_with_a_tombstone_is_stripped():
    row = {
        "pk": COACH_PK,
        "sk": "CHAT#2026-08-09#abc123",
        "text": "kept",
        "tombstone": True,
        "phase": "pilot",
        "cycle": 12,
        "tombstoned_at": "2026-08-09T20:58:10Z",
        "tombstoned_reason": "experiment_restart_2026-08-10",
    }
    assert taxonomy.classify(COACH_PK, row["sk"]) == taxonomy.CROSS_PHASE
    acts = actions_of(plan(make_table([wipe_evidence_row(), row])), recon.GROUP_A)
    assert len(acts) == 1
    assert acts[0].issue == 3514
    expr, names, values = acts[0].update
    assert expr.startswith("REMOVE ")
    assert set(names.values()) == {"tombstone", "phase", "cycle", "tombstoned_at", "tombstoned_reason"}
    assert values == {}  # a strip carries no values at all — nothing can be written


def test_cross_phase_relationship_row_with_only_a_write_time_stamp_is_stripped():
    """The DA-6 instance: coach_state_updater stamps every row it writes."""
    row = {"pk": COACH_PK, "sk": "RELATIONSHIP#state", "phase": "experiment", "cycle": 16}
    acts = actions_of(plan(make_table([wipe_evidence_row(), row])), recon.GROUP_A)
    assert [a.sk for a in acts] == ["RELATIONSHIP#state"]
    assert set(acts[0].update[1].values()) == {"phase", "cycle"}


def test_a_clean_cross_phase_row_is_not_selected():
    """Negative control — without this, group A's count means nothing."""
    row = {"pk": COACH_PK, "sk": "CHAT#2026-08-09#clean", "text": "kept"}
    assert actions_of(plan(make_table([wipe_evidence_row(), row])), recon.GROUP_A) == []


def test_group_a_never_touches_an_experiment_scoped_row_on_the_same_partition():
    """A stamped THREAD# on the SAME COACH# pk is scoped — its stamp is correct."""
    row = {"pk": COACH_PK, "sk": "THREAD#topic", "phase": "experiment", "cycle": 16, "created_at": POST_GENESIS.isoformat()}
    result = plan(make_table([wipe_evidence_row(), row]))
    assert actions_of(result, recon.GROUP_A) == []
    assert actions_of(result, recon.GROUP_C) == []  # post-genesis: new-cycle state


# ── group B (#3513): stamp the phase the TAGGER would give ────────────────────


def test_unstamped_pre_genesis_insight_gets_pilot_and_the_closing_cycle():
    row = {"pk": INSIGHTS_PK, "sk": f"INSIGHT#{DAY_BEFORE_GENESIS}#daily_brief#tldr", "created_at": POST_GENESIS.isoformat()}
    acts = actions_of(plan(make_table([wipe_evidence_row(), row])), recon.GROUP_B)
    assert len(acts) == 1 and acts[0].issue == 3513
    assert acts[0].after == {"phase": "pilot", "cycle": CLOSING_CYCLE}
    _expr, _names, values = acts[0].update
    assert values[":phase"] == "pilot" and values[":cycle"] == CLOSING_CYCLE


def test_unstamped_post_genesis_insight_gets_the_current_phase_and_no_cycle():
    """The phase is DERIVED from the row's date, never a constant: a row dated on
    or after genesis is this cycle's and must stay visible."""
    row = {"pk": INSIGHTS_PK, "sk": f"INSIGHT#{GENESIS}#daily_brief#tldr"}
    acts = actions_of(plan(make_table([wipe_evidence_row(), row])), recon.GROUP_B)
    assert [a.after for a in acts] == [{"phase": "experiment"}]


def test_an_already_stamped_insight_is_not_selected():
    row = {"pk": INSIGHTS_PK, "sk": f"INSIGHT#{DAY_BEFORE_GENESIS}#daily_brief#tldr", "phase": "pilot"}
    assert actions_of(plan(make_table([wipe_evidence_row(), row])), recon.GROUP_B) == []


def test_an_undatable_scoped_row_is_flagged_never_stamped():
    """No date dimension = no derivable phase. Reported, never guessed."""
    row = {"pk": INSIGHTS_PK, "sk": "INSIGHT#no-date-anywhere"}
    result = plan(make_table([wipe_evidence_row(), row]))
    assert actions_of(result, recon.GROUP_B) == []
    assert (INSIGHTS_PK, "INSIGHT#no-date-anywhere") in result["undatable"]


# ── group C (#3511): the countdown-window escapees ────────────────────────────


def test_in_window_scoped_coach_row_is_planned_with_the_countdown_reconcile_write():
    row = {"pk": COACH_PK, "sk": "VOICE#state", "phase": "experiment", "cycle": 16, "updated_at": IN_WINDOW.isoformat()}
    acts = actions_of(plan(make_table([wipe_evidence_row(), row])), recon.GROUP_C)
    assert len(acts) == 1 and acts[0].issue == 3511
    expr, _names, values = acts[0].update
    assert values[":tomb"] is True and values[":phase"] == "pilot" and values[":cycle"] == CLOSING_CYCLE
    assert values[":reason"].startswith("countdown_gap_reconcile_")
    assert "if_not_exists" in expr  # never overwrites a prior generation's identity


def test_a_cross_phase_row_reported_by_the_sweep_is_never_written_by_group_c(monkeypatch):
    """Defence in depth for the #3514 sweep fix: even if the sweep regresses and
    reports a CROSS_PHASE row as an escapee, group C refuses it by CLASS."""
    row = {"pk": COACH_PK, "sk": "RELATIONSHIP#state", "phase": "experiment", "updated_at": IN_WINDOW.isoformat()}
    fake_sweep = {"escapees": [("coach_sleep", COACH_PK, "RELATIONSHIP#state", IN_WINDOW.isoformat())]}
    acts, misrouted = recon.plan_group_c(fake_sweep, {f"{COACH_PK}::RELATIONSHIP#state": row}, NOW_ISO, CLOSING_CYCLE)
    assert acts == []
    assert [a.sk for a in misrouted] == ["RELATIONSHIP#state"]


# ── the #3514 sweep fix itself ────────────────────────────────────────────────


@pytest.mark.parametrize("sk", ["CHAT#2026-08-09#abc", "CHAT#summary#2026-08-09", "RELATIONSHIP#state", "RELATIONSHIP#bits"])
def test_sweep_mode_skips_cross_phase_rows_on_a_coach_partition(sk):
    """Was ESCAPEE/FLAG_PRE_WINDOW before the `pk` argument was passed — i.e. a
    reconcile --apply would have tombstoned Matthew's coach relationship."""
    row = {"pk": COACH_PK, "sk": sk, "updated_at": IN_WINDOW.isoformat()}
    assert taxonomy.classify(COACH_PK, sk) == taxonomy.CROSS_PHASE
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, 16) == sweep.MODE_SKIP


def test_sweep_still_catches_the_scoped_row_on_the_same_partition():
    """Positive control for the line above — the carve-out must not blanket the
    partition, only the rows whose CLASS earns it."""
    row = {"pk": COACH_PK, "sk": "THREAD#topic", "created_at": IN_WINDOW.isoformat()}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, 16) == sweep.ESCAPEE


# ── refusal: a class the taxonomy does not cover stops the run ────────────────


def test_an_unclassifiable_row_refuses_the_whole_run(monkeypatch):
    unknown_pk = f"{wipe.USER_PK_PREFIX}zzz_source_that_is_not_in_the_registry"
    monkeypatch.setattr(recon, "scanned_partitions", lambda: [(unknown_pk, "")])
    table = make_table([{"pk": unknown_pk, "sk": "DATE#2026-09-01"}])
    result = plan(table)
    assert result["unclassified"] and result["actions"] == []
    assert table.updates == []


def test_main_exits_2_and_writes_nothing_when_a_row_is_unclassifiable(monkeypatch):
    import boto3

    unknown_pk = f"{wipe.USER_PK_PREFIX}zzz_source_that_is_not_in_the_registry"
    table = make_table([{"pk": unknown_pk, "sk": "DATE#2026-09-01"}])
    monkeypatch.setattr(recon, "scanned_partitions", lambda: [(unknown_pk, "")])
    monkeypatch.setattr(boto3, "resource", lambda *a, **k: type("R", (), {"Table": staticmethod(lambda _n: table)})())
    monkeypatch.setattr(recon, "REPO_ROOT", Path(str(REPO_ROOT)))
    assert recon.main(["--apply", "--closing-cycle", str(CLOSING_CYCLE)]) == 2
    assert table.updates == []


# ── idempotency: the whole plan, applied, re-planned ─────────────────────────


def test_the_plan_is_empty_after_its_own_writes_are_applied():
    rows = [
        wipe_evidence_row(),
        # group A: both live shapes
        {"pk": COACH_PK, "sk": "CHAT#2026-08-09#abc", "tombstone": True, "phase": "pilot", "cycle": 12, "tombstoned_at": "x"},
        {"pk": COACH_PK, "sk": "RELATIONSHIP#state", "phase": "experiment", "cycle": 16},
        # group B
        {"pk": INSIGHTS_PK, "sk": f"INSIGHT#{DAY_BEFORE_GENESIS}#daily_brief#tldr"},
        # group C
        {"pk": COACH_PK, "sk": "VOICE#state", "phase": "experiment", "cycle": 16, "updated_at": IN_WINDOW.isoformat()},
    ]
    table = make_table(rows)
    first = plan(table)
    assert {a.group for a in first["actions"]} == {recon.GROUP_A, recon.GROUP_B, recon.GROUP_C}

    for a in first["actions"]:
        expr, names, values = a.update
        kwargs = {"Key": {"pk": a.pk, "sk": a.sk}, "UpdateExpression": expr}
        if names:
            kwargs["ExpressionAttributeNames"] = names
        if values:
            kwargs["ExpressionAttributeValues"] = values
        table.update_item(**kwargs)

    # the writes did what the diff said
    chat = table.store[(COACH_PK, "CHAT#2026-08-09#abc")]
    assert not recon.provenance_attrs_on(chat)
    assert table.store[(INSIGHTS_PK, f"INSIGHT#{DAY_BEFORE_GENESIS}#daily_brief#tldr")]["phase"] == "pilot"
    assert table.store[(COACH_PK, "VOICE#state")]["tombstone"] is True

    second = plan(table)
    assert second["actions"] == [], [f"{a.group} {a.pk}/{a.sk}" for a in second["actions"]]
