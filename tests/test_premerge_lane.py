"""tests/test_premerge_lane.py — ADR-139's regression guard (#1344).

The advisory pre-merge lane lives in git precisely because GitHub settings
evaporate on visibility flips (#1319). This guard pins the lane's existence
and its three checks so it can't silently vanish; the OTHER half of the
posture (required-ness = none, owner toggle) is GET-verified weekly by
deploy/drift_sentinel.py against deploy/github_posture.json.

Deliberately stdlib-only (string asserts, no yaml dep) — the guard for the
collection-error killer must never itself be a collection error.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_premerge_lane_exists_and_triggers_on_pull_request():
    assert WORKFLOW.is_file(), "ADR-139: .github/workflows/pr-checks.yml is gone"
    text = _text()
    assert "pull_request:" in text, "ADR-139: the lane must trigger on pull_request"
    assert "branches: [main]" in text


def test_premerge_lane_carries_the_three_checks():
    text = _text()
    assert "--collect-only" in text, "ADR-139: the collection gate (the #1297 class) is gone"
    assert "deploy_critical and not integration" in text, "ADR-139: the deploy-critical subset is gone"
    assert "black --check" in text, "ADR-139: the format gate is gone"


def test_premerge_lane_is_read_only():
    assert "contents: read" in _text(), "ADR-139: the lane must stay read-only (no write permissions)"
