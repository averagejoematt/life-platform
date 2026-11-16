"""tests/test_core_alias_6090.py — a core-12 habit's public id is a neutral alias (#6090, owner ruling 2026-11-16).

The owner ruled: remove the private habit identifier from the current public repository, keep the 43 historical computed
rows (and their keys) as they are, no history rewrite. So the public charter carries a NEUTRAL alias for that one core
habit (`id_alias`), the id its rows are stored under stays owner data in the habit registry (`core` = the stored id,
`core_alias` = the alias, PROFILE#v1), and `health.core_habits.resolve_spec` swaps one for the other before anything is
graded or keyed. What is held here, on SYNTHETIC ids only:

  1. THE CHARTER carries only ids on a neutral allow-list, and every alias is `core_h<NN>`.
  2. THE MAPPING: with it, the aliased habit grades and keys exactly as a charter naming the stored id would — the
     same members, states, score and `core_status` / `component_details` keys (the replay equivalence).
  3. THE FAIL-SAFE: without it, the habit has no members — unknown, never a miss, never a crash — a WARNING names the
     alias (never the stored id), and the drift check reports it.
  4. THE OWNER SCRIPT writes the mapping dry-run first and idempotently, translates `--set ALIAS=KEY` to the stored id.
  5. THE REPOSITORY SWEEP: no tracked file carries a string from the off-repo private-identifier list (the content-filter
     channel, #2503/#2370) — skipped visibly when no channel source carries the list.

No clock is read on any of these paths.
# premerge-gate: sweeps every git-tracked file for the off-repo private-identifier list (a repo-shape ratchet)
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for _k, _v in [("AWS_REGION", "us-west-2"), ("AWS_DEFAULT_REGION", "us-west-2"), ("TABLE_NAME", "life-platform"), ("USER_ID", "matthew")]:
    os.environ.setdefault(_k, _v)
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "scripts"))

from health import core_habits  # noqa: E402
from training import training_charter as tc  # noqa: E402

DAY = "2026-10-21"
ALIAS = "core_h10"
STORED = "synthetic_stored_h10"  # a synthetic stand-in for the private stored id; never a real habit name
# Every id the public charter may carry (habits.core and the disruption playbook's held/paused lists). A new core id is
# a reviewed addition here: a descriptive id that spells a private habit is exactly what this list exists to stop.
NEUTRAL_IDS = frozenset(
    {
        "weigh_in",
        "food_logged",
        "calories_in_band",
        "protein_floor",
        "steps_floor",
        "planned_session_done",
        "evening_checkin",
        "no_alcohol",
        "no_solo_takeout",
        "core_h10",
        "out_of_bed_on_time",
        "one_connection",
    }
)
ALIAS_RE = re.compile(r"^core_h\d{2}$")


def _habitify_ids() -> list[str]:
    return [e["id"] for e in core_habits.core_spec() if e["basis"] == "habitify"]


def _registry(*, flag_for_alias: str, mapped: bool) -> dict:
    """One active entry per Habitify-basis id; the aliased habit has two members flagged `flag_for_alias`."""
    reg = {f"Habit {cid}": {"status": "active", "tier": 1, "core": cid} for cid in _habitify_ids() if cid != ALIAS}
    for name in ("Habit pair_a", "Habit pair_b"):
        reg[name] = {"status": "active", "tier": 1, "core": flag_for_alias, **({"core_alias": ALIAS} if mapped else {})}
    reg["Retained floss"] = {"status": "active", "tier": 0}
    return reg


def _stored_spec() -> list[dict]:
    """The charter as it read before #6090, synthetically: the aliased entry under its stored id, no `id_alias`."""
    out = []
    for e in core_habits.core_spec():
        e = {k: v for k, v in e.items() if k != "id_alias"}
        out.append({**e, "id": STORED} if e["id"] == ALIAS else e)
    return out


def _grade(registry, spec=None, *, broken: str = "Habit pair_b"):
    readings = {k: (0.0 if k == broken else 1.0) for k in registry}
    wakes = {f"2026-10-{d:02d}": "06:00" for d in range(7, 21)} | {DAY: "06:05"}
    return core_habits.grade_day(
        registry, day=DAY, reading=lambda k, m: readings.get(k), steps=tc.charter_value("steps.floor"), wakes=wakes, checkin=True, spec=spec
    )


# ── 1. the public charter ───────────────────────────────────────────────────────────────────


