"""tests/test_synced_skill_drift_5086.py — the coach-session skill has ONE repo source, a drift check
holds the claude.ai synced copy to it, and the Telegram coach's training route reads the C4 context (#5086).

Every synced copy here is a FIXTURE under tmp_path: the real `~/.claude/skills/synced` tree is never
read (discovery is pointed at a fixture `--home`, and `$SYNCED_SKILL_PATHS` is cleared).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, str(ROOT / "lambdas"))

_spec = importlib.util.spec_from_file_location("check_synced_skill_drift", ROOT / "scripts" / "check_synced_skill_drift.py")
drift = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(drift)

SKILL = ROOT / ".claude" / "skills" / "coach-session" / "SKILL.md"
SOURCE = SKILL.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_env_paths(monkeypatch):
    monkeypatch.delenv(drift.ENV_VAR, raising=False)


def _synced_tree(home: Path, text: str) -> list[Path]:
    """Both places the desktop app keeps a copy, under a fixture home."""
    a = home / ".claude/skills/synced/org_acct/coach-session/SKILL.md"
    b = home / "Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/org/acct/skills/coach-session/SKILL.md"
    for p in (a, b):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return [a, b]


def _reflowed_upload_form(text: str) -> str:
    """What the upload leaves: frontmatter cut to name + description (quoted), the body re-wrapped and
    carrying trailing spaces and extra blank lines — none of which is drift."""
    fields, body = drift._parse_frontmatter(text)
    head = f'---\nname: "{fields["name"]}"\ndescription: "{fields["description"]}"\n---\n'
    body = body.replace("skip the\nbasics.", "skip the basics.   ").replace("\n\n", "\n\n\n")
    assert "skip the basics.   " in body, "the fixture no longer re-wraps anything"
    return head + body


# ── the drift check ─────────────────────────────────────────────────────────────────────────
def test_a_matching_copy_is_in_sync_in_both_synced_locations(tmp_path, capsys):
    _synced_tree(tmp_path, _reflowed_upload_form(SOURCE))
    assert drift.run(["--home", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("in sync:") == 2 and "2 of 2 synced copies match" in out


def test_a_differing_copy_is_drift_with_the_line_named(tmp_path, capsys):
    """Mutation: one instruction in the synced copy reverts to the retired flow."""
    stale = SOURCE.replace("`manage_hevy_routine` action `draft`", "`manage_hevy_routine` action `draft_custom`", 1)
    assert stale != SOURCE
    copies = _synced_tree(tmp_path, SOURCE)
    copies[1].write_text(stale, encoding="utf-8")
    assert drift.run(["--home", str(tmp_path), "--diff-lines", "0"]) == 1
    out = capsys.readouterr().out
    assert "in sync: " + str(copies[0]) in out and "DRIFT: " + str(copies[1]) in out
    assert "action `draft_custom`" in out and "1 of 2 synced copies match" in out


def test_a_description_change_alone_is_drift(tmp_path):
    fields, body = drift._parse_frontmatter(SOURCE)
    (copy,) = _synced_tree(tmp_path, f'---\nname: coach-session\ndescription: "an older description"\n---\n{body}')[:1]
    assert drift.compare(SKILL, copy)["state"] == "drift"


def test_no_synced_copy_is_skipped_with_the_reason_never_in_sync(tmp_path, capsys):
    assert drift.run(["--home", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == drift.SKIPPED == "skipped: no synced copy on this machine"


def test_explicit_paths_and_the_env_var_outrank_discovery(tmp_path, monkeypatch):
    discovered = _synced_tree(tmp_path / "home", "stale")
    good = tmp_path / "good.md"
    good.write_text(SOURCE, encoding="utf-8")
    assert drift.run(["--home", str(tmp_path / "home"), "--synced", str(good)]) == 0
    monkeypatch.setenv(drift.ENV_VAR, str(good))
    assert drift.run(["--home", str(tmp_path / "home")]) == 0
    monkeypatch.setenv(drift.ENV_VAR, os.pathsep.join([str(good), str(discovered[0])]))
    assert drift.run(["--home", str(tmp_path / "home")]) == 1
    missing = tmp_path / "gone.md"  # a NAMED copy that is absent is drift, never a skip
    assert drift.run(["--synced", str(missing)]) == 1


def test_a_missing_repo_source_exits_2(tmp_path):
    assert drift.run(["--root", str(tmp_path), "--home", str(tmp_path)]) == 2


def test_the_upload_package_round_trips_in_sync(tmp_path):
    out = tmp_path / "coach-session.zip"
    assert drift.run(["--package", str(out)]) == 0
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == ["coach-session/SKILL.md"]
        text = z.read("coach-session/SKILL.md").decode("utf-8")
    fields, _body = drift._parse_frontmatter(text)
    assert set(fields) == {"name", "description"}, "the upload carries no Claude Code-only frontmatter key"
    unpacked = tmp_path / "unpacked.md"
    unpacked.write_text(text, encoding="utf-8")
    assert drift.compare(SKILL, unpacked)["state"] == "in_sync"


# ── the one repo source, rewritten to the charter ─────────────────────────────────────────────
def test_the_coach_session_skill_runs_the_order_contract_from_the_packet():
    from training import coach_context

    assert "get_coach_session_packet" in SOURCE and "coach_context" in SOURCE
    i_packet = SOURCE.index("`get_coach_session_packet`")
    i_plan = SOURCE.index("**`plan_next_session`**")
    i_draft = SOURCE.index("`manage_hevy_routine` action `draft`")
    assert i_packet < i_plan < i_draft, "the skill states the ORDER contract out of order"
    assert coach_context.ORDER == ("pre_flight", "plan_next_session", "manage_hevy_routine draft")
    assert "`lambdas/training/coach_context.py::ORDER`" in SOURCE
    assert "`departure_reason`" in SOURCE and "`draft_custom` is ONLY for a departure he has stated" in SOURCE
    assert "action `deload`" in SOURCE and "action `disruption`" in SOURCE and "`disruption_end`" in SOURCE
    assert "may_frame" in SOURCE and "`cardio_menu`" in SOURCE and "`effort_ceilings.overage_tolerance_rpe`" in SOURCE
    assert "`deload_recommendation`" in SOURCE and "`steps_ramp`" in SOURCE
    for key in ("split.lifting_days_per_wk", "split.sequence", "effort_ceilings.ceiling_change_proposal", "governing_goal.target_date"):
        assert f"`{key}`" in SOURCE, f"the skill names the charter key {key} instead of copying its value"


def test_the_skill_carries_no_retired_frame():
    """The synced copy's stale content (#5086 Set): the role-play board, the v0.4 four-session lock and
    the commit-to-git step the commit call replaced."""
    for stale in (
        "Personal Board",
        "Sarah Chen",
        "v0.4 upper/lower",
        "4-session",
        "remind him to git commit",
        # review round 2: word-form copies of charter values the derivation guard cannot see
        "five lifting days",
        "Two weeks of most sets",
        "May 2027",
    ):
        assert stale not in SOURCE, stale


def test_the_old_prompt_is_a_pointer_not_a_second_source():
    old = (ROOT / "docs" / "coaching" / "COACH_SESSION.md").read_text(encoding="utf-8")
    assert "`.claude/skills/coach-session/SKILL.md`" in old
    assert len([ln for ln in old.splitlines() if ln.strip()]) <= 12, "COACH_SESSION.md grew back into a second copy"
    assert "get_coach_session_packet" not in old and "plan_next_session" not in old


def test_the_open_checkin_pointer_names_the_skill_not_the_board():
    text = (ROOT / ".claude" / "skills" / "open-checkin" / "SKILL.md").read_text(encoding="utf-8")
    assert "Personal Board" not in text and "`.claude/skills/coach-session/SKILL.md`" in text


# ── the Telegram coach's training route reads the one assembly (C4, verified end to end) ─────
def test_the_telegram_training_seat_assembles_the_coach_context(monkeypatch):
    """Through the worker's own `_assemble`, not the domain-pack helper alone: the physical seat's
    `domain` (what the reply prompt and the grounder are given) carries the charter, the order contract
    and the May frame; another seat does not. Mutation: drop the route-key branch in
    coach_domain_facts.domain_facts_block and the first assertion fails."""
    from coach import coach_domain_facts as df, telegram_worker_lambda as tw

    class _Table:
        def query(self, **_):
            return {"Items": []}

        def get_item(self, **_):
            return {}

    monkeypatch.setattr(tw, "_table", lambda: _Table())
    monkeypatch.setattr(tw, "_s3_client", lambda: None)
    monkeypatch.setattr(tw, "display_name", lambda *a, **k: "Coach")
    monkeypatch.setattr(tw, "_thread_today", lambda pid: [])
    monkeypatch.setattr(tw, "_facts", lambda: {})
    monkeypatch.setattr(tw, "_memory_block", lambda pid: "")
    monkeypatch.setattr(tw, "_current_moment_line", lambda: "")
    monkeypatch.setattr(tw, "_pacific_now", lambda: datetime(2026, 10, 20, 9, 0))
    monkeypatch.setattr(tw, "_colleagues_block", lambda *a, **k: "")
    monkeypatch.setattr("coach.persona_core.persona_block", lambda *a, **k: "")
    monkeypatch.setattr("coach.coach_vision.thread_block", lambda *a, **k: "")
    monkeypatch.setattr("health.clinical_facts.clinical_context_block", lambda table, published=True: "CLINICAL BLOCK")
    monkeypatch.setattr(df, "_experiment_frame_lines", lambda today: [])

    seat = tw._assemble("physical_coach", "physical_coach")
    assert "CHARTER v" in seat["domain"] and "ORDER: pre_flight -> plan_next_session" in seat["domain"]
    assert "May frame:" in seat["domain"] and "CLINICAL BLOCK" in seat["domain"]
    assert seat["domain"] in seat["facts_block"]
    other = tw._assemble("sleep_coach", "sleep_coach")
    assert "CHARTER v" not in other["domain"] and "CLINICAL BLOCK" in other["domain"]
