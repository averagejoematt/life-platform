# Handover — 2026-08-23 (evening, Fable 5, mixed→autonomous): Phase D0 of the A-Grade Program — every P0 the diligence confirmed is now fixed, deployed, and verified live

**Session:** Fable 5. Drove: "Boot Phase D0 of the A-Grade Program" — the plan's
"P0 truth: privacy, trust, and the claims that lied" phase
(`~/.claude/plans/lively-juggling-candle.md`), MIXED mode: three owner decisions
surfaced first, then autonomous merge+deploy. Owner calls received up front:
**#3043 → S3 owner-prefix** (`config/coaching/`) · **#3044 → anonymize-at-unsubscribe
+ honest copy** · **#3045 → the FULL currently-served surface consented** (nothing
stripped). Previous handover archived as
`HANDOVER_2026-08-23_agrade-program-diligence.md` on `session-archive`.

## What shipped (all merged AND deployed, postflight sha-verified)

- **#3043 coaching containment (DIL-001/012, P0)** — PR #3052. 5 PRIVATE-marked docs
  uploaded to `s3://matthew-life-platform/config/coaching/` BEFORE the repo removal
  merged; **verified live: raw.githubusercontent 404 ×5, S3 objects ×5**. DATA_GOVERNANCE
  scope note tells the truth (repo PUBLIC since 07-20); the inverted
  `check_doc_facts.py` visibility gate now asserts LIVE `gh api` visibility (offline =
  loud SKIP); marker guard over `git ls-files` (mutation-proved); DIL-012 recon pass
  (break-glass ordering redacted; account id/IAM/secret-names accepted with dated notes);
  dated historical-exposure risk acceptance in the register. CLOSED, realized.
- **#3044 subscriber trust (DIL-003/013, P0)** — PR #3054. Signed-HMAC unsubscribe
  tokens (email HASH, never the address) across all 7 senders; anonymize-at-unsubscribe
  inline (548d window → 0, weekly sweep = backstop ≤7d); `/privacy/` §05 rewritten to
  the implemented contract. **Deployed 17:40–42Z**: cdk Email+Web (token-secret grants
  on 6 roles + all sender code), `delete-user-data` backstop; **live /privacy/ verified**
  ("anonymized on the spot", hash-as-suppression-record, 7-day hard-delete SLA). No new
  secret needed (reuses `subscriber-token-secret`). Legacy plaintext links sunset
  2026-09-22 (dated in code). CLOSED, realized.
- **#3045 Tier-2 publication ADR (DIL-008/011, gate:owner)** — PR #3055. **ADR-155**
  records the owner consent; `TIER_OWNER_PUBLISHED` stamp in `field_tiers.py` (above
  OWNER_ONLY so naive `>=` fails closed); full registry port (42 wired field pairs + 15
  source-level tiers incl. private_intake/flourishing/felt_probe); DATA_GOVERNANCE now
  GUARDED against the registry both directions. Discovery: the served surface was WIDER
  than the report saw (sleep stages, lean mass, full DEXA summary) — all brought inside
  recorded consent. **MCP Lambda deployed 17:45Z.** CLOSED, realized.
- **#3046 prediction gradeability (DIL-007, P0)** — PR #3053. Emission contract
  (`gradeable_by` stamped; qualitative → `observation`, never pending; #715 criterion 3
  is now a regression test); evaluator retires legacy qualitative rows at window end;
  due-context scorecard **verified live: pending 83→34 with 49 observational split out,
  "0 due yet — earliest verdict due 2026-08-31" derived from the corpus**; `GradableShare`
  + `prediction-gradable-share-low` alarm live (new `monitoring_prediction_alarms.py` —
  monitoring_stack was at its exact ratchet cap). Agent also found+fixed a real JS bug:
  created-dates used as due-dates made the scorecard claim windows closed a week early.
  CLOSED, realized.
- **D0.5 doc-truth sweep** — PR #3051 (Part of #3042/#2986). All 16 MANAGED_WHERE_LEDGER
  rows re-verified live + per-row Verified column + monthly `managed-where-reverify`
  dead-man on the #2832 calendar; client_ip docstrings, CONTRIBUTING, README ($85 →
  ADR-133 wording, "100% IaC" → declared out-of-IaC ring), evidence_meta.js + /method/build
  + org-chart essay fixed at their GENERATORS; `check_doc_facts.py` ceiling scan now covers
  183 site js/html/generator files (planted-defect mutation proof).
