"""tests/test_duration_budget_ratchet.py — the suite-duration budget's
three-literal agreement guard (#1966).

The CI suite-duration budget (`coverage_gap_warn.py --duration-budget-seconds`,
#1349) went unenforced by any consistency check: the ONLY place it lived was a bare
literal in one workflow line. #1966 found it breached (520s measured vs the 480s
budget, since climbed further to 641-725s across 9,396+ tests) with nothing making
sure a deliberate raise actually landed everywhere the number is expressed.

This guard mirrors tests/test_coverage_floor_ratchet.py's shape exactly:

  BUDGET_SECONDS below is the committed value. The guard asserts that all THREE
  places the budget is expressed —
    1. scripts/coverage_gap_warn.py  DEFAULT_DURATION_BUDGET_SECONDS  (the
       script's own default, used by any bare/manual invocation)
    2. .github/workflows/ci-test.yml  `--duration-budget-seconds N`  (the value
       CI actually passes every run)
    3. THIS FILE's BUDGET_SECONDS constant                            (the
       committed, reviewable high-water mark)
  are ALL EQUAL.

  Unlike the coverage floor (which is enforced and up-only by construction — a
  regression there silently sheds real coverage), a duration budget can legitimately
  move either direction: up when honest test growth demands headroom (#1966's own
  fix), down after a real optimization pass trims dominating outliers. So this guard
  is agreement-only, not up-only — to change the budget, bump all three literals
  together in one reviewable PR (this test then passes at the new value); a
  one-line drift in just the workflow (or just the script default) reds this test
  instead of silently diverging from what's actually enforced.

#3224 (2026-08-27) ADDED A FOURTH LITERAL — `HARD_CEILING_SECONDS` — because
"agreement-only" turned out to be the defect. See the class record below.

═══════════════════════════════════════════════════════════════════════════════
THE CLASS, IN ONE PLACE (#1349 → #1966 → #2152 → #3025 → #3106 → #3224 → #3265)
═══════════════════════════════════════════════════════════════════════════════
Every instance of this class has been answered by re-deriving the budget UPWARD, and
the trend line between instances has been steeper than the raises — until #3224 broke
that streak, and #3265 kept it broken:

  issue   date        measured    budget moved to   response
  #1349   (origin)     157s        —                the gate itself
  #1966   2026-08-04   688s avg    480 →  900       raise
  #2152   2026-08-06   830s avg    900 → 1200       raise
  #3025   2026-08-23  1394s       1200 → 1500       raise (+ 1 pathological test fixed)
  #3106   2026-08-24  1507s       1500 → 1950       raise
  #3224   2026-08-27  1994s       1950 → 1950       SHED — the first non-raise
  #3265   2026-08-30  2244s       1950 → 1950       SHED — the second non-raise

#3265 (2026-08-30) — ATTRIBUTION, METHOD NAMED (so the next instance repeats it rather
than re-deriving from scratch). The 2244s in this file's own trigger issue is the
`##[warning]Unit Tests job took 2244s...` line from run 33102082658 (job 98623415851,
2026-08-27T18:14:07Z — the "test / Unit Tests" job, read via `gh run view --job --log`,
not re-derived from a different measurement). Two things were measured before any
number was touched:

  1. VARIANCE, ACROSS THE WHOLE POST-#3224 WINDOW. Sampled all 44 "test / Unit Tests"
     job runs on `main` from 33030125667 (2026-08-27T01:30, the run immediately after
     #3224 merged) through 33326794702 (2026-08-30T18:04, the run immediately before
     this fix) via the GitHub API + `gh run view --job --log`, reading each run's own
     final `pytest` summary line (`N passed, ... in Ws`) rather than re-deriving it:
     collected tests grew 22,266 -> 23,004 (+738, +3.3%); pytest wall clock ranged
     1307.30s -> 2464.35s, an **88.5% spread against 3.3% test growth**. Pearson r
     between per-run test count and per-run wall clock over the 44 points: **0.257** —
     test count explains under 7% of the variance (r²). 32 of the 44 runs breached the
     1950s budget; the very next run after this window (33326794702, unmodified code)
     measured 1589.34s — comfortably under budget. This is #3224's own documented
     "raw CI wall clock is a NOISY instrument" warning, now measured at n=44 instead of
     n=3: attributing any SINGLE over-budget reading to code growth, without also
     measuring the surrounding spread, would have re-derived a raise on noise.
  2. THE INSTANCE ITSELF, DECOMPOSED THE SAME WAY #3224 DID (new-test time vs existing-
     test slowdown), anchored at #3224's own landing sha (678a0598, run 33030125667:
     22,266 tests, 1947.68s, mean 0.08748s/test) against this issue's trigger run
     (9f... at 18:14, 33102082658: 22,541 tests, 2202.69s, mean 0.09773s/test):
     new tests priced at the old mean explain 24.06s of the +255.01s delta (9.4%);
     EXISTING TESTS GETTING SLOWER explain 228.2s (89.5%); interaction 2.82s (1.1%).
     (Trigger run 33102082658 @ 3eff37e6f, 2026-08-27T18:14:07Z.) Same shape as #3224
     (79.7% existing-test slowdown there) — so the same remedy applies: find what got a
     duplicated whole-repo scan, not what got a new test.

`pytest --durations=25` on the first green run after #3224 (33326794702, unmodified
code) named the new dominant terms directly — not the check_doc_facts.py family #3224
already shed (those now sit at 15-26s each, the shed held), but two OTHER whole-repo
scans that were ALREADY duplicating themselves before #3224 landed and simply hadn't
been the biggest term yet:

  * `tests/test_fixture_frame_pairing_3222.py::test_the_one_hop_blind_spot_stays_measured`
    (56.55s, the single slowest test in the suite) re-ran the exact same
    `pt_paired_utc_today_sites` scan over all ~1,036 files in `_test_files()` that
    `_measure()` — 5 lines above it, `functools.lru_cache`d — already computed for the
    ratchet tests in the same file. Fixed by reading `_measure()`'s cached dict for the
    direct-set membership check instead of re-scanning. Local measurement (this file
    alone, 3-run means, `-p no:randomly`): file total 32.83s -> 23.56s (-28.2%); the
    fixed test itself 20.99s -> 11.25s (-46.4%).
  * `tests/test_platform_model_drift.py`'s `_built()` (which calls
    `generate_platform_model.build_model()`, itself a scan of `lambdas/`, `mcp/`,
    `cdk/`) was called ONCE PER TEST with no memoization at all — 6 full builds per run
    (5 tests, one of which calls it twice to prove determinism) against a function the
    file's own `test_generation_is_deterministic` PROVES is deterministic. Fixed with
    one `@functools.lru_cache(maxsize=1)`. Local measurement (this file alone, 2-run
    mean before / 3-run mean after): file total 40.21s -> 6.91s (-82.8%).

Combined local saving across the two files: ~42.6s per full suite run. Projected onto
CI's coverage-instrumented per-test costs (using the CI `--durations` figures directly,
since local-vs-CI absolute times differ but the SAME calls were eliminated): the
platform-model-drift family alone was 99.55s of CI wall clock across its 5 tests
(33.94+17.68+16.00+15.97+15.96s) collapsing toward one real build (~17s) plus four
near-zero cache hits, ~82.5s of that CI run's 1589.34s pytest wall clock; the
fixture-pairing fix removes roughly the same 46.4% ratio from its 56.55s CI reading,
~26.3s more. **Estimated ~109s of CI wall clock shed**, restoring headroom rather than
narrowing it further.

NOT RAISED. 1950 stays — the measured spread (§1 above) means a single 2244s reading is
not, by itself, evidence the honest cost grew; the decomposition (§2) says what DID grow
was duplicated scanning, which is now shed at its two live sites. If a future instance
survives both checks — spread that does not explain it AND a decomposition dominated by
new tests rather than existing-test slowdown — that is the argued-raise case #3224's
"AT MOST ONE more raise" note reserves; this is not that case.

WHAT #3224 MEASURED (method named, so the next instance can repeat it rather than
re-derive from scratch). Two green-main "test / Unit Tests" runs, read from the
Actions API — 32762278235 @ 9331995b (the run that filed #3106) and 33030125667 @
678a0598 (the run that filed #3224):

  * tests collected   21,146 → 22,266   (+1,120, +5.3%)
  * pytest wall clock 1465.46s → 1947.68s (+482.22s, +32.9%)
  * mean cost/test    0.0693s → 0.0875s   (+26.2%)

So the suite did not mostly get bigger — it got MORE EXPENSIVE PER TEST. Decomposing
the +482s: new tests priced at the old mean explain 77.6s (16.1%); existing tests
getting slower explain 384.2s (79.7%); the interaction term 20.3s (4.2%).

The `--durations=25` blocks of those same two runs name the mechanism. Four tests
roughly DOUBLED while the repo grew only 3.1% in tracked files:

  test_doc_facts_ops_1957::test_gate_passes_on_the_repo   13.10s → 27.95s
  test_wiki_checkers::test_verified_advisory_is_warn_only 12.88s → 27.57s
  test_doc_facts_ops_2003::test_gate_passes_on_the_repo   12.86s → 27.54s
  test_wiki_checkers::test_doc_facts_clean                13.27s → 27.14s

Reproduced locally at both shas (same machine, `time python3
scripts/check_doc_facts.py`, worktrees at each sha): **7.29s at 9331995b, 15.41s at
10315b618** — the script did not get twice as careful, it acquired one more whole-repo
scan. `cProfile` on the same command attributes 47% of it (8.09s of a 17.17s
profiled run) to ONE addition landed between the two shas: #3126/#3156 put
`gate_census.build_census()` — 1,189,573 `re.Pattern.search` calls over the whole tree
— on `sync_doc_metadata`'s auto-discovery path, which `check_doc_facts.py` runs.

That census is not paid once. Instrumenting `discover_gate_census_count` with a
counter and running the FULL local suite on a clean 10315b618 worktree (2026-08-27,
22,336 collected, 970.20s) recorded **19 complete census builds, every one against the
same unmutated repo root, mean 8.07s — 153.3s, or 15.8% of the entire local suite
wall clock**. None of that cost existed when #3106 measured 1507s.

WHAT THE SHED MEASURED (local, `pytest --durations=20 -p no:randomly` over the seven
files that hold the repo-scan family, before vs after, same machine):

  before  129 tests in 163.76s   1957 / 2003 / wiki all near 15.5s in the top-20
  after   129 tests in 135.41s   -28.35s (-17.3%); 2003 and wiki::test_doc_facts_clean
                                 leave the top-20 entirely (they are now cache hits)

AND THE SHED'S OWN FIRST ATTEMPT SHIPPED HALF-BROKEN, which is the lesson worth more
than the seconds. PR #3231's first CI run still showed
`test_wiki_checkers.py::test_doc_facts_clean` at 21.59s: the cache's own test file
used an autouse `cache_clear()` on the SHARED memo table, and it sorts BETWEEN
`test_doc_facts_ops_*.py` and `test_wiki_checkers.py`, so it discarded a scan the
suite had already paid for. Every one of those tests was green; the entire symptom
was one line in a `--durations` block. The fixture now swaps in a private table
(`repo_scan_cache.new_cache()`) and `test_k_this_files_own_fixture_must_never_clear_
the_SHARED_cache` pins it via AST. Re-measured locally in the interleaved order
(1957 -> 2003 -> the cache tests -> wiki): ONE 14.92s scan remains, plus the
deliberately-unshared decade-clock advisory run. A performance fix has no failing
test to tell you it did not work — check the durations, not the checkmarks.

THE CLASS IS THEREFORE NOT "we keep adding tests". It is:

    suite cost = (number of tests that shell out to a shared repo scanner)
                 x (cost of one whole-repo scan)

Both factors grow with the repo, so the curve is superlinear and a fixed-percentage
headroom raise is consumed faster every time — which is exactly the observed history.
One check added to a shared scanner is multiplied into CI by the size of its caller
set. THAT is why five raises produced a sixth instance.

THE DECISION FOR THE CLASS (not the instance):
  1. SHED the multiplier where it is pure duplication. `tests/repo_scan_cache.py`
     memoizes a scan of the UNMUTATED tree for the lifetime of one pytest process;
     the three tests that ran the byte-identical `check_doc_facts.py` now share one
     spawn. `tests/test_repo_scan_cache_3224.py` pins both directions (it really
     collapses duplicates; it never collapses two scans that differ) and guards the
     three call sites structurally, because a silent cache miss would look exactly
     like a working cache.
  2. DO NOT RAISE for this instance. 1950 stays. If the shed leaves green main still
     over budget, the warning is supposed to keep firing — that is the instrument
     working, not a reason to move the number.
  3. CAP THE ESCAPE HATCH. `HARD_CEILING_SECONDS` below is a wall, in the exact shape
     `tests/test_module_size_guard.py` already runs against module size in this repo
     (HARD_CEILING + a baseline that only ratchets down — standing record 6
     collisions, 0 raises). A budget above the ceiling FAILS this file. At 1950 there
     are 150s (7.7%) of room left, so AT MOST ONE more raise exists before shedding
     becomes the only legal answer — a checkable statement, not "we'll watch it".

WHAT THE NEXT INSTANCE SHOULD MEASURE FIRST — cost per test, not wall clock. Wall
clock rises with honest growth and therefore always argues for a raise; cost-per-test
does not, and it is what actually moved here (+26.2%). Note also that raw CI wall
clock is a NOISY instrument: three pre-merge full-suite runs on 2026-08-27 over an
essentially identical suite (22,168-22,214 tests) measured 962.58s / 1074.24s /
1310.61s — a 36% spread with no code difference, and the SLOWEST of the three ran
alone while the fastest ran alongside three other PRs. Cross-PR contention is a
queueing effect on GitHub-hosted runners, not a job-duration one; do not attribute
growth to it.
"""

