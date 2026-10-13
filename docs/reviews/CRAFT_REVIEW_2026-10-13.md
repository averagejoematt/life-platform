# Craft Review — 2026-10-13 (Sonnet panel, Opus verification)

> **Status:** log · **Owner:** Matthew · **Run:** `craft-2026-10-13-sonnet-panel` · **Grades:** [`craft_grades_2026-10-13.json`](craft_grades_2026-10-13.json) · **Previous:** [`CRAFT_REVIEW_2026-08-27.md`](CRAFT_REVIEW_2026-08-27.md) · Refs #4773

> **What these grades are (ER-05).** Internal self-assessment by AI personas against a rubric
> the platform authored (`docs/ENGINEERING_STANDARDS.md` D1–D10). It measures conformance to the
> platform's own stated values, not external quality. The only trustworthy A-grade arbiter is one
> real senior engineer reading the repo cold (`docs/REVIEW_METHODOLOGY.md`).

```
REVIEW ANCHORS — sealed artifact (#3607)

  artifact   docs/reviews/anchors/ANCHORS.json
  sha256     af9f958947dc30c8023d47553fc378e505dc01b56006afb154f183e71be96f57
  sealed_at  2026-09-21T04:51:14.637047+00:00
  frozen_at  2026-09-20   lenses: 17

  Placeholders resolved for this run:
    ${a11y_viewports} = desktop, mobile   [qa/a11y_audit.VIEWPORTS]
    ${ceiling} = 215   [scripts/budget_ceilings.budget_amount_usd() — the value cdk/stacks/core_stack.py synths]
    ${cycle} = 17   [SSM /life-platform/experiment-cycle]
    ${cycle_day} = 37   [lambdas/common/constants.EXPERIMENT_START_DATE (2026-09-06) vs 2026-10-12]
    ${distinct_margin} = 35.0   [lambdas/ai/voice_fidelity_core._DISTINCT_MARGIN_PTS]
    ${lane_budget} = 1286   [deploy/github_posture.json::main_required_checks_ruleset.required_status_checks[].typical_seconds (max — the checks run in parallel)]
    ${min_n} = 6   [lambdas/ai/voice_fidelity_core.MIN_N_FOR_VERDICT]
    ${mobile_viewport} = 390   [qa/a11y_audit.MOBILE_VIEWPORT['width']]
    ${page_count} = 93   [qa/qa_manifest.visual_pages()]
    ${surge_ceiling} = 252   [scripts/budget_ceilings.read_family().active_pair()]
    ${type_floor_px} = 11.0   [qa/visual_qa.SVG_TEXT_FLOOR_PX]

  Owner-signed loosenings: none — every clause is at or above the previous seal.
```

**The seal has no `craft` record** (`python3 scripts/review_anchor_seal.py --lens craft` → `no anchor
record for lens 'craft'`, exit 2). The clauses graded here are the A cells of
`docs/ENGINEERING_STANDARDS.md` D1–D10 at `75e3a0071`, frozen for the run; the rubric prose is
fingerprinted by `anchor_freeze`:

```json
{"anchor_freeze": {"lens": "craft", "frozen_at": "2026-10-12", "graded_sha": "75e3a00712f9f5c8706a51196197e3cf9c02cab5",
  "rubric": {".claude/skills/review/SKILL.md": "sha256:d044e0a84ee7b329", ".claude/skills/review/references/craft.md": "sha256:264b661ef84453a9"},
  "carry_forward_cap_days": 28}}
```

## Why this run exists

#4773's last acceptance box: one `/review` lens run before and after review panelists moved to
Sonnet, with the finding counts and verifier pass rate posted, to show quality held. The one
deliberate parameter: **every panelist ran on `model: sonnet`; every verifier ran on
`model: opus`** (`finding-verifier`, pinned in its frontmatter and passed explicitly). The driver
(Phase 0, Phase-3 scoring) ran on the session model, `claude-opus-5-5`.

**Ground truth (Phase 0).** main `75e3a0071`; `/version.json` build `6b25c54` (an ancestor;
later commits are not site changes); repo PUBLIC; cycle 17, day 37; budget tier 1 (internal/dev AI
paused). Boot brief: model CONSISTENT, 108 lambdas, 88 MCP tools. Anchors from
`scripts/review_anchors.py`: `test_modules` 1499, `deploy_entrypoints` 180, `ci_workflows` 27,
`lambda_modules` 619, `adr_records` 159. Gate census (`scripts/gate_census.py`): 784 gates,
260 proven.

