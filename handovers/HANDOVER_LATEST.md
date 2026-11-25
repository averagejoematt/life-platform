# Handover — Editorial Overhaul 2026-11-21 → 25: eight Chronicle second editions published and verified, the compact Morning Brief live, outbound consolidation made standing, the editorial release live; four other sessions' handovers carried verbatim

## Driving instruction
One session ran from the owner's editorial, coaching and experience review (21 Nov) through his rulings to publication. In order, the owner asked for: the Chronicle back-catalogue remastered and published as second editions with privacy corrections; a one-minute Morning Brief and an audit of every outbound message; an independent outside-in review of the public site; and an editorial release that makes the human story the product. He then called a two-week observation period (24 Nov → 7 Dec): no new workstreams, fixes only for things that break, closure notes on 30 Nov and 7 Dec, escalation only for an actual privacy exposure, a significant failure or a rollback.

Every owner ruling of this session is saved verbatim in private folders (never in the repo). The single index of what is verified, what is started but unconfirmed and what is deferred is the commitment register at `~/Documents/Claude/closure-2026-11-23/COMMITMENT_REGISTER.md`. Four other sessions closed beside this one; each handover is carried below, verbatim.

## Editorial Overhaul — what is COMPLETE (merged, deployed, verified live)
- **Eight Chronicle second editions** (#6193; PRs #6201, #6219, #6222, #6228, #6235, #6236). Each deployed chapter and each of the seven historical pages matches its owner-approved SHA-256 when rebuilt from the live page (`scripts/chronicle_edition_verify.py`, re-run on 25 Nov after the editorial release: all eight pass). Nothing was sent to subscribers. Edition withdrawal and site rollback have only been simulated.
- **Privacy corrections on the back catalogue**: 46 removed passages are absent from live pages, stored copies and the archive's chapter files; legacy `/journal/posts/<id>/` addresses redirect (#6234); weeks 8, 9 and 11 are retired in the record (#6200); held audio stays held; old link-preview images quarantined; nine CI artifacts carrying pre-correction pages deleted after private preservation.
- **Compact Morning Brief** (#6240; PRs #6241, #6248). Switched on 23 Nov; the first real send was 24 Nov 18:01Z: compact format, 206 words, no fallback, no error, one send. The owner is the check on how it reads in his mail client.
- **Outbound consolidation is standing** (#6243; PR #6247): no end date; only an explicit per-item `False` restores a message. Verified on real runs so far: Monday Compass suppressed, single-channel evening check-in. Not yet observed: Sundays 29 Nov and 13 Dec.
- **Public-content corrections from the independent reader review** (#6224; PRs #6261, #6262, #6255): unsupported medical wording and a pending-data claim withheld from the coaching pages and two public data files; vice and restraint data withheld at the API; the essay's stale summary, the chapter call-card labels, the subscribe page, the podcast and attempts placeholders; 25 unscorable calls now serve a sentence (was 24 blank). All read back on the live site.
- **`/next/` previews retired** (#6223; PR #6257): 21 pages removed at source, 21 redirects published, stored copies quarantined, guard passing.
- **The editorial release** (#6258–#6260; PR #6263), live 25 Nov 06:37Z: homepage first screen with the owner's approved first-person headline and opening as static text, a platform-voiced dated progress line, the featured path, "Park's Blind Spot, revisited" at `/story/features/parks-blind-spot-revisited/` (rebuilt from the live page: SHA-256 `68406186…`, the approved hash), three-coach introduction, date-first chapter labels, one new feed item. No subscriber email.
- **Public forecast**: first filing 23 Nov 17:00Z; the public route returned 500 until #6239 deployed (~19:30Z); it now serves the forecast. Not yet graded.
- **Public-copies guard** (#6251): a cleared status comment is no longer treated as a withholding; verified on a real root build with the exemption count printed.

## Editorial Overhaul — built and NOT live, or live and NOT yet exercised
- **Recommendation-record pilot** (#6158; PR #6232): merged with `CANONICAL_INTAKE_LIVE = False`. The writer function and both stacks are deployed, production permissions were simulated against the live roles, and the dark validation (one read pass, three refusals) passed with zero rows written. A real write, a real response and an outcome have never happened. Activate only on the owner's go, after the compact brief has run well.
- **Short Saturday Nutrition Review** (#6245; PR #6249): switch set to `compact` on 24 Nov; first send is Saturday 28 Nov.
- **Between-chapters subscriber email** (#6244; PR #6246): repaired and HELD in code (`OWNER_RELEASE = None`); its schedule was also disabled by hand on 23 Nov and has not been re-enabled. Release needs the owner's review of a rendered copy.
- **Coach-context switch** (#6149): off. Round 5 failed three of six criteria.

## Editorial Overhaul — awaiting the owner
- The five-person unprimed reader test (approved; who and when).
- Two optional questions put to him for the human centre of the new feature (why 30 September had no logged session; whether he knew of the wrong scoreboard grades at the time). Never inferred.
- Release or keep holding the between-chapters email, after reviewing its render.
- Corrected Episode 0 audio (his listen); Episode 4 stays held.
- Whether the pre-experiment weight series (back to January 2024) should stay publicly served.
- The private weekly recap card prints a count that includes private categories; three related outlets are unswept (a character-sheet effect, the temptation resist-rate, the challenge catalogs).
- Week 6's superseded interview correction text (hide it or not); Week 5's lab-reference sentence on its historical page.
- The Evening Ritual row in the nightly nudge, and whether two weekly probes that lost their only collection route should be collected another way.
- Activation of the recommendation pilot.
- His draft priority statement (never written into his record as his words).

## Editorial Overhaul — gotchas learned
- **A matching fingerprint is not a true attribution.** An owner-dictated one-line correction would have attributed the narrator's bet to him; the published chapters settled it. Check the record, stop that one item, show the evidence, offer the fix.
- **A privacy removal must follow images, CI artifacts, generated public JSON and subscriber mail**, not only the pages the guard enumerates. The Morning Brief's summary line was being copied into two public data files and the archive.
- **Verify the thing a person receives.** The hybrid brief "sent in the trial format" was 13 pages; the send record said nothing about length.
- **A new token-gated route needs a declared refusal in the smoke sweep**, or every root build's smoke reds and the rollback baseline stops advancing.
- **The fixture must be the wire**: a null `url` on retired weeks crashed the edition verifier; `Decimal` values broke the forecast route on its first live row.
- **Stored text is validated only at build time**: a correction note's evidence line broke every site build twice. Proposal-time validation now exists; an approved feature text still tripped the raw-id check at PR time.
- **A commit hook's doc sweep rides a plain `git commit`** when concluding a merge; conclude lane merges in agent-commit mode.
- **This machine sleeps**: background checks paused twice overnight. Long waits belong to the pipeline, not to a local timer.
- **The release's own page checks are vacuous on a hand-fetched folder** (`is_site_build` is false); recompute the hash directly when verifying live.

## Cross-session notes the next session must hold
- **The remediation agent is OFF** by the owner's ruling of 24 Nov (#6265; SSM `/life-platform/remediation-mode` = `off`). Any older text saying "shadow permanently" is superseded; do not set it back without a separate owner approval.
- **`qa-smoke-warnings` red now carries information** (retuned by #6231): read its `PERSISTENT` line. **`calibration-deadman` is red on purpose** until the owner logs a real tape and photo entry.
- **Weekly digest reader numbers still include the platform's own tools**; only the subscribe funnel lines are corrected (#6267). Do not cite page views or unique visitors as readership.
- **"Deployed" is not "exercised"** for the research PRs (#6213, #6214, #6217), the pilot writer, the cadence change and the edition withdrawal path.
- **The phrase "AI journalist" is permitted** (owner, 23 Nov); the fault is implying a human with personal experience of events.
- **Generic "this cycle" wording stays**; numeric cycle or attempt counts do not appear on the public site.
- The three official pillars (owner, 24 Nov): understand me; research for me; learn what works for me. The human documentary is their public expression, not a fourth pillar.

## Product assessments session — carried verbatim from its 2026-11-25 handover (private file, abridged for the public repo)

Sections carried word for word: 1, 2, 3, 4, 6, 7, 8, 10. Omitted here and kept in the private file `~/Documents/Claude/closure-2026-11-23/handovers/product-assessments.md`: the owner's rulings quoted verbatim, the working-state inventory of private folders, and anything that must not be public.

### What this session was for
Three analysis-only product assessments commissioned by the owner (legacy and hidden capabilities; visual experience with four mockups; cost economics) and one unified portfolio. The owner then issued rulings on four items the assessments surfaced, and this session executed them.

### Shipped
| Item | Status |
|---|---|
| Assessment package (3 reports, portfolio, 4 mockups, appendices) — private files only, nothing in the repo | Delivered; owner read it and ruled on it 24 Nov |
| **#6264** (`3e57477ae`) — numeric cycle reference removed from the `/system/calibration/` header | **VERIFIED IN REAL USE** — live page read 25 Nov ~16:45Z: header reads "System · the Coaching Room · through 24 November 2026"; no "cycle N" on the page |
| **#6265** (`8eb3e6075`) — remediation agent OFF: CLAUDE.md, PROPORTIONALITY, REMEDIATION_TAXONOMY, RUNBOOK, remediation/README, ADR-129 amendment, recorded value in `tests/public_claims_registry.py` | **MERGED; switch read back `off`** (25 Nov ~16:45Z). The gate's no-op on a scheduled run is **not yet observed** — next scheduled run is Wed 25 Nov 17:35Z |
| **#6266** (`442887eee`) — two legacy pages replaced by a "no longer available" stub; public-copies guard rule E extended to both | **VERIFIED IN REAL USE** — both addresses serve the 274-byte stub; stored objects are the stub (written 07:41Z); archive regenerated; `check_public_copies.py --remediation` exits clean on every copy |
| **#6267** (`1ebae0aba`) — traffic digest subscribe funnel counts the platform's own tools apart from readers; canary on its own line; reader traffic labelled an estimate; funnel HTML builder moved to `lambdas/operational/traffic_digest_funnel_html.py` | **DEPLOYED BUT NOT YET EXERCISED** — deployed function code contains the change (read from the function's bundle, LastModified 08:38Z); no real digest has run with it. First real run: Monday 30 Nov ~17:02Z |

### Still open
- **No open PRs or drafts from this session.** All four PRs merged.
- **Four lane worktrees still on disk, clean, branches merged** — not removed, per instruction:
  - `~/dev/worktrees/life-platform/fix-calibration-no-cycle-number` (`fix/calibration-no-cycle-number`)
  - `~/dev/worktrees/life-platform/docs-remediation-off` (`docs/remediation-agent-off-2026-11-24`)
  - `~/dev/worktrees/life-platform/fix-legacy-two-pages` (`fix/legacy-two-pages-quarantine`)
  - `~/dev/worktrees/life-platform/fix-digest-internal-ua` (`fix/digest-exclude-internal-tools`)
  Remote branches: none of the four remain on origin (deleted on merge). Next action: retire the worktrees and local branches at wrap.
- **No locks held. No background jobs or scheduled checks running.**
- **Two failed "v9 deploy (preview · root)" runs** (heads `3e57477a` and `95a9ffe0`, 25 Nov ~06:33–07:10Z): the only failed job was the public-copies guard; sync, smoke and visual QA passed and nothing rolled back. Cause for `3e57477a` was not read from the log (unverified); it ran while the two legacy pages were being re-published and the archive was older than the build. The guard is green now. Next action: confirm the next v9 deploy run is green.
- **To observe, not yet seen:** (a) Wed 25 Nov 17:35Z remediation run no-ops at the gate; (b) Mon 30 Nov digest shows the new funnel lines.

### Shared state changed (including what git does not show)
- **SSM `/life-platform/remediation-mode`: `shadow` → `off`**, version 6, set 25 Nov 04:16Z by this session on the owner's ruling. Roll back (needs a separate owner approval): `aws ssm put-parameter --name /life-platform/remediation-mode --value shadow --type String --overwrite --region us-west-2`. Parameter history shows version 5 (`shadow`) was set 2026-10-17 under `matthew-admin` with no recorded decision.
- **S3 quarantine, run twice** with `deploy/quarantine_public_copy.sh --apply` for `site/legacy/story/index.html` and `site/legacy/archive/v1/supplements_protocol/index.html`:
  - `s3://matthew-life-platform/backups/quarantine/public-copies/20261125T063912Z/`
  - `s3://matthew-life-platform/backups/quarantine/public-copies/20261125T073900Z/` (same two originals again)
  Each run removed the public objects and invalidated the four CloudFront paths. The public keys now hold the stub (from the #6266 site deploy).
- **`life-platform-permanence` invoked by hand** (~16:43Z 25 Nov) to regenerate the public archive; then a CloudFront invalidation of `/archive/*`. Archive sha256 matched its manifest.
- **Cost Explorer queried** 8 times by the cost assessment (~$0.08). Read-only otherwise.
- **Memory written before this handover request** (see section 9 note): three new memory files and three new lines in `MEMORY.md`.
- Nothing else: no schedules changed, no secrets or tokens touched, no IAM or CDK change, no DynamoDB write, no test subscribers, no email sent.

### Waiting on the owner
- The actual billed Claude and OpenAI charges (Monarch hides the amounts); the cost report's subscription row is blank.
- Whether the site-wide page-view and unique-visitor counts should also exclude the platform's own tools (left unchanged; they feed the emitted traffic metrics).
- Who runs the five-person reader test and when.
- Go-ahead and scope for the scoreboard release and the forecast chart (direction approved, build not authorised).
- The original text of the two quarantined pages remains in the public repo's git history — whether that joins the existing repo privacy remediation plan.

### Safeguards tested only synthetically
- **Rule E for the two quarantined pages** — proven red on planted filler in tests; never fired on a real re-publication.
- **Digest internal-tool separation** — unit-tested on fixture log rows using the real user-agent strings; not yet run on real logs.
- **Remediation `off` gate** — code read (`remediation/agent.py` exits at `mode == "off"`); not observed on a real scheduled run since the flip. Live reconciliation test (`CLAIMS_LIVE_RECONCILE=1`) could not run locally (invalid token under pytest); the value was read back by CLI instead.

### Deferred on purpose
| Item | Why | Resume when |
|---|---|---|
| Scenario explorer, documentary timeline, character representation, reader-call supply | Owner: "preserved future opportunities" | Owner asks |
| Staged retirement of unused legacy features and public write paths | Owner's investment #4; plan not started | After the reader test and scoreboard, on owner's go |
| AWS cost-reduction programme | Owner ruled it out for $20–45/month | Not unless the bill changes materially |
| Re-pour of `/subscribe/` and share cards | Direction favoured, build not authorised | Owner's go |
| Excluding own tools from site-wide traffic counts | Outside the "narrowly scoped" correction; feeds emitted metrics | Owner decision (section 6) |
| Cost ledger close rows for September and October; GitHub Actions contingent figure ($53 recorded vs ~$524 measured) | Bookkeeping, not ruled on | Next cost close |

### The one thing the next session will get wrong without being told
**The weekly digest's reader numbers are mostly the platform talking to itself.** In the week to 23 Nov all 117 "successful sign-ups" were the subscribe canary, about 280 of 358 `/subscribe/` views were QA and audit tools, and the last real subscriber row is from 3 July. The funnel lines are corrected from the next run, but the headline page views, unique visitors (3,885) and returning share (4%) are **not** — they still include those tools and still feed the emitted traffic metrics. Do not cite them as readership, and do not read a rise on a heavy build day as audience growth.



## Platform Integrity session — carried verbatim from its 2026-11-25 handover (private file, abridged for the public repo)

Sections carried word for word: 1, 2, 3, 4, 6, 7, 8, 10. Omitted here and kept in the private file `~/Documents/Claude/closure-2026-11-23/handovers/platform-integrity.md`: the owner's rulings quoted verbatim, the working-state inventory of private folders, and anything that must not be public.

### What this session was for
An independent, read-only audit of why the platform passed technical review while producing avoidable experience failures (22 Nov), then a narrow implementation phase under owner rulings (23 Nov): close the public CI-artifact path, retune one alarm, change one charter cadence, start a manual weekly scorecard, and verify other sessions' fixes. Role going forward: independent verifier, not a feature owner.

### Shipped
| Change | Status |
|---|---|
| PR #6229 — `web-gate.yml` and `v4-gate.yml` no longer upload `v9-preview-<sha>` / `pr-render-gate-capture` | **VERIFIED IN REAL USE.** Merged 23 Nov 02:16Z. No artifact of either kind created since; checked at four sweeps on 23 Nov, on 24 Nov, and now (25 Nov 16:47Z) across runs from several lanes |
| PR #6231 — `qa-smoke-warnings` watches `PersistentWarnCount` (same warning three Pacific days running; `reader_truth:confirm` from day one; owner check-in warning counted apart) | **VERIFIED IN REAL USE.** Lambda deployed 23 Nov 04:32Z; monitoring stack 05:10Z. Observed: day-one rule named `reader_truth:confirm` on 22 Nov PT; alarm cleared ALARM→OK at 23 Nov 23:28 PT after a clean day; three-day rule fired OK→ALARM at 24 Nov 00:07 PT naming `data:pk_family_census`, `public_brief:cycle_liveness`, `story_season:chapter_door` (and `weeks:fact_agreement` in three runs). In ALARM now on those ids. Its fail-closed and dry-run paths: unit tests only |
| PR #6230 — charter 1.53.0, tape and photo cadence 2 → 4 weeks | **DEPLOYED BUT NOT YET EXERCISED.** Deployed bundle carries 1.53.0; deployed code on the live table returns both kinds two cycles overdue. No real entry has been logged, so the cycle reset is unobserved |
| Scorecard week 1 (manual, read-only; outside the repo) | Produced 23 Nov; owner accepted it as baseline. Not a deployed thing |
| Five issues filed: #6223, #6224, #6225, #6226, #6227 | Open. See section 3 |
| Verification of PR #6221 (Editorial's) — fallback attribution guard, five narrator prompts | **DEPLOYED BUT NOT YET EXERCISED.** Deployed bundles carry build `4cce3a54e`; the deployed gate flags a synthetic bad draft. No real fallback draft has passed through it |

### Still open
- **Open PRs or drafts of mine:** none.
- **Remote branches of mine:** none (all three deleted at merge).
- **Lane worktrees, all unlocked, clean, merged — not removed:** `~/dev/worktrees/life-platform/issue-6223-pr-artifact-uploads`, `issue-5067-calibration-cadence-4wk`, `issue-5928-qa-smoke-persistent-warns`. Next action: the reaper retires them at wrap. (Two other `issue-6223-*` worktrees there are LOCKED and are not mine.)
- **Locks held:** none.
- **Background jobs or scheduled checks:** none. The three one-shot overnight sweeps of 22–23 Nov fired and expired.
- **Owed by this role, undone:**
  - Scorecard week 2 — manual run on or after 30 Nov: `python3 scorecard/experience_health.py` and `public_copy_inventory.py` in my private folder.
  - Trim the preserved artifacts (section 8).
- **#6223:** eight screenshot/build upload steps remain; 43 page or screenshot artifacts are public now (`v9-root` 11, `v9-root-visual-qa` 10, `visual-qa-screenshots` 14, `site-deploy-visual-qa-screenshots` 5, standalone 2, webkit 1). Per-step recommendation is in my comment on the issue. Owner: Editorial / CI. Manifest not built by me; later work on it by others is unverified by me.
- **#6224:** the 190 g example is still in `lambdas/coach/coach_extraction_prompt.py` on main (read now). Stored corrections re-check, real-render tests, the spoken Episode 0 line: unverified since 23 Nov.
- **#6226, #6227:** nothing built by me; later commits by others unverified by me.
- **Residue of #6231, unassigned:** `docs/alarm_citations.json` and `scripts/check_alarm_citations.py` still describe `qa-smoke-warnings` as an any-warning alarm.

### Shared state I changed
**Not visible in git:**
- **CloudFormation:** `LifePlatformMonitoring` deployed 23 Nov 05:10Z with `bash deploy/cdk_deploy.sh LifePlatformMonitoring -- --require-approval never --exclusively`, on the owner's go. Changed the `QaSmokeWarnings` alarm's metric (`WarnCount` → `PersistentWarnCount`) and removed tags from two dashboards (pre-existing drift carried by the deploy). Rollback: revert the #6231 commit, deploy that stack again.
- **DynamoDB:** the QA job now writes one state row every run — pk `USER#matthew#SOURCE#qa_predict_dark`, sk `STATE#warn_streaks`. Not written by hand. Inert if #6231 is reverted.
- **New CloudWatch metrics** in `LifePlatform/QaSmoke`: `PersistentWarnCount`, `OwnerEngagementWarnCount` (the second has no alarm, by ruling).
- **GitHub Actions artifacts deleted:** 55 in total (18 + 10 on 23 Nov, 27 in four pre-approved sweeps to 12:47Z 23 Nov), page and screenshot kinds from finished runs only, never `v9-root-<sha>`. Each was downloaded and its archive verified first. Lists: `inventory_before.tsv`, `preserved.tsv`, `round2/log.tsv`, `overnight/log.tsv` in the preserved folder.
- **GitHub issue comments** recording owner rulings: #6223 (×3), #6224 (×2), #6225, #6226 (×2), #5067 (×2), #5928 (×2), #5934.
- **Main checkout:** fast-forwarded once (`git pull --ff-only`, 23 Nov ~05:08Z) for that deploy.

**Visible in git:** PRs #6229, #6230, #6231 only.

**Not changed by me:** switches, feature flags, schedules, secrets or tokens, IAM, S3 objects, any content row.

### Waiting on the owner
- Log a real tape measurement and progress-photo set (`calibration-deadman` stays red until then).
- May one memory entry about this role be added? (Listed below instead of written.)
- Approve trimming the preserved artifacts, once the remaining upload steps are closed.
- Who edits the remaining upload steps under #6223, if not the Editorial session.

### Safeguards tested only synthetically
- Fallback-writer attribution guard (#6221): deployed code run on a synthetic draft only.
- `qa-smoke-warnings`: the fail-closed path (unreadable state → every warning counts) and the dry-run no-write path — unit tests only. Its two firing rules are now observed live.
- Charter cadence: computed on live data; no real entry has exercised it.
- Everything in `regression_pack/candidates.py` (manifest check, removed-sentence check, forecast-history diff, provenance refusal, duplicate finding, context-case harness, dark-capability check): synthetic fixtures, not in the repo, not adopted.
- The public-copy inventory script: a read-only prototype, run by hand three times.
- From another session's report, unchecked by me: the #6214 experiment-overlap gate fails open on a read error.

### Deferred on purpose
| What | Why | Resume when |
|---|---|---|
| Moving regression-pack cases into owners' test suites | Owner: only after clean-case and real-path validation, by the owner of each area | Each fix lands and its owner adopts the case |
| Binding the coach-context cases to real builders | Belongs to Coaching (#6226); the #6149 pilot stays off | Coaching takes #6226 |
| Trimming 3.1 GB of preserved artifacts | Kept as remediation evidence | Remaining upload steps closed and the owner agrees |
| Scorecard automation, a repo home for the script and registry | Owner: four manual weeks first | After week 4 (on or after 14 Dec) |
| Repetition threshold | Classifier is coarse; owner: descriptive only | Recommendation ids and reasons exist |
| Updating the alarm citation entry and script for #6231 | Kept the PR narrow; no owner named | An infrastructure owner picks it up |

### One thing the next session will get wrong without being told
**`qa-smoke-warnings` being red is now information, not noise — read the `[QA] PERSISTENT warn 3d <ids>` line before doing anything about it.** It is red today because three checks have warned on three consecutive days. The reflex from the last month (it is always red; cite it and move on) is exactly what the retune removed. And the reverse trap: `calibration-deadman` is red on purpose and must not be "fixed" by anything except the owner's real entries.



## Research engine session — carried verbatim from its 2026-11-25 handover (private file, abridged for the public repo)

Sections carried word for word: 1, 2, 3, 4, 6, 7, 8, 10. Omitted here and kept in the private file `~/Documents/Claude/closure-2026-11-23/handovers/research-engine.md`: the owner's rulings quoted verbatim, the working-state inventory of private folders, and anything that must not be public.

### What this session was for
A discovery spike, then a controlled build, for the owner's "understand me, research for me, learn what works" brief. It produced one assessment, five PRs under epic #6206, and the first research finding stored in production.

### Shipped
| Item | Status |
|---|---|
| #6220 findings store + `manage_research_finding` (squash `8060905d2`) | **VERIFIED IN REAL USE.** 2026-11-23T08:51Z: one finding written through the deployed tool and read back by the tool and by direct table query |
| Finding `rf_20261123_45fa9263` (4 rows) | **VERIFIED IN REAL USE** as a stored record. Not a completed loop: no coach review, no scan, no outcome |
| #6217 lift outcome metrics, baseline snapshot, public-analysis allowlist (squash `d6f95cf9d`) | **DEPLOYED BUT NOT YET EXERCISED.** Bundles read back 11-23 (site API 07:22Z, MCP 07:25Z). No experiment uses a lift metric |
| #6214 experiment overlap rule, three-state result (squash `9707507d6`) | **DEPLOYED BUT NOT YET EXERCISED.** Bundle read back 11-23 06:52Z. No experiment created since |
| #6213 optional `finding_id` on the recommendation head (squash `db6e66e19`) | **DEPLOYED BUT NOT YET EXERCISED.** Bundle read back 11-23 18:11Z; live `list` answers, 0 recommendations |
| #6215 qualified coach-context facts | **Not shipped.** Open draft, unwired |
| Issues filed: epic #6206, stories #6208–#6212 | #6208 closed on live proof. Others open |

### Still open
- **PR #6215** (draft, branch `issue-6212-grounded-intake-facts`, head `157eb9ee1`). Not restacked since 11-23; mergeability unverified. Next action: Coaching owner includes it in the next #6149 pilot; the wiring PR must delete its unwired guard and its entry in the dead-code guard's allowlist.
- **Lane worktree still LOCKED:** `~/dev/worktrees/life-platform/issue-6212-grounded-intake-facts`. Do not release until #6215 merges or closes.
- **Lane worktrees released, still on disk** (reaper retires them): issue-6208, 6209, 6210, 6211.
- **Issues open on a live-proof condition:** #6209 (a live design naming a lift metric), #6210 (a live `create_experiment` response with an overlap block), #6211 (a recorded recommendation carrying a finding id), #6212, epic #6206.
- **Coach review of the finding:** not done. Next action is the owner's (item 6).
- **Background jobs / scheduled checks:** none running. No subagent is live.
- **Not started:** the two manual monthly research reviews; any analysis of journal text.

### Shared state changed
- **DynamoDB, manual writes through the deployed tool** (not visible in git): 4 rows under `USER#matthew#SOURCE#research_findings`, all `FINDING#rf_20261123_45fa9263…` (head, decision, state change, one correction). Conditional puts only. Rollback: none built in; the store is append-only and has no delete. No other partition was written.
- **New partition `research_findings`:** owner-only, cross-phase. The MCP role's existing table-wide grant covers it; scope is enforced in code, not IAM.
- **MCP tool count +1** (`manage_research_finding`). Gate census pins moved by #6220.
- **`config/evidence_source_allowlist.json` 2.0.0 → 2.1.0:** added `guideline_hosts` only.
- **Public route `/api/experiments`:** `analysis` is now served through an allowlist (`PUBLIC_ANALYSIS_KEYS`). Output for existing rows unchanged.
- **`create_experiment` default changed:** a caller passing no new argument is treated as behavioural and is refused on a same-metric overlap unless it passes `acknowledge_overlap`.
- **Deploy-order rule (from #6217):** site API ships before or with the MCP code; never roll the site API back alone after a lift experiment has closed.
- **No switch, flag, schedule, secret, IAM or CDK change.** No file or object quarantined or deleted in AWS.
- **Deleted locally 11-22:** 38 MB of private DynamoDB extracts in the session's `data/` folder (owner ruling).
- **GitHub:** comments on #6208, #6209, #6210, #6211; #6208 closed.
- **Memory files this session already wrote** (before this instruction): `project_research_engine_spike_2026_11_22.md` and its one line in `MEMORY.md`. Not touched since.

### Waiting on the owner
- Send the drafted question in the Telegram training-coach thread.
- Book the scan; choose an interval for a second scan.
- Arrange the clinician and dietitian review he said was warranted.
- Decide whether to obtain three closed-access papers.
- Decide when to run the first manual monthly research review.

### Safeguards tested only synthetically
- #6214: three-state overlap result, pagination, malformed-row handling, closing caveat. Fake tables only.
- #6217: snapshot write-once and immutability, late-capture marking, exercise identity, the public allowlist (fake rows; the live route has no stored analysis).
- #6220: lifecycle table, tighten-only risk, clinician hold, tier-5 blocks, risk-word tripwire, verifier redirect refusal, invalid-event replay. Real use covers one path only: record, decide, `observation_planned`, one correction.
- #6220: `publishable()` is called by nothing.
- #6213: id format check. #6215: everything.

### Deferred on purpose
- **#6215 wiring:** the context pilot failed its evaluation and is off. Resume when the next #6149 pilot passes.
- **Automated research review:** resume after two manual reviews are judged.
- **Journal-text analysis:** journal is too sparse (4 entries since the phase start; Notion search found no more). Resume when there is material.
- **A private script to get a coach reply:** the Coaching owner did not want a session-made path. Resume only on an owner ruling.
- **Three closed-access papers:** abstract-only until access is obtained.
- **Weekly-correlation detrending and a causal-wording rule:** outside this lane; raised by Platform Integrity.

### The one thing the next session will get wrong
It will read "merged, deployed, verified" for #6214, #6217 and #6213 as "works". Only the findings store has been used for real. The other three have never run against a real experiment or recommendation, and the finding itself has informed nothing yet: no coach has seen it.



## Token rotation session — carried verbatim from its 2026-11-25 handover (private file, abridged for the public repo)

Sections carried word for word: 1, 2, 3, 6. Omitted here and kept in the private file `~/Documents/Claude/closure-2026-11-23/handovers/pat-rotation.md`: the owner's rulings quoted verbatim, the working-state inventory of private folders, and anything that must not be public.

### What this session was for
The owner asked whether to renew the expiring `reconcile-push` fine-grained PAT. The session renewed it: the owner regenerated it, and the session stored it as the repo secret `RECONCILE_PUSH_TOKEN` and recorded the rotation date in `docs/SECURITY.md`. Along the way it answered two coordination messages from Editorial Overhaul.

### Shipped
- **Repo secret `RECONCILE_PUSH_TOKEN`, rotated 2026-11-23T19:14Z.** VERIFIED IN REAL USE: post-merge reconcile commits have landed on main since then (`01f10499d` 2026-11-23 22:02 PT, `877009e22`, `95a9ffe09` 2026-11-24 22:07 PT). The ci-cd reconcile runs were green on 11-24 and 11-25. The reconcile job checks out with that secret, so those pushes used the new token. I did not inspect the run logs to confirm which identity pushed.
- **PR #6256** (`docs/security-token-row`), which updates the `RECONCILE_PUSH_TOKEN` row date in `docs/SECURITY.md` to 2026-11-23. NOT MERGED; open.
- **PR #6252**: closed unmerged and its branch deleted (superseded by #6256; see §4).

### Still open
- **PR #6256**, open and one commit (`5251ce526`), doc-only. Next action: the owner or the wrap session merges it once CI is green.
- **Worktree** `~/dev/worktrees/life-platform/security-token-row` on branch `docs/security-token-row`, which is pushed and clean. Next action: retire it after #6256 merges. It is listed here, not removed.
- No locks, deploy leases, background jobs or scheduled checks are held.

### Waiting on me
- Merge #6256 (doc-only date change).
- Optional: open the `reconcile-push` token's settings page on GitHub to confirm its scope is still this repo only, Contents read-and-write, and nothing more.
- Whether and when to compact MEMORY.md. A hook warned at 21.5KB against the 24.4KB limit; I left it alone because other sessions were editing it.


## Residual / next picks
All five sessions' queues, merged. Each line cites its issue or is tagged not-work.
- #6240 — confirm the compact brief over the observation period (reading burden, repetition, accuracy, quiet days); the homepage of the release measures 7.61 phone screens on live data against the 7.5 budget.
- #6245 — verify Saturday 28 Nov's short Nutrition Review: three-minute format, menu and shopping list intact, complete-day count in the subject; then the Monthly Coach's Letter.
- #6243 — keep open until the send log shows the Sunday "what changed" email and no Weekly Report on 29 Nov and again on 13 Dec; first real QA failure should land in the digest with no email.
- #6244 — the between-chapters note is held in code and its schedule is disabled; re-enable the schedule only after confirming the deployed code hold, release only on the owner's review; check the Weekly Signal's Sunday send.
- #6158 — the recommendation pilot is deployed dark; first real offer, response and outcome are unproven; activation is the owner's.
- #6237 — many roles can still write the recommendation-record partition; a separate, tested least-privilege change.
- #6149 — coach context stays off until the next pilot passes the known-answer cases (#6226); draft #6215 waits on it and its lane lock stays.
- #6223 — the public-copy manifest: images, CI artifact uploads (eight upload steps remain), generated public JSON; a bounded retry on the guard's anonymous fetches; quarantine ordering (repo change first).
- #6224 — remaining guard fixes: the stale 190 g example in the coach extraction prompt, the text rule on stored corrections, the spoken Episode 0 line, real-render tests; the publication gate treats a withheld row's frozen engine text as withheld words.
- #6227 — write-once forecast registration before forecasts are cited as a track record.
- #6225 — Experience Health scorecard weeks 2–4, by hand, from 30 Nov.
- #6258 — Chronicle reading experience: correction presentation, human-centred progression, chapter naming; any further chapter treatment needs the owner's approval.
- #6259 — reader journey: two page designs still coexist; `/story/moments/` has no in-site link; the three "What happens next" questions are collapsed on the homepage.
- #6260 — subscriber journey.
- #6211 — a recommendation carrying a finding link has never been recorded; #6209 and #6210 wait on a real experiment.
- #6206 — the research finding has had no coach review; two manual research reviews are approved and not started.
- #5067 — the tape and photo cadence change is deployed; a real entry has never exercised it.
- #5928 — `qa-smoke-warnings` is red on persisting warnings; read its `PERSISTENT` line before acting.
- #6256 — the token-rotation date PR is open, docs only; merge when green.
- #6271 — the site API's first uncached read of `/api/chapters` and `/api/edition` takes 6–9 s since the second editions went live (the latency alarm flaps 26–45 times a day); cause not established.
- #6268 — three QA checks lag sanctioned changes (legacy 301s read as a blackhole; a withdrawn chapter expected by the recall sensor; a month-rounded age against a 20% tolerance); they hold `qa-smoke-failures` red.
- #6269 — the census probe's 6 s cap times out on the same slow reads.
- #6270 — the weekly field notes were held by the grounding gate two Sundays running; the generator keeps producing ungrounded drafts.
- #4531 — `chronicle-delivery-heartbeat` is red correctly: the 25 Nov Wednesday draft awaits the owner's approval; with chapters no longer weekly, its seven-day expectation needs a ruling.
- #5515 — three guard gaps from this week's incidents: the fleet deploy script is not on the ask list, unquoted heredoc bodies are read as data, nothing checks the branch before a pull in the shared checkout.
- #6224 — the incident procedure calls for a focused privacy review after an exposure (three rows this week); not run, because the owner ruled out new broad audits — his call.
- #6216 — a docs-and-config patch for the narrator's configuration twins was not applied at this wrap (it changes `config/` files); it and four stale docs patches (#6176, #6194, #6199, #6158) need regenerating against main.
- not-work — five auto-maintained ADR-count figures update through the post-merge reconcile job after this wrap is pushed; confirm they read 172 / ADR-174.
- not-work — the owner's own actions: approve or decline the 25 Nov chapter draft; answer the two optional questions; choose reader-test participants; listen to Episode 0; send the coach question; book the scan; log a tape and photo entry.
- not-work — observation-period notes are due on 30 Nov and 7 Dec; routine progress otherwise on request.
- not-work — the reconcile token's scope has not been checked on its settings page (an owner look); its settings are recorded privately and are not restated in public text.

**Build beat:** none — the owner called an observation period on 24 Nov; no further public copy without his approval, and the release itself is the public record of this work.
**Docs:** `docs/DECISIONS.md` (ADR-172, ADR-173, ADR-174 + index) · `docs/INCIDENT_LOG.md` (12 rows + patterns) · `docs/alarm_citations.json` (six entries re-derived, one added) · `docs/OPERATING_KNOWLEDGE_LEDGER.md` (15 rows) · `docs/OPERATING_DISCIPLINE.md` §3a.7 · `docs/PROPORTIONALITY.md` (7 rows + a note) · `docs/RUNBOOK.md` (legacy chapter redirects) · `docs/SITE_AUTHORING.md`, `docs/SITE_MAP_AND_INTENT.md` (`/next/` retirement) · `docs/CONVENTIONS.md` §9a · lane and skill rules under `.claude/` (worktree-implementer, worktree, land, new-machinery, review).
**Decisions:** ADR-172, ADR-173, ADR-174 filed.
**Main:** green (1ebae0ab) — two root site builds on 25 Nov ~06:33–07:10Z were red on the public-copies guard for non-privacy causes (incident row); the next scheduled build was green.
**Incidents:** 12 rows added — a lane-run deploy path, correction text breaking site builds, a frozen rollback baseline (~8.7 h), the verifier crash on live data, the forecast route's 500, restricted wording in unguarded copies, a grandfathered disclosure, the subscriber email around the gate, a test-order red on main, two guard reds, a branch in the shared checkout, and a combined process row.
**Stash/hooks:** clean · worktree-reap removed 73 and released 42 merged locks; lanes with open or draft PRs stay locked (#6132, #6040, #6096, #6215), and `issue-6158-context-fixes` is kept.
**Closures:** #6144, #6162 commented · DoD: scanned 5, hits 0 after commenting (one unhomed residual homed on #1348).
**Backlog:** Now live at 6/25/5 (fable/opus/sonnet); no refill needed; no stale Later issues; filing-contract violations on this week's issues fixed (0 blocking).
**Alarms:** 5 red >72h, all cited (calibration-deadman #5907, chronicle-delivery-heartbeat #4531, field-notes-missing #6270, freshness-interior-gap self-clearing by 2026-11-29, qa-smoke-failures #6268/#6269/#5928); also lit under 72 h and cited: qa-smoke-warnings, site-api-p95-latency-high (#6271).
**CI warnings:** none.
**Ledger:** seven rows added (compact-brief safeguards, public-claim screen and restraint withholding, edition fingerprint checks, between-chapters hold, the dark recommendation writer, the qa-smoke persistence rule, the attended legacy-redirect tool) and a dated note on the public-copies guard row.
