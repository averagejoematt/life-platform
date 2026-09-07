#!/usr/bin/env python3
"""tests/test_platform_state_3691.py — the contract between the build readout's
generator, its artifact, and the page that renders it.

WHAT THIS PROTECTS
  `/method/state/` exists to be trusted at a glance by someone deciding what to work on
  next. That makes a WRONG number on it worse than no page at all — it would be believed.
  Three failure modes are specifically possible here, and each has an assertion below:

  1. **The page and the JSON drift.** A figure typed into the renderer instead of read
     from the artifact keeps rendering after the artifact moves on. The generator's whole
     premise is that it is the single join; a hard-coded number in the view is a second,
     silent one.
  2. **A section is added to one side only.** The generator grows a section the renderer
     never shows (invisible work), or the renderer reads a section the generator never
     emits (a permanently blank block). Asserted in BOTH directions, because each
     direction fails silently in its own way.
  3. **A degraded section is dressed as a value.** This is the #3681 shape: an
     unreachable source reported as something benign while the previous artifact ships
     on. The honesty contract — every section carries `as_of`/`source`/`error`, and a
     failure is `data: None` WITH a reason — is what makes the page safe, so it is
     asserted on the generator's own emitted shape rather than trusted from a docstring.

  Deliberately NOT asserted: the VALUES. They are live (a GitHub count, a clock, the
  budget governor's projection), so pinning them would red on the passage of time and be
  trained away within a week. The registry classifies this generator BUILDER for exactly
  that reason. What is pinned is the shape, the wiring, and the honesty.
"""

import ast
import json
import os
import re

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GEN = os.path.join(_REPO, "scripts", "build_platform_state.py")
_ARTIFACT = os.path.join(_REPO, "site", "data", "platform_state.json")
_RENDERER = os.path.join(_REPO, "site", "assets", "js", "evidence_meta.js")
_ROUTER = os.path.join(_REPO, "site", "assets", "js", "evidence.js")
_SYNC = os.path.join(_REPO, "deploy", "sync_site_to_s3.sh")

# The nine sections the generator promises. Held here as the third opinion: the
# generator declares them, the renderer consumes them, and this list is what makes a
# one-sided change fail instead of half-shipping.
SECTIONS = ("board", "delivery", "quality", "incidents", "cost", "autonomy", "grades", "bets", "jury_out")


def _read(p: str) -> str:
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _render_state_body(strip_comments: bool = False) -> str:
    """Just the renderState function — the rest of evidence_meta.js is other pages.

    `strip_comments` matters for the hard-coded-figure guard: this renderer is heavily
    commented, and a number quoted in EXPLANATORY PROSE ("N from reviews") is not a
    hard-coded figure. Scanning comments made the guard fire on its own documentation,
    which is the kind of false positive that gets a real guard deleted.
    """
    src = _read(_RENDERER)
    i = src.index("export function renderState")
    body = src[i:]
    if strip_comments:
        body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
        body = re.sub(r"(?m)^\s*//.*$", "", body)
        body = re.sub(r"(?<![:\w])//[^\n\"\'`]*$", "", body, flags=re.M)
    return body


@pytest.fixture(scope="module")
def artifact() -> dict:
    if not os.path.exists(_ARTIFACT):
        pytest.skip("platform_state.json not generated in this checkout")
    return json.loads(_read(_ARTIFACT))


# ── 1. The generator declares exactly the sections it emits ──────────────────
def test_the_generator_builds_exactly_the_promised_section_set():
    """AST-read the keys `build_state()` actually assembles, and require them to equal
    SECTIONS.

    The first version of this test asserted `declared is None or True`, which is true for
    every possible input — a check that cannot fail, in a file whose subject is checks
    that cannot fail. Replaced with the real thing: parse the dict literal returned by
    build_state() and compare its section keys to the contract.
    """
    tree = ast.parse(_read(_GEN))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_state")
    keys = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    missing = sorted(set(SECTIONS) - keys)
    assert not missing, f"build_state() never assembles section(s) {missing} that this contract promises"
    # And the reverse: a section built but absent from SECTIONS would be invisible to
    # every other assertion in this file.
    meta = {"generated_at", "schema", "about", "degraded_sections", "healthy"}
    extra = sorted(k for k in keys if k not in set(SECTIONS) | meta)
    assert not extra, f"build_state() assembles unregistered section(s) {extra} — add them to SECTIONS"


def test_the_artifact_carries_every_promised_section(artifact):
    missing = [s for s in SECTIONS if s not in artifact]
    assert not missing, f"generator dropped section(s): {missing}"


def test_the_artifact_carries_its_own_generation_stamp(artifact):
    """The dead-man. A page whose value is being current must say when it was made, so a
    reader can see staleness rather than infer it from the numbers looking familiar."""
    assert artifact.get("generated_at"), "platform_state.json must carry generated_at"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", artifact["generated_at"])
    assert "degraded_sections" in artifact, "the artifact must declare which sections failed"
    assert "healthy" in artifact


# ── 2. The honesty contract, asserted on the emitted shape ───────────────────
@pytest.mark.parametrize("name", SECTIONS)
def test_every_section_carries_its_own_provenance(artifact, name):
    """`as_of` + `source` per section, not one stamp for the whole file. The sections are
    computed from different places at different moments; one global stamp would claim a
    freshness the slowest member does not have (the #3252 lesson, applied here)."""
    sec = artifact[name]
    assert isinstance(sec, dict), f"{name} must be an object carrying its own provenance"
    assert sec.get("as_of"), f"{name} must carry as_of"
    assert sec.get("source"), f"{name} must name its source"
    assert "error" in sec, f"{name} must carry an explicit error field (None when healthy)"


