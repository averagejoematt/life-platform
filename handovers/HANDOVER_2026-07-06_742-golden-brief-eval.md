# HANDOVER — #742 golden-brief eval harness (falsifiable honesty layer) — 2026-07-06

> Instruction: "anything best tasked for opus" + "I authorize you to do all merges and
> deploys." Picked **#742** (R21 epic #720/E6) as the highest-reasoning, self-contained
> opus issue that hardens the platform's central honesty moat. Shipped end-to-end: code →
> PR #773 → squash-merged to `main` (`284ef440`) → CI GREEN → #742 closed. **No deploy
> needed** (pure test/CI infra; plan found nothing deployable). Single-threaded on `main`.

## What shipped — #742 / ADR-127

The platform sells "N checks, 0 flags" on every AI narrative surface, but all three
honesty controls (ADR-104 grounded-number gate, `grounding_guard` vital-contradiction,
ADR-108 quality gate) are **runtime** gates that fire during generation and discard their
work — nothing proved they catch anything. Worse, `grounding_guard` fails **open** on an
import error, so a "0 flags" report was indistinguishable from a silently-dead gate.
**"0 flags" was unfalsifiable.** This makes it falsifiable.

| File | What |
|------|------|
| `tests/golden_brief_eval.py` | The harness. Replays ~30 frozen `(coach_id, authoritative_facts, generation_brief, reference_output)` fixtures across all 8 coaches through the SAME deterministic gate (`grounded_generation.grounding_findings` + a deterministic anti-pattern check). Verdict = FAIL iff any golden output draws a finding (false positive), any of 5 canaries is missed, or a cross-coach distinctiveness pair trips. Advisory Haiku voice rubric (`--judge`) + `LifePlatform/GoldenBrief` metrics (`--emit`) + `ops_line()` — advisory, **never** gates (ADR-076, mirrors `ai_quality_canary_lambda`). |
| `tests/fixtures/golden_briefs/golden.json` | ~30 known-good outputs (4/4/4/4/4/4/3/3 across the 8 coaches). Every number traces to facts/brief or is benign. |
| `tests/fixtures/golden_briefs/canaries.json` | 5 seeded faults: fabricated HRV (evidence_ceiling), recovery 30% vs 64% (grounding_contradiction), invented weight (evidence_ceiling), fabricated glucose trend (evidence_ceiling), blacklisted phrases (anti_pattern). Span all 3 deterministic dimensions. |
| `tests/fixtures/golden_briefs/README.md` | Fixture schema + the authoring rules (the number-collision trap below). |
| `tests/test_golden_brief_eval.py` | 14 tests, **`deploy_critical` marker (ADR-117)** → a gate regression BLOCKS deploy. Includes the **self-referential guard**: asserts `grounding_guard` is importable AND a live synthetic contradiction fires (a dead gate can't report a false green). |
| `.github/workflows/golden-brief-eval.yml` | Weekly (Mon 15:17 UTC) drift check; deterministic + free by default. `--judge`/`--emit` is **manual workflow_dispatch only**. |
| `docs/DECISIONS.md` | ADR-127. |
| `lambdas/web/site_api_common.py` | doc-sync literals (`adrs 112→113`, `test_count 2410→2424`) — required for the `sync_doc_metadata.py --check` CI gate. |

## Verification

- `python3 tests/golden_brief_eval.py` → `✓ OK — 30 golden across 8/8 coaches (0 false
  flags), 5/5 canaries caught`. Each canary caught by exactly its expected check; max
  cross-coach Jaccard 0.195 (ceiling 0.55).
- `pytest tests/test_golden_brief_eval.py` → 14 passed. Full offline suite **3716 passed,
  0 failures**. black + ruff clean.
- **Main CI/CD run 28814515379 = success:** Lint ✓, **Deploy-critical tests ✓** (the
  golden-brief `deploy_critical` tests ran here and passed — the gate is live-gating on
  main), Unit Tests ✓, Plan ✓. Deploy / Smoke / Visual-QA **skipped** — the plan's
  change-detection found nothing deployable (the `site_api_common.py` doc-literal doesn't
  hit the CDK deploy path). So "all deploys authorized" needed no deploy action.

## Gotchas confirmed this session

- **Canary self-collision:** a canary's injected fake number must NOT appear in its own
  `authoritative_facts`/`generation_brief`, or it's grounded and the gate (correctly)
  ignores it. The weight canary first used `172 lb` while `protein_g_avg=172` was in
  facts → the fabrication slipped. Fixed to 174 (absent from all inputs).
- **flake8 does NOT lint `tests/`** (CI runs `flake8 lambdas/ mcp/` only) — but **black
  and ruff DO** (`black --check … tests/…`, `ruff check … tests/…`). So E203/E501 in a
  test file are moot; black+ruff clean is the real bar. Ran both before commit.
- **`deploy_critical` is the right home for an honesty gate** — the marker's own
  description names "a core honesty/safety contract the running system depends on."
- Deploy-from-main model: the full CI/CD pipeline runs on `push: main`, **not** on the PR
  branch (only a `validate` no-op check shows on the PR). Local full-suite green is the
  pre-merge signal; CI validates post-merge on main.

## Not done / open

- **Deferred cosmetic:** the live site shows the old adr/test counts until the next
  site-api deploy (the repo literals are now correct; not worth forcing a deploy).
- **ADR-127 follow-up:** wiring the weekly `--judge`/`--emit` to auto-run needs a
  dedicated least-privilege role (`bedrock:InvokeModel` haiku + `cloudwatch:PutMetricData`)
  — deliberately not bolted onto the broad deploy role (ADR-063 budget / least-privilege).
- Carried from the prior session: deploy held **Operational → v118** on the HAE reconcile
  (lands `coherence_semantic`'s tier-1 pause); watch `GenerationSkippedUnchanged` (#738).
- **Untouched opus backlog:** Attended (#755 DR restore, #750 site-CI deploy, #687 OIDC),
  gated (#746), large features (#734 audio, #409 batch-inference, #422, #421, #753, #395,
  #749, #475), #730 (scoped+deferred). Each a focused session.
- Optional #380 build beat for #742 — outward-facing content, Matthew's call (not done).
- Untracked `docs/reviews/R21_BACKLOG.md` left alone (pre-existing).
