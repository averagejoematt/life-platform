"""tests/test_retirement_ledger_5141.py — the retirement ledger: each charter story names what it
removes, and an add-only wave states a reason (#5141, epic #5134).

The five charter primitives, and where each one is:
  1. Registry — `ledgers/retirement_ledger.py` (RETIREMENTS + ADDS_ONLY): the one place a
     named removal, its story and its status live.
  2. Derivation guard — which waves RETIRE is derived from the ledger through
     `backlog_next.wave_of` (never hand-listed on the wave), and the dark-feed set is derived
     from `source_registry`'s `paused` facet; both are tested here as SET equalities.
  3. Ratchet — keys are append-only and a `retired` row never goes back
     (`SEED_KEYS_2026_10_23` / `SEED_RETIRED_2026_10_23` below).
  4. Contract test — the ledger <-> `docs/PROPORTIONALITY.md` Retired table join, in both
     directions; the hygiene rules run on `build_ctx` over the real `gh issue list` shape.
  5. Dead-man — `rule_retirement_ledger_liveness`: a `planned` row whose story left the open
     corpus reds the nightly wrap (wrap-nightly.yml) and /wrap e7.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import backlog_contract as bc  # noqa: E402
import backlog_next as bn  # noqa: E402
import backlog_retirement as br  # noqa: E402
import check_backlog_hygiene as hy  # noqa: E402
from ingestion import source_registry  # noqa: E402

_spec = importlib.util.spec_from_file_location("retirement_ledger_5141", REPO_ROOT / "ledgers" / "retirement_ledger.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

WAVES_SPEC = json.loads((REPO_ROOT / "scripts" / "backlog_waves.json").read_text(encoding="utf-8"))
PROPORTIONALITY = (REPO_ROOT / "docs" / "PROPORTIONALITY.md").read_text(encoding="utf-8")

# The append-only pin (primitive 3) — typed out, not derived, so deleting a row reds here.
SEED_KEYS_2026_10_23 = {
    "coach-daily-reflection",
    "food-delivery-daily-feed",
    "partner-email-journal-section",
    "titration-payback-cap",
    "lifting-rpe-caps",
    "character-steps-8000-fallback",
    "scheduled-program-week-6-deload",
    "hand-copied-rate-targets",
    "plan-daily-calories-constant-1500",
    "personal-board-text-and-training-coach-config",
    "two-1500-prompted-meal-emails",
    "program-v04-revert-generator",
    "program-v03-history",
    "public-meal-endpoints",
    "garmin-direct-api",
    "youtube-schedule",
    "bluesky-schedule",
    "mastodon-schedule",
}
SEED_RETIRED_2026_10_23 = frozenset(
    {
        "bluesky-schedule",
        "character-steps-8000-fallback",
        "coach-daily-reflection",
        "garmin-direct-api",
        "hand-copied-rate-targets",
        "lifting-rpe-caps",
        "mastodon-schedule",
        "partner-email-journal-section",
        "scheduled-program-week-6-deload",
        "titration-payback-cap",
        "youtube-schedule",
    }
)  # frozen at the 2026-10-23 seed: a planned row that later retires joins the ledger, never this floor
NAMES_A_REMOVAL = ("planned", "retired", "demoted")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── 1. the registry's shape ─────────────────────────────────────────────────────
def test_every_row_has_the_fields_its_status_requires():
    bad = []
    for key, row in L.RETIREMENTS.items():
        status = row.get("status")
        if status not in L.STATUSES:
            bad.append(f"{key}: status {status!r} not in {L.STATUSES}")
            continue
        if len(row.get("what") or "") < 20:
            bad.append(f"{key}: `what` must name the removed thing concretely")
        story = row.get("story")
        if not (isinstance(story, int) or (story is None and status == "kept")):
            bad.append(f"{key}: only a `kept` row may have no story")
        if status in ("retired", "demoted") and not _DATE.match(row.get("date") or ""):
            bad.append(f"{key}: a {status} row carries its date (YYYY-MM-DD)")
        if status in NAMES_A_REMOVAL and len(row.get("record") or "") < 40:
            bad.append(f"{key}: a {status} row quotes its evidence in `record`")
        if status == "kept" and (len(row.get("reason") or "") < 40 or not row.get("retire_when")):
            bad.append(f"{key}: a kept row states its reason and what would retire it")
        if "pr" in row and not isinstance(row["pr"], int):
            bad.append(f"{key}: `pr` is a PR number")
    for key, row in L.ADDS_ONLY.items():
        if not (isinstance(row.get("story"), int) and isinstance(row.get("pr"), int) and len(row.get("reason") or "") >= 40):
            bad.append(f"ADDS_ONLY {key}: story, pr and a real reason")
    assert not bad, "\n".join(bad)


def test_the_ledger_is_append_only_and_a_retired_row_stays_retired():
    missing = SEED_KEYS_2026_10_23 - set(L.RETIREMENTS)
    assert not missing, f"#5141: ledger rows never disappear — change the status instead: {sorted(missing)}"
    reopened = sorted(k for k in SEED_RETIRED_2026_10_23 if L.RETIREMENTS[k]["status"] != "retired")
    assert not reopened, f"#5141: a retired row cannot go back: {reopened}"
    assert len(SEED_RETIRED_2026_10_23) == 11, "the seed's retired count is the ratchet's floor"


def test_the_backfill_carries_the_briefed_rows():
    """The 2026-10-23 backfill, each from its PR's own text."""
    rows = L.RETIREMENTS
    assert (rows["coach-daily-reflection"]["pr"], rows["coach-daily-reflection"]["status"]) == (5263, "retired")
    assert (rows["food-delivery-daily-feed"]["pr"], rows["food-delivery-daily-feed"]["status"]) == (5261, "demoted")
    assert L.ADDS_ONLY["pr-5226-charter-twin-list"]["story"] == 5220
    assert rows["plan-daily-calories-constant-1500"]["story"] == 5095
    assert rows["food-delivery-daily-feed"]["story"] == 5108


