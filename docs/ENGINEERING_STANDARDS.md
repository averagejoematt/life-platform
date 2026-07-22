# Engineering Standards — the "definition of an A" for this codebase

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-21

> **What this is.** The single, durable source for *how code and the repo should look and hold
> together* here — the craft an outside engineer judges cold. It is both the **standard new
> code must meet** and the **rubric `/craft-review` grades against** (the two share this one
> file so they can never drift). It is scoped to **craft**: cleanliness, structure, naming,
> aesthetics, trustworthy gates, and standards conformance. It deliberately does **not** cover
> deploy integrity, product correctness, or the SDLC process — those live in `docs/CONVENTIONS.md`,
> `docs/DECISIONS.md`, and are graded by `/fullreview` and `/sdlc-review`.
>
> **Posture, not perfectionism (ADR-103).** One person runs this platform. A loose setting that
> is *documented as a chosen posture* (an ADR that defends it) is an **A**, not a defect. The
> defect is the *undocumented* loose setting. Every standard below has an escape hatch; using it
> means writing down why.

---

## The craft rubric — 10 dimensions, A / C / F anchors

`/craft-review` grades each dimension A–F against these anchors. Grades are "A *for a solo
public platform's stated postures*," not "A for a 50-engineer org."

| # | Dimension | **A** (an outside panel nods) | **C** (works, but a skeptic frowns) | **F** (a reviewer stops reading) |
|---|-----------|-------------------------------|--------------------------------------|-----------------------------------|
| **D1** | **First impression / repo cleanliness** | Root is load-bearing dirs only; every tracked dir earns its place; no committed archives, process exhaust, or throwaway artifacts | A few stray dirs; some tracked junk; tree needs the README to be legible | Committed dead-code archives, spike PNGs, session transcripts, backups; the root reads as a working directory |
| **D2** | **Structure & module hygiene** | Packaging finished; no source file over the size ceiling without a documented reason; boundaries are obvious | Half-done packaging (subpackages + a flat pile); one or two god-modules | A flat pile of modules; multiple 2–3k-line files; no discernible structure |
| **D3** | **Naming & code aesthetics** | Idiomatic, consistent, self-explaining names; earned abstractions; a stranger reads a random file and nods | Mostly consistent; some cryptic or inconsistent names; occasional cleverness tax | Inconsistent conventions; misleading names; abstraction for its own sake |
| **D4** | **Trustworthy gates** | A skeptic believes lint/type/coverage mean something: real mypy, no blanket waivers, a credible coverage floor | Gates pass but are visibly loose (broad `disable_error_code`, per-dir suppressions) — or loose-but-documented | Gates are decorative — everything substantive silenced; green means nothing |
| **D5** | **CI/CD maintainability** | Pipelines are DRY: shared setup in composite actions, thin reusable workflows; no mega-file | Duplicated setup across workflows; one large workflow file | A single multi-thousand-line workflow + N near-duplicate copies |
| **D6** | **Supply-chain & security posture** | Secret-scan + SAST + CVE gate + SBOM present; the security-relevant gates block or ratchet | Some scanning, mostly advisory/non-blocking; no SBOM | No secret-scanning, no SAST, no CVE gate — or all `continue-on-error` |
| **D7** | **Team-readiness signals** | `main` protected (posture documented), real ownership routing, a contribution path that works | Trivial CODEOWNERS; conventions cultural not mechanical; protection undocumented | No branch protection, no ownership, no contribution path, no explanation |
| **D8** | **Testing depth** | Beyond example-based: property-based on pure calculators + honesty gates; a documented coverage ratchet | Example-based only, but well-structured and non-brittle | Sparse or brittle tests; coverage floor is a fig leaf |
| **D9** | **AI-era engineering & proportionality** | Every AI surface has a deterministic gate + an eval; AI code meets the human bar; the complexity/keep-retire ledger is legible | Strong AI guardrails but surface size unexplained | AI output ungated/unevaluated; sprawling machinery with no rent story |
| **D10** | **Docs & decision hygiene** | Living, self-critical, non-aspirational; anti-drift machinery; the active set is easy to see | Large surface, some staleness, no drift machinery | Aspirational docs stating intended state as fact; rotting wiki |

---

## The standards (what new code must meet)

### 1. Repo cleanliness (D1)
- **The tree self-documents.** A newcomer reading `ls` at the root can tell load-bearing dirs
  from support dirs without opening the README. Target **≤ ~10 top-level dirs** that carry
  first-party code/config; anything else earns a one-line README explaining why it's kept.
- **Git is the archive.** Never commit a manual `archive/` of superseded code, one-shot
  migration scripts that already ran, throwaway spikes, before/after render PNGs, or personal
  workstation tooling. If you need old state, it's in history (`git show <sha>:path`).
- **Process exhaust stays out of the product tree.** Session handovers, RCA scratch, and review
  churn are engineering-log, not product — keep only the live pointer in-tree.
- Enforced by the **root-clutter ratchet guard** (below).

### 2. Structure & module size (D2)
- **Finish the packaging.** New modules go into the domain subpackage they belong to
  (`lambdas/<domain>/`), not the flat root. Shared helpers go to a single `common/` (or `core/`),
  not the root pile.
- **Module-size ceiling: ~800 lines.** A source file over ~800 lines is a smell; over ~1,200 is
  a finding. Split into cohesive helper modules behind the same public entrypoint (no contract
  change). **Escape hatch:** a generated file, or a registry/dispatch table where splitting hurts
  legibility, may exceed the ceiling *if it carries a top-of-file comment naming the exception* —
  which registers it with the module-size guard.
- Enforced by the **module-size ratchet guard** (below).

