"""tests/test_cast_roster_consistency.py — #1904, the #1891 cast guard generalised.

#1891 shipped `/method/game/` naming a real, non-consenting clinician as platform
staff, because the pillar owners never got the pilot-era cast rename. Its guard
(scripts/v4_build_game_explained.assert_cast_current) fixed ONE field of ONE file.

#1904 is the same defect in a second place: `site/config/challenges_catalog.json`
carried 49 entries naming five people who are not on the live roster — rendered to
readers as "recommended by {name}" on the discovery cards. An enumerated guard
could not have caught it, because the enumeration was "pillar owners".

So this guard is written against the SET, not the instance: it discovers the
coach-naming fields by scanning reader-facing config, and validates every value
against the roster derived from the persona registry. A sixth surface added
tomorrow is covered without anyone remembering this file exists.

Two failure modes it must resist:

  * An EMPTY roster or an EMPTY field set would validate nothing while reporting
    green — the "gate that was never running" shape (#1908/#1920). Both are
    asserted non-empty first.
  * Off-roster names are not all retired personas. `Coach Maya Rodriguez` and
    `Dr. Kai Nakamura` ARE in config/personas.json (non-operational); `Dr. Lena
    Johansson`, `Sofia Herrera` and `Raj Mehta` are in no registry at all. So the
    check is "on the LIVE roster", never "absent from the retired list".
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
sys.path.insert(0, str(_REPO / "scripts"))

from coach import persona_registry  # noqa: E402

# Reader-facing config whose values are DISPLAY NAMES a visitor sees, and the
# field that carries them. Keyed by path so a new surface is one line — and
# `test_every_known_recommender_field_is_still_present` fails if a listed field
# disappears, so a rename cannot silently drop a surface out of the guard.
NAME_FIELDS = {
    "site/config/challenges_catalog.json": "board_recommender",
    # #2084: the same catalog is ALSO published bucket-root as the twin
    # `/api/challenges` reads. It is byte-identical to the `site/` copy above
    # (enforced by tests/test_config_site_mirror_parity.py), so this entry is
    # belt-and-braces — but it is the entry that would have caught the two
    # endpoints serving two different casts for three weeks, so it stays.
    "config/challenges_catalog.json": "board_recommender",
    "config/character_sheet.json": "owner",
}

# Non-person values legitimately allowed in an owner-ish field. IMPORTED from the
# #1891 guard rather than restated: my first cut hand-listed a plausible-looking
# set and it was wrong (it missed "Social Connection", the relationships pillar's
# real owner label), which would have made this guard red on correct config. Two
# copies of an allowlist is how the original drift happened.
from v4_build_game_explained import OWNER_ROLE_LABELS as ROLE_LABELS  # noqa: E402


def _roster() -> set:
    """Display names the public sees on /api/coaches: operational coaches + lead."""
    names = {p.get("name") for p in persona_registry.operational_personas().values()}
    lead = persona_registry.resolve(persona_registry.LEAD_PERSONA_ID)
    if lead:
        names.add(lead.get("name"))
    return {n for n in names if n}


def _values(path: str, field: str) -> list:
    """Every value of `field` anywhere in the JSON at `path`, with a locator."""
    doc = json.loads((_REPO / path).read_text())
    found = []

    def walk(node, where):
        if isinstance(node, dict):
            if isinstance(node.get(field), str) and node[field].strip():
                found.append((node[field], node.get("id") or node.get("name") or where))
            for k, v in node.items():
                walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")

    walk(doc, path)
    return found


# ── the guard cannot be a no-op ──────────────────────────────────────────────


def test_roster_is_not_empty():
    """An empty roster would pass every name — validating against nothing."""
    roster = _roster()
    assert len(roster) >= 8, f"roster resolved to {roster} — the guard would be inert"


def test_every_known_recommender_field_is_still_present():
    """A renamed field must fail loudly, not quietly drop a surface from the guard."""
    for path, field in NAME_FIELDS.items():
        assert (_REPO / path).is_file(), f"{path} is gone — update NAME_FIELDS"
        vals = _values(path, field)
        assert vals, f"{path} has no {field!r} values — the field was renamed, or the guard is now inert"


# ── the guard itself ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("path,field", sorted(NAME_FIELDS.items()))
def test_every_named_person_is_on_the_live_roster(path, field):
    roster = _roster()
    offenders = [(v, where) for v, where in _values(path, field) if v not in roster and v not in ROLE_LABELS]
    assert not offenders, (
        f"{path}: {len(offenders)} {field} value(s) name someone off the live roster "
        f"(#1904; #1891 was the same defect elsewhere):\n"
        + "\n".join(f"    {v!r} at {where}" for v, where in sorted(set(offenders))[:12])
        + f"\n  Live roster: {sorted(roster)}"
    )


def test_challenges_catalog_specifically_is_clean():
    """The #1904 instance, named so a regression reads as itself in CI output."""
    roster = _roster()
    bad = [v for v, _ in _values("site/config/challenges_catalog.json", "board_recommender") if v not in roster]
    assert not bad, f"off-roster recommender(s) back on the discovery cards: {sorted(set(bad))}"


