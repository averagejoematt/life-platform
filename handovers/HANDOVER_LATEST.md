# HANDOVER — Backend serial phase 2: the coaches-review-the-site loop — 2026-06-29

Phase 2 of four backend serial phases. Coaches now **react to the challenges/experiments Matthew
has committed to on the site** instead of treating those protocol surfaces as separate from the
coaching. Built, deployed live (full layer dance), and verified end-to-end.

**2 PRs, both MERGED + DEPLOYED:** **#273** (the feature) · **#274** (the `SHARED_LAYER_VERSION`
91→92 hygiene bump). Matthew merged both and authorized "do all the deploys" this session.
**main == live, fleet uniform on layer v92, 0 open PRs, no drift.**

---

## 1. What shipped (all live, verified)

Phase 1 (the coach-opinion engine) made `coach_narrative_orchestrator._gather_all_state` the seam each
coach reads its evolving context from. **Phase 2 extends that same seam** — one new gather step.

- **`coach_narrative_orchestrator.py`** — new `_gather_site_protocols(coach_id)`:
  - Reads active **challenges** (clean `domain` field) + **experiments** (routed by `tags`), filtered
    per-coach via a deterministic `COACH_DOMAINS` map. `explorer_coach` (domains=None) sees all; an
    experiment whose tags match no domain falls through to explorer **only** — never mis-attributed,
    never silently dropped.
  - Reads go through `_query_begins_with` → **ADR-058 phase-filtered**, so the coach sees exactly the
    active set the site/MCP surface (`_apply_phase_filter`). Confirmed: challenge writes set **no**
    `phase` attr → active items pass `attribute_not_exists`; stale pre-genesis `pilot` candidates stay
    hidden.
  - **Fail-soft** (wrapped → returns `{}`; the daily run can't be aborted by this gather).
  - `_protocols_for_brief` trims/caps (≤5 per surface, drops nulls); surfaced in the planning message
    and **injected into the brief deterministically on every path** (success/fallback/default) — the
    exact seam `current_stance` uses.
- **`ai_calls.py`** — one ACTIVE PROTOCOLS instruction: acknowledge commitments BY NAME, **never invent**
  progress/streak/adherence numbers (ground in real data or say it's not visible yet); the N=1 /
  decision-class ceilings still apply.
- **`coach_history_summarizer.py`** (folded-in stance polish) — the stance no-numbers rule now explicitly
  covers **TARGETS and GAPS-TO-TARGET, even accurate ones** ("running short of the protein target", NOT
  "26% short of 190g"). Clears labs_coach's persistent `grounding_flag` while keeping the one-invariant
  guard (a stance is an opinion, never a readout). Takes effect on the next weekly summarizer run.

**Scope held tight (board recommendation):** challenges + experiments only. **Habits DEFERRED** — the
65-item registry is ongoing behavior whose adherence already reaches coaches via `domain_data`;
re-surfacing risks number-fabrication. No persisted protocol-read record (phase 3/4). No site-api /
read-path changes.

**Tests:** +10 in `tests/test_coach_stance_engine.py` (domain routing, active-only, tag routing,
explorer-catches-untagged, trim/cap, brief surfacing + deterministic injection, omit-when-empty,
fail-soft). **30/30 pass; ruff + black clean; 198 coach tests green** (creds-blanked per the CI lesson).

## 2. Deploy — the full layer dance (Matthew authorized "do all the deploys")

`ai_calls.py` is a **layer module**; the orchestrator + summarizer are standalone Compute assets. Sequence
(every `cdk diff` read first — layer re-point + benign shared-asset re-hash, **zero destroys, zero IAM**):

1. `bash deploy/build_layer.sh`
2. `cdk diff`+`deploy LifePlatformCore` → publishes **layer v92** (diff was ONLY the layer content hash).
3. Bump `SHARED_LAYER_VERSION` 91→92 in `cdk/stacks/constants.py` (→ #274).
4. **Redeploy ALL 5 consumer stacks** (Compute + Ingestion + Email + MCP + Operational) so the whole fleet
   attaches v92 — **fleet uniformity** is the gate (the v89 lesson: a mixed fleet trips the Plan
   layer-consistency check). Compute also carried the orchestrator + summarizer code.

The Operational site-api `Code` S3Key change was the **known-benign `Code.from_asset` re-hash**, not a
code revert: `lambdas/web/` matched origin/main exactly, so the CDK asset == live. (Reminder: the targeted
site-api deploy path is `deploy/deploy_site_api.sh`, but a `cdk deploy LifePlatformOperational` for a layer
bump is safe when web/ == main, as it was here.)

**Verified live:** fleet histogram **71/71 layer-attached functions on v92**; orchestrator + summarizer
fresh code on v92; **live smoke invoke** of `coach-narrative-orchestrator` → `200`, no error → the new
gather path runs clean against the real phase-filtered partitions, **correctly omits `site_protocols`**
(nothing active right now → the block surfaces the moment Matthew activates a challenge), and
`current_stance` intact (no phase-1 regression).

## 3. ⚠️ The reverse squash-drift trap (handled)

The `SHARED_LAYER_VERSION` bump HAD to land on main (#274) or a future `cdk deploy` from main would
revert the fleet to `:91`. Main was one constant behind live until #274 merged. Now reconciled —
main == live for both code (#273) and layer version (#274).

## 4. ⚠️ OUTSTANDING — next sessions

- **Backend serial phases 3–4 (each its own session + deploys):** Elena-written "previously on" recaps;
  arbitrary historical-window APIs (`/api/character?date=` already time-travels — extend to data/waveform);
  data→chronicle cross-links. All extend the same `_gather_all_state` hook.
- **SS tail (B/C):** SS-08 monthly "what changed" · SS-09 podcast format rotation · SS-11 editorial-image
  guard.
- **Watch:** labs_coach `grounding_flag` across the next few weekly summarizer runs — the prompt fix
  should clear it; if it persists, tighten further (don't chase stochastic output, but a persistent flag
  is signal). The summarizer still caps OUTPUT# at 20 but NOT threads/predictions (52/39) — a longer-term
  input-bound follow-up.
- **To see it work:** activate a challenge (MCP `activate_challenge`) → the relevant coach reacts to it
  by name on the next daily run; `jq '.generation_brief.site_protocols'` on an orchestrator invoke
  confirms.