## Before / after — the #4773 numbers

| Run | Panel model | Verification | Raw findings | Sent to verification | Upheld | Refuted / not upheld | Verifier pass rate | Controls |
|---|---|---|---|---|---|---|---|---|
| **2026-08-27** | `claude-opus-5[1m]` (session model, inherited, no pin) | driver re-reproduction, same model; no separate verifier | 24 (23 graded + 1 adjacent claim; 3 more self-killed by graders before submitting) | 24 | 23 | 1 | **95.8%** | none (pre-#3603, grandfathered) |
| **2026-10-13** | **`sonnet`** (6 panelists, pinned) | **`finding-verifier` × 5, `opus`**, adversarial, area-batched | **29** | **29** | **21** | **8** (6 refuted + 2 weak-plausible) | **72.4%** | 5 planted, **0** confirmed · 1 valid withheld issue, **found** → CALIBRATED |

**Raw findings per panelist (2026-10-13):**

| Panelist (sonnet) | Dimensions | Raw | Upheld | Not upheld |
|---|---|---|---|---|
| Eng I / new hire | D1 | 4 | 2 | 2 (eng1-4 refuted; eng1-1 weak) |
| Senior engineer | D3, D10 | 5 | 4 | 1 (senior-3) |
| Staff engineer | D2, D5 | 6 | 4 | 2 (STAFF-3 dup #4270; STAFF-4 weak) |
| Principal engineer | D4, D9 | 5 | 4 | 1 (principal-3) |
| Engineering manager | D7, D8 | 4 | 4 | 0 |
| CIO / acquirer | D6 | 5 | 3 | 2 (CIO-1 dup; CIO-3) |
| **Total** | | **29** | **21** | **8** |

**Reading the comparison honestly.** The two pass rates are not like-for-like. 08-27's 95.8% is a
driver re-check of its own panel's claims with no planted controls. 10-13's 72.4% is an
adversarial pass by a separate Opus verifier carrying five planted false findings. Of the eight
findings it did not uphold, five restated a documented posture or sanctioned pattern, two were
duplicates, and one misread a scope. That is the false-positive class the spine predicts for
first-pass agents ("already-resolved or already-decided, flagged again"). It is the class the
Sonnet-panel decision bet verification would catch, and it did. **Quality held at the verified
layer:**
- the upheld count (21) is close to 08-27's 23, from a larger raw pool;
- every upheld finding carries reproduced tree evidence;
- verification also corrected numbers on nine upheld findings (below);
- the controls fired in both directions: no plant was confirmed, and the one live withheld issue
  was found.

One caveat: n is small, and five plants and one withheld issue are a sample, not a proof.

## Calibration (planted controls, #3603)

- **Planted false findings: 5, confirmed by verifiers: 0.** Each verifier batch carried one. Each
  was a true property of the system written up as a defect:
  - `eng1-5`: no `.env` template. This is the Secrets-Manager-only posture.
  - `STAFF-7`: lint and test are split into reusable workflows. This is the §5 composition pattern.
  - `principal-6`: 140-column lines with E501 ignored. Documented in `.flake8` and §4.
  - `CIO-6`: CodeQL is advisory. ADR-148.
  - `EM-5`: the coverage floor of 82 is above the 70% target. Up-only by design.
- **Withheld known issues: 2.**
  - **#4270** was found. The Staff panelist raised it as STAFF-3 (56 non-test modules at the root
    of `tests/`), and the verifier refuted it as a duplicate of #4270, which is the control firing.
  - **#4276** is **void**, not missed. Every acceptance box on it is ticked, and the tree shows
    the parse consolidated in `lambdas/ai/structured_json.py`. The Senior panelist graded that
    consolidation as an A, which is the correct reading.
- **Verdict: CALIBRATED.**

## Grades

| Dim | Area | Grade | Frozen+proposed | Previous (08-27) | Trend | One line |
|---|---|---|---|---|---|---|
| D1 | First impression / repo cleanliness | **B** | B | B | → | Root clean; first-day QUICKSTART commands exit 1 and README advertises a retired door. Panel's C+ re-derived after the archive and README findings failed verification |
| D2 | Structure & module hygiene | **B+** | A- | B | ↑ | Packaging done, debt −37%; instrument blind at the wall and `qa/` outside the guard |
| D3 | Naming & code aesthetics | **B** | B+ | B | → | Names clean, parse consolidated; 156 functions >150 lines, private `safe_float` copies |
| D4 | Trustworthy gates | **B** | B+ | B | → | Gates armed; `mypy.ini` census 350 vs 673, ~86% dead `noqa` codes |
| D5 | CI/CD maintainability | **B** | A- | B | → | D5-1 fixed; `ci-cd.yml` 1440 → 1748 lines, 3 unpinned actions |
| D6 | Supply-chain & security | **A-** | A- | A | ↓ (stricter) | All four controls; SBOM scoped to source, secret-scan undeclared, estate rows blank |
| D7 | Team-readiness | **A-** | A | B | ↑ | Live 3-check ruleset, no drift; squash titles unchecked, prose says two |
| D8 | Testing depth | **B+** | A- | B | ↑ | Property tier well aimed; `stats_core` lacks it, tier undocumented |
| D9 | AI-era engineering & proportionality | **A-** | A | A | ↓ (stricter) | Derived AI-surface registry; a ledger row credits the wrong gate. That defect was present at 08-27's A too |
| D10 | Docs & decision hygiene | **B** | A- | B | → | ADRs legible, stamps gated; tombstone miss plus cross-lens doc-truth defects |

**Overall: B.** That is 3 A-, 2 B+ and 5 B, up a notch within the band from 08-27's 2 A and 8 B.
The frozen+proposed column grades against the panelists' proposed extensions. Those extensions do
not bind this run: function length (D3), size instruments that cover the full scope (D2), SHA-pin
and workflow-size ratchets (D5), and an SBOM over the shipped artifact (D6).

**No D3 or D10 grade moved on the proposed column alone.** Two prior premises flipped under
verification:
- **08-27 D10-2** ("Verified stamps have no owner") is refuted. `scripts/check_doc_index.py` gates
  the stamps: 90 days advisory, 180 days hard.
- **08-27 D1-1** (the archive) is reframed. `deploy/archive` is ADR-059 policy (#4258).

## The through-line, unchanged

The 08-27 verdict still holds: **the machinery is stronger than its self-description.** The
machinery fixed the biggest 08-27 finding. Main now carries a live three-check ruleset that the
posture file declares and the sentinel verifies, and `apply_branch_protection.py --check` reports no
drift. The prose kept drifting. Of the 21 upheld findings, eight are docs or comments that state
something the tree contradicts:
- QUICKSTART commands that exit 1
- the README's `/evidence/` door
- the ruleset context list in the ledger and the ADR-148 body
- `mypy.ini:6`'s 350-module census against 673
- `PROPORTIONALITY.md:161` crediting the wrong gate
- the "4 codes" comment where there are 3
- `mcp/utils.py:12`'s superseded-ADR claim
- the TESTING.md runtime contradiction

## Verified findings and disposition

**Filing is deferred to the driver.** Nothing below was filed. The table is the would-be filing
set for `issue-filer` (`.claude/agents/issue-filer.md`), and the review batch label would be
`review:craft-2026-10-13`. Severities are after verifier correction.

| # | Finding | Dim | Sev | Effort | Class | Dedup | Disposition (would-file) |
|---|---|---|---|---|---|---|---|
| 1 | QUICKSTART: 4 one-arg `deploy_lambda.sh` calls exit 1 (`:94,97,125,281` vs `deploy_lambda.sh:41`); the script is EMERGENCY-only; stack list 9 vs 10; `ONBOARDING.md:129` path moved | D1 | P2 | S | A | persisting D1-2; class of closed #1258 | file; guard: doc-command arg-floor test |
| 2 | `README.md:25` advertises the retired `/evidence/` door | D1 | P3 | S | A | persisting D1-4 | file; derive in `sync_doc_metadata.py` |
| 3 | Size-guard scope: `qa/visual_qa.py` 1686 and `qa/qa_manifest.py` 1092 logical lines, unbaselined, outside `SCOPE_DIRS` after #4270's move | D2 | P2 | S | B | extends #4270 | comment on #4270 (not a new issue) |
| 4 | `headroom_table()` blind to unbaselined files at 1000/1000 (`program_structure.py`, `owner_redlines.py`) | D2 | P3 | S | A | persisting D2-1; extends #3537 | file |
| 5 | 156 functions over 150 lines, no function-length gate | D3 | P2 | L | B | new | file as a story; the B-item rent is a reuse of the ratchet shape |
| 6 | Private `_safe_float` copies ×4 beside `digest_utils.safe_float`, with exception sets drifting | D3 | P3 | S | A | extends #970 (closed) | file |
| 7 | Core pep8-naming subset unclaimed; JS style neither linted nor documented as unenforced | D3 | P3 | S | A | persisting D3-1/2 | file |
| 8 | `mypy.ini:6` census says 350 modules, live clean set is 673; no count guard | D4 | P2 | S | A | persisting D4-1 | file |
| 9 | 849 of 985 `noqa` code mentions name rules no configured linter reports (BLE001 346 → 659) | D4 | P3 | S | A | persisting D4-2, regressed | file |
| 10 | `test_mypy_clean_modules.py:41` "4 structural codes" vs 3 | D4 | P3 | S | A | persisting D4-3 | fold into #8 |
| 11 | `ci-cd.yml` 1748 lines (+21%), 831 inline run lines, no workflow-size ratchet | D5 | P2 | M | B | extends #1655 (closed) | file |
| 12 | 3 action refs on floating `@v7`; only `site-deploy.yml` is SHA-pin-asserted | D5 | P3 | S | A | new (CIO-1 merged) | file |
| 13 | `secret_scanning` and `push_protection` live but undeclared in `github_posture.json` | D6 | P2 | S | A | persisting D6-1; extends #3042 | file |
| 14 | `ACCOUNTS.md:84-90` estate rows UNDOCUMENTED, so bus-factor is 1; #1029 closed with that leg unfilled | D6 | P2 | S | B | extends #1029 | file **gate:owner** (only the owner can supply it) |
| 15 | SBOM scans `dir:.`, so the shipped layers are absent (lameenc missing) | D6 | P3 | S | A | new | file |
| 16 | Squash titles never checked against Conventional Commits; `CONTRIBUTING.md:17` says "mechanical" | D7 | P3 | S | B | persisting D7-2; extends #1663 | file |
| 17 | Ledger row 40 and the ADR-148 body say two required checks; live has three | D7 | P3 | S | B | new | file |
| 18 | `stats_core.py` has no property test and no pure-calculator registry | D8 | P2 | M | B | persisting D8-1 | file |
| 19 | No maintainer doc mentions the Hypothesis tier; TESTING.md says "~3 sec" and "~2.5 min" | D8 | P3 | S | B | persisting D8-2/3 | file |
| 20 | `PROPORTIONALITY.md:161` credits the weekly workflow with gating every push | D9 | P3 | S | A | persisting D9-1 | file |
| 21 | Tombstone gate green over `mcp/utils.py:12` (superseded ADR-027) | D10 | P3 | S | A | persisting D10-1 | file |

**Driver observations** (found by the driver, not the panel; not counted in the pass rate):
- **D1 · `craft.md:30` contradicts the spine.** It says "**Model-agnostic.** Nothing here pins a
  model … every row agent inherits it", while `SKILL.md` Phase 1 says "Panelists run on Sonnet
  (#4773)". The Principal panelist graded tier statements consistent without seeing this.
  Disposition: fold into #4773 as a one-line rubric edit.
- **D2 · No sealed `craft` record in `ANCHORS.json`.** Disposition: would-file, to seal the D1–D10
  A cells at the next freeze.

**B-class items, filed or declined (#3603).** Rows 3, 5, 11, 14, 16, 17, 18 and 19 are B-class and
would all be filed. None is declined. Row 3 rides on the open #4270 rather than opening a new issue.

**Not upheld, and why:**
- **eng1-1, weak.** The archive is ADR-059 policy. The residue is a standards contradiction, below.
- **eng1-4.** `ledgers/` and `qa/` are classed load-bearing, so the README rule does not apply.
- **senior-3.** Stamps are gated by `check_doc_index.py`. Side note: the 2026-05-19 stamps reach
  the 180-day hard limit on **2026-11-15** and will red Docs CI then.
- **STAFF-3.** Duplicate of #4270.
- **STAFF-4, weak.** The flat `deploy/` is a grading observation; no standard is broken.
- **principal-3.** The unproven-gate pile is the #3329 down-only ratchet.
- **CIO-1.** Duplicate of STAFF-6, and its `contents: write` aggravator is false.
- **CIO-3.** "Zero third-party" appears only in the 08-27 snapshot.

**Corrections verification made to upheld findings:**
- **eng1-2:** a fourth one-arg call at `:281`.
- **STAFF-1:** P2 → P3.
- **STAFF-2:** the real escape is `qa/`, not `remediation/`.
- **STAFF-5:** extends #1655.
- **principal-2:** the flags-off half is a documented posture.
- **principal-4:** the grounding-wiring half is historical narrative, not a census.
- **senior-1:** the copies' bodies drift.
- **EM-3:** the hook never sees squash titles.
- **EM-4:** `DECISIONS.md:4665` is accurate history.

## What is already A

- **The biggest 08-27 finding was fixed by machinery, not prose.** The live ruleset is declared in
  the posture file, verified by the sentinel, and `--check` is clean.
- **Module-size debt fell 37%** (42,701 → 27,021 baselined logical lines) with no baseline raised.
  The earned-headroom rule works.
- **The AI-surface registry is AST-derived and asserted in both directions** (35 = 35). There is a
  single Bedrock chokepoint, and no `bedrock-runtime` client exists anywhere else.
- **LLM JSON parsing went from five copies to one door** (`structured_json.py`).
- **The supply chain is sound:**
  - two blocking gitleaks lanes plus push protection;
  - `pip-audit` blocking on a zero-entry allowlist;
  - a fail-loud SBOM step with its own regression test;
  - 27/27 workflows declare `permissions:`;
  - OIDC only;
  - 0 open alerts.
- **A class-level family of wall-clock time-bomb guards** (extended again in #4848).

**Confirmed-correct deliberate postures.** These were refuted as findings and are graded as
chosen, not faulted:
- 140-column lines
- Secrets Manager only, no `.env`
- CodeQL advisory (ADR-148)
- reusable lint and test workflows
- a coverage floor above target under an up-only ratchet
- the gate-census down-only ratchet (#3329)
- `deploy/archive` (ADR-059)
- `Verified:` freshness gated by `check_doc_index.py`

## Process verdict: which layer should have caught each class

- **Prose stating a count or list the tree contradicts** (rows 1, 2, 8, 10, 17, 20). The
  doc-sync and reconcile machinery derives literals only where a generator exists. Each row names
  the guard that turns its prose into an assertion. This is the same B-class remedy as 08-27, and
  the class has not been closed.
- **Instruments scoped narrower than the standard that cites them** (rows 3, 4, 12, 15).
  `/new-machinery`'s derivation-guard check should ask what set the instrument enumerates, and
  whether that is the set the standard names.
- **The review machinery itself** (driver observations). The rubric and the spine disagree on model
  tier, and the craft lens has no sealed record. Both are #4773- and #3607-shaped.

## Standards-doc sync

The rubric asks that implied rules land in `docs/ENGINEERING_STANDARDS.md` in the same PR. **No
edit is made here, because both implied rules need an owner direction first:**
1. **Archives.** §1 "Never commit a manual `archive/`" contradicts ADR-059 and the deploy/README
   Archive Policy (#4258). Pick one and supersede the other.
2. **Function length** (row 5). It is a proposed new D2/D3 observable, not yet a rule, and per the
   spine it lands between runs, by PR.

## Coverage boundary

- The test suite was **not** run. Only targeted files were: the coverage ratchet and grounding
  wiring.
- Not examined:
  - site JS as code
  - CDK factoring
  - IAM and OIDC trust scope (#4257)
  - the scheduled `pip_audit_lambda`'s last run
  - git history for old secrets
  - Hypothesis strategy quality
- The Senior panelist sampled 12 of ~690 Python files cold. The Eng I panelist checked command
  contracts statically.
- Deploy integrity, product correctness and SDLC process are out of scope; defer to fullreview
  2026-09-05 and sdlc 2026-07-18.
- The panel's raw outputs and the verifier verdicts are summarized here and in the grades JSON. The
  scratch transcripts are not committed.