def test_marcus_webb_prefix_is_normalised():
    """One entry read `Marcus Webb` where every other use carries the `Dr.` prefix."""
    vals = {v for v, _ in _values("site/config/challenges_catalog.json", "board_recommender")}
    assert "Marcus Webb" not in vals
    assert "Dr. Marcus Webb" in vals


# ── prove it fires ───────────────────────────────────────────────────────────


def test_guard_rejects_a_retired_pilot_persona():
    """Maya Rodriguez is still IN config/personas.json but off the public roster.

    A guard written as "not in the retired list" would pass her. This one checks
    membership of the LIVE roster, which is why it does not.
    """
    assert "Coach Maya Rodriguez" not in _roster()


def test_guard_rejects_a_name_in_no_registry_at_all():
    """Lena Johansson / Sofia Herrera / Raj Mehta appear in no registry.

    They were the bulk of #1904 (30 of the 49 entries), and they are the reason
    the check cannot be phrased against a known-retired set.
    """
    roster = _roster()
    for orphan in ("Dr. Lena Johansson", "Sofia Herrera", "Raj Mehta", "Dr. Kai Nakamura"):
        assert orphan not in roster


def test_guard_would_fail_on_an_injected_off_roster_name():
    """Negative control: the assertion logic actually rejects, it does not just pass."""
    roster = _roster()
    injected = [("Dr. Peter Attia", "challenge-x")]
    offenders = [(v, w) for v, w in injected if v not in roster and v not in ROLE_LABELS]
    assert offenders, "the guard's own predicate accepts a real non-consenting clinician"


# ── #2384: reader-bound PROMPT LITERALS ──────────────────────────────────────
#
# Config was only half the fork surface. `wednesday_chronicle_lambda.py`'s
# fallback prompt staged interviews with "Dr. Nakamura (neuroscience)" — a
# persona off the live roster — and `chronicle_email_sender_lambda.py` mapped a
# retired key to "Dr. Kai Nakamura", so a chronicle draft could interview a
# coach that does not exist. This section scans the SET of prompt-building
# modules (every .py under lambdas/emails/ + lambdas/intelligence/, discovered
# by glob, never hand-listed) for persona names off the live cast.
#
# What counts as forbidden is DERIVED, not enumerated:
#   * every registry persona whose display name is off the live cast
#     (operational + lead + the narrator/meta show personas the public site
#     bills: Elena Voss, Margaret Calloway, The Chair);
#   * the real-expert inspirations encoded in registry KEYS (andrew_huberman,
#     layne_norton, ...) — a real, non-consenting clinician's name must never
#     appear in a prompt literal (#1891's harm class);
#   * the known phantom corpus: names that shipped on surfaces but exist in NO
#     registry at all (#1904's bulk, plus this issue's finds).
# Each root also matches its bare/honorific surname forms ("Dr. Nakamura",
# "Rodriguez would say") when the surname is unambiguous vs the live cast.
#
# Docstrings are deliberately EXCLUDED: incident history lives there (e.g.
# integrator_prompts.py documents the Nakamura byline incident) and a docstring
# never reaches a reader. Comments are invisible to the AST already.

PROMPT_LITERAL_DIRS = ("lambdas/emails", "lambdas/intelligence")

# Names that shipped on a surface but exist in NO registry (so they cannot be
# derived). "On the LIVE roster", never "absent from the retired list" — same
# reasoning as the config guard above.
PHANTOM_NAMES = {
    "Dr. Elena Rodriguez": "hand-invented behaviourist (monday_compass fallback, #2384)",
    "Dr. Daniel Murthy": "phantom rename of vivek_murthy (chronicle sender map, #2384)",
    "Dr. Lena Johansson": "in no registry (#1904)",
    "Sofia Herrera": "in no registry (#1904)",
    "Raj Mehta": "in no registry (#1904)",
}