- **D0.7 CodeQL (#3047)** — 7 alerts triaged: js/redos FIXED (d02e64d63), #152 dismissed
  false-positive (integer counter, name heuristic — NOT a real #1902 recurrence), #153–157
  dismissed intentional (emoji-block ranges). **Verified 0 open post-re-scan; CLOSED.**
  Sentinel can-it-fail question filed on #2578.
- **#2959 oracle debts (both)** — the visual-qa/diagnosis CI role now has
  `ssm:GetParameter` on the experiment-cycle param (applied live from the checked-in
  permissions file, `verify_oidc_iam.py` CLEAN); the WEEK-1 finding got a **structural
  ruling** (`is_position_banner_misread` — the position banner is a clock, not a content
  label; both wire notes are fixtures; the #2941 banner-actually-wrong residue survives
  at full severity) instead of a ledger entry (the ledger's own contract forbids
  hand-growing, and the predicate covers the shape on every page).
- **The receipts-caption re-deploy went green** after one more rollback round: the ruling
  killed the WEEK-1 shape, but the tail raised 2 novel highs on `/coaching/lab-notes/` +
  `/method/wrong/` (cross-phase content genuinely unlabeled — the producer gap is
  #2957's scope); both baselined via the sanctioned `--update-truth-baseline` sweeps,
  a doomed queued sweep cancelled pre-gate, and dispatch 32654357546 passed
  **smoke + visual-qa end-to-end, no rollback**. Two more gated deploys (privacy copy,
  regenerated scorecard shells) also green — three consecutive green gated site deploys.
- **Main-red repair mid-train:** the #3051+#3052 merges redded 5 gates (module-size ×3,
  premerge registration ×2 — caught by the #3044 agent's full-suite run). Fixed by
  extracting the DG fact gate to `scripts/doc_facts_governance.py` (#1665 ceiling),
  re-wrapping one comment, registering the marker sweep with premerge (#2372). Also
  fixed at boot: the wrap's own INCIDENT_LOG Patterns staleness and the #3005 guard
  tripping on the previous handover's own wording.

## Deploys (hand-deployed from exact merged shas; leases rejected with decodes)

qa-smoke 17:29Z · coach-prediction-evaluator + coach-state-updater 17:20Z · site-api
17:2xZ · life-platform-mcp 17:45Z · delete-user-data 17:42Z · cdk LifePlatformMonitoring
17:24Z + LifePlatformEmail/Web 17:40Z · site ×3 gated green (receipts+D0.5 → privacy copy
→ scorecard shells). 4 production leases disposed (rejected with #2467 decodes); no
waiting leases at close.

## Gate lines

**Build beat:** 2026-08-23-d0-p0-truth
**Docs:** DATA_GOVERNANCE (scope note, retention row v2, ADR-155 carve-out + tier guard) ·
MANAGED_WHERE_LEDGER (16 rows re-verified, dead-man) · README · CONTRIBUTING ·
DECISIONS (ADR-155 + index) · SCHEMA (PREDICTION# row) · API.md · INCIDENT_LOG (+1 row +
Patterns regen) · PROPORTIONALITY (+1 row) · alarm_citations untouched ·
docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md (all D0 rows flipped to FIXED+DEPLOYED
with evidence)
**Decisions:** ADR-155 filed (Tier-2 self-publication by owner consent, #3045)
**Main:** stranded — run 32655256700 R8-ST6 Plan-red at 53e0a357 (#1901 class),
transient: it planned against live BEFORE the 17:40Z hand cdk deploy of the same IAM
diff; both subsequent runs planned green and are rejected-superseded leases (#2467,
hand-deployed + verified above). No recovery dispatch owed — every artifact is live at
its merged sha.
**Incidents:** 1 row added — the receipts-re-deploy auto-rollback (2 novel oracle highs
on genuinely-unlabeled cross-phase surfaces → baselined as #2957 debt, next dispatch
green)
**Stash/hooks:** clean
**Closures:** #3043, #3044, #3045, #3046, #3047 commented (5 ADR-099 verdicts, all
realized with live deploy evidence)
**Backlog:** Now live at 5 actionable; no stale Later issues; hygiene OK (69 issues
clean)
**Alarms:** 0 red >72h; 4 flaps in the window, decoded — `ingest-auth-unhealthy-24h`/
`-dropbox` + `ingest-liveness-unhealthy` (the known #2976 recovery-episode cluster,
single cycle each) and `site-api-invocation-spike` ×3 (self-inflicted: this session's
three full-surface QA sweeps during deploy verification; no reader symptom). Closed with
`--decoded`.
**CI warnings:** none — the newest completed main run isn't green (a rejected-superseded
lease), so there is nothing to triage (that's the main-green gate's finding, decoded
above).
**Ledger:** Prediction-gradeability contract row added (posture + rent + demote trigger;
the #2832 calendar row already covers the new managed-where-reverify dead-man entry)

## Residuals / next picks

- **D0.6 branch protection — BLOCKED ON OWNER:** `apply_branch_protection.py --apply`
  structurally refuses until a fine-grained PAT (Contents read-write, this repo only,
  owned by averagejoematt) exists as the `RECONCILE_PUSH_TOKEN` repo secret + ci-cd.yml's
  reconcile checkout uses it (CONVENTIONS §4c). Then: `--apply`, add the #3025 full-suite
  context to `deploy/github_posture.json`, re-apply. not-work — owner-only PAT mint, in
  the batched ask below.
- **Owner batch (ONE ask):** ① RECONCILE_PUSH_TOKEN PAT (unblocks D0.6, main's first
  required checks) · ② `DEPLOY_GATE_JANITOR_TOKEN` secret (#3021, arms the lease
  janitor) · ③ respiratory_rate + disturbance_count consent call (#3045 left them
  default-public deliberately — stamp or consent) · ④ carried: billing-alarm dupes
  (#2961) · #2834 IAM posture · WAF decision (#2828) · notion-secret retire (#2890).
- **#2957 got two new class members** (lab-notes diary reaction, /method/wrong validator
  table) — the producer fix (cycle labels on cross-phase content) drains both baseline
  entries; commented on the issue.
- **Scheduled observations (not-work — dated):** `prediction-gradable-share-low` may
  fire ~3d on the legacy corpus and clears as retirement drains it from 08-24;
  first real prediction grades as windows mature (corpus earliest 2026-08-31); #2978
  30-day re-measure ~09-22; legacy unsubscribe-link sunset 2026-09-22; next Monday's
  retention sweep anonymizes the legacy subscriber backlog.
- **Next phase:** D1 (control boundaries — WAF/#2828, budget-guard fail-closed under
  #2824, secrets #2890, CSP #3048) per `~/.claude/plans/lively-juggling-candle.md`;
  the D0 register rows are the re-grade evidence pack.
