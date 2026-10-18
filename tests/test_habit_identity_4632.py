"""#4632 — a habit is its vendor habit id; names are aliases; only an explicit correction un-ticks.

HELD on #4644 Q26/Q27 — built on the recommended answers:
  Q26: "same habit keeps its streak (id-keyed), applied to the history too"
  Q27: "b (explicit correction only)"

Box 1: the ingest stamps `aliases` (every other name the same vendor id carried on the prior
stored day) on each `habit_statuses` entry, and the tiered scoring lookup + the streaks resolve
a registry habit by id, then name, then alias — so a rename mid-history is ONE streak.

Box 3: a vendor-authored `failed`, decided on a successful logs read, withdraws a stored
`completed` only on an explicit `{"date_override": D, "correction": true}` run; a fetch failure
(journal fallback, a vanished habit) or a platform-inferred miss never does, flag or not.

Fixture = the wire: `tests/fixtures/habitify/habitify_2026-09-06_wire.json` (LIVE Habitify
journal + logs, captured read-only for #3666). The archived raw object
`raw/matthew/habitify/2026/10/2026-10-15.json` (registry `raw_layout`: date-tree) was read
read-only to confirm the same shape is still on the wire: `raw.journal[*].id` on all 61
entries, unique, and `logs[*][*].habit_id`. Only public supplement names are renamed here.

Run:  python3 -m pytest tests/test_habit_identity_4632.py -v
"""

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import habitify_lambda  # noqa: E402
import pytest  # noqa: E402
from habitify_lambda import (  # noqa: E402
    _bridge_entries,
    correction_dates_from_event,
    identity_from_record,
    reset_identity_cache,
    transform,
    upgrade_only_merge,
)
from health.habit_streaks import compute_habit_streaks  # noqa: E402
from health.scoring_engine import habitify_reading, score_habits_registry  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "habitify", "habitify_2026-09-06_wire.json")
DAY = "2026-09-06"
OLD, NEW = "Collagen", "Collagen Peptides"  # a public supplement habit (#4333)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # A fixed clock: the wire day is CLOSED (the day after), never "today" by the live clock.
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-07")
    monkeypatch.setattr(habitify_lambda, "_ALIAS_GROUPS_CACHE", [])  # no registry aliases at all
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset())
    reset_identity_cache()
    yield
    reset_identity_cache()


def _wire():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def _raw(wire):
    return {"date": DAY, "area_map": wire["area_map"], "journal": wire["journal"], "moods": [], "logs": wire["logs"]}


def _renamed(wire, old=OLD, new=NEW):
    w = copy.deepcopy(wire)
    for e in w["journal"]:
        if e["name"] == old:
            e["name"] = new
    w["logs"][new] = w["logs"].pop(old)
    return w


def _entry(wire, name):
    return next(e for e in wire["journal"] if e["name"] == name)


def _stored_day():
    return transform(_raw(_wire()), DAY)[0]


# ── Box 1: identity by vendor id, names as aliases ───────────────────────────────────────


def test_the_ingest_derives_the_old_name_as_an_alias_from_id_continuity():
    before = _stored_day()
    assert before["habit_statuses"][OLD]["status"] == "completed"
    habit_id = before["habit_statuses"][OLD]["habit_id"]
    reset_identity_cache(lambda _d: identity_from_record(before))
    after = transform(_raw(_renamed(_wire())), DAY)[0]
    assert OLD not in after["habit_statuses"]
    renamed = after["habit_statuses"][NEW]
    assert renamed["habit_id"] == habit_id
    assert renamed["aliases"] == [OLD]
    # A habit that was NOT renamed carries no aliases.
    assert "aliases" not in after["habit_statuses"]["Creatine"]


def test_the_alias_chain_carries_every_earlier_name_forward():
    first = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(first))
    second = transform(_raw(_renamed(_wire())), DAY)[0]
    reset_identity_cache(lambda _d: identity_from_record(second))
    third = transform(_raw(_renamed(_wire(), OLD, "Collagen (Marine)")), DAY)[0]
    assert third["habit_statuses"]["Collagen (Marine)"]["aliases"] == [OLD, NEW]


