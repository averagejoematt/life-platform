# HANDOVER — Documentation accuracy pass + generalized drift guardrails + local-file sunset — 2026-07-13

> Instruction thread: Matthew relayed a ChatGPT repo assessment — "documentation volume
> beginning to exceed documentation truth" — with 4 concrete drift examples (README 64
> vs ARCHITECTURE 127 MCP tools; repo desc $75 vs current $85/$100; bedrock_client.py
> still says "shared layer" though retired; TESTING 1,217 vs ~3,000 tests) and the meta-
> point: *the repo is better at expressing drift governance than achieving it.* Ask:
> "right-size all documentation, ensure accuracy, and build guardrails from drift."
> Plus two riders: (2) sunset local-only laptop files in favor of git; (3) a 5th finding
> about public infra-identifier disclosure. Mid-session Matthew noted the **repo is now
> PRIVATE** (was public) and "a lot more merges/deploys since," so I re-verified ground
> truth before touching anything.

## What shipped — PR #1189 (OPEN, 4 commits, awaiting Matthew's merge)

Branch `docs/accuracy-and-drift-guardrails`. Full offline suite **5106 passed / 0 fail**;
all six doc gates green; both new gates proven to catch planted drift.

**Phase 1 — Accuracy (commit aba73513).** Every confirmed drift fixed against ground truth:
- `ARCHITECTURE.md:227` `**Tools:** 127`→64 (self-contradicted line 5's ruled 64 — the
  phrasing had no sync rule); `Modules: 26`→34. `DEPENDENCY_GRAPH.md:228` 127→64.
- `TESTING.md` `1,217`→3,646 (now marked sync-managed). Published essay (`.md` + live HTML
  `site/journal/essays/org-chart-of-one/`): `8 CDK stacks`→9, `~140 API tools`→~64, `$75`→$85.
