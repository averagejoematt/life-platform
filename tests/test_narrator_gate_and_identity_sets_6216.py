"""tests/test_narrator_gate_and_identity_sets_6216.py — two guards that covered the listed sources, not the set (#6216).

1. Every call site of ``story_checks.all_findings`` in lambdas/, mcp/ and scripts/ passes ``owner_lines``, so the
   first-person attribution check (#6199/#6204) runs on every gate path. The fallback writer's gate skipped it.
2. No prompt-bearing source under lambdas/ or scripts/ states the narrator's identity with a retired phrase; the
   identity is rendered from ``content/elena_canon.py``.

# premerge-gate: walks lambdas/, mcp/ and scripts/ for call sites and retired phrases (a repo-shape ratchet)
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")


def _py_files(*roots):
    for root in roots:
        for dirpath, dirnames, files in os.walk(_REPO / root):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules", ".venv")]
            for f in files:
                if f.endswith(".py"):
                    yield Path(dirpath) / f


# A caller that genuinely holds no owner lines may register here with a reason. None is registered: every caller has them.
OWNER_LINES_EXEMPT: dict = {}


def _calls_missing_owner_lines():
    missing = []
    for p in _py_files("lambdas", "mcp", "scripts"):
        rel = str(p.relative_to(_REPO))
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if name != "all_findings":
                continue
            if any(k.arg == "owner_lines" for k in node.keywords) or any(k.arg is None for k in node.keywords):
                continue
            if rel in OWNER_LINES_EXEMPT:
                assert OWNER_LINES_EXEMPT[rel].strip(), f"{rel}: an exemption needs a reason"
                continue
            missing.append(f"{rel}:{node.lineno}")
    return missing


def test_every_all_findings_caller_passes_owner_lines():
    missing = _calls_missing_owner_lines()
    assert not missing, f"story_checks.all_findings called without owner_lines (the attribution check is skipped): {missing}"


def test_the_sweep_sees_the_known_call_sites():
    # the sweep must find the three story_pipeline call sites, or it is walking the wrong tree
    n = sum(
        1
        for p in _py_files("lambdas")
        if p.name == "story_pipeline.py"
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "all_findings"
    )
    assert n >= 3, n


AUDIT_SENTENCE = "The weight was never really the problem, he has said."


def test_the_fallback_gate_holds_an_attribution_when_no_words_of_his_are_on_record():
    from content import story_pipeline

    class G:
        n = 11
        dossier = {"week": 11}
        allowed: set = set()
        nye: list = []
        previous: dict = {}
        context: dict = {}
        corpus = story_pipeline.story_craft._norm("nothing")
        owner_lines: list = []
        weight_known = True
        craft_post = story_pipeline._Gates.craft_post

    md = f'"A week"\n\n[Weight: 288.5 lbs | Week Grade: avg 60 | T0 Streak: 3 days]\n\n{AUDIT_SENTENCE}\n\n---\n*Week 11 of The Measured Life*'
    found = story_pipeline.legacy_gate_findings(G(), md, {"titles": []}, fact_check=lambda *a, **k: [])
    assert any(f.startswith("source:") and "he has said" in f for f in found), found

    G.owner_lines = ["I slept badly and said so."]  # words of his on record: the same sentence is then not flagged
    found = story_pipeline.legacy_gate_findings(G(), md, {"titles": []}, fact_check=lambda *a, **k: [])
    assert not any("attributes words to him" in f for f in found), found


# ── the narrator's identity comes from the canon ─────────────────────────────

RETIRED = ("embedded journalist", "freelance journalist", "the journalist living inside", "ai journalist")

# path -> why a retired phrase may stay. The canon module itself never needs an entry (it states none).
ALLOW = {
    "lambdas/emails/coach_panel_podcast_lambda.py": "INTRO_COLD_OPEN is a SPOKEN line; the canon has no spoken-intro wording and new "
    "spoken words are an editorial choice, held for the owner (#6216)",
    "lambdas/emails/panelcast_repair.py": "INTRO_NAME_SENTENCE is a SPOKEN line, held for the owner for the same reason (#6216)",
    "scripts/gate_census_proofs.py": "the census record quotes the retired phrase in a mutation description",
}


def _literals(path: Path) -> str:
    """Every string literal in the module, adjacent literals already joined by the parser (a phrase split across two source
    lines is one string), lower-cased. Comments are not prompts and are not read."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return ""
    return "\n".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)).lower()


def test_no_prompt_source_states_the_narrator_with_a_retired_phrase():
    offenders = []
    for p in _py_files("lambdas", "scripts"):
        rel = str(p.relative_to(_REPO))
        if rel == "lambdas/content/elena_canon.py" or rel in ALLOW:
            continue
        low = _literals(p)
        hits = [ph for ph in RETIRED if ph in low]
        if hits:
            offenders.append(f"{rel}: {hits}")
    assert not offenders, f"render the narrator from content/elena_canon.py, not a restated identity: {offenders}"


def test_the_allowlist_holds_only_the_two_spoken_lines():
    for rel, ph in (
        ("lambdas/emails/coach_panel_podcast_lambda.py", "the journalist living inside"),
        ("lambdas/emails/panelcast_repair.py", "the journalist living inside"),
    ):
        text = _literals(_REPO / rel)
        assert ph in text, f"{rel} no longer carries the spoken line: drop its ALLOW entry"
        for other in RETIRED:
            if other != ph:
                assert other not in text, f"{rel} still restates the narrator with {other!r} outside the spoken line"


def test_the_rewritten_prompts_render_from_the_canon():
    from content import elena_canon
    from emails import elena_state_updater, panelcast_qa

    assert (
        elena_canon.NAME in elena_state_updater.EXTRACTION_SYSTEM_PROMPT and "AI narrator" in elena_state_updater.EXTRACTION_SYSTEM_PROMPT
    )
    assert elena_canon.host_summary().removeprefix(elena_canon.NAME + ", ") in panelcast_qa._WEEKLY_RUBRIC
    assert elena_canon.host_summary().removeprefix(elena_canon.NAME + ", ") in panelcast_qa._INTRO_RUBRIC
