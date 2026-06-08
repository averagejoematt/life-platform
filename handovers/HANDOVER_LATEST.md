# HANDOVER — 2026-06-07/08 (Product/Growth summit → PG front-door + Wedge-B build; reset still pending)

> A full-day PG burndown off the 2026-06-07 **Product + Personal summit** (ADR-078).
> Shipped six PG items live, merged a creative spike, and left two backend PRs
> queued for the operator. **The Monday 2026-06-08 experiment reset is still
> un-run** — it remains the headline pending action.

> 🔴 **READ FIRST — two operator actions, in this order:**
> 1. **Run the Monday 2026-06-08 reset** (still not executed — see "The reset" below). All
>    tooling is landed + dry-run-validated; the operator runs the `--apply`.
> 2. **After the reset**, merge + approve the two held backend PRs:
>    **#36 (PG-04 native-SES welcome)** and **#39 (PG-10 public-AI hardening)**. Both are
>    pure Lambda code, CI-deploy through the GitHub **production** gate; held off
>    deliberately so they don't ride the reset's Core/Compute/Email deploy.
> 3. Everything else is **committed + pushed**; `main == origin/main`; the only open PRs
>    are the two above. Production behavior is unchanged until the reset + those merges.

**Previous handover:** `handovers/HANDOVER_2026-06-07_PhaseTaxonomyResetStaged.md` (the reset's full design + ADR-077 taxonomy).

---

## The reset (still the headline — NOT yet run)

**One command** (after the morning Withings weigh-in syncs — auto-anchors the genesis weight):
```
# dry-run first, review surface:
python3 deploy/restart_pipeline.py --genesis 2026-06-08 --keep-chronicle DATE#2026-02-28
# then apply (operator runs this):
python3 deploy/restart_pipeline.py --genesis 2026-06-08 --keep-chronicle DATE#2026-02-28 --apply
```
Pre-flight: confirm `DATE#2026-06-08` exists in the withings partition (else `--override-weight-lbs`). Post-reset: `aws ssm put-parameter --name /life-platform/experiment-cycle --value 3 --overwrite`. Full design + June-8 dry-run validation (7,525 records archived, coach_thread leak covered, "Before the Numbers" kept) is in the previous handover. **PG-05 was built specifically for this** — the genesis-emptied Evidence pages now read as integrity, not breakage.

---

## PG session — what shipped (ADR-078 / summit `docs/reviews/SUMMIT_2026-06-07_PRODUCT_GROWTH_REVIEW.md`)

**Foundation:** committed the summit record + **ADR-078** (commercial wedge — Wedge **B build-in-public now** / A transformation-story accruing / C SaaS shelved) + 14 **PG-series** backlog items with the governing test (*more likely, or less likely, to reach 185?*) and the Reeves/Viktor **build cap** (document what exists; no new platform features).

### Live on averagejoematt.com (deployed + verified, smoke 65/0 · visual_qa 20/0)
- **PG-01** — hero "who it's for" line (everyman/Wedge-A framing). `index.html` + `story.css`.
- **PG-02** — cockpit first-run orientation card (dismissible, `localStorage ajm-cockpit-intro-v1`, non-modal). `cockpit.js` + `cockpit.css`.
- **PG-03** — per-dispatch subscribe foot (→ `/subscribe/`) + RSS (→ `/rss.xml`) + "start from the beginning" (earliest-by-date). `dispatches.js` + `story.css`.
- **PG-05** — genesis-aware Evidence empty-states (correlations/predictions/benchmarks). `evidence.js`.
- **PG-06** — Wedge-B **`/evidence/build/`** ("How it's built"): 6 build-in-public writeups (the board, interpret-only rule, budget governor, remediation agent, vision-QA), each citing the real ADR/module. New editorial topic in `v4_build_evidence.py`. **First sanctioned Wedge-B work; no new Lambda/inference.**

### Merged but NOT deployed
- **PG-14 spike** — `spikes/pg14_ai_me/` (a faceless, data-driven SVG body figure that morphs with the real weight 304→185) + `docs/specs/PG-14_ai_me_spike.md` (go/no-go). Lives outside `site/`, so it never deploys. **Rec: GO Tier A** as one contained artifact (productionize post-reset, anchored to new genesis); defer photoreal/video tiers (honesty/privacy/quality). Owner's call.

### Held for operator (post-reset) — both pure Lambda code, no IAM/CDK
- **PR #36 — PG-04** (native SES): the subscribe→confirm→welcome sequence already existed; fixed v4-migration staleness (welcome email linked legacy `/character//mind/` → v4 doors, dispatch-#1 first). **PG-04b follow-up logged:** the `subscriber-onboarding` role has no `s3:GetObject` grant, so the day-2 bridge's dynamic cards always fall back — needs an IAM/CDK change, deliberately deferred.
- **PR #39 — PG-10** (public-AI hardening): endpoints were already ~95% hardened (DDB rate limits, HTTP-200 paused-degrade before inference on both handlers, `max_tokens`+500-char caps, reserved concurrency=2); **verified + pinned with 7 guard tests** (`tests/test_ai_endpoint_hardening.py`) and added the last gap — `/api/ask` now enforces **correlative-only + confidence-labelled** output (Henning standard).

---

## ⚠️ Operator follow-ups
1. **Run the reset** (above); bump SSM `/life-platform/experiment-cycle` to 3 after.
2. **Post-reset: merge + approve #36 and #39** (production gate). A trivial one-line BACKLOG/CHANGELOG conflict between them is possible — keep both bullets.

## Deferred / not built (all genuinely gated)
- **PG-04b** — IAM grant + CDK for the bridge's real dispatch cards (post-reset).
- **PG-07** (reader predict-the-week) — needs PG-10 (done, in #39) **and** the D-05 prediction ledger producing verdicts (~Jun 17).
- **PG-13** (agent activity feed) — sources `ENSEMBLE#`/remediation data the reset re-curates; roster half is already covered by PG-06.
- **PG-14 productionization** — owner decision; post-reset.
- **PG-09** (methodology/SEO pages) — buildable but overlaps `/evidence/methodology/` + the new `/evidence/build/`; low marginal value.
- **PG-08** (one social channel) — content/process, not code. **PG-11/12** — hard-gated on ~30 lb progress + a sustained list.

**Verify quickly:** `bash deploy/smoke_test_site.sh` (65/0) · `python3 tests/visual_qa.py` (20/0) · `python3 -m pytest tests/test_ai_endpoint_hardening.py -q` (7/0, on #39's branch).
