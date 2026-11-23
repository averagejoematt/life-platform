"""tests/test_narrator_gate_and_identity_sets_6216.py — two guards that covered the listed sources, not the set (#6216).

1. Every call site of ``story_checks.all_findings`` in lambdas/, mcp/ and scripts/ passes ``owner_lines`` (a literal None
   counts as omitted), so the first-person attribution check (#6199/#6204) runs on every gate path; a path that cannot
   supply the record gets a distinguishable finding, never silence.
2. Every string under lambdas/ or scripts/ that tells a model or a listener who the narrator is renders the canon's identity
   text (a restated one must still disclose AI and claim no human career, on a reasoned allowlist).

# premerge-gate: walks lambdas/, mcp/ and scripts/ for call sites and retired phrases (a repo-shape ratchet)
"""

from __future__ import annotations

import ast
import os
import re
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
            kw = [k for k in node.keywords if k.arg == "owner_lines"]
            # a literal None is the same silence as an omitted keyword (#6216); **kwargs and any other expression pass
            if (kw and not (isinstance(kw[0].value, ast.Constant) and kw[0].value.value is None)) or any(
                k.arg is None for k in node.keywords
            ):
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


class _G:
    """The fallback gate's object, built by hand (the same fields ``_Gates`` carries)."""

    def __init__(self, owner_lines):
        from content import story_pipeline

        self.n = 11
        self.dossier = {"week": 11}
        self.allowed: set = set()
        self.nye: list = []
        self.previous: dict = {}
        self.context: dict = {}
        self.corpus = story_pipeline.story_craft._norm("nothing")
        self.owner_lines = owner_lines
        self.weight_known = True

    def craft_post(self, md):
        from content import story_pipeline

        return story_pipeline._Gates.craft_post(self, md)


def _md(body):
    return f'"A week"\n\n[Weight: 288.5 lbs | Week Grade: avg 60 | T0 Streak: 3 days]\n\n{body}\n\n---\n*Week 11 of The Measured Life*'


def _fallback(owner_lines, body):
    from content import story_pipeline

    return story_pipeline.legacy_gate_findings(_G(owner_lines), _md(body), {"titles": []}, fact_check=lambda *a, **k: [])


def test_the_fallback_gate_holds_the_audits_sentence_with_no_words_of_his_on_record():
    found = _fallback([], AUDIT_SENTENCE)
    assert any(f.startswith("source:") and "he has said" in f for f in found), found


def test_an_unrelated_owner_line_does_not_clear_an_attribution():
    found = _fallback(["I slept badly and said so."], AUDIT_SENTENCE)
    assert any("none of his recorded words this week is about that" in f for f in found), found


def test_a_matching_recorded_line_clears_that_attribution():
    found = _fallback(["The weight was never the problem for me; the evenings were."], AUDIT_SENTENCE)
    assert not any("attributes words to him" in f or "attribution evidence" in f for f in found), found


def test_a_gate_path_with_no_evidence_says_so_distinguishably():
    found = _fallback(None, AUDIT_SENTENCE)
    assert any("attribution evidence unavailable" in f and f.startswith("source:") for f in found), found
    from content import story_checks

    assert "attribution evidence unavailable" in story_checks.ATTRIBUTION_UNAVAILABLE
    assert "owner_lines" in story_checks.ATTRIBUTION_UNAVAILABLE, "the message names what to pass"


def test_a_clean_week_passes_the_fallback_gate_whatever_the_evidence():
    clean = "The scale read 288.5 this week, down from where the week began. The evenings were quiet."
    for lines in ([], None, ["I walk because it clears my head."]):
        found = _fallback(lines, clean)
        assert not any("attribut" in f for f in found), (lines, found)


def test_the_ast_sweep_rejects_a_literal_none(tmp_path, monkeypatch):
    src = "def f(sc, t):\n    return sc.all_findings(t, stop_reason=None, allowed=set(), owner_lines=None)\n"
    tree = ast.parse(src)
    (call,) = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "all_findings"]
    (kw,) = [k for k in call.keywords if k.arg == "owner_lines"]
    assert isinstance(kw.value, ast.Constant) and kw.value.value is None
    # and the real sweep's predicate treats it as missing: plant it in a copy of the sweep over a temp tree
    monkeypatch.setattr(sys.modules[__name__], "_REPO", tmp_path)
    (tmp_path / "lambdas").mkdir()
    (tmp_path / "lambdas" / "x.py").write_text(src, encoding="utf-8")
    assert _calls_missing_owner_lines() == ["lambdas/x.py:2"]


# ── the narrator's identity comes from the canon ─────────────────────────────

# Secondary denylist: phrases that assert a human career. "journalist" alone is not one (owner, 2026-11-22): the test is
# whether a string implies a real human journalist rather than the disclosed AI editorial narrator.
HUMAN_CAREER = ("embedded journalist", "freelance journalist", "the journalist living inside")

# The two SPOKEN intro lines keep their wording until the owner chooses new spoken words (owner decision pending, #6216).
SPOKEN_PENDING = {
    "lambdas/emails/coach_panel_podcast_lambda.py": "INTRO_COLD_OPEN",
    "lambdas/emails/panelcast_repair.py": "INTRO_NAME_SENTENCE",
}
CENSUS_QUOTES = {"scripts/gate_census_proofs.py": "the census record quotes the retired phrases in mutation descriptions"}