import os
import re
import subprocess
import sys

import pytest

# ── THE BUDGET. Bump alongside the two literals below in the SAME PR. ────────
# #1966 (2026-08-04): raised 480 -> 900 after 6 sampled green-main runs measured
# 641-725s (avg ~688s) against a 9,396+-test suite with no dominating outlier in
# `pytest --durations=25` (honest broad growth, not a few slow tests) — 900s is
# ~24% headroom above the observed max.
# #2152 (2026-08-06): the 900s budget breached same-day (985s) after the same
# session merged ~200 more tests — raised 900 -> 1200 after sampling ALL 8
# green-main "Unit Tests" runs in the post-#2132 era: 704/945/745/745/922/764/
# 985/833s (avg ~830s, max 985s). See ci-test.yml's comment for the full
# derivation.
# #3025 (2026-08-23): raised 1200 -> 1500 with CI's own --durations measurement as
# the rationale (green run 32613992699): 20,509 tests in 1394s, of which 180.85s was
# ONE pathological test (unmocked _trigger_cover network attempt — fixed in the same
# PR) and ~166s the platform-model drift family. Post-fix projection ~1215s; 1500s is
# ~23% headroom, against a budget that had been breached 5 times in 3 weeks at 1200s —
# a warning firing on every green run is background noise, not an instrument. The NEW
# per-test warner (conftest.py PER_TEST_WARN_SECONDS, #3025) now owns the
# single-test-regression half; this aggregate budget owns honest broad growth.
# #3106 (2026-08-24): the 1500s budget breached on green main at 9331995b (1507s, 7s
# over) after the D2 session (2026-08-23/24) merged ~230 more tests across 15 PRs —
# ADR-105 measure-first, not a blind bump. Sampled ALL 10 green-main "test / Unit
# Tests" job runs since #3025 landed the 1500s budget (via the GitHub API,
# runs 32637512129..32762278235, 2026-08-23 11:50 through 2026-08-24 18:29):
# 1175/1022/1179/1204/1358/1580/1255/1305/1467/1507s (avg ~1305s, max 1580s) —
# TWO of those 10 already breached 1500s outright (1580s and 1507s), a 20% breach
# rate on a budget raised the same session. `pytest --durations=25` on the current
# run (21,146 tests) shows no single test over 51s and no dominating outlier: the
# top 5 (50.07/27.31/27.24/25.03/24.89s) are all tests/test_platform_model_drift.py
# — the same known, already-assessed generation/drift family #3025 priced at ~166s
# total (real work asserting real generated artifacts, not a slow-test mistake to
# trim). Honest broad growth again, so re-derive rather than shed: applying the
# same ~23% above-observed-max headroom #1966/#2152/#3025 each used (1580 * 1.23 ≈
# 1943s), raised 1500 -> 1950 (~49% above the 10-run average, ~23% above the
# observed max) — enough headroom to absorb the next few weeks of this session's
# growth curve without flapping on every green run, while a genuine regression
# still trips it.
# #3224 (2026-08-27): NOT RAISED. 1994s measured against this 1950s budget — the fifth
# instance of the class — was answered by removing two redundant whole-repo scans
# (tests/repo_scan_cache.py) instead of by a fifth re-derivation. See the class record
# in this file's docstring for the attribution and the method.
# #3265 (2026-08-30): NOT RAISED (the second non-raise). 2244s measured against this
# 1950s budget on run 33102082658 — the sixth instance of the class — decomposed into
# 9.4% new-test time / 89.5% existing-test slowdown (same shape as #3224) and shed at
# its two live sites: tests/test_fixture_frame_pairing_3222.py's one-hop-blind-spot test
# duplicated a scan tests/repo_scan_cache.py's own SIBLING function in that file
# (`_measure()`) had already computed; tests/test_platform_model_drift.py called
# `generate_platform_model.build_model()` fresh on every one of its 6 test invocations
# with no memoization at all. NOTE, for honesty: #3106's own comment three entries above
# named this exact family ("the top 5 ... are all tests/test_platform_model_drift.py")
# and called it "real work asserting real generated artifacts, not a slow-test mistake
# to trim" — that assessment was WRONG for 5 of the 6 calls, which were pure duplicate
# invocation of a function the file's own test proves deterministic; #3106 correctly
# identified the file, incorrectly ruled out the fix. See the class record in this
# file's docstring for the full attribution and both measured before/after deltas.
BUDGET_SECONDS = 1950