### 3. Naming & aesthetics (D3)
- **Python:** `snake_case` modules/functions/vars, `PascalCase` classes, `UPPER_SNAKE` constants.
  Module names say what's inside (`adherence_calc.py`, not `utils2.py`). Test files mirror the
  module under test (`test_<module>.py`); test functions read as sentences (`test_<subject>_<condition>`).
- **JS/ES modules:** `camelCase` functions/vars, `PascalCase` components/classes, file names in
  the site's existing convention.
- **Earned abstraction, no cleverness tax.** Prefer the obvious implementation a stranger reads
  in one pass over the clever one that saves three lines. An abstraction earns its place when it
  removes real duplication or names a real concept — not preemptively.
- **Match the neighbours.** New code reads like the file around it: same comment density, same
  naming idiom, same structure. Consistency beats personal preference.

### 4. Trustworthy gates (D4)
- **Types mean something.** The target end-state is mypy strict-clean across `lambdas/`, `mcp/`,
  `web/` with an **empty global `disable_error_code`** list; the clean-module test
  (`tests/test_mypy_clean_modules.py`) covers the whole first-party surface. New code is written
  type-clean; it does not add to a disable list.
- **No blanket waivers.** No directory-wide lint suppression (`ruff "<dir>/*" = [...]`) and no
  whole-dir `.flake8` excludes. A genuine registration/import pattern uses a **per-line `# noqa:<code>`
  with a reason**, at the specific site.
- **Line length** is 140 by deliberate posture — that choice is documented in `.flake8`; don't
  relitigate it, and don't loosen further.
- **Coverage** floor is a real, enforced number (target **70%**) and moves **up only** — never
  regresses (the up-only guard below).

### 5. CI/CD as composition (D5)
- Shared setup (checkout + language setup + cloud auth) lives in **one composite action**, not
  copied per job/workflow. Each pipeline is a thin caller of **reusable workflows**. No
  multi-thousand-line workflow file; no N near-duplicate workflows. *Merge duplication into
  shared building blocks — never into a monolith.*

### 6. Supply-chain & security (D6)
- Secret-scanning (gitleaks/trufflehog) and dataflow SAST (CodeQL) run in CI; the dependency-CVE
  gate (`pip-audit`) **blocks or ratchets** (not `continue-on-error`); an **SBOM** is generated
  for the deploy artifact. Security-relevant gates are not advisory-only.

### 7. Team-readiness (D7)
- `main` carries branch protection; if the posture is intentionally light (a solo advisory lane),
  that scoping is written in an **ADR** — the point is the decision is *visible*, not that it
  matches a big-co default.
- Conventions that matter are **mechanical, not cultural**: a commit-message hook, a PR template,
  ownership routing — so they survive a second contributor.

### 8. Testing depth (D8)
- Pure calculators and the AI honesty/grounding gates carry **property-based tests** (Hypothesis
  `@given`), not just examples. Tests are structured (arrange/act/assert, intent docstring,
  stable ids), name their intent, and don't encode wall-clock/date time-bombs.

### 9. AI-era engineering (D9) — the 2026→2028 lens
- **Every AI-touched surface has a deterministic gate and an eval.** No LLM output reaches a
  reader without a deterministic grounding/honesty check (ADR-104/105) and a golden/canary eval
  that fails the build when the gate regresses. LLM-judge layers stay advisory; deterministic
  layers block.
- **AI-authored code meets the same bar as human code** — same naming, size, type, and test
  standards; a diff's provenance (human or agent) changes nothing about the standard it must meet.
- **Prompt/agent changes ship with their eval.** A change to a prompt, tool schema, or agent
  contract lands with the golden eval that guards it, in the same PR.
- **Proportionality is answered, not defended.** The complexity-posture ledger (ADR-103) is kept
  legible: per subsystem, what it costs vs. earns, and how it gets demoted/retired on a cadence
  (ADR-129 is the worked example — an AI agent demoted for earning zero merges). Machinery that
  can't state its rent is a finding.

### 10. Docs hygiene (D10)
- Docs state **current truth**, never intended state as fact (verify live at write time). Facts
  that drift are **generated, never hand-typed** (`docs/CONVENTIONS.md` meta-rule). ADRs mark
  superseded status so the active set is legible.

---

## Ratchet guards (how the grade can't erode)

These CI guards make regression *fail the build* rather than accumulate silently — the same
philosophy as the existing `reconcile` / doc-sync anti-drift machinery, extended to craft.
(Implemented under the Engineering-excellence epic; listed here as the standing contract.)

- **Root-clutter guard** — an allowlist of sanctioned top-level dirs; a new unlisted top-level
  dir fails CI until it's either removed or added to the allowlist with a reason (D1).
- **Module-size guard** — a new source file over the ceiling fails CI unless it's a generated
  file or carries a registered top-of-file exception comment (D2).
- **Coverage up-only guard** — `--cov-fail-under` may rise, never fall; a PR that lowers measured
  coverage below the floor fails (D4/D8).
- **mypy clean-set guard** — `tests/test_mypy_clean_modules.py` covers a set that only grows; a
  PR may not shrink it or add a global disable code (D4).

---

## How this doc is used

- **Writing code:** meet the standards above; use an escape hatch only by documenting why.
- **`/craft-review`:** grades the 10 dimensions against the anchors here and files gaps as
  backlog under the Engineering-excellence epic; any new rule the review implies is written back
  into this doc in the same PR (rubric and grader share this source).
- **Onboarding / showcase:** this doc is the honest statement of the bar the codebase holds
  itself to — a reviewer reading it sees the standard *and* the postures where we deliberately
  deviate.