def test_a_rename_mid_history_is_one_streak():
    """Three days under the old name, two under the new one: ONE Tier-0 streak of five."""
    before = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(before))
    after = transform(_raw(_renamed(_wire())), DAY)[0]
    rows = {"2026-09-10": after, "2026-09-09": after, "2026-09-08": before, "2026-09-07": before, "2026-09-06": before}
    profile = {"habit_registry": {OLD: {"status": "active", "tier": 0}}}
    out = compute_habit_streaks(profile, "2026-09-10", lambda _src, d: rows.get(d))
    assert out["tier0_streak"] == 5


def test_the_tiered_scoring_lookup_reads_the_renamed_habit_under_its_registry_key():
    before = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(before))
    after = transform(_raw(_renamed(_wire())), DAY)[0]
    profile = {"habit_registry": {OLD: {"status": "active", "tier": 0}}}
    score, details = score_habits_registry({"habitify": after, "date": "2026-09-10"}, profile)
    assert details["tier_status"][0] == {OLD: True}
    assert OLD not in details.get("unobserved", [])
    assert score == 100


def test_a_registry_habitify_id_keys_the_lookup_with_no_name_in_common():
    day = _stored_day()
    habit_id = day["habit_statuses"][OLD]["habit_id"]
    meta = {"status": "active", "tier": 0, "habitify_id": habit_id}
    assert habitify_reading(day["habits"], "A Name Habitify Never Used", meta, day["habit_statuses"]) == 1.0
    # Without the day's statuses it is the #4362 name lookup: unobserved, never a miss.
    assert habitify_reading(day["habits"], "A Name Habitify Never Used", meta) is None


def test_a_same_day_rename_by_id_is_one_row_and_keeps_the_stored_completion(monkeypatch):
    stored = _stored_day()
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: DAY)  # the day is still open
    renamed_wire = _renamed(_wire())
    renamed_wire["logs"][NEW] = []  # this run cannot see the tick (no log attributed yet)
    fresh = transform(_raw(renamed_wire), DAY)[0]
    assert fresh["habit_statuses"][NEW]["status"] == "pending"
    merged = upgrade_only_merge(stored, fresh)
    statuses = merged["habit_statuses"]
    assert OLD not in statuses
    assert statuses[NEW]["status"] == "completed"
    assert statuses[NEW]["aliases"] == [OLD]
    assert len(statuses) == len(stored["habit_statuses"])
    assert merged["total_completed"] == stored["total_completed"]


def test_an_unreadable_prior_day_yields_no_aliases_never_a_lost_day():
    def _boom(_d):
        raise RuntimeError("throttled")

    reset_identity_cache(_boom)
    rec = transform(_raw(_renamed(_wire())), DAY)[0]
    assert NEW in rec["habit_statuses"] and "aliases" not in rec["habit_statuses"][NEW]


def test_the_ddb_reader_takes_the_nearest_earlier_day_that_has_statuses(monkeypatch):
    calls = []
    good = _stored_day()

    class _Table:
        def query(self, **kw):
            calls.append(kw)
            return {"Items": [{"sk": "DATE#2026-09-05", "absent": True}, good]}

    monkeypatch.setattr(habitify_lambda, "_table", _Table())
    ids = habitify_lambda._ddb_prior_identity(DAY)
    assert ids[good["habit_statuses"][OLD]["habit_id"]] == {OLD}
    assert calls[0]["ScanIndexForward"] is False


def test_the_bridge_resolves_a_renamed_supplement_through_its_alias():
    before = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(before))
    after = transform(_raw(_renamed(_wire(), OLD, "Marine Collagen")), DAY)[0]
    names = {e["name"] for e in _bridge_entries(after, [])}
    assert "Marine Collagen" in names


# ── Box 3: only an explicit correction lets the vendor's failed withdraw a completion ─────


def _unticked(wire, name=OLD, logs_fetched=True):
    """The vendor's view after the owner un-ticks `name`: no log, and the journal says failed."""
    w = copy.deepcopy(wire)
    _entry(w, name)["status"] = "failed"
    if logs_fetched:
        w["logs"][name] = []
    else:
        w["logs"].pop(name)  # the logs GET for this habit failed (journal fallback)
    return w