def test_the_public_charter_carries_only_neutral_ids():
    core = tc.charter_value("habits.core")
    whole = tc.charter_value("disruption.whole_day")
    ids = {e["id"] for e in core} | set(whole["held_habits"]) | set(whole["paused_habits"])
    assert ids <= NEUTRAL_IDS, f"{len(ids - NEUTRAL_IDS)} charter id(s) not on the neutral allow-list"
    aliased = [e for e in core if e.get("id_alias")]
    assert [e["id"] for e in aliased] == [ALIAS] and all(ALIAS_RE.match(e["id"]) and e["basis"] == "habitify" for e in aliased)
    assert tc.public_view()["habits"]["core"] == core, "the alias is what a published surface sees"


# ── 2. the mapping: identical grading, identical keys ───────────────────────────────────────


def test_the_alias_grades_and_keys_exactly_as_the_stored_id_did():
    mapped = _registry(flag_for_alias=STORED, mapped=True)
    before = _grade(_registry(flag_for_alias=STORED, mapped=False), _stored_spec())
    after = _grade(mapped)
    for g in (before, after):
        g.pop("charter_version")  # the version stamp moves with any charter bump; nothing else may
    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)
    st = {r["id"]: r["state"] for r in after["habits"]}
    assert st[STORED] == "missed" and ALIAS not in st, "the row is keyed by the stored id, never the alias"
    fields = core_habits.habit_scores_fields(after)
    assert set(fields["core_status"]) == {e["id"] for e in _stored_spec()}
    assert core_habits.members(mapped)[STORED] == ["Habit pair_a", "Habit pair_b"]
    assert core_habits.flag_drift(mapped)["core_flag_unknown"] == 0 and core_habits.flag_drift(mapped)["core_ids_unflagged"] == 0
    assert core_habits.core_keys(mapped) >= {"Habit pair_a", "Habit pair_b"}


def test_resolution_is_idempotent_and_leaves_the_charter_spec_untouched():
    mapped = _registry(flag_for_alias=STORED, mapped=True)
    spec = core_habits.core_spec()
    snapshot = copy.deepcopy(spec)
    once = core_habits.resolve_spec(spec, mapped)
    assert core_habits.resolve_spec(once, mapped) == once and spec == snapshot
    assert core_habits.alias_map(mapped) == {ALIAS: STORED}


def test_an_alias_flagged_directly_needs_no_mapping():
    direct = _registry(flag_for_alias=ALIAS, mapped=False)
    st = {r["id"]: r["state"] for r in _grade(direct)["habits"]}
    assert st[ALIAS] == "missed"


# ── 3. the fail-safe ────────────────────────────────────────────────────────────────────────


def test_no_mapping_is_unknown_never_a_miss_and_says_so(caplog):
    unmapped = _registry(flag_for_alias=STORED, mapped=False)
    with caplog.at_level(logging.WARNING, logger="health.core_habits"):
        g = _grade(unmapped)
    st = {r["id"]: r["state"] for r in g["habits"]}
    assert st[ALIAS] == "unknown" and STORED not in st
    assert (g["known"], g["unknown"]) == (11, 1), "the unmapped habit leaves the score; nothing is scored as missed for it"
    warned = [r.getMessage() for r in caplog.records if ALIAS in r.getMessage()]
    assert len(warned) == 1 and "no private mapping" in warned[0]
    assert not any(STORED in r.getMessage() for r in caplog.records), "a log line never carries the stored id"
    d = core_habits.flag_drift(unmapped)
    assert (d["core_ids_unflagged"], d["core_flag_unknown"]) == (1, 2), "the missing mapping is drift the check reports"


def test_an_ambiguous_mapping_is_left_unresolved(caplog):
    reg = _registry(flag_for_alias=STORED, mapped=True)
    reg["Habit pair_b"]["core"] = "another_stored_id"
    with caplog.at_level(logging.WARNING, logger="health.core_habits"):
        assert core_habits.alias_map(reg) == {}
    assert any("2 different stored ids" in r.getMessage() for r in caplog.records)
    assert not any(STORED in r.getMessage() or "another_stored_id" in r.getMessage() for r in caplog.records)


def test_an_unarmed_registry_never_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="health.core_habits"):
        g = core_habits.grade_day({}, day=DAY)
    assert not g["armed"] and g["unknown"] == 12 and not caplog.records


# ── 4. the owner script ─────────────────────────────────────────────────────────────────────