# ── 2. derivation: waves, and the dark feeds ────────────────────────────────────
def retiring_waves(waves, retirements):
    """Wave ids with at least one removal row — derived through backlog_next.wave_of."""
    out = set()
    for row in retirements.values():
        if row.get("status") not in NAMES_A_REMOVAL:
            continue
        idx = bn.wave_of({"number": row.get("story"), "epic_parent": None}, waves)
        if idx is not None:
            out.add(waves[idx]["id"])
    return out


def wave_reason_problems(waves, retirements):
    retiring = retiring_waves(waves, retirements)
    problems = []
    for w in waves:
        reason = (w.get("adds_only_reason") or "").strip()
        if w["id"] in retiring and reason:
            problems.append(f"{w['id']}: retires (a ledger row names it) but still claims `adds_only_reason`")
        if w["id"] not in retiring and len(reason) < 60:
            problems.append(f"{w['id']}: no story in it names a removal — state why in `adds_only_reason`")
    return problems


def test_every_wave_retires_something_or_states_why_it_only_adds():
    problems = wave_reason_problems(WAVES_SPEC["waves"], L.RETIREMENTS)
    assert not problems, "#5141 box 3:\n" + "\n".join(problems)


def test_the_wave_rule_fails_in_both_directions():
    waves = [dict(w) for w in WAVES_SPEC["waves"]]
    # (a) drop the only nutrition-W0 removal: that wave must now state a reason
    without = {k: v for k, v in L.RETIREMENTS.items() if k != "plan-daily-calories-constant-1500"}
    assert any(p.startswith("nutrition-W0:") for p in wave_reason_problems(waves, without))
    # (b) a stale adds-only claim on a wave that retires
    stale = [dict(w, adds_only_reason="x" * 80) if w["id"] == "training-W0" else w for w in waves]
    assert any(p.startswith("training-W0:") for p in wave_reason_problems(stale, L.RETIREMENTS))


def test_every_dark_feed_has_a_retire_or_keep_row():
    paused = {k for k, v in source_registry.SOURCE_REGISTRY.items() if v.get("paused")}
    feeds = [row["feed"] for row in L.RETIREMENTS.values() if row.get("feed")]
    assert len(feeds) == len(set(feeds)), "one row per feed"
    assert paused, "the paused set went empty — the derivation has gone blind"
    assert set(feeds) == paused, (
        f"#5141 box 4: paused registry sources {sorted(paused)} != ledger feed rows {sorted(set(feeds))} — "
        "a newly dark feed needs its row, a revived one loses the `feed` key"
    )


def test_the_legacy_generator_has_a_named_story_or_keep_reason():
    row = L.RETIREMENTS["program-v04-revert-generator"]
    assert row["status"] in L.STATUSES and (row["status"] != "kept" or row["reason"])
    assert (REPO_ROOT / "lambdas" / "training" / "program_v04.py").exists(), "the row names a file that no longer exists — retire it"