- **35 shared-layer docstrings** across `lambdas/`+`mcp/` reworded to "bundled per-function"
  (via an auditable one-shot migration script; files that correctly say "NOT the shared
  layer" left alone). `SCHEMA.md`/`PHASE_TAXONOMY.md` `(shared layer)` parentheticals.
- GitHub repo description `$75`→$85 (via `gh repo edit`). **`BACKLOG.md` $75 left intact by
  design** — loudly-frozen historical archive; the ceiling really was $75 then.

**Phase 2 — Generalized guardrails (commit 8952ec01) — the structural deliverable:**
- **`scripts/check_doc_facts.py` (NEW)** — generalized stale-number gate. Imports
  `sync_doc_metadata`'s discoverers (one source of truth) and fails on a stale count/budget
  in ANY phrasing, not just pre-registered regexes. Precision-first: forward-only patterns,
  a letter/digit glue-guard (kills `python3 tests/`==「3 tests」), `lambda_count`
  deliberately UNPOLICED (subset counts irreducibly ambiguous), ledger + historical-line +
  `<!-- drift-ok -->` exemptions. **First run found a real stale "~125 MCP tools" in
  RUNBOOK_REENTRY** (fixed).
- **`check_doc_tombstones.py` now scans `lambdas/`+`mcp/`** with one broad
  `shared (?:Lambda )?layer` rule replacing 3 narrow ones that missed the dominant "part of
  the shared Lambda layer" phrasing entirely. Exempt-line regex broadened. Proven
  non-vacuous by a new test.
- **`sync_doc_metadata.py`**: `test_count` wired into discovery + 2 new RULES (ARCHITECTURE
  `**Tools:**/Modules:`, TESTING.md). Both gates wired into docs-ci.yml + ci-cd.yml;
  documented in `CONVENTIONS.md` §8; `test_wiki_checkers.py` +2 tests.

**Phase 3 — Right-size (commit 8bdc46da).** Untracked `docs/restart/_*.txt`/`_*.log` — 22
generated run-reports (~1 MB, incl. 450 KB grep dumps) regenerated every reset run.
Gitignored like `deploy/qa_report/`. Deferred (cosmetic, gate-exempt): archiving the 7
`REVIEW_BUNDLE_*` snapshots.

**Phase 4 — Local-file sunset (commit 0eb9d0bc).** Local-state audit: almost everything
laptop-only already has a git/S3 home. `.config.json` (only uncovered credential) is
regenerable from `life-platform/mcp-api-key` → documented `NEW_MACHINE_BOOTSTRAP` §3b;
Full Disk Access grant (unblocks #1026 datadrops leg + ingest watcher) → §3c. Reconciled
stale "#1026 not landed" across DR docs (it LANDED, commit 48f635e3; memory leg live daily)
and fixed a wrong datadrops S3 restore path (`uploads/…` 30-day-expires → top-level
`datadrops-archive/`).

## Gotchas hit
- **The whole point, live:** `sync --check` passed GREEN while ARCHITECTURE contained both
  64 (ruled) and 127 (un-ruled) — the cleanest proof that per-phrasing regexes miss.
- **Fact-scanner precision is everything:** first pass = 34 hits, ~32 false positives
  (`python3 tests/`, subset Lambda counts, "24h", reverse-pattern number grabs). Tightened
  to forward-only + glue-guard + dropped lambda_count → 2 hits, both real (1 stale claim, 1
  budget FP fixed by requiring ceiling-word adjacency). A false-positive gate gets disabled.
- **Vacuous-scan trap:** planted "part of the shared Lambda layer" did NOT fire until I
  added the broad rule — the dominant phrasing matched NONE of the 3 narrow rules. Always
  prove a new gate catches a planted violation.
- Adding the 2 new tests bumped `def test_` 3644→3646, re-drifting the sync literal — had
  to `--apply` again (correct: the number is now auto-managed).
- My Phase-1 comment rewords touched compute lambdas → `check_doc_index --strict` engine-doc
  drift; bumped HYPOTHESIS/READINESS/SCORING Verified dates (comment-only, formulas unchanged).
- Interactive-shell for-loop reported spurious exit-2 on the DECISIONS-parsing gates;
  direct runs + pytest confirm exit 0. Not a real failure.

## 5th finding (infra disclosure) — no action, mooted
Repo went private 2026-07-13. Disclosure sweep found **zero credential VALUES** in-repo
(R22 redaction verified clean). Aggregate recon surface (account ID, bucket, dist IDs) is
load-bearing in CI/CDK and defensibly accept-as-documented-risk. Only residual (auth on
public Function URLs) already covered by R22 hardening.

**Build beat:** none — PR #1189 is open, merge + any deploy await Matthew ("I run deploys/merges").
**Docs:** updated in-PR (ARCHITECTURE, TESTING, DEPENDENCY_GRAPH, SCHEMA, PHASE_TAXONOMY,
RUNBOOK_REENTRY, CONVENTIONS §8, NEW_MACHINE_BOOTSTRAP, DISASTER_RECOVERY, engines/{HYPOTHESIS,
READINESS,SCORING}, content essay); all Verified dates bumped; wiki checkers green at the
branch HEAD. No separate wrap-commit doc changes needed.

## Next picks / residual queue
- **Merge PR #1189** (Matthew) — 4 doc commits, no deploy needed (docs + gates + gitignore;
  site essay HTML change auto-deploys via site-deploy.yml on merge). Then the new gates go
  live on every push.
- Deferred in-PR (optional follow-up): archive the 7 `REVIEW_BUNDLE_*` snapshots (~20k lines,
  gate-exempt dir) + delete near-empty reviews/ stubs.
- Matthew's laptop actions (documented, not automatable): grant `/bin/bash` Full Disk Access
  (unblocks datadrops backup + ingest watcher); remove dead `may25-pivot.plist`.
- Standing from prior session: #1187 podcast music, #1114 portraits, #741 essay, #1148 +
  coach traits; `/fullreview` 17-lens relaunch after weekly reset (~07-18).

Full narrative of new gate machinery + ground-truth counts: memory
`project_doc_drift_guardrails_2026_07_13`. Prior session: `HANDOVER_2026-07-13_GreenMainPrereg.md`.