# A string that states who the narrator is, in the words of the string: "Elena Voss" followed by an appositive, a
# parenthetical or "is a/the" — or the host line "ELENA (host)". Docstrings and comments describe code, not a prompt.
_IDENTITY = re.compile(
    r"elena(?: voss)?\W{0,3}\s*(?:\(|,\s*(?:the|a|an|our|who|her)\b|\s+(?:is|was)\s+(?:the|a|an)\b|—)",
    re.IGNORECASE,
)
# Names whose presence inside an f-string's braces means the identity is rendered from the canon's own functions.
_CANON_NAMES = {"elena_canon", "_canon", "_ELENA_HOST", "_elena_host_summary"}

# path -> why a RESTATED identity string may stay beside the canon. Each must still disclose AI and claim no human career.
RESTATED_OK = {
    "lambdas/content/story_writers.py": "the desk's story-picker rubric names her 'the series' AI narrator'; the canon voice block is rendered "
    "into the writer prompts beside it (test_elena_canon_6155)",
    "lambdas/emails/chronicle_podcast_lambda.py": "listener-facing episode descriptions that disclose 'a model' / 'a language model'",
    "scripts/v4_build_rss.py": "the RSS channel disclosure, pinned byte-for-byte to NARRATOR_WHO by test_narrator_byline_6178",
    "scripts/season_rebuild.py": "a rebuild prompt that states 'an AI narrator — a character written by a language model'",
}
_DISCLOSES = re.compile(r"\bAI\b|language model|a model\b|persona", re.IGNORECASE)


def _identity_strings(path: Path):
    """(lineno, text, canon_derived) for every non-docstring string literal or f-string stating who the narrator is."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    inner, docs = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.JoinedStr):
            inner.update(id(v) for v in n.values)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = n.body[0] if n.body else None
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant):
                docs.add(id(b.value))
    out = []
    for n in ast.walk(tree):
        if id(n) in inner or id(n) in docs:
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            text, derived = n.value, False
        elif isinstance(n, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
            derived = any(
                (isinstance(x, ast.Name) and x.id in _CANON_NAMES) or (isinstance(x, ast.Attribute) and x.attr in _CANON_NAMES)
                for v in n.values
                if isinstance(v, ast.FormattedValue)
                for x in ast.walk(v)
            )
        else:
            continue
        if _IDENTITY.search(text):
            out.append((n.lineno, text, derived))
    return out


def test_every_identity_string_renders_the_canon_or_is_a_reasoned_exception():
    offenders = []
    for p in _py_files("lambdas", "scripts"):
        rel = str(p.relative_to(_REPO))
        if rel == "lambdas/content/elena_canon.py" or rel in CENSUS_QUOTES:
            continue
        for lineno, text, derived in _identity_strings(p):
            if derived:
                continue
            low = text.lower()
            if rel in SPOKEN_PENDING and "journalist living inside" in low:
                continue  # owner decision pending
            if rel in RESTATED_OK and _DISCLOSES.search(text) and not any(h in low for h in HUMAN_CAREER):
                continue
            offenders.append(f"{rel}:{lineno}: {text[:90]!r}")
    assert not offenders, (
        "a string that says who Elena is must be built from content/elena_canon.py (identity_line/host_summary/NAME/SERIES), "
        f"not restated — a new phrasing cannot pass by being new: {offenders}"
    )


def test_the_identity_property_catches_a_new_phrasing(tmp_path):
    f = tmp_path / "m.py"
    f.write_text('P = "HOST is Elena Voss, a veteran reporter. Write her lines."\n', encoding="utf-8")
    ((_, _, derived),) = _identity_strings(f)
    assert derived is False
    g = tmp_path / "n.py"
    g.write_text(
        'from content import elena_canon\nP = f"HOST is Elena Voss, the {elena_canon.NAME} narrator. Write her lines."\n',
        encoding="utf-8",
    )
    assert [d for _, _, d in _identity_strings(g)] == [True]


def test_no_string_asserts_a_human_career():
    offenders = []
    for p in _py_files("lambdas", "scripts"):
        rel = str(p.relative_to(_REPO))
        if rel == "lambdas/content/elena_canon.py" or rel in CENSUS_QUOTES:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        low = "\n".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)).lower()
        for ph in HUMAN_CAREER:
            if ph in low and not (rel in SPOKEN_PENDING and ph == "the journalist living inside"):
                offenders.append(f"{rel}: {ph!r}")
    assert not offenders, offenders


def test_the_spoken_exceptions_still_exist_and_nothing_else_leans_on_them():
    for rel in SPOKEN_PENDING:
        assert any(
            "journalist living inside" in t.lower() for _, t, _ in _identity_strings(_REPO / rel)
        ), f"{rel} no longer carries its spoken line: drop the SPOKEN_PENDING entry"


def test_the_rewritten_prompts_render_from_the_canon():
    from content import elena_canon
    from emails import elena_state_updater, panelcast_qa

    assert (
        elena_canon.NAME in elena_state_updater.EXTRACTION_SYSTEM_PROMPT and "AI narrator" in elena_state_updater.EXTRACTION_SYSTEM_PROMPT
    )
    assert elena_canon.host_summary().removeprefix(elena_canon.NAME + ", ") in panelcast_qa._WEEKLY_RUBRIC
    assert elena_canon.host_summary().removeprefix(elena_canon.NAME + ", ") in panelcast_qa._INTRO_RUBRIC
