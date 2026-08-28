"""tests/test_doc_facts_budget_2899.py — the ceiling half of the doc-facts gate.

#2899. `scripts/check_doc_facts.py` reported "✅ no live doc/source states a stale
count/budget" across 122 docs + 416 source files while three docs still stated the
retired $85 as current truth. The issue guessed the cause was markdown formatting
(bold / table cells / blockquotes). It was not — bold matched fine. Reproducing each
site against the real matcher found THREE DIFFERENT mechanisms:

  1. docs/ARCHITECTURE.md:89  — the regex DID find $85. The line also said "raised
     from $75", and the exemption was per-LINE, so the historical framing of one
     figure exempted the stale CURRENT figure beside it.
  2. docs/INFRASTRUCTURE.md:16 — the regex found NOTHING. "$85/month all-in" carries
     no budget/ceiling/cap/guardrail word within the 20-char window, so the pattern
     never fired at all.
  3. docs/COST_TRACKER.md:7   — the regex WOULD have flagged it. The file is on the
     gate's own EXEMPT_FILES skip list — so the one doc the gate names as the
     canonical spend ledger was the one doc whose ceiling nothing checked.

Each mechanism gets its own fixture below, because a fix for one is not a fix for
the others. The charter's gate rule is the bar: a gate that cannot fail is a green
light wired to nothing, so every fixture is a PLANTED defect asserted to flag.
"""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("_cdf", ROOT / "scripts" / "check_doc_facts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def facts():
    return _load()


# ── Mechanism 1: the per-LINE exemption swallowed a current claim ─────────────

ARCHITECTURE_89 = "**$85/mo all-in cap** (ADR-063, raised from $75 + surge-to-$100 rule per ADR-133)"


def test_historical_framing_does_not_exempt_a_current_claim_on_the_same_line(facts):
    """The measured ARCHITECTURE.md:89 miss. "raised from $75" is legitimate history;
    the "$85 ... cap" beside it is a stale CURRENT claim and must still flag."""
    offenders = facts._budget_offenders(ARCHITECTURE_89)
    assert 85 in offenders, f"the stale current $85 must flag, got {offenders}"


def test_the_historical_figure_on_that_same_line_is_still_exempt(facts):
    """Precision half: fixing mechanism 1 must not start flagging real history.
    $75 is framed by "raised from" and leads a "-> " transition; it must stay silent."""
    assert 75 not in facts._budget_offenders(ARCHITECTURE_89)


@pytest.mark.parametrize(
    "line",
    [
        "the ceiling was $85 all-in",
        "budget ceiling $85 -> $150",
        "budget ceiling $85 → $150",
        "raised the cap from $85",
        "the $75 reference ceiling",  # _THRESHOLD_REFERENCE_CEILING, a live constant
        "budget ceiling $85 <!-- drift-ok: quoting the pre-ADR-133 ladder -->",
    ],
)
def test_genuine_history_is_not_flagged(facts, line):
    """Guard the SET of exemption shapes, not one instance — prefix framing, both
    arrow glyphs, the reference-ceiling postfix, and the documented drift-ok hatch."""
    assert facts._budget_offenders(line) == [], line


# ── Mechanism 2: no trigger word near the figure, so nothing matched ──────────

INFRASTRUCTURE_16 = "$85/month all-in, **enforced** (… floats to $100 on reader-traffic surge)"


def test_all_in_phrasing_is_matched_at_all(facts):
    """The measured INFRASTRUCTURE.md:16 miss: the old vocabulary
    (budget|ceiling|cap|guardrail) found ZERO matches on this line."""
    assert 85 in facts._budget_offenders(INFRASTRUCTURE_16)


def test_per_user_projection_is_not_mistaken_for_a_ceiling(facts):
    """Precision: widening the vocabulary must not swallow the shape the 20-char
    window exists to protect — a per-user cost projection that merely says /month."""
    assert facts._budget_offenders("projected spend of $405/month per active reader") == []


# ── Mechanism 3: the canonical ledger was on the gate's own skip list ─────────

COST_TRACKER_7 = "> Budget ceiling: **$85/month all-in** base, floating to **$100 in surge mode**"


def test_cost_tracker_ceiling_is_scanned_despite_the_file_being_exempt(facts, tmp_path):
    """docs/COST_TRACKER.md stays in EXEMPT_FILES (a ledger may state history), but
    its CEILING claim is now scanned explicitly. Without this the canonical spend doc
    is the only one a reader is pointed to and the only one unchecked."""
    doc = tmp_path / "COST_TRACKER.md"
    doc.write_text(f"**Verified:** {dt.date.today().isoformat()}\n\n{COST_TRACKER_7}\n", encoding="utf-8")
    hits = facts._cost_tracker_hits(doc, today=dt.date.today())
    assert any("$85" in h for h in hits), f"the exempt ledger's ceiling claim must flag, got {hits}"


def test_cost_tracker_is_still_exempt_from_the_general_doc_scan(facts):
    """The re-inclusion is targeted. Removing the file from EXEMPT_FILES wholesale
    would flag its historical monthly-actuals rows, which are legitimate history."""
    assert "docs/COST_TRACKER.md" in facts.EXEMPT_FILES


# ── Markdown shapes: asserted, since the issue named them as the suspect ──────


@pytest.mark.parametrize(
    "shape,line",
    [
        ("bold", "The budget ceiling is **$85** all-in"),
        ("table-cell", "| Budget | $85/month all-in, **enforced** | alerts at 50/70/85/100% |"),
        ("blockquote", "> Budget ceiling: **$85/month all-in** base"),
        ("plain", "the $85 budget ceiling"),
    ],
)
def test_planted_defect_flags_in_every_markdown_shape(facts, shape, line):
    """Mutation evidence across formatting. These all pass on the OLD code too —
    formatting was never the defect — but they are pinned so a future precision
    tightening cannot quietly lose them."""
    assert 85 in facts._budget_offenders(line), f"{shape}: {line}"


# ── The second gap: only the BASE was ever checked ────────────────────────────


def test_allowed_set_is_derived_from_the_governor_not_hand_typed(facts):
    """Charter rule 1. The permanent base/surge pair must come from
    cost_governor_lambda.py, so moving the ceiling cannot leave this gate behind."""
    allowed, provenance = facts._governor_ceilings(today=dt.date(2026, 9, 15))
    assert {215, 252} <= allowed, f"base/surge must be parsed from the governor, got {allowed}"
    assert "base/surge" in provenance


def test_dated_window_value_is_allowed_only_while_the_window_is_in_effect(facts):
    """The $115-for-twelve-days defect. BUDGET_OK held only the permanent base, so
    nothing had an opinion about the figure actually in force. The window pair is now
    allowed inside its dates and flagged outside them — an auto-revert matching the
    governor's own, with no deploy and nobody having to remember."""
    inside, _ = facts._governor_ceilings(today=dt.date(2026, 8, 15))
    outside, _ = facts._governor_ceilings(today=dt.date(2026, 9, 1))  # window end is exclusive

    assert {200, 235} <= inside, f"August's raised window must be allowed inside it, got {inside}"
    assert 200 not in outside and 235 not in outside, f"September must reject August's window, got {outside}"

    line = "the budget ceiling is $200 all-in"
    assert facts._budget_offenders(line, allowed=inside) == []
    assert 200 in facts._budget_offenders(line, allowed=outside)


# ── Non-vacuity + the live integration assertion ──────────────────────────────


def test_the_scan_surface_is_non_empty(facts):
    """A floored surface, in the style of test_pacific_today_guard_2414.py: every
    assertion above is worthless if the real gate walks zero files."""
    assert len(facts._scan_files()) >= 50
    assert len(facts._scan_source_files()) >= 50


def test_live_repo_states_no_stale_ceiling(facts):
    """The integration half: the real corpus must be clean under the widened gate."""
    hits = [h for h in facts._cost_tracker_hits(ROOT / "docs" / "COST_TRACKER.md") if "budget ceiling claims" in h]
    for doc in facts._scan_files():
        for line in doc.read_text(encoding="utf-8").splitlines():
            hits += [f"{doc.relative_to(ROOT)}: ${a}" for a in facts._budget_offenders(line)]
    assert hits == [], "live docs state a stale ceiling:\n" + "\n".join(hits)


# ── #3042 D0.5: the published-site surface (.js/.html + v4 generators) ────────
# The 2026-08-23 diligence fact-check found "$85 hard ceiling" shipping live in
# evidence_meta.js, in every /method/ shell's embedded registry blurb, and in two
# editorial strings inside scripts/v4_build_evidence.py — none of it scanned by any
# gate (register finding 4: check_doc_facts scanned .md and lambdas/*.py only).
# The site's most-quoted number must not ship un-guarded again.


def test_site_surface_includes_the_files_that_actually_shipped_stale(facts):
    """Guard the SET: the surface must contain the exact classes the miss lived in —
    the hand-maintained assets JS, a generated method shell, and the generator whose
    string literals are the editorial's source (fix-the-HTML-only is the
    drift-on-next-build trap). site/legacy/ (frozen mirror) must stay out."""
    rels = {str(p.relative_to(ROOT)) for p in facts._scan_site_surface()}
    assert "site/assets/js/evidence_meta.js" in rels
    assert "site/method/build/index.html" in rels
    assert "site/journal/essays/org-chart-of-one/body.html" in rels
    assert "scripts/v4_build_evidence.py" in rels
    assert not any(r.startswith("site/legacy/") for r in rels), "the frozen legacy mirror is history, not a claim"
    assert len(rels) >= 100, "the site surface collapsed — the scan went near-vacuous"


def test_planted_stale_ceiling_in_site_js_flags(facts, tmp_path):
    """Mutation proof (CONVENTIONS §9): the widened scan FAILS on a planted stale
    literal in a .js file — the exact renderCost shape that shipped for weeks."""
    js = tmp_path / "planted.js"
    js.write_text(
        'export function renderCost(d) { return fig("$85", "hard ceiling") + "a self-imposed $85 hard ceiling"; }\n',
        encoding="utf-8",
    )
    hits = facts._source_hits([js])
    assert any("$85" in h for h in hits), f"planted stale .js ceiling must flag, got {hits}"


def test_planted_stale_ceiling_in_site_html_flags(facts, tmp_path):
    """Same proof for the generated-shell shape: a registry blurb quoting a retired
    ceiling inside a one-line embedded JSON script tag."""
    page = tmp_path / "index.html"
    page.write_text(
        '<script>window.__X__ = [{"blurb": "the meter behind the $85 ceiling, live."}]</script>\n',
        encoding="utf-8",
    )
    hits = facts._source_hits([page])
    assert any("$85" in h for h in hits), f"planted stale .html ceiling must flag, got {hits}"


def test_live_site_surface_states_no_stale_ceiling_now_and_after_the_window_reverts(facts):
    """Integration: the live site is clean under today's allowed set AND under the
    post-September set — a site string quoting August's temporary $200 would pass
    today and rot on 2026-09-01 with no deploy to catch it, so the revert case is
    asserted here rather than discovered by October's first red CI run."""
    hits_now = facts._source_hits(facts._scan_site_surface())
    assert hits_now == [], "live site states a stale ceiling:\n" + "\n".join(hits_now)

    post_revert, _ = facts._governor_ceilings(today=dt.date(2026, 9, 2))
    saved = facts.BUDGET_OK
    try:
        facts.BUDGET_OK = post_revert
        hits_post = facts._source_hits(facts._scan_site_surface())
    finally:
        facts.BUDGET_OK = saved
    assert hits_post == [], "site quotes a dated-window ceiling that rots on revert:\n" + "\n".join(hits_post)


# ── #3249: the rollover the allowed-set check could not see ───────────────────
# `figures()` answers "may prose say this today?". On 2026-09-01 the August window
# closes and $200/$235 simply drop out of the allowed set — but dropping OUT is not
# the same as being FORBIDDEN, because `BUDGET_NEAR` only inspects a figure sitting
# within 20 characters of a ceiling word. Measured on 2026-08-27 by standing the real
# scanners at 2026-09-02: **2 of the 14 unframed $200/$235 occurrences were caught.**
# The other 12 would have stated a retired ceiling as current truth with CI green.
#
# `retired_figures()` closes that by matching the retired pair with NO proximity
# requirement — safe only because it is a closed set of dead literals, so there is no
# population of legitimate matches to shield. The two tests below are the pair the
# charter asks for: one proves the scan CAN fail, one proves the live tree is clean
# at the date it will fire. Without the first, the second passes vacuously forever.


def _at(facts, when):
    """Run every budget surface as though `today` were `when`. Patches the SAME module
    globals the live gate reads, so the test exercises the shipped code path."""
    allowed, _ = facts._governor_ceilings(today=when)
    retired = facts._retired_window_figures(today=when)
    saved_ok, saved_re = facts.BUDGET_OK, facts._RETIRED_RE
    try:
        facts.BUDGET_OK = allowed
        facts._RETIRED_RE = facts._retired_regex(retired)
        hits = []
        for doc in facts._scan_files():
            rel = doc.relative_to(facts.ROOT)
            for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                hits += [f"{rel}:{lineno}: ${amt}" for amt in facts._budget_offenders(line)]
        hits += facts._source_hits(facts._scan_source_files())
        hits += facts._cost_tracker_hits(facts.ROOT / "docs" / "COST_TRACKER.md", today=when)
        return hits
    finally:
        facts.BUDGET_OK, facts._RETIRED_RE = saved_ok, saved_re


def test_retired_window_scan_can_actually_fail(facts):
    """Mutation proof. A doc phrasing the retired pair with NO ceiling word nearby —
    the exact shape `BUDGET_NEAR` is blind to — must flag once the window closes, and
    must NOT flag while it is still in force."""
    line = "August 2026 ONLY the base is $200 / surge $235, auto-reverting."
    after = facts._retired_window_figures(today=dt.date(2026, 9, 2))
    during = facts._retired_window_figures(today=dt.date(2026, 8, 15))

    assert facts._budget_offenders(line, allowed={215, 252}, retired=after) == [200, 235], (
        "the retired-window scan did not fire on a stale claim after the revert — " "this gate cannot fail, so it is not a gate"
    )
    assert during == set(), "inside its own window the pair is truth, not drift"
    assert facts._budget_offenders(line, allowed={150, 176, 200, 235}, retired=during) == []

    # ...and historical framing still exempts, or every honest retrospective reds.
    framed = "For August 2026 only, a dated window raised the base to $200 / surge $235."
    assert facts._budget_offenders(framed, allowed={215, 252}, retired=after) == []


def test_live_tree_states_no_retired_ceiling_after_the_window_reverts(facts):
    """The rollover assertion, run every day BEFORE the rollover. `test_live_site_...`
    (above) already does this for the site surface only; docs, source and the spend
    ledger had no equivalent, which is where all 12 missed occurrences lived."""
    assert _at(facts, dt.date(2026, 8, 15)) == [], "the tree is not clean under today's own allowed set"
    post = _at(facts, dt.date(2026, 9, 2))
    assert post == [], "a live doc/source file states August's retired ceiling as current truth:\n" + "\n".join(post)
