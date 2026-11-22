"""tests/test_elena_canon_6155.py — one Elena, no personal details or real people in prompts, a legacy door with the
desk's checks, and a story bible that points at the record (#6155).

What is pinned, and why each one is here:

  1. ONE canon. ``content.elena_canon`` carries every field the issue names (identity + disclosure, evidence,
     uncertainty, range, what she never does, length, voice anchors, a version). Every writer path renders her from it:
     the desk's chronicle writer, the desk's Panel script, the legacy writer and its fallback (one rendering now), the
     Panel's two-pass legacy script, Episode 0 and the recap. The contradictions the four old definitions carried
     ("don't break the fourth wall", an invented career, four length ranges, full journal access) cannot return.
  2. NO PERSONAL DETAIL in a prompt. Every string literal under lambdas/ and mcp/ is swept for a literal age and the
     job-title class; the narrator prompts are swept for relationship details. The detectors are proven against planted
     text, so the sweep is never a no-op.
  3. NO REAL PERSON as an interviewee. The legacy writer's team is the coach registry's operational roster
     (``interviewees ⊆ roster``, structural — no name is spelled here), and every rendered narrator prompt is clean
     under ``privacy_guard``'s real-name list (which already lives in the repo).
  4. THE LEGACY DOOR. A legacy-written draft runs the desk's quote, callback and title checks and is always held for
     the owner with the reasons named; the approve path's audit then refuses it.
  5. THE STORY BIBLE points only at objects that exist and states no ruled-out detail.

# premerge-gate: sweeps every .py under lambdas/ and mcp/ for personal-detail string literals, and reads docs/content/STORY_BIBLE.md
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
# the chronicle facade reads these at import time (the same setdefaults its own behaviour tests use)
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

from content import autopublish_audit, elena_canon, story_craft, story_pipeline, story_writers  # noqa: E402
from privacy import privacy_guard  # noqa: E402

_VICE = "neutral-fixture-terms"  # the legacy prompt's off-repo vocabulary slot, filled with a neutral token


def _real_names(text: str):
    """privacy_guard's real-name list (in the repo already; no name is spelled in this file). The vice half of
    find_violations needs the off-repo vocabulary, which this test does not need or load."""
    low = text.lower()
    hits = [n for n in privacy_guard.BANNED_FULL_NAMES if n in low]
    return hits + [n for n in privacy_guard.BANNED_SURNAMES if re.search(rf"\b{re.escape(n)}\b", text, re.I)]


# ── 1. one canon ─────────────────────────────────────────────────────────────


def test_the_canon_carries_every_field_and_a_version():
    c = elena_canon
    assert re.fullmatch(r"\d+\.\d+\.\d+", c.ELENA_CANON_VERSION)
    for field in ("IDENTITY", "DISCLOSURE", "TEMPERAMENT", "EVIDENCE", "UNCERTAINTY", "RANGE", "NEVER", "VOICE_ANCHORS"):
        assert getattr(c, field), f"the canon's {field} is empty"
    assert {name for name, _ in c.RANGE} >= {"factual report", "reflective observation", "narrative tension"}
    assert "AI editorial persona" in c.DISCLOSURE and "no career" in c.DISCLOSURE


def test_one_length_range_and_it_sits_inside_the_craft_gate():
    lo, hi = elena_canon.CHRONICLE_BODY_WORDS
    glo, ghi = story_craft.CHRONICLE_WORDS
    assert glo <= lo < hi <= ghi, "the writer's range must sit inside the craft gate's tolerance"


def _legacy():
    from emails import chronicle_prompt

    return chronicle_prompt.legacy_prompt(vice_terms=_VICE)


def _narrator_prompts():
    """Every system prompt that speaks as, or describes, Elena — rendered, not read from source."""
    from emails import chronicle_recap, panelcast_scripts

    return {
        "canon.voice_block": elena_canon.voice_block(),
        "canon.host_block": elena_canon.host_block(),
        "story_writers.ELENA_VOICE": story_writers.ELENA_VOICE,
        "story_writers.EPISODE_VOICE": story_writers.EPISODE_VOICE,
        "story_writers.SEASON_BRIEF": story_writers.SEASON_BRIEF,
        "chronicle_prompt.legacy_prompt": _legacy(),
        "chronicle_recap._RECAP_SYSTEM_PROMPT": chronicle_recap._RECAP_SYSTEM_PROMPT,
        "panelcast_scripts._elena_host_summary": panelcast_scripts._elena_host_summary(),
    }


def test_every_writer_path_renders_elena_from_the_canon():
    from emails import chronicle_recap, panelcast_scripts

    voice = elena_canon.voice_block()
    assert voice in story_writers.ELENA_VOICE, "the desk writer no longer renders the canon"
    assert elena_canon.host_block() in story_writers.EPISODE_VOICE, "the desk's Panel script no longer renders the canon"
    assert voice in _legacy(), "the legacy writer no longer renders the canon"
    assert chronicle_recap._RECAP_SYSTEM_PROMPT.startswith(elena_canon.identity_line())
    assert panelcast_scripts._elena_host_summary() == elena_canon.host_summary()
    # the Panel's two-pass legacy script: its Elena pass opens on the canon's host block (read from the call site)
    src = (_REPO / "lambdas" / "emails" / "podcast_script_v2.py").read_text(encoding="utf-8")
    assert "_canon.host_block()" in src and "embedded journalist and host" not in src


def test_the_legacy_fallback_is_the_same_rendering(monkeypatch):
    from emails import chronicle_prompt, wednesday_chronicle_lambda as m

    monkeypatch.setattr(chronicle_prompt, "_vice_terms_clause", lambda: _VICE)
    assert m._fallback_elena_prompt() == m._build_elena_prompt_from_config() == _legacy()


def test_the_old_contradictions_cannot_return():
    banned = {
        "fourth wall": r"fourth wall",
        "an invented career": r"freelance journalist|spent years watching",
        "an old length range": r"1,?200\s*-\s*1,?800|1,?100\s*-\s*1,?500",
        "journal access": r"full access to Matthew's journal|weather may inform you",
    }
    hits = [f"{name}: {what}" for name, text in _narrator_prompts().items() for what, rx in banned.items() if re.search(rx, text, re.I)]
    assert hits == [], "a resolved contradiction is back:\n" + "\n".join(hits)


def test_rendered_prompts_name_no_snake_case_keys_beyond_the_desks():
    # the canon rides inside the desk's prompt contract (tests/test_story_dossier_4532.py); keep it key-free
    assert not re.search(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", elena_canon.voice_block() + elena_canon.host_block())


def test_voice_anchors_are_short_published_lines_that_pass_the_reader_door():
    from content import story_checks

    for a in elena_canon.VOICE_ANCHORS:
        assert a["source"].startswith("/story/") and a["source"].endswith("/"), a
        assert 4 <= len(a["text"].split()) <= 30, a
        assert not _real_names(a["text"]), a
        assert not story_checks.reader_surface(a["text"]), a


# ── 2. no personal detail in a prompt ────────────────────────────────────────

# A literal age about a person ("a 37-year-old", "Matthew Walker, 36,"); the job-title class.
_AGE = re.compile(r"\b\d{2}[- ]years?[- ]old\b|\bMatthew(?: Walker)?,\s*\d{2}\b", re.I)
_JOB = re.compile(r"\bSenior Director\b|\b(?:Director|Manager|VP|Vice President|Head of \w+)\s+at\b|\bat a SaaS company\b|\bSaaS\b")
_RELATIONSHIP = re.compile(
    r"\b(?:his|her|matthew's)\s+(?:girlfriend|boyfriend|wife|husband|fianc[eé]e?|spouse|partner)\b|\blives with\b|\bmarried\b", re.I
)
# Generic, not about a person: the strength helpers' "a 50-year-old needs …" style norms. None in string literals today.
_AGE_ALLOW: tuple = ()


def _detail_findings(text: str, *, relationship: bool = False):
    out = [f"age {m.group(0)!r}" for m in _AGE.finditer(text) if m.group(0) not in _AGE_ALLOW]
    out += [f"job title {m.group(0)!r}" for m in _JOB.finditer(text)]
    if relationship:
        out += [f"relationship {m.group(0)!r}" for m in _RELATIONSHIP.finditer(text)]
    return out


def test_the_detectors_catch_what_they_exist_for():
    """The sweep below is only worth something if these fire on the shapes that shipped (mutation control)."""
    planted = "You've been embedded with Matthew — a 37-year-old Senior Director at a SaaS company who lives with his girlfriend"
    found = _detail_findings(planted, relationship=True)
    assert any(f.startswith("age") for f in found) and any(f.startswith("job") for f in found)
    assert any(f.startswith("relationship") for f in found)
    assert _detail_findings("Matthew Walker, 36, Seattle.")
    assert not _detail_findings("no job details, no third parties, no family members, no partner", relationship=True)


def _string_literals(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    return [(n.lineno, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_no_prompt_or_template_string_states_an_age_or_a_job_title():
    roots = [_REPO / "lambdas", _REPO / "mcp"]
    files = [p for r in roots for p in r.rglob("*.py") if "__pycache__" not in p.parts]
    assert len(files) > 300, f"only {len(files)} modules swept — the sweep collapsed"
    hits = [f"{p.relative_to(_REPO)}:{ln}: {f}" for p in files for ln, s in _string_literals(p) for f in _detail_findings(s)]
    assert hits == [], "a prompt/template states a personal detail the owner has ruled out:\n" + "\n".join(hits)


def test_no_narrator_prompt_states_a_relationship_detail_or_names_a_real_person():
    bad = []
    for name, text in _narrator_prompts().items():
        bad += [f"{name}: {f}" for f in _detail_findings(text, relationship=True)]
        bad += [f"{name}: real person {t!r}" for t in _real_names(text)]
    assert bad == [], "\n".join(bad)


# ── 3. no real person (or off-roster coach) as an interviewee ────────────────


def test_legacy_interviewees_are_the_operational_roster_and_nothing_else():
    from coach import persona_registry
    from emails import chronicle_prompt

    team = chronicle_prompt.operational_team()
    people = persona_registry.personas()
    roster = {persona_registry.plain_name(people[c]["name"]) for c in persona_registry.OPERATIONAL_COACH_IDS}
    assert team and {name for name, _ in team} <= roster
    # the board config's interviewee path is not read by the legacy prompt any more
    src = (_REPO / "lambdas" / "emails" / "chronicle_prompt.py").read_text(encoding="utf-8")
    assert "board_loader" not in src, "the legacy prompt reads Elena and the team from the canon and the registry, not the board"
    # and every name the board config ever offered as an interviewee that is off the roster stays out of the prompt
    board = json.loads((_REPO / "config" / "board_of_directors.json").read_text(encoding="utf-8"))
    offered = {m["name"] for m in board["members"].values() if (m.get("features") or {}).get("chronicle", {}).get("role") == "interviewee"}
    legacy = _legacy()
    leaked = sorted(n for n in offered - roster if re.search(rf"\b{re.escape(n)}\b", legacy))
    assert leaked == [], f"an off-roster interviewee reached the legacy prompt: {leaked}"


# ── 4. the legacy door ───────────────────────────────────────────────────────


class _Gates:
    corpus = story_craft._norm("Protein is the lever this week and the floor is the floor")
    previous = {4: "Week 4 said recovery came in at 62 percent."}


def test_legacy_findings_run_the_desks_quote_callback_and_title_checks():
    md = (
        '"Fast Enough"\n\n[Weight: 300 lbs | Week Grade: avg 60 | T0 Streak: 3 days]\n\n'
        '"He said the numbers never lie and the plan is perfect, every single day," a coach told me.\n\n'
        "In Week 4 recovery sat at 71 percent.\n\n---\n*Week 5 of The Measured Life*"
    )
    found = story_pipeline.legacy_findings(_Gates(), md, {"titles": [{"week": 4, "title": "Fast Enough"}]})
    assert any(f.startswith("quote:") for f in found), found
    assert any(f.startswith("callback:") and "71" in f for f in found), found
    assert any(f.startswith("ledger:") for f in found), found
    assert not any("300" in f for f in found), "the legacy machine header is not prose and is not checked as a quote/callback"


def test_legacy_audit_is_never_empty_and_names_why_it_holds():
    class Broken:
        def query(self, **k):
            raise RuntimeError("ddb down")

    out = story_pipeline.legacy_audit(Broken(), "2026-11-17", '"T"\n\nbody')
    assert out[0] == story_pipeline.LEGACY_NOTE and len(out) == 2
    out = story_pipeline.legacy_audit(Broken(), "2026-11-18", '"T"\n\nbody')  # a Wednesday: never a season week end
    assert out[0] == story_pipeline.LEGACY_NOTE and len(out) == 2


def test_a_held_legacy_row_is_refused_by_the_publish_audit():
    findings = [story_pipeline.LEGACY_NOTE]
    row = {
        "content_markdown": "A clean paragraph.",
        "date": "2026-11-17",
        "desk_findings_json": json.dumps({"post": findings, "episode": []}),
        "desk_craft_json": "[]",
        "publish_hold": story_pipeline.LEGACY_HOLD,
    }
    blocking = autopublish_audit.blocking_items(row)
    assert any(story_pipeline.LEGACY_NOTE in b for b in blocking)
    assert not all(b.startswith("craft hold") for b in blocking), "an approval click alone would publish it"
    assert autopublish_audit.legacy_episode_blocking(row, "a line", "2026-11-17"), "the Panel's legacy writer must hold too"


def test_attaching_the_legacy_audit_never_writes_a_passing_record():
    from emails import chronicle_store

    writes = []

    class T:
        def update_item(self, **k):
            writes.append(k)

    chronicle_store.attach_legacy_audit("2026-11-17", [], _g={"table": T(), "USER_ID": "matthew", "logger": None})
    post = json.loads(writes[0]["ExpressionAttributeValues"][":f"])["post"]
    assert post and post[0] == story_pipeline.LEGACY_NOTE
    assert writes[0]["ExpressionAttributeValues"][":h"] == story_pipeline.LEGACY_HOLD


# ── 5. the story bible ───────────────────────────────────────────────────────


def test_the_story_bible_points_only_at_objects_that_exist_and_states_no_ruled_out_detail():
    text = (_REPO / "docs" / "content" / "STORY_BIBLE.md").read_text(encoding="utf-8")
    assert "investigative, never prewritten arcs" in text
    missing = []
    for ref in sorted(set(re.findall(r"`([^`\s]+/[^`\s]+)`", text))):
        path, _, attr = ref.partition("::")
        p = _REPO / path.replace("{coach_id}", "sleep_coach")
        if not p.exists():
            missing.append(ref)
        elif attr and not re.search(rf"^def {re.escape(attr)}\b", p.read_text(encoding="utf-8"), re.M):
            missing.append(ref)
    assert missing == [], f"the story bible points at objects that do not exist: {missing}"
    assert not _detail_findings(text, relationship=True)
    for name in ("season_spine", "elena_canon", "own_words.js", "moments.js", "corrections.js", "ELENA_PREQUEL_BRIEF.md"):
        assert name in text, f"the bible no longer points at {name}"


def test_the_bible_lists_the_seven_open_threads():
    text = (_REPO / "docs" / "content" / "STORY_BIBLE.md").read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith("| ") and not ln.startswith("| Thread") and "---" not in ln]
    assert len(rows) == 7 and all(ln.count("|") == 4 for ln in rows), rows
