"""tests/test_board_lead_single_character.py — #1986, one character runs the board.

Two characters used to occupy the board-lead role on the same door. The roster at
`/api/coaches` billed the registry's `lead: true` persona; the weekly call, the
month rollup, the experiment arc and the `/coaching/` noscript were all signed by
a *different* character, hardcoded as a string literal in five places and in the
three integrator prompts. #1112 introduced the roster lead and never reconciled
the byline, so a reader could not determine who ran the board.

This guard is written against the SET, not the instances — the same shape as
`tests/test_cast_roster_consistency.py` (#1904), for the same reason: an
enumerated list of "the five known hardcodes" would not have caught the sixth.

  * `config/personas.json` resolves EXACTLY ONE lead, and that is the only
    character permitted to hold the role anywhere.
  * Every constant byline in the site-api's dict literals is DISCOVERED by AST
    scan and must name a live-roster persona — a future hardcode of an off-roster
    name fails here without anyone remembering this file exists.
  * The three integrator prompts are BUILT and must open in the lead's voice.
  * The reader-facing static surfaces are DISCOVERED by their byline markers and
    must render the registry's lead.
  * Every fallback literal (the loader's, the site-api's, the front-end's) is
    pinned equal to the registry — a fallback that drifts is a second source of
    truth, which is the defect this issue is about.

Failure modes it must resist (#1908/#1920 — "the gate that was never running"):
every discovery step asserts a non-empty result before validating, and the
predicate has a negative control proving it actually rejects.
"""

import ast
import json
import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from coach import persona_registry  # noqa: E402

# Reader-visible bylines are served under these keys. Discovered by AST scan over
# the whole site-api package, so a NEW handler that hardcodes one is covered.
_BYLINE_NAME_KEYS = {"coach_name"}
_BYLINE_TITLE_KEYS = {"coach_title"}

# The static surfaces that carry a baked board-lead byline. Discovered by marker
# rather than enumerated by path (a sixth page added tomorrow is covered), and
# `site/legacy/**` is excluded on purpose — it is the verbatim pre-v4 rollback
# copy (ADR-071) and is deliberately never re-rendered.
_BYLINE_MARKERS = ("the week's call", "the month's read", "· the arc")


def _personas() -> dict:
    return persona_registry.load_registry(force_refresh=True).get("personas", {})


def _roster_names() -> set:
    """Display names a reader can legitimately see billed as platform staff."""
    names = {p.get("name") for p in persona_registry.operational_personas().values()}
    names.add(persona_registry.lead_name())
    return {n for n in names if n}


def _live_site_files() -> list:
    """Non-legacy site files that bake a board-lead byline."""
    out = []
    for path in sorted((_REPO / "site").rglob("*")):
        if not path.is_file() or path.suffix not in (".html", ".js"):
            continue
        if "legacy" in path.relative_to(_REPO / "site").parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        low = text.lower()
        if any(m in low for m in _BYLINE_MARKERS):
            out.append((path, text))
    return out