def test_without_a_correction_a_vendor_failed_never_downgrades_a_completion():
    stored = _stored_day()
    fresh = transform(_raw(_unticked(_wire())), DAY)[0]
    assert fresh["habit_statuses"][OLD]["status"] == "failed"
    assert fresh["habit_statuses"][OLD]["miss_source"] == "vendor"
    merged = upgrade_only_merge(stored, fresh)
    assert merged["habit_statuses"][OLD]["status"] == "completed"
    assert "corrections" not in merged


def test_an_explicit_correction_lets_the_vendors_failed_withdraw_a_completion(monkeypatch):
    stored = _stored_day()
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", correction_dates_from_event({"date_override": DAY, "correction": True}))
    fresh = transform(_raw(_unticked(_wire())), DAY)[0]
    merged = upgrade_only_merge(stored, fresh)
    assert merged["habit_statuses"][OLD]["status"] == "failed"
    assert merged["habits"][OLD] == 0
    assert merged["total_completed"] == stored["total_completed"] - 1
    assert merged["corrections"] == [f"{OLD}:completed->failed"]
    # The supplements bridge follows the stored record: the un-ticked supplement is retracted.
    prior_bridge = _bridge_entries(stored, [])
    assert OLD in {e["name"] for e in prior_bridge}
    assert OLD not in {e["name"] for e in _bridge_entries(merged, prior_bridge)}


def test_a_fetch_failure_cannot_downgrade_a_completion_even_under_a_correction(monkeypatch):
    stored = _stored_day()
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset({DAY}))
    # (a) the logs GET failed: the journal's failed is not per-day truth (#3666's UTC bucketing).
    fresh = transform(_raw(_unticked(_wire(), logs_fetched=False)), DAY)[0]
    assert fresh["habit_statuses"][OLD]["status_channel"] == "journal"
    assert upgrade_only_merge(stored, fresh)["habit_statuses"][OLD]["status"] == "completed"
    # (b) the habit vanished from the journal altogether.
    gone = copy.deepcopy(_wire())
    gone["journal"] = [e for e in gone["journal"] if e["name"] != OLD]
    gone["logs"].pop(OLD)
    assert upgrade_only_merge(stored, transform(_raw(gone), DAY)[0])["habit_statuses"][OLD]["status"] == "completed"
    # (c) nobody said failed: the platform resolved an in_progress habit at day close.
    platform = copy.deepcopy(_wire())
    platform["logs"][OLD] = []
    fresh_p = transform(_raw(platform), DAY)[0]
    assert fresh_p["habit_statuses"][OLD]["miss_source"] == "platform"
    assert upgrade_only_merge(stored, fresh_p)["habit_statuses"][OLD]["status"] == "completed"


def test_the_correction_trail_survives_a_later_ordinary_run(monkeypatch):
    stored = _stored_day()
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset({DAY}))
    corrected = upgrade_only_merge(stored, transform(_raw(_unticked(_wire())), DAY)[0])
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset())
    later = upgrade_only_merge(corrected, transform(_raw(_unticked(_wire())), DAY)[0])
    assert later["habit_statuses"][OLD]["status"] == "failed"
    assert later["corrections"] == [f"{OLD}:completed->failed"]


def test_a_correction_needs_an_explicit_date_and_an_explicit_flag():
    assert correction_dates_from_event({"date_override": DAY, "correction": True}) == frozenset({DAY})
    assert correction_dates_from_event({"date_override": DAY}) == frozenset()
    assert correction_dates_from_event({"date_override": DAY, "correction": "yes"}) == frozenset()
    assert correction_dates_from_event({"date_override": "today", "correction": True}) == frozenset()
    assert correction_dates_from_event({"correction": True}) == frozenset()