# ── THE WALL (#3224). A raise past this FAILS. Shed instead. ─────────────────
# 2100s = 35 minutes = `timeout-minutes` on pr-checks.yml's `full-suite` job, the
# longest any lane in this repo is permitted to run, and the one every PR waits on.
# The rule it encodes: no lane may be BUDGETED past the longest wall any lane is
# allowed to RUN. Raising the pre-merge timeout to escape is possible but it is a
# different, visible decision that slows every PR — and
# test_hard_ceiling_tracks_the_premerge_full_suite_timeout below forces that PR to
# edit this constant in the same diff rather than letting the ceiling drift upward on
# its own. Same idiom as tests/test_module_size_guard.py's HARD_CEILING.
HARD_CEILING_SECONDS = 2100

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPT = os.path.join(_REPO, "scripts", "coverage_gap_warn.py")
_CI_TEST = os.path.join(_REPO, ".github", "workflows", "ci-test.yml")
_PR_CHECKS_YML = os.path.join(_REPO, ".github", "workflows", "pr-checks.yml")


def _premerge_full_suite_timeout_minutes():
    """`timeout-minutes` of pr-checks.yml's `full-suite` job, read from the workflow.

    Deliberately dependency-free (no PyYAML): #3156's incident was a doc gate that
    degraded to a frozen constant in an environment without yaml installed, and a
    ceiling that silently skips is a ceiling that cannot fail. A missing job or a
    missing key is an assertion failure here, never a skip.
    """
    with open(_PR_CHECKS_YML, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^  full-suite:\s*$", ln)), None)
    assert start is not None, "pr-checks.yml no longer defines a `full-suite:` job — the ceiling's anchor is gone"
    for ln in lines[start + 1 :]:
        if re.match(r"^  \S", ln):  # next job key at the same indent
            break
        m = re.match(r"^    timeout-minutes:\s*(\d+)\s*$", ln)
        if m:
            return int(m.group(1))
    raise AssertionError("pr-checks.yml's `full-suite` job has no timeout-minutes — the suite has no wall at all")


def _script_default():
    with open(_SCRIPT, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"DEFAULT_DURATION_BUDGET_SECONDS\s*=\s*([\d.]+)", src)
    assert m, "coverage_gap_warn.py no longer defines DEFAULT_DURATION_BUDGET_SECONDS"
    return float(m.group(1))


def _ci_duration_budget():
    with open(_CI_TEST, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"--duration-budget-seconds\s+(\d+)", src)
    assert m, "no --duration-budget-seconds N found in ci-test.yml — the enforced duration budget is missing"
    return int(m.group(1))


def test_script_default_matches_committed_budget():
    assert _script_default() == BUDGET_SECONDS, (
        f"scripts/coverage_gap_warn.py DEFAULT_DURATION_BUDGET_SECONDS={_script_default():.0f} disagrees with "
        f"the committed budget {BUDGET_SECONDS} in this file — bump both together."
    )


def test_ci_test_yml_matches_committed_budget():
    assert _ci_duration_budget() == BUDGET_SECONDS, (
        f"ci-test.yml --duration-budget-seconds={_ci_duration_budget()} disagrees with the committed "
        f"budget {BUDGET_SECONDS} in this file — bump both together."
    )


def test_all_three_budget_literals_agree():
    """The script default, the enforced CI value, and this file's committed budget
    must be the SAME number — otherwise a bare invocation of the script silently
    diverges from what CI actually enforces (the #1206/#1349 drift class, applied
    to duration instead of coverage)."""
    script_default = _script_default()
    ci_value = _ci_duration_budget()
    assert script_default == ci_value == BUDGET_SECONDS, (
        f"duration-budget literals disagree: script default={script_default:.0f}, "
        f"ci-test.yml={ci_value}, committed={BUDGET_SECONDS}. Keep all three in lockstep."
    )


# ══════════════════════════════════════════════════════════════════════════════
# #3224 — THE WALL. Agreement alone let the budget be re-derived upward forever
# (5 raises, 157s -> 1994s, 12.7x). These three make the sixth raise a decision
# somebody has to argue for rather than a one-line edit.
# ══════════════════════════════════════════════════════════════════════════════


def test_budget_may_not_exceed_the_hard_ceiling():
    """THE #3224 gate. Read the class record in this file's docstring before touching
    HARD_CEILING_SECONDS: the answer to a breach is to shed a repeated whole-repo scan
    (tests/repo_scan_cache.py is the worked example), not to move the wall."""
    assert BUDGET_SECONDS <= HARD_CEILING_SECONDS, (
        f"the suite-duration budget ({BUDGET_SECONDS}s) is above the {HARD_CEILING_SECONDS}s hard ceiling. "
        "This is the sixth instance of the class #1349/#1966/#2152/#3025/#3106/#3224 track, and a raise is "
        "no longer the permitted answer — shed the cost (see the class record in this file's docstring: the "
        "dominant term is duplicated whole-repo scans, not test count) or make raising the ceiling its own "
        "argued PR."
    )


def test_hard_ceiling_tracks_the_premerge_full_suite_timeout():
    """The ceiling is not a taste number — it is the longest wall any lane in this repo
    is allowed to run (pr-checks.yml `full-suite`'s own timeout). Raising that timeout
    must therefore also be a deliberate edit HERE, in the same PR, rather than quietly
    widening the room the budget has to grow into."""
    minutes = _premerge_full_suite_timeout_minutes()
    assert HARD_CEILING_SECONDS == minutes * 60, (
        f"HARD_CEILING_SECONDS={HARD_CEILING_SECONDS} no longer equals pr-checks.yml's full-suite "
        f"timeout-minutes ({minutes} -> {minutes * 60}s). If the pre-merge wall genuinely moved, move this "
        "constant with it in the same PR and say why in the class record above."
    )


def test_the_ceiling_can_actually_fail(monkeypatch):
    """Mutation proof — this repo's most-repeated defect is a check that cannot fail.
    Plants an over-ceiling budget and re-runs the REAL gate function (not a restatement
    of its comparison), then proves it is quiet exactly at the wall."""
    mod = sys.modules[__name__]

    monkeypatch.setattr(mod, "BUDGET_SECONDS", HARD_CEILING_SECONDS + 1)
    with pytest.raises(AssertionError, match="hard ceiling"):
        test_budget_may_not_exceed_the_hard_ceiling()

    monkeypatch.setattr(mod, "BUDGET_SECONDS", HARD_CEILING_SECONDS)
    test_budget_may_not_exceed_the_hard_ceiling()  # at the wall is legal; over it is not


def test_the_ceiling_reader_fails_loudly_rather_than_defaulting(monkeypatch):
    """A ceiling derived from a file that vanished must red, never fall back to a
    number nothing measured (#3156's class, applied here)."""
    monkeypatch.setattr(sys.modules[__name__], "_PR_CHECKS_YML", os.path.join(_REPO, ".github", "workflows", "does-not-exist.yml"))
    with pytest.raises((AssertionError, OSError)):
        _premerge_full_suite_timeout_minutes()


def test_the_shipped_budget_still_fires_the_warning_on_the_wire(tmp_path):
    """The budget number is only an instrument if the warner actually trips AT IT.
    Runs scripts/coverage_gap_warn.py end-to-end at BUDGET_SECONDS+1 and BUDGET_SECONDS-1
    — a budget raised so high it can never fire is the same defect as no gate at all.
    (tests/test_coverage_gap_warn.py proves the mechanism against a synthetic 480s
    budget; this proves it against the value CI actually ships.)"""
    xml = tmp_path / "coverage.xml"
    xml.write_text('<?xml version="1.0" ?><coverage line-rate="0.8332"></coverage>', encoding="utf-8")

    over = subprocess.run(
        [
            sys.executable,
            _SCRIPT,
            "--coverage-xml",
            str(xml),
            "--floor",
            "74",
            "--duration-seconds",
            str(BUDGET_SECONDS + 1),
            "--duration-budget-seconds",
            str(BUDGET_SECONDS),
        ],
        capture_output=True,
        text=True,
    )
    assert (
        "::warning title=Unit Tests job is over its duration budget::" in over.stdout
    ), f"the shipped {BUDGET_SECONDS}s budget did not warn one second over it:\n{over.stdout}{over.stderr}"
    assert f"over the {BUDGET_SECONDS}s budget" in over.stdout

    under = subprocess.run(
        [
            sys.executable,
            _SCRIPT,
            "--coverage-xml",
            str(xml),
            "--floor",
            "74",
            "--duration-seconds",
            str(BUDGET_SECONDS - 1),
            "--duration-budget-seconds",
            str(BUDGET_SECONDS),
        ],
        capture_output=True,
        text=True,
    )
    assert "over the" not in under.stdout, f"the duration warning fires below budget — it would be noise, not signal:\n{under.stdout}"