# Owner/partner-private senders may name non-operational registry personas —
# but only by explicit entry here, keyed by the ROOT name the pattern derives
# from. Reader-bound modules get no entry: a name off the live cast is a
# failure there, full stop.
PROMPT_LITERAL_ALLOWLIST = {
    # Partner email (private, to Matthew's partner — never a reader surface):
    # its Rodriguez/Murthy sections are registry board personas, kept by
    # explicit decision. Restructuring the sections onto the live roster is a
    # product call, not a guard call.
    "lambdas/emails/partner_email_lambda.py": {"Coach Maya Rodriguez", "Dr. Vivek Murthy"},
    # Owner-private digests (to Matthew only): their offline FALLBACK prompts
    # keep the Maya Rodriguez behavioural section that the live board config
    # also still stages for these features.
    "lambdas/emails/weekly_digest_lambda.py": {"Coach Maya Rodriguez"},
    "lambdas/emails/monthly_digest_lambda.py": {"Coach Maya Rodriguez"},
}


def _strip_honorific(name: str) -> str:
    for pre in ("Dr. ", "Coach "):
        if name.startswith(pre):
            return name[len(pre) :]
    return name


def _live_cast_names() -> set:
    """Live roster + the narrator/meta show personas the public site bills."""
    reg = persona_registry.personas()
    show = {p.get("name") for p in reg.values() if p.get("type") in ("narrator", "meta")}
    return _roster() | {n for n in show if n}


def _forbidden_roots() -> dict:
    """name -> why it may not appear in a reader-bound prompt literal."""
    reg = persona_registry.personas()
    live_cast = _live_cast_names()
    roots = dict(PHANTOM_NAMES)
    for key, p in reg.items():
        name = p.get("name") or ""
        if name and name not in live_cast:
            roots[name] = f"registry persona {key!r} is off the live cast"
        # The registry KEY encodes the real-expert inspiration where it differs
        # from the display name (andrew_huberman -> "Dr. Kai Nakamura").
        if key.endswith("_coach") or p.get("lead") or p.get("type") in ("narrator", "meta"):
            continue
        real = key.removesuffix("_interim").replace("_", " ").title()
        if " " in real and real.lower() != _strip_honorific(name).lower():
            roots[real] = f"registry key {key!r} names a real, non-consenting expert (#1891)"
    return roots


def _forbidden_patterns() -> dict:
    """compiled regex -> set of root names it detects."""
    live_surnames = {n.split()[-1] for n in _live_cast_names()}
    pats: dict = {}

    def add(pattern: str, root: str):
        pats.setdefault(pattern, set()).add(root)

    for root in _forbidden_roots():
        add(rf"\b{re.escape(root)}\b", root)
        surname = _strip_honorific(root).split()[-1]
        if surname not in live_surnames:
            # bare + honorific short forms: "Dr. Nakamura", "Rodriguez would say"
            add(rf"\b(?:Dr\.?\s+|Coach\s+)?{re.escape(surname)}\b", root)
    return {re.compile(p, re.IGNORECASE): roots for p, roots in pats.items()}


def _scanned_modules() -> list:
    return sorted(f for d in PROMPT_LITERAL_DIRS for f in (_REPO / d).rglob("*.py"))


def _string_literals(pyfile: Path):
    """(lineno, value) for every string literal in the file, docstrings excluded."""
    tree = ast.parse(pyfile.read_text(), filename=str(pyfile))
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                doc_ids.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids and len(node.value) >= 4:
            # identifier-shaped strings ("rodriguez", "maya_rodriguez") are code
            # keys — section ids, dict keys — never reader-bound display text.
            # A display name in a prompt always carries casing or surrounding
            # prose, which this shape cannot have.
            if re.fullmatch(r"[a-z0-9_.\-]+", node.value):
                continue
            yield node.lineno, node.value


def _prompt_literal_offenders(pyfile: Path, relkey: str, patterns=None) -> list:
    """(root_names, lineno, excerpt) for every forbidden-name hit not allowlisted."""
    patterns = patterns or _forbidden_patterns()
    allowed = PROMPT_LITERAL_ALLOWLIST.get(relkey, set())
    offenders = []
    for lineno, value in _string_literals(pyfile):
        for rx, roots in patterns.items():
            m = rx.search(value)
            if m and not (roots & allowed):
                start = max(0, m.start() - 30)
                offenders.append((tuple(sorted(roots)), lineno, m.group(0), value[start : m.end() + 30].replace("\n", " ")))
    return offenders


# ── the prompt-literal guard cannot be a no-op ───────────────────────────────