# ── 4. contract: the ledger <-> the PROPORTIONALITY Retired table ───────────────
def retired_table_rows(doc: str):
    section = doc.split("## Retired", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and _DATE.match(cells[1][:10]):
            rows.append((cells[0], cells[1][:10], line))
    return rows


def _cites(text: str, row: dict) -> bool:
    return any(isinstance(n, int) and re.search(rf"#{n}\b", text) for n in (row.get("story"), row.get("pr")))


def test_proportionality_retired_rows_and_the_ledger_agree():
    table = retired_table_rows(PROPORTIONALITY)
    assert len(table) >= 5, "the Retired-table parse found too few rows — the parser has gone blind"
    problems = []
    for key, row in L.RETIREMENTS.items():
        if row.get("posture_row") and not any(_cites(line, row) for _s, _d, line in table):
            problems.append(f"ledger `{key}` says posture_row but no Retired-table row cites #{row.get('story')}/#{row.get('pr')}")
    for subsystem, date, line in table:
        if date >= L.LEDGER_START and not any(_cites(line, r) for r in L.RETIREMENTS.values()):
            problems.append(f"Retired-table row `{subsystem[:60]}` ({date}) has no ledger row citing it")
    assert not problems, "\n".join(problems)


def test_the_join_fails_when_a_new_retired_row_skips_the_ledger():
    doc = PROPORTIONALITY.replace(
        "## How to read this as a CIO", "| Fake subsystem | 2099-01-01 | #999999 — removed |\n\n## How to read this as a CIO", 1
    )
    table = retired_table_rows(doc)
    assert any(s == "Fake subsystem" for s, _d, _l in table)
    assert not any(_cites(line, r) for s, _d, line in table if s == "Fake subsystem" for r in L.RETIREMENTS.values())


# ── the grammar (backlog_contract.retires_statement) ────────────────────────────
def test_retires_statement_parses_both_forms_and_the_none_arm():
    assert bc.retires_statement("## Retires\n- the 1500 constant\n") == bc.Retires(False, None, "- the 1500 constant")
    s = bc.retires_statement("## Retires\nnone — adds a calibration prompt nothing replaces\n## Acceptance\n")
    assert s.is_none and s.reason == "adds a calibration prompt nothing replaces"
    assert bc.retires_statement("**Retires:** none").is_none
    assert bc.retires_statement("**Retires:** the v0.4 sequence").text == "the v0.4 sequence"
    assert bc.retires_statement("## Retires\n\n## Next\nbody") is None
    assert bc.retires_statement("Retires the constant in prose only") is None


# ── the hygiene rules, on the real `gh issue list --json` record shape ──────────
def _issue(number, body, created="2026-10-26T01:00:00Z", labels=("type:story", "area:infra")):
    return {
        "number": number,
        "title": f"story {number}",
        "labels": [{"name": n} for n in labels],
        "milestone": {"title": "Now"},
        "body": body,
        "createdAt": created,
        "updatedAt": created,
        "author": {"login": "averagejoematt"},
        "comments": [],
    }


_SPEC = {"waves": [{"id": "w", "issues": [9001, 9002, 9003, 9004], "epics": [9100]}]}


class _Ledger:
    RETIREMENTS = {"x": {"story": 9004, "status": "planned"}, "gone": {"story": 9050, "status": "planned"}}
    ADDS_ONLY: dict = {}


def _run(issues, ledger=_Ledger):
    return br.run([hy.build_ctx(i) for i in issues], spec=_SPEC, ledger=ledger)


def test_a_new_charter_story_with_no_retires_line_is_a_violation():
    out = _run([_issue(9001, "## Outcome\n**operator** — x\n")])
    assert [(r[0], r[1], r[3]) for r in out if r[0] == "retires_section"] == [("retires_section", 9001, br.VIOLATION)]


def test_named_removal_none_with_reason_and_ledger_row_all_pass():
    issues = [
        _issue(9001, "## Retires\nthe 1500 constant\n"),
        _issue(9002, "**Retires:** none — adds a weekly prompt that nothing replaces\n"),
        _issue(9004, "no line, but the ledger names it"),
    ]
    assert [r for r in _run(issues) if r[0] == "retires_section"] == []


def test_a_bare_none_is_not_a_reason():
    out = _run([_issue(9003, "## Retires\nnone — tbd\n")])
    assert [r[1] for r in out if r[0] == "retires_section"] == [9003]


def test_epic_children_are_charter_stories_and_unwaved_stories_are_not():
    issues = [_issue(9200, "**Epic:** #9100\n"), _issue(9300, "**Epic:** #1\n"), _issue(9001, "x", labels=("type:epic",))]
    assert [r[1] for r in _run(issues) if r[0] == "retires_section"] == [9200]


def test_an_older_story_is_named_once_in_an_advisory_never_silent():
    out = _run([_issue(9001, "x", created="2026-10-20T00:00:00Z"), _issue(9002, "y", created="2026-10-21T00:00:00Z")])
    rows = [r for r in out if r[0] == "retires_section"]
    assert len(rows) == 1 and rows[0][3] == br.ADVISORY and "[9001, 9002]" in rows[0][2]


def test_liveness_reds_a_planned_row_whose_story_left_the_open_corpus():
    out = _run([_issue(9004, "x")])
    assert [(r[1], r[3]) for r in out if r[0] == "retirement_ledger_liveness"] == [(9050, br.VIOLATION)]
    assert not [r for r in _run([_issue(9004, "x"), _issue(9050, "x")]) if r[0] == "retirement_ledger_liveness"]


def test_the_live_ledger_has_no_stale_planned_row_shape():
    """Every planned row names an int story, so the dead-man can see it."""
    assert all(isinstance(r["story"], int) for r in L.RETIREMENTS.values() if r["status"] == "planned")


def test_severity_names_match_the_linter_and_fixtures_stay_unarmed():
    assert (br.VIOLATION, br.ADVISORY) == (hy.VIOLATION, hy.ADVISORY)
    fixture = [_issue(5095, "x")]
    assert not [f for f in hy.check(fixture) if f.rule.startswith("retire")], "an offline check() must not arm the ledger rules"
    armed = hy.check(fixture, retirement=True)
    assert any(f.rule == "retirement_ledger_liveness" for f in armed), "armed, the committed ledger's other planned rows are stale here"
