"""tests/test_story_label_gate_1349.py — the /wrap label-completeness gate (#1349).

Replays the SDLC-review finding: `.claude/agents/issue-filer.md`'s ADR-099 contract
requires every filed issue to carry "exactly one model:*" label, but nothing checked
that the rule held over time. Two open type:story issues (#1243, #1228) carried no
model:* label at all despite the rule — invisible until someone happened to grep for
it, and every session seeding from a model:* label query silently skipped them.

Every test here fails on the pre-#1349 tree (missing gate wiring / a vacuous checker /
the checker failing to catch the pinned pre-fix fixture).
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAP = ROOT / ".claude" / "commands" / "wrap.md"


def _load(script):
    spec = importlib.util.spec_from_file_location("_story_labels_1349", ROOT / script)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── the gate is wired into the /wrap skill ──────────────────────────────────────
def test_wrap_skill_has_label_completeness_gate():
    wrap = WRAP.read_text(encoding="utf-8")
    assert (
        "Label-completeness gate" in wrap or "label-completeness gate" in wrap.lower()
    ), "#1349: the /wrap label-completeness gate step is missing"
    assert "check_story_labels.py" in wrap, "#1349: the gate script must actually be invoked from wrap.md, not just described"
    assert "model:" in wrap.split("abel-completeness gate")[1][:2000].lower()


def test_guardrails_section_lists_the_label_gate():
    wrap = WRAP.read_text(encoding="utf-8")
    guardrails = wrap.split("## Guardrails")[1]
    assert "#1349" in guardrails


# ── the checker itself is non-vacuous, mirroring the #1189/#1340 house style ────
def test_unlabeled_stories_is_not_vacuous():
    chk = _load("scripts/check_story_labels.py")
    issues = [
        {"number": 1, "title": "has a model label", "labels": [{"name": "type:story"}, {"name": "model:sonnet"}]},
        {"number": 2, "title": "no model label at all", "labels": [{"name": "type:story"}, {"name": "area:infra"}]},
    ]
    hits = chk.unlabeled_stories(issues)
    assert len(hits) == 1, f"label-completeness scan is VACUOUS or over-flags — got {len(hits)} hits, expected 1"
    assert hits[0]["number"] == 2


def test_unlabeled_stories_accepts_bare_string_labels_too():
    """gh's --json labels shape is normally [{"name": ...}], but keep the parser tolerant
    of a plain list-of-strings fixture too, since it costs nothing and matches the
    house style in check_residual_queue.py of testing the pure function directly."""
    chk = _load("scripts/check_story_labels.py")
    issues = [{"number": 3, "title": "bare string labels", "labels": ["type:story", "model:opus"]}]
    assert chk.unlabeled_stories(issues) == []


# ── regression guard: fires on the pre-fix tree (#1349 AC 4) ────────────────────
def test_regression_guard_fires_on_pre_fix_tree():
    """Pins the exact pre-fix evidence from the issue: #1243 and #1228 were open
    type:story issues with no model:* label. A third, correctly-labeled issue proves
    the check isn't just flagging everything."""
    chk = _load("scripts/check_story_labels.py")
    pre_fix_issues = [
        {
            "number": 1243,
            "title": "site-ux finding",
            "labels": [{"name": "type:story"}, {"name": "area:site-ux"}, {"name": "review:2026-07-16"}],
        },
        {
            "number": 1228,
            "title": "infra finding",
            "labels": [{"name": "type:story"}, {"name": "area:infra"}, {"name": "review:2026-07-16"}],
        },
        {
            "number": 1111,
            "title": "properly labeled story",
            "labels": [{"name": "type:story"}, {"name": "area:infra"}, {"name": "model:sonnet"}],
        },
    ]
    hits = chk.unlabeled_stories(pre_fix_issues)
    hit_numbers = sorted(h["number"] for h in hits)
    assert hit_numbers == [1228, 1243], f"#1349: regression guard did not reproduce the pinned pre-fix violators, got {hit_numbers}"


def test_cli_offline_mode_exit_1_on_violators(tmp_path, capsys):
    chk = _load("scripts/check_story_labels.py")
    fixture = tmp_path / "issues.json"
    fixture.write_text(
        json.dumps(
            [
                {"number": 1243, "title": "unlabeled", "labels": [{"name": "type:story"}]},
            ]
        )
    )
    rc = chk.main(["--issues-json", str(fixture)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "1243" in out


def test_cli_offline_mode_exit_0_when_clean(tmp_path, capsys):
    chk = _load("scripts/check_story_labels.py")
    fixture = tmp_path / "issues.json"
    fixture.write_text(
        json.dumps(
            [
                {"number": 42, "title": "labeled", "labels": [{"name": "type:story"}, {"name": "model:fable"}]},
            ]
        )
    )
    rc = chk.main(["--issues-json", str(fixture)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out


def test_cli_fail_open_when_gh_unavailable(monkeypatch, capsys):
    """No network/gh auth in CI's test job — a live-fetch failure must never red the
    suite (mirrors coverage_gap_warn's fail-open contract)."""
    chk = _load("scripts/check_story_labels.py")
    monkeypatch.setattr(chk, "_fetch_live_issues", lambda: None)
    rc = chk.main([])
    capsys.readouterr()
    assert rc == 0