def test_a_failed_section_is_an_absence_with_a_reason_not_a_stale_value():
    """The #3681 shape, asserted on the code path rather than hoped for.

    `_failed()` must set data to None AND state the reason. A version that returned the
    last-known payload would be the theme-river defect: an AccessDenied rendered as
    'skipped (offline?)' while yesterday's artifact ships on, for the life of the build.
    """
    src = _read(_GEN)
    i = src.index("def _failed(")
    body = src[i : i + 700]
    assert '"data": None' in body, "_failed() must null the payload — never retain a previous value"
    assert "error" in body and "{type(exc).__name__}" in body, "_failed() must state the reason"


def test_truncation_is_derived_from_the_true_population_not_from_our_own_cap():
    """The bug this generator shipped in its own first draft: it capped GitHub paging at
    400, reported `closed: 400, prs: 400` — both exactly the cap — and computed a median
    over an arbitrary subset. 'We fetched N' and 'there are N' were indistinguishable.

    The cure is that the true count is asked for directly, so a sample can be LABELLED a
    sample. If `_gh_total_count` ever disappears, that ambiguity is back."""
    src = _read(_GEN)
    assert "_gh_total_count" in src, "the true population must be queried, not inferred from the page size"
    assert "total_count" in src, "the search API's own count is the authority on population size"
    assert '"sampled"' in src or "sampled=" in src, "a truncated read must be labelled as sampled"


# ── 3. Page ↔ artifact, both directions ──────────────────────────────────────
def test_the_renderer_hard_codes_no_figure_that_lives_in_the_artifact(artifact):
    """The drift guard. Any number the artifact owns must be READ, never typed."""
    body = _render_state_body(strip_comments=True)
    owned = []
    for key in ("total_open", "actionable", "from_review_total", "reader_facing"):
        v = (artifact.get("board") or {}).get(key)
        if isinstance(v, int):
            owned.append(v)
    for key in ("gates_total", "gates_proven_can_fail", "gates_unproven", "test_functions"):
        v = (artifact.get("quality") or {}).get(key)
        if isinstance(v, int):
            owned.append(v)
    hard = [n for n in owned if re.search(r"(?<![\w.])" + str(n) + r"(?![\w.])", body)]
    assert not hard, f"renderState hard-codes artifact-owned figure(s) {hard} — read them from the data"


@pytest.mark.parametrize("name", SECTIONS)
def test_the_renderer_consumes_every_section_the_generator_emits(name):
    """Direction A: a section added to the generator and not to the page is invisible
    work — computed on every deploy, shown to nobody."""
    body = _render_state_body()
    assert re.search(r"\b" + re.escape(name) + r"\b", body), f"renderState never reads section {name!r} — it is computed and never shown"


def test_the_renderer_reads_no_section_the_generator_does_not_emit(artifact):
    """Direction B: a section the page reads and the generator never writes renders as a
    permanently blank block that looks like 'no data' rather than 'no such thing'."""
    body = _render_state_body()
    # Section names are read off `d.<name>` in the renderer.
    read = set(re.findall(r"\bd\.([a-z_]+)\b", body))
    known = set(SECTIONS) | {"generated_at", "degraded_sections", "healthy", "board", "about", "schema"}
    unknown = sorted(x for x in read if x not in known)
    assert not unknown, f"renderState reads section(s) the generator never emits: {unknown}"


def test_the_router_wires_the_slug():
    """A renderer nothing dispatches to is dead code that reads as a working page."""
    router = _read(_ROUTER)
    assert "state: renderState" in router, "evidence.js must map the `state` slug to renderState"
    assert "renderState" in router.split('from "/assets/js/evidence_meta.js"')[0], "renderState must be imported"


# ── 4. The deploy wiring, and the swallow it must NOT have ───────────────────
def test_the_generator_runs_on_every_site_deploy():
    sync = _read(_SYNC)
    assert "build_platform_state.py" in sync, "the generator must run in deploy/sync_site_to_s3.sh"


def test_the_deploy_step_does_not_swallow_a_generator_failure():
    """Its neighbours all use `|| echo \"… skipped (offline?)\"`. That idiom IS #3681 —
    an IAM denial degraded into a benign message while the previous artifact ships on.

    This generator already degrades per-section internally, so a non-zero exit means the
    generator itself broke, and shipping yesterday's board silently is precisely the
    outcome the page exists to prevent. The step must therefore stay unguarded."""
    sync = _read(_SYNC)
    line = next(ln for ln in sync.splitlines() if "build_platform_state.py" in ln and not ln.strip().startswith("#"))
    assert "|| echo" not in line, (
        "the build-readout step must NOT swallow its own failure into a message — "
        "that is the #3681 defect, and this page's whole value is that its numbers are current"
    )


def test_every_section_renders_a_GAP_when_it_could_not_be_computed():
    """The footer claims degraded sections "are shown as gaps above". Three sections
    originally had no error branch at all — `bets`, `jury_out` and `autonomy` simply
    vanished from the page on failure, which reads as "nothing to report" rather than
    "we could not measure this", and made that footer sentence untrue.

    Found by actually running the negative control (a `gh` that exits 1) rather than by
    reading the code: four sections went null, and only one of them rendered a gap.

    Nine sections, nine `stErr(...)` call sites. A section added without one regresses
    the page's central honesty claim.
    """
    body = _render_state_body()
    sites = re.findall(r'stErr\(\s*\w+\s*,\s*"([^"]+)"', body)
    assert len(sites) == len(SECTIONS), (
        f"expected one gap branch per section ({len(SECTIONS)}), found {len(sites)}: {sites}. "
        "A section with no error branch disappears silently when its source is unreachable."
    )