def test_the_mapping_write_is_planned_counted_and_idempotent():
    import apply_habit_core_flags as ap

    unmapped = _registry(flag_for_alias=STORED, mapped=False)
    writes, already, errors = ap.alias_plan(unmapped, ALIAS)
    assert sorted(writes) == ["Habit pair_a", "Habit pair_b"] and already == 0 and not errors
    ok, line = ap.alias_readback(unmapped, ALIAS)
    assert not ok and "resolves=no" in line and STORED not in line
    mapped = _registry(flag_for_alias=STORED, mapped=True)
    writes, already, errors = ap.alias_plan(mapped, ALIAS)
    assert writes == [] and already == 2 and not errors, "a second run writes nothing"
    ok, line = ap.alias_readback(mapped, ALIAS)
    assert ok and "active_members=2" in line and STORED not in line and "Habit pair_a" not in line


def test_the_mapping_write_refuses_what_it_cannot_tell_apart():
    import apply_habit_core_flags as ap

    two = _registry(flag_for_alias=STORED, mapped=False)
    two["Habit pair_b"]["core"] = "another_stored_id"
    _, _, errors = ap.alias_plan(two, ALIAS)
    assert errors and "2 distinct core flags" in errors[0] and not any(STORED in e for e in errors)
    _, _, errors = ap.alias_plan(_registry(flag_for_alias=STORED, mapped=False), "weigh_in")
    assert errors and "not a Habitify-basis id_alias entry" in errors[0]
    _, _, errors = ap.alias_plan(_registry(flag_for_alias=ALIAS, mapped=False), ALIAS)
    assert errors and "nothing to map" in errors[0]


def test_set_translates_the_alias_to_the_stored_id_and_refuses_an_unmapped_one():
    import apply_habit_core_flags as ap

    mapped = _registry(flag_for_alias=STORED, mapped=True)
    writes, errors = ap.plan(mapped, [f"{ALIAS}=Retained floss"])
    assert writes == [("Retained floss", STORED)] and not errors, "a new member keys like the old ones"
    _, errors = ap.plan(_registry(flag_for_alias=STORED, mapped=False), [f"{ALIAS}=Retained floss"])
    assert errors and "no private mapping yet" in errors[0]


# ── 5. the repository sweep against the off-repo list ───────────────────────────────────────


def _tracked_hits(terms: list[str], files: dict[str, str]) -> list[str]:
    """The paths whose text carries any term (case-insensitive substring). Never the term."""
    low = [t.lower() for t in terms if t]
    return sorted(p for p, text in files.items() if any(t in text.lower() for t in low))


def _tracked_text() -> dict[str, str]:
    paths = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout.decode().split("\0")
    out = {}
    for p in filter(None, paths):
        f = REPO / p
        try:
            raw = f.read_bytes()
        except OSError:
            continue  # a tracked path deleted in the working tree
        if b"\0" in raw[:4096]:
            continue  # binary
        out[p] = raw.decode("utf-8", errors="ignore")
    return out


def test_the_sweep_finds_a_planted_identifier_and_never_echoes_it():
    files = {"a.json": '{"id": "Planted_Private_X1"}', "b.py": "clean = True"}
    assert _tracked_hits(["planted_private_x1"], files) == ["a.json"]
    assert _tracked_hits([], files) == []


def test_no_tracked_file_carries_a_private_identifier(monkeypatch):
    """The gate itself. The list is the content-filter channel's optional `private_identifiers` (env CONTENT_FILTER_JSON
    as CI's secret, config/content_filter.local.json, or the private S3 object) — never a tracked file. Skips visibly
    when no channel source carries it."""
    import conftest as _conftest
    from privacy import content_filter_channel

    if _conftest.REAL_CONTENT_FILTER_ENV:
        monkeypatch.setenv("CONTENT_FILTER_JSON", _conftest.REAL_CONTENT_FILTER_ENV)
    else:
        monkeypatch.delenv("CONTENT_FILTER_JSON", raising=False)
    content_filter_channel.reset_cache()
    try:
        terms = content_filter_channel.private_identifiers(require=False)
    finally:
        content_filter_channel.reset_cache()
    if not terms:
        pytest.skip("no content-filter channel source carries `private_identifiers` — armed via the CI secret / local.json / S3")
    files = _tracked_text()
    assert len(files) > 1000, f"suspiciously few tracked text files ({len(files)})"
    hits = _tracked_hits(terms, files)
    assert not hits, f"{len(hits)} tracked file(s) carry a private identifier (terms masked): {hits}"