def test_the_handler_arms_the_correction_for_that_invocation_only(monkeypatch):
    seen = []
    monkeypatch.setattr(habitify_lambda, "run_ingestion", lambda *a, **k: seen.append(habitify_lambda._CORRECTION_DATES) or {})
    habitify_lambda.lambda_handler({"date_override": DAY, "correction": True}, None)
    habitify_lambda.lambda_handler({}, None)
    assert seen == [frozenset({DAY}), frozenset()]


# ── #4632 follow-on: every reader resolves a habit by vendor id (#4644 Q26) ──────────────
#
# PR #4945 keyed the scoring and the streaks on id; seven reader call sites (coach context in
# `ai/ai_calls.py` + `ai/ai_context.py`, the brief HTML in `content/html_builder.py`) still
# called `habitify_reading` WITHOUT the day's `habit_statuses`, i.e. the #4362 name-only
# lookup, so a habit renamed after ids were stored read as unobserved there. Rows below are
# the real `transform` output over the committed wire capture, renamed by id continuity.


def _renamed_days():
    """(done, missed): the renamed day as stored, and the same day after a vendor un-tick."""
    before = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(before))
    done = transform(_raw(_renamed(_wire())), DAY)[0]
    missed = transform(_raw(_unticked(_renamed(_wire()), NEW)), DAY)[0]
    assert done["habit_statuses"][NEW]["aliases"] == [OLD] == missed["habit_statuses"][NEW]["aliases"]
    assert missed["habit_statuses"][NEW]["status"] == "failed"
    return done, missed


def _reader_modules():
    for k, v in (("AWS_DEFAULT_REGION", "us-west-2"), ("AWS_ACCESS_KEY_ID", "testing"), ("AWS_SECRET_ACCESS_KEY", "testing")):
        os.environ.setdefault(k, v)
    from ai import ai_calls, ai_context  # noqa: E402
    from content import html_builder  # noqa: E402

    return ai_calls, ai_context, html_builder


def test_every_reader_call_site_resolves_a_renamed_habit_to_the_same_identity():
    """One test over all seven sites (one census gate): each names every site that lost the habit."""
    ai_calls, ai_context, html_builder = _reader_modules()
    done, missed = _renamed_days()
    meta = {"status": "active", "tier": 0, "synergy_group": "stack", "why_matthew": "w"}
    by_id = {"status": "active", "tier": 0, "habitify_id": done["habit_statuses"][NEW]["habit_id"]}
    profile = {"habit_registry": {OLD: meta}}
    cs = {"pillar_mind": {"raw_score": 90, "level": 5}, "pillar_sleep": {"raw_score": 40, "level": 2}}
    checks = {
        # ai_calls.py — call_board_of_directors (missed T0/T1 + synergy) and call_tldr_and_guidance
        "ai_calls._missed_registry_habits": ai_calls._missed_registry_habits(profile["habit_registry"], missed) == [(OLD, meta)],
        # ai_context.py — the 7-day T0/T1 trend lines (two calls)
        "ai_context._build_habit_outcome_context": "T0 1/1" in ai_context._build_habit_outcome_context({"habitify_7d": [done]}, profile),
        # ai_context.py — the pillar effort count (registry key with no name in common: the id keys it)
        "ai_context._compute_diminishing_returns": "Diminishing returns on: Mind"
        in ai_context._compute_diminishing_returns(cs, {"habitify": done}, {"habit_registry": {"journal": by_id}}),
        # html_builder.py — the HABITS DEEP-DIVE rows and its synergy count
        "html_builder._habits_deep_dive (done)": "✅" in html_builder._habits_deep_dive({"habitify": done}, profile),
        "html_builder._habits_deep_dive (missed)": "❌" in html_builder._habits_deep_dive({"habitify": missed}, profile),
    }
    lost = sorted(k for k, ok in checks.items() if not ok)
    assert not lost, f"a renamed habit lost its identity at: {lost}"


# ── the SET guard: no reader looks a habit up by name through the old path ───────────────
# premerge-gate: #4632: AST sweep of lambdas/ + mcp/ — every habitify_reading call passes the day's habit_statuses

_SWEEP_ROOTS = ("lambdas", "mcp")
_LOOKUPS = {"habitify_reading": (3, "statuses"), "day_name_for": (1, "statuses")}  # fn -> (statuses arg index, kw name)