def test_prompt_literal_scan_set_is_not_empty():
    """Empty module set or empty forbidden set = the gate that never ran (#1908)."""
    modules = _scanned_modules()
    assert len(modules) >= 30, f"only {len(modules)} modules discovered — the scan set collapsed"
    names = {p.name for p in modules}
    # the incident files this guard exists for must be inside the derived set
    for known in ("wednesday_chronicle_lambda.py", "chronicle_email_sender_lambda.py", "monday_compass_lambda.py"):
        assert known in names, f"{known} left the scan set — the guard no longer covers its own incident"
    roots = _forbidden_roots()
    assert len(roots) >= 8, f"forbidden set collapsed to {sorted(roots)}"
    for expected in ("Dr. Kai Nakamura", "Coach Maya Rodriguez", "Andrew Huberman", "Dr. Elena Rodriguez"):
        assert expected in roots, f"{expected!r} missing from the derived forbidden set"


def test_prompt_allowlist_entries_are_real_and_in_use():
    """A stale allowlist entry is a hole waiting for a file rename to open it."""
    for relkey, roots in PROMPT_LITERAL_ALLOWLIST.items():
        path = _REPO / relkey
        assert path.is_file(), f"allowlist entry {relkey} is gone — remove or update it"
        patterns = {rx: rs for rx, rs in _forbidden_patterns().items() if rs & roots}
        hits = set()
        for _, value in _string_literals(path):
            for rx, rs in patterns.items():
                if rx.search(value):
                    hits |= rs & roots
        unused = roots - hits
        assert not unused, f"{relkey}: allowlisted name(s) no longer used — remove {sorted(unused)}"


# ── the prompt-literal guard itself ──────────────────────────────────────────


@pytest.mark.parametrize("pyfile", _scanned_modules(), ids=lambda p: str(p.relative_to(_REPO)))
def test_prompt_literals_name_only_the_live_cast(pyfile):
    relkey = str(pyfile.relative_to(_REPO))
    offenders = _prompt_literal_offenders(pyfile, relkey)
    assert not offenders, (
        f"{relkey}: {len(offenders)} prompt literal(s) name someone off the live cast "
        f"(#2384 — a chronicle draft could interview a coach that does not exist):\n"
        + "\n".join(f"    line {ln}: {hit!r} in ...{ctx!r}... (matches {roots})" for roots, ln, hit, ctx in offenders[:12])
    )


# ── prove the prompt-literal guard fires ─────────────────────────────────────


def test_prompt_guard_catches_a_planted_retired_name(tmp_path):
    """Mutation proof: a retired name planted in a scanned prompt literal is caught."""
    planted = tmp_path / "planted_lambda.py"
    planted.write_text(
        '"""Module docstring — Dr. Kai Nakamura here must NOT trip the guard."""\n'
        "PROMPT = (\n"
        '    "About twice a month you include a Board interview — "\n'
        '    "Dr. Nakamura is enthusiastic and tangential (neuroscience)."\n'
        ")\n"
    )
    offenders = _prompt_literal_offenders(planted, "lambdas/emails/planted_lambda.py")
    assert offenders, "a planted retired short-form name (Dr. Nakamura) was not caught"
    docstring_hits = [o for o in offenders if o[1] == 1]
    assert not docstring_hits, "the guard is reading docstrings — incident history would red the build"


def test_prompt_guard_catches_a_full_retired_name_and_a_real_expert():
    patterns = _forbidden_patterns()
    for planted in (
        "an interview with Dr. Kai Nakamura",
        "Coach Maya Rodriguez reads the picture",
        "as Andrew Huberman says",
        "Rodriguez would say",
    ):
        assert any(rx.search(planted) for rx in patterns), f"{planted!r} slipped through the derived patterns"


def test_prompt_guard_does_not_flag_the_live_cast():
    patterns = _forbidden_patterns()
    for fine in (
        "Dr. Marcus Webb is blunt and practical",
        "Dr. Reyes is precise",
        "Elena Voss, embedded journalist",
        "The Chair synthesises",
    ):
        hits = [rx.pattern for rx in patterns if rx.search(fine)]
        assert not hits, f"live-cast mention {fine!r} would red the guard via {hits}"


def test_prompt_guard_allowlist_is_per_file_not_global(tmp_path):
    """The partner-email allowance must not leak to reader-bound modules."""
    planted = tmp_path / "allowlist_scope.py"
    planted.write_text('PROMPT = "Coach Maya Rodriguez specialises in behaviour change"\n')
    assert not _prompt_literal_offenders(planted, "lambdas/emails/partner_email_lambda.py"), "the allowlist stopped covering its own file"
    assert _prompt_literal_offenders(
        planted, "lambdas/emails/wednesday_chronicle_lambda.py"
    ), "a private-sender allowance leaked into a reader-bound module — a retired name could return"
