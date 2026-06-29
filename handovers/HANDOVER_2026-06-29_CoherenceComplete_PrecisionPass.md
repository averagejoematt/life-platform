# HANDOVER — Coherence Program COMPLETE + content-bug fix + precision pass + asset-completeness guard — 2026-06-29

**One long session.** The 4-phase Self-Management & Coherence Program is fully shipped, deployed, and live-validated; a real served-content bug it caught is fixed with a self-correcting backstop; the Sentinel's signal was tuned for precision and made honest; and the CDK asset glitch that silently broke the Sentinel is now caught by a postflight guard. **9 PRs merged (#250–258), all deploys done (Matthew authorized "you do all deploys this session"). main green, 0 open PRs, postflight fully green ("fleet consistent").**

---

## 1. Phase 4 — self-healing gets eyes on content (#250/#251/#252)
The remediation agent could only triage infra (alarms, CI, DLQ). It now also sees the "alive but not right" class.
- **#250** — Coherence Sentinel persists its findings to `s3://matthew-life-platform/coherence-log/{latest,<date>}.json` (the durable "WHAT failed"; the `coherence-overall` alarm only carries "OverallAlarm>=1") + grounds on `canonical_facts.build_canonical_facts` (closes the grounding↔detection loop). New scoped IAM `s3:PutObject` on `coherence-log/*`.
- **#251** — `agent.py::_coherence_findings()` reads the artifact as a `coherence` signal (no new IAM); `docs/REMEDIATION_TAXONOMY.md` "Content & coherence signals" section routes every invariant to **Bucket B/C only, NEVER auto-merge**; content/AI surfaces on the hard denylist; **a test asserts the auto-merge ALLOWLIST has no content path** (the safety invariant). Agent runs from the repo → merge = live.
- **#252** — fix: `build_record.status` mirrored `_emit_overall`, so a semantic-only incoherence read alarm too (else the agent's status filter drops it = alarm-with-no-detail). *(Later superseded — see §3.)*

## 2. The content-bug investigation + self-correcting backstop (#254)
The Sentinel's first live run caught a real served bug: coaches stating **RHR 53 vs the canonical 64** (Whoop's 7-day RHR is 55–64; 53 appears nowhere — a correlated hallucination across coaches). Root cause: the Phase-3 grounding backstop only LOGGED, and the layer validator missed it (its RHR regex needs "resting heart rate"/"resting HR", not the "RHR" abbreviation; 25% tolerance lets a 17% miss through).
- **Fix (self-contained in `ai_expert_analyzer`, no layer dance):** `_hard_canonical_contradictions(text, facts)` detects RHR/recovery/HRV contradictions; the grounding backstop now **self-corrects** — regenerates the narrative ONCE on a hard contradiction, keeps it only if contradictions drop. **Proven working** (logs: training recovery-73→fixed, glucose, sleep auto-corrected) + a no-invent-trends prompt rule.

## 3. Precision pass + honest alarm (#255/#256/#257)
Once the Sentinel was reliably catching things, the next risk was a noisy alarm (a noisy alarm gets ignored).
- **#255** — (a) Sentinel `facts_agreement` flags a metric only if a wrong value is cited AND the canonical value is cited NOWHERE (`_mentions_value`) — kills the historical/trend false-fire. (b) email-subscriber CDK timeout 15s→30s to match live (no deploy; postflight config-drift now green). (c) coach-grounding pass: the detector adopts the same grounded-anywhere logic + the format prompt no longer says "lead with the number" unconditionally.
- **#256** — tightened the Haiku semantic prompt to ignore omissions / <25% variance / total-vs-rate framing.
- **#257 (the capstone)** — **`coherence-overall` now fires on the DETERMINISTIC invariant verdict ONLY.** The Haiku semantic pass proved too unreliable to gate a daily-emailing alarm (it lists items it concludes are *fine* in `issues` and returns `coherent:false`), so it's **advisory** (kept in the digest + `semantic_incoherent` flag for a human/agent, doesn't trip the alarm). Result: the Sentinel reports **OVERALL OK** (deterministic green); the CloudWatch alarm self-clears within ~24h (Maximum-over-1-day window).

## 4. Postflight asset-completeness guard (#258)
While verifying, the new check found the Sentinel **broken again** (CodeSize 7339 = 2 entries, no root modules → ImportModuleError, but invoke still returns 200). The CDK asset glitch is **REPRODUCIBLE**: CDK skips re-uploading an asset whose hash-key already exists in S3, so a corrupt `<hash>.zip` poisons every lambda on that hash, and `cdk deploy --force` won't fix it. Fixed live by pushing the correct `b6ec` asset via `aws lambda update-function-code`. Added `session_postflight.check_asset_completeness()` (download each bundled-asset canary's zip, assert imported root modules present; fail-soft). See memory `reference_cdk_asset_staging_glitch`.

---

## State of `main` + production
- 9 PRs merged (#250–258). main green. Sentinel healthy (CodeSize ~1.2 MB, runs clean, status OK). Postflight: **layer uniformity ✓ · asset completeness ✓ · config drift ✓ — fleet consistent.**
- `coherence-overall` CloudWatch alarm may read ALARM for up to ~24h after the §3 change (digest-alarm Maximum-over-1-day window ages out the old 1.0 datapoints); the metric is emitting 0.

## Open follow-ups (small / deliberate-later)
1. **Coach fabrication is a quality frontier, not solved-to-zero.** Egregious cases now self-correct + trip a precise deterministic alarm; soft Haiku noise is advisory. Pushing further is an iterative prompt-engineering effort — its own focused session.
2. **`ai_calls.py` nutrition guardrail** rides the next layer rebuild (merged, low urgency).
3. **CI Deploy gate** sits pending (intentional manual gate; this session's deploys went direct).
4. **Optional:** wire `session_postflight` (incl. the new asset check) into CI; a monthly deep semantic-audit `Workflow` (needs opt-in).

## Deploy-hygiene lesson (important)
The CDK asset glitch can silently ship a Lambda zip missing root modules. **A 200 invoke is NOT proof** — check for `body` in the response (a broken import returns 200 + `errorMessage`) or verify CodeSize. When in doubt, `rm -rf cdk/cdk.out`, and if a stack reports "(no changes)" but the live code is wrong, overwrite the S3 asset object (a re-publish from another stack on the same hash works) then `aws lambda update-function-code`. The postflight guard now automates detection.

## Memories updated
`reference_cdk_asset_staging_glitch` (the full reproducible mechanism), the Self-Management & Coherence Program pointer in `MEMORY.md` (Phases 1–4 + precision pass + the design decision that deterministic drives the alarm).
