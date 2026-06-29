# HANDOVER — Self-Sustainability (SS) A-tier: built, deployed, verified — 2026-06-29

The highest-leverage slice of the 6-month "hands-off" foresight backlog. **Five SS items built, tested, and deployed live** (Matthew authorized all deploys), plus a real **squash-merge drift bug caught and reconciled** along the way.

**3 PRs:** **#266 (SS-03) MERGED** · **#267 (SS-02/04/05/06 + SS-01 reconcile) open + `CLEAN`/mergeable** · **#268 (docs reconcile + this wrap) open**.

---

## 1. What shipped (all deployed live, verified)

| Item | What | Deploy | PR |
|---|---|---|---|
| **SS-03** | `budget-tier-hardstop` alarm (`BudgetTier≥3` → URGENT: all Bedrock off, daily brief data-only) | `LifePlatformMonitoring` ✅ | **#266 merged** |
| **SS-06** | Write-time `PredictionGradableShare` metric (leading indicator of extraction drift) | `LifePlatformCompute` ✅ | #267 |
| **SS-05** | `check_experiment_continuity` Sentinel invariant + the *runs-continuously* decision | `LifePlatformOperational` ✅ | #267 |
| **SS-02** | Podcast soft-HOLD aging escape (auto-retry quality holds; safety stays human) | `LifePlatformEmail` ✅ | #267 |
| **SS-04** | Dependabot safe-auto-merge (validate + self-gated automerge, dev-tooling only) | — (merge-activated) | #267 |

**Verified-down discipline (it paid off twice):**
- **SS-03:** 4 of 5 proposed monitors already existed (Garmin → `ingest-liveness-unhealthy`; podcast-HOLD → `panelcast-no-episode-7d`; budget≥2 → the existing `budget-tier-escalation` digest). Built only the genuine gap (tier-3 *urgent*). token-expiry-7d deferred (noisy); Dependabot-PR-age → SS-04.
- **SS-06:** the C-3 fix already killed the `machine`/threshold=None spec — the residual gap was *visibility*, not the spec, so the deliverable is a metric, not a rewrite.

**Key design calls:**
- **SS-02 safety:** holds carry `hold_class` (default `safety`, fail-closed). The sweep RE-GENERATES a *quality* hold through every gate (incl. the hard safety gate) and publishes only if a fresh attempt clears the bar — it never ships the flagged draft as-is. **Sensitivity/compassion holds are SAFETY (human-only)** — a deliberate override of the foresight note that lumped them as "soft".
- **SS-05 decision:** the experiment **runs continuously**; a reset is a manual `restart_pipeline.py` act. The invariant flags only a counter that *disagrees with genesis* (the stale-pre-reset leak), not unbounded growth.
- **SS-04 safety:** the repo's full CI/CD only runs on push-to-main and Dependabot PRs get a read-only token, so the workflow is **self-gated on a `workflow_run` success** (no `allow_auto_merge`/branch-protection dependency) and does **no PR-code execution under a write token**. Inert/safe until a dev-tooling PR appears.

New tests: `test_budget_tier_alarms` · `test_prediction_gradability` (gradability metric) · `test_panelcast_hold_aging` · `test_coherence_invariants` (experiment-continuity) · the recovered `test_chronicle_autopublish`.

## 2. ⚠️ The squash-drift bug (caught by `cdk diff`)

Deploying SS-02 surfaced that **SS-01 (the chronicle auto-publish, shipped + deployed live LAST session) was never on `main`** — #265's squash dropped the entire changeset (sweep lambda + the `ChronicleApproveSchedule` EventBridge rule + autopublish env + `dynamodb:Query` IAM). A naive `cdk deploy LifePlatformEmail` from a main-based branch would have **destroyed the live schedule and reverted the sweep lambda** — a silent regression of a working feature.

**Caught only by reading the `cdk diff`:** `[-] AWS::Events::Rule ChronicleApproveSchedule … destroy`.

**Reconciled:** recovered the live SS-01 source from `feat/serial-reader` (12 commits ahead of main; verified as a clean SS-01-only delta), folded it into #267 so the Email deploy **preserved SS-01 while adding SS-02**. Post-deploy verified live: `ChronicleApproveSchedule` + `CHRONICLE_AUTOPUBLISH_HOURS=48` intact, `PanelHoldSweep` rule live, sweep dry-run returns `swept:[]`.

**Durable reflexes (memory `feedback_squash_merge_drops_unpushed_commits`, updated):**
1. **`cdk diff` before EVERY deploy and READ it** — a `destroy`/`[-]` of a resource you didn't touch means main is behind live.
2. **Never trust "main == live"** after a squash-heavy session; check the dangerous part: `git diff --stat origin/main..<live-branch> -- lambdas/ cdk/`.
3. The full live state often lives on an unmerged branch — one squash PR captures only part of it.

## 3. ⚠️ OUTSTANDING — next session

### Merges (Matthew — his boundary)
- **#267** — SS-02/04/05/06 + the SS-01 reconciliation. All its code is already deployed live; merging makes `main == live` for SS-01.
- **#268** — this session's wrap docs + last session's docs that the #265 squash also dropped (CLAUDE/CHANGELOG/handover). Pure docs, additive, disjoint from #267.
- After both: `main == live`, closing the recurring squash-drift. (The rest of `feat/serial-reader` — site/docs already live — can be retired once #268 lands its history.)

### Backlog (each its own session)
- **SS tail (B/C, lower priority):** SS-08 monthly "what changed" · SS-09 podcast format rotation · SS-11 editorial-image guard.
- **Backend serial phases:** the coach-opinion engine (a stance that evolves beyond the weight-ladder) + the coaches-review-the-site loop (feed `challenges`/`habits`/`experiments` into `coach_narrative_orchestrator`); Elena-written "previously on" recaps; arbitrary historical-window APIs (`/api/character?date=` already time-travels — extend to data/waveform).

## 4. Deploys done this session (Matthew authorized "you proceed")
`LifePlatformCompute` (SS-06), `LifePlatformOperational` (SS-05), `LifePlatformEmail` (SS-02 + SS-01 preserved), `LifePlatformMonitoring` (SS-03, from the #266 branch). Every `cdk diff` confirmed non-destructive (or, for Email, made non-destructive via the SS-01 reconciliation) before deploying. SS-04 = no deploy.