def _name_keyed_lookups(source: str, path: str = "<src>") -> list[str]:
    """`path:line fn` for each call of `habitify_reading` / `day_name_for` that does not pass
    the day's `habit_statuses` (argument missing, or the literal None) — the #4362 name-only
    path #4632 retired. `**kwargs` / `*args` splats are trusted (not statically decidable)."""
    import ast

    out = []
    for node in ast.walk(ast.parse(source, filename=path)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        if fn not in _LOOKUPS:
            continue
        idx, kw = _LOOKUPS[fn]
        if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
            continue
        arg = node.args[idx] if len(node.args) > idx else next((k.value for k in node.keywords if k.arg == kw), None)
        if arg is None or (isinstance(arg, ast.Constant) and arg.value is None):
            out.append(f"{path}:{node.lineno} {fn}")
    return out


def _sweep_tree() -> list[str]:
    offenders = []
    for root in _SWEEP_ROOTS:
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, root)):
            for f in sorted(files):
                if f.endswith(".py"):
                    p = os.path.join(dirpath, f)
                    with open(p, encoding="utf-8") as fh:
                        offenders += _name_keyed_lookups(fh.read(), os.path.relpath(p, ROOT))
    return offenders


def test_no_reader_looks_a_habit_up_by_name_without_the_days_statuses():
    planted = (
        "from health.scoring_engine import habitify_reading\n"
        "a = habitify_reading(h_map, h_name, meta)\n"
        "b = habitify_reading(h_map, h_name, meta, None)\n"
        "c = day_name_for(h_map, None, key, meta)\n"
        "ok = habitify_reading(h_map, h_name, meta, day.get('habit_statuses'))\n"
        "ok2 = habitify_reading(h_map, h_name, meta=meta, statuses=s)\n"
    )
    assert _name_keyed_lookups(planted, "planted.py") == [
        "planted.py:2 habitify_reading",
        "planted.py:3 habitify_reading",
        "planted.py:4 day_name_for",
    ]
    offenders = _sweep_tree()
    assert not offenders, f"name-keyed habit lookups (pass the day's habit_statuses — #4632, #4644 Q26): {offenders}"


# ── the drift check treats a renamed habit (same id, new name) as the same registry entry ──


def test_the_drift_check_matches_a_renamed_habit_by_id_not_as_two_orphans(tmp_path, capsys):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import check_habit_registry_drift as drift  # noqa: E402

    journal = copy.deepcopy(_renamed(_wire())["journal"])  # the live wire, Collagen renamed in the app
    habit_id = next(e for e in journal if e["name"] == NEW)["id"]
    live = drift.live_names(journal)
    others = {n: {} for n in live if n != NEW}
    stale = {**others, OLD: {"habitify_id": habit_id}}  # the registry still says the old name
    counts = drift.drift_counts(live, stale, [], drift.live_ids(journal))
    assert (counts["live_without_registry"], counts["registry_without_live"]) == (0, 0)
    # Without ids it is the name rule: the same rename reads as one orphan on each side.
    blind = drift.drift_counts(live, stale, [])
    assert (blind["live_without_registry"], blind["registry_without_live"]) == (1, 1)
    # The bridge resolves through the id-matched entry too, and an id with no live habit stays an orphan.
    assert (
        drift.drift_counts(
            live, {**stale, OLD: {"habitify_id": habit_id, "habitify_names": ["Supp X"]}}, ["Supp X"], drift.live_ids(journal)
        )["bridge_without_live"]
        == 0
    )
    gone = drift.drift_counts(live, {**others, OLD: {"habitify_id": "no-such-id"}}, [], drift.live_ids(journal))
    assert (gone["live_without_registry"], gone["registry_without_live"]) == (1, 1)
    # End to end through --fixture (the journal carries ids), exit code kept: 0 aligned.
    p = tmp_path / "habit_drift_4632_rename.json"
    p.write_text(json.dumps({"journal": journal, "habit_registry": stale, "bridge_keys": []}))
    assert drift.main(["--fixture", str(p)]) == 0
    assert NEW not in capsys.readouterr().out