def _byline_entries() -> list:
    """(file, lineno, key, value_or_None) for every byline key in a site-api dict literal.

    ``value`` is the string when the byline is a hardcoded constant, and ``None``
    when it is derived at runtime (the fixed shape). Both are returned so the
    "did the scan go inert?" check counts byline SITES, not just the broken ones —
    otherwise fixing the last hardcode would silently disarm the guard.
    """
    found = []
    for path in sorted((_REPO / "lambdas" / "web").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                if key.value not in (_BYLINE_NAME_KEYS | _BYLINE_TITLE_KEYS):
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.strip():
                    found.append((path.name, value.lineno, key.value, value.value))
                else:
                    found.append((path.name, value.lineno, key.value, None))
    return found


# ── the registry resolves exactly one lead ───────────────────────────────────


def test_exactly_one_persona_claims_the_lead():
    leads = [k for k, v in _personas().items() if v.get("lead")]
    assert leads == [persona_registry.LEAD_PERSONA_ID], f"board lead is forked or missing: {leads}"


def test_lead_resolves_to_a_name_and_a_title():
    """An empty byline would make every check below vacuously true."""
    name, title = persona_registry.lead_byline()
    assert name and name.strip() and not name.startswith("eli_"), f"lead name unresolved: {name!r}"
    assert title and title.strip(), f"lead title unresolved: {title!r}"


def test_no_second_character_holds_the_integrator_role():
    """#1986's root cause: a duplicate seat carrying the lead's role.

    Derived, not enumerated — any persona or board member whose role title reads
    as the board-lead job must BE the lead, whatever it is called next time.
    """
    lead_name = persona_registry.lead_name()
    role_re = re.compile(r"integrative health director|principal investigator|program lead", re.I)

    offenders = [
        (pid, p.get("name"), p.get("board_role"))
        for pid, p in _personas().items()
        if role_re.search(str(p.get("board_role") or "")) and p.get("name") != lead_name
    ]
    board = json.loads((_REPO / "config" / "board_of_directors.json").read_text())["members"]
    offenders += [
        (mid, m.get("name"), m.get("title"))
        for mid, m in board.items()
        if (
            role_re.search(str(m.get("title") or ""))
            or any((f or {}).get("role") == "panel_chair" for f in (m.get("features") or {}).values())
        )
        and m.get("name") != lead_name
    ]
    assert not offenders, f"a second character holds the board-lead role (the #1986 defect): {offenders}"


def test_the_retired_integrator_seat_is_not_back():
    """The duplicate `integrator` seat is retired; the lead owns the role key."""
    board = json.loads((_REPO / "config" / "board_of_directors.json").read_text())["members"]
    assert "integrator" not in board, "the duplicate integrator board seat is back — the role belongs to the lead"
    lead = _personas()[persona_registry.LEAD_PERSONA_ID]
    assert "integrator" in (lead.get("lead_role_keys") or []), "the lead no longer claims the integrator role"


# ── every hardcoded byline names the lead ────────────────────────────────────


def test_the_byline_scan_is_not_inert():
    """A scan that finds nothing validates nothing."""
    entries = _byline_entries()
    assert len(entries) >= 4, f"only {len(entries)} byline site(s) found in lambdas/web — the AST scan went inert"


def test_every_constant_site_api_byline_is_on_the_live_roster():
    roster = _roster_names()
    titles = {p.get("board_role") for p in _personas().values() if p.get("board_role")}
    offenders = []
    for fname, lineno, key, value in _byline_entries():
        if value is None:  # derived at runtime — the shape this guard is protecting
            continue
        allowed = roster if key in _BYLINE_NAME_KEYS else titles
        if value not in allowed:
            offenders.append(f"{fname}:{lineno} {key}={value!r}")
    assert not offenders, "site-api serves byline(s) naming someone off the live roster (#1986):\n    " + "\n    ".join(offenders)


# ── the prompts speak in the lead's voice ────────────────────────────────────


@pytest.mark.parametrize("builder", ["build_synthesis_prompt", "build_month_rollup_prompt", "build_arc_prompt"])
def test_integrator_prompts_are_signed_by_the_registry_lead(builder):
    from intelligence import integrator_prompts

    args = {
        "build_synthesis_prompt": ("coach sections", "{}", "facts", "presence"),
        "build_month_rollup_prompt": ("weeks", "{}", "facts", 4, "2026-07"),
        "build_arc_prompt": ("weeks", "{}", "facts", 4),
    }[builder]
    prompt = getattr(integrator_prompts, builder)(*args)

    lead_name = persona_registry.lead_name()
    assert lead_name in prompt, f"{builder} does not open in the lead's voice ({lead_name!r})"

    # And no OTHER cast member's surname may claim the first-person voice.
    off_roster = {p["name"] for p in _personas().values() if p.get("name")} - _roster_names()
    intruders = sorted(n for n in off_roster if n in prompt)
    assert not intruders, f"{builder} still names an off-roster persona: {intruders}"


# ── the static reader surfaces render the lead ───────────────────────────────


def test_static_byline_surfaces_are_discovered():
    files = _live_site_files()
    assert files, f"no live site file carries a board-lead byline marker {_BYLINE_MARKERS} — the discovery went inert"


def test_static_byline_surfaces_never_name_an_off_roster_persona():
    off_roster = {p["name"] for p in _personas().values() if p.get("name")} - _roster_names()
    assert off_roster, "every persona is on the roster — the off-roster predicate would be inert"
    offenders = []
    for path, text in _live_site_files():
        for name in sorted(off_roster):
            if name in text:
                offenders.append(f"{path.relative_to(_REPO)} names {name!r}")
    assert not offenders, "a board-lead byline surface names someone off the live roster (#1986):\n    " + "\n    ".join(offenders)


def test_the_coaching_noscript_carries_the_lead():
    """The #1986 instance, named so a regression reads as itself in CI output."""
    lead_name = persona_registry.lead_name()
    for rel in ("site/coaching/index.html", "site/coaching/read/index.html"):
        text = (_REPO / rel).read_text(encoding="utf-8")
        assert "the week's call" in text.lower(), f"{rel}: the noscript byline block is gone — update the guard"
        assert lead_name in text, f"{rel}: the noscript week's call is not signed by the board lead ({lead_name!r})"


# ── no fallback becomes a second source of truth ─────────────────────────────


def test_every_fallback_literal_equals_the_registry_lead():
    """Three layers keep a pinned fallback for when the registry can't be read.

    Each is a *copy* of the lead's name, and a copy that drifts is exactly the
    two-characters-one-role defect this issue fixed. They are pinned here.
    """
    name, title = persona_registry.lead_byline()
    assert persona_registry.LEAD_FALLBACK_NAME == name
    assert persona_registry.LEAD_FALLBACK_TITLE == title

    for rel, needle in (
        ("lambdas/web/site_api_coach.py", "_LEAD_FALLBACK = "),
        ("lambdas/intelligence/integrator_prompts.py", 'name, title = "'),
        ("site/assets/js/coaching.js", "const LEAD_BYLINE_FALLBACK = "),
    ):
        text = (_REPO / rel).read_text(encoding="utf-8")
        line = next((ln for ln in text.splitlines() if needle in ln), None)
        assert line, f"{rel}: fallback literal {needle!r} not found — it was renamed; re-pin it here"
        assert name in line, f"{rel}: fallback byline has drifted from the registry lead ({name!r}): {line.strip()}"


# ── prove it fires ───────────────────────────────────────────────────────────


def test_the_predicate_rejects_the_original_defect():
    """Negative control: the exact string that shipped must not validate."""
    roster = _roster_names()
    assert "Dr. Kai Nakamura" not in roster, "the retired integrator byline is back on the roster"
    assert "Integrative Health Director" not in {p.get("board_role") for p in _personas().values()}
