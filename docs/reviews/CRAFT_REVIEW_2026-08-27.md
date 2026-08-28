# Craft Review — 2026-08-27 (first run)

> **Status:** log · **Owner:** Matthew · **Run:** `craft-2026-08-27-laneH` · **Grades:** [`craft_grades_2026-08-27.json`](craft_grades_2026-08-27.json)

The first-ever `/craft-review`. It grades the repository as a craft artifact the way a
promotion committee (Eng I → CIO) would read it cold, against `docs/ENGINEERING_STANDARDS.md`
D1–D10. Six lenses, one grader each, over a shared verbatim context block; every load-bearing
claim was then re-reproduced by the driver before it entered the grades file.

Magnitudes come from `scripts/review_anchors.py` (derived at run time, #3273) and
`scripts/gate_census.py` — **no magnitude in this review is hand-typed**, because the anchors
this ritual's sibling used were measured 2.7× stale the same night.

## Grades

| Dim | Area | Grade |
|---|---|---|
| D1 | First impression / repo cleanliness | B |
| D2 | Structure & module hygiene | B |
| D3 | Naming & code aesthetics | B |
| D4 | Trustworthy gates | B |
| D5 | CI/CD maintainability | B |
| D6 | Supply-chain & security posture | **A** |
| D7 | Team-readiness signals | B |
| D8 | Testing depth | B |
| D9 | AI-era engineering & proportionality | **A** |
| D10 | Docs & decision hygiene | B |

**Overall: B.**

## The one-sentence verdict

This is a repo whose **machinery is consistently stronger than its self-description** — nearly
every B is the same defect wearing a different hat: a mechanism that works, graded down because
the document naming that mechanism describes something else.

## The through-line

Session I's through-line — *things that work, but not by the mechanism their own documentation
names* — was not merely present, it was the **dominant finding shape**, arriving independently
in all ten dimensions from six graders who could not see each other's work. Eight of the eleven
P2s are instances:

- **`CONVENTIONS.md`'s section titled "What gates the MERGE" describes a merge gate that does
  not exist.** Live `main` has **zero** required status checks (`branches/main/protection` →
  404; one ruleset, rules `[deletion, non_fast_forward]`). The *correct* statement sits in the
  same tree — `MANAGED_WHERE_LEDGER.md:40`, "**NOT YET APPLIED** … `main` has NO required status
  checks today" — machine-pinned by `github_posture.json`'s `"applied": false` and held by a
  test. **The honest record is guarded; the false one is not.**
- **The tombstone gate is green over a live violation of the class it was built for.**
  `mcp/utils.py:12` claims membership of the ADR-027 "Layer" — superseded, and a tier
  `DECISIONS.md:3939` says "never existed". The gate scans `mcp/` and passes, because its rule
  requires the literal word `shared`. It was built *because* #781 left 35+ such claims; the 36th
  survived. (Known phrase-matched-suppressor class.)
- **82% of `Verified:` stamps are older than the content they certify** — 48 of 58 docs,
  excluding automated commits, up to 100 days. The rubric doc defining D10 is itself stale by
  23 days. The class has had **no open owner** since #2619 closed.
- **The module-size headroom instrument reports 9 files at zero headroom; the true set is 12** —
  completing the cure moves a file from the monitored set to the *un*monitored one.
- **The CI composite 45 call sites depend on has been committed exactly once, at creation**, and
  pins an action SHA *older* than every call site while its own comment asserts parity.
  Dependabot's `directory: "/"` cannot see nested composite actions.
- `mypy.ini` records a "350-module surface"; it is 468. `check_untyped_defs=False` means **56% of
  function-body lines are never entered** — the green is true and covers under half the code.
- **439 of 524 `# noqa` waivers name a code no linter reports** (346 × `BLE001`), so
  `except Exception:` reads as a linted, justified class and is entirely unlinted.
- Both first-day `QUICKSTART` deploy commands pass one argument to scripts that require two.

## What is genuinely A

Named honestly, not as courtesy — and the calibration rule requires it:

- **The operating calendar made `NEVER-RUN` its own state** rather than printing `OK` over
  rituals nobody had run. The repo caught its own instrument lying and gave it a distinct exit
  code. *This review exists because that fix landed.*
- **The `applied:false` posture contract (#3207)** — documents an **unapplied** control
  accurately, and pins the admission so it cannot rot into a false green **in either direction**.
- **Zero third-party imports in the production runtime**, a `pip-audit` gate that genuinely
  blocks with a **zero-entry allowlist**, OIDC everywhere, `permissions:` on 23/23 workflows.
- **`tests/grounding_wiring.py`** — AST-*discovers* 30 AI surfaces and asserts both directions
  against policy with written per-surface exemptions. The best single artifact read.
- **The module-size ratchet caught *itself* being decorative** and invented the earned-headroom
  N/5 rule rather than re-baselining. Debt is measurably shrinking; no baseline was ever raised.
- **Two lenses falsified their own assigned hypotheses.** The mypy clean set genuinely covers
  468/468 modules — the documented non-recursive-glob trap is closed by construction.

## Confirmed-correct deliberate postures (graded A, not faulted)

`check_untyped_defs=False` (cost *measured* at 330/159, owner #2638, and `mypy.ini:80-84` says
outright that "mypy passed" overclaims) · 21 top-level dirs against the "≤~10" target (every dir
carries a README *and* an allowlist reason; the guard honestly labels "≤10" as aspirational) ·
CodeQL/SBOM advisory by written decision (ADR-148, quoted inline) · the AI-code bar enforced
**provenance-blind** — a provenance-detecting gate would create a second, softer standard by
existing.

## Coverage boundary

Stated plainly, because false comprehensiveness is this review's failure mode. **The test suite
was never run** — every claim about a gate is a claim about its *source*. Actual coverage % was
not computed. **No gate was proven able to fail** (520 of 563 are UNPROVEN, #2578), except four
shown green over real violations — proven *blind*, the opposite direction. Hypothesis strategy
quality was not audited (the vacuous-control class was not ruled out). Not examined: the site
front-end as code, the 153 ADRs end-to-end, `docs/archive/`, CDK/IAM correctness, AWS runtime
state (never queried), and ~400 lambda modules for property-test suitability. Product
correctness, deploy integrity and SDLC process are out of scope by design.

One lens claim was **refuted** in verification and is recorded in the grades file rather than
filed.
