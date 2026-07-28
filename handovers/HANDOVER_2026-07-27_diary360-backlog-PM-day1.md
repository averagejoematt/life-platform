# HANDOVER — Day-1 continuation + diary-360 chain complete + the backlog PM upgrade lands — 2026-07-27 (day session)

> Instruction thread: **solo fable session, owned main** — (1) Day-1 experiment watches,
> (2) infra pair #1858/#1859, (3) queue paydown (diary-360 chain, #1396, gate checks on
> #1655/#1543/#1402), (4) #1653 only-if-quiet. Standing approval: all merges, Deploy-gate
> approvals, deploys incl. deploy_all; CDK via Matthew's `!`. **Mid-session Matthew added
> epic #1863 (backlog PM upgrade)** — worked #1865→#1866→#1869 + the #1864→#1871 docs
> lane + #1867/#1868/#1870, leaving only the two Later stories. #1653 was explicitly
> dropped (not a quiet day). Sub-issues question: ratified `## Stories` task lists over
> `gh --parent` (task lists already give computable progress; a second linkage mechanism
> would drift; door stays open as a cheap later chore).

## The headline: 14 PRs + a 64-issue corpus surgery, and the backlog now ranks itself

**Main-green repair, zero deploys:** the wrap's decoded red (deploy_all-4 I1/I2/I5,
runner-side STS OIDC ETIMEDOUT) cleared via `gh run rerun --failed` — transient confirmed,
no fleet cycle spent.

**Shipped — every PR verified on-branch, squash-merged locally, full suite green each
round (suite grew 7,632 → 8,141 tests):**
- **#1858** (PR #1860, c9b0c28f) — IAM cycle-read audit: 7 roles granted scoped
  `ssm:GetParameter` on experiment-cycle (milestone-digest was the observed AccessDenied;
  site-api-ai/insight-email-parser verified correctly excluded — their paths never invoke
  `read_cycle()`). **NEEDS Matthew's CDK one-liner** (below).
- **#1859** (PR #1862, 55547f4a) — rollback-net residuals: per-function region from
  lambda_map (email-subscriber us-east-1 revert now resolves; S3 stays pinned us-west-2),
  fleet-push rollback rebuilds its matrix from lambda_map (was 0/0/0 twice on 07-27).
  Tally semantics fc18f0c2/5d36b4a9 preserved byte-identical.
- **Diary-360 chain COMPLETE (#1841–#1846):** claims ledger (PR #1861 — LLM-proposes/
  code-admits into the ONE prediction grader, consent is-True fail-closed) · vocal
  biomarkers (PR #1875 — pure SRT→6 metrics, SET-only guarded writes, driver-side mypy
  union-attr fix on the branch) · diary-day intervention variable (PR #1877 — explicit-0
  daily count + one idempotent code-registered hypothesis) · channel-divergence prereg
  (PR #1882 — **sealed + published + SHA-verified live** at
  /experiments/prereg/spoken-vs-typed-divergence_2026-07-27.json) · cut→engagement loop
  (PR #1885 — GoodhartViolation fail-closed purpose enum + **import-graph test: nothing
  under mcp/ or lambdas/coach/ may import engagement** — the interviewer is
  engagement-blind by CI-enforced construction) · consent-gated diary shelf (PR #1886 —
  `/story/diary/` + `/api/diary_shelf`, **deploy order honored**: site-api deployed and
  verified live BEFORE the site push; serving the honest empty state, withheld:1).
- **#1396** (PR #1874, 0c934047) — calibration engine as an open artifact:
  `oss/calibration-core/` (MIT, zero deps, Python↔JS bit-parity incl. CPython banker's
  rounding in BigInt) + `/method/grade-your-coach/` live (site-deploy + visual-QA green).
  **OSS repo publication = owner one-liner in PR #1874's body.**
- **Epic #1863 backlog PM upgrade — Now+Next COMPLETE:** ADR-099 amendment (PR #1876 —
  canonical score line, body shapes, closure contract, backfill decision recorded
  verbatim) · label census + prio derivation (PR #1878) · doc-drift repair + PR-template
  Outcome line (PR #1879) · `backlog_next.py` + shared `backlog_contract.py` (PR #1880 —
  verified live) · /uplevel rewired onto the stored rank (PR #1881 — "fresh discovery
  outranks backlog replay" preserved verbatim) · hygiene linter advisory (PR #1883 —
  231-violation honest baseline) · wrap gates (e7)/(e8)/(e9) (PR #1884) · **#1868 corpus
  backfill (no PR — 60 issue bodies, 226→1 violations, zero information destroyed by
  programmatic check, 32 authored-at-backfill Outcome lines provenance-stamped in-body)**.
  Remaining: **#1872** (blocking flip, Later — deliberately settling per ADR-108 pattern)
  + **#1873** (closed-epic comments, Later).

## Verified
Full suite after every merge round (final 8,141 passed / ~2.5m) + 6-dir black/ruff each
round. Site deploys ×2 green incl. visual-QA (calibration page, diary shelf). site-api
deployed direct + `/api/diary_shelf` verified live pre-push. Prereg SHA matches live.
`backlog_next.py`/`check_backlog_hygiene.py` exercised live at wrap. Day-1 watches all
healthy (below).

## Day-1 watches (WS1) — verified live
Docket honest-empty (`/api/coach_docket` live; ensemble digest LLM correctly
paused-by-tier-2, deterministic fallback, 0 disagreements → no opens possible — expected)
· dossier's first real render through #1853's pair-scoped keys + PII screen (6
commitments, 0 withheld, not degraded) · #1840 AC4 both halves (`channel: video_diary`
stamped; diary reaction fail-closed private, nothing leaked; conversational lane honestly
paused_by_budget) · coach-nudge hourly quiet-honest · youtube poller healthy, no upload
yet · **remediation cron DID fire 16:48Z** (~2h schedule drift, not a second miss).
Pending (event-gated): evening intake 03:00Z, first calibration write (nothing resolved
yet — 0 evaluable predictions on Day 1), youtube first capture, Tuesday's first character
sheet + brief citing 321.09 without the advisory.

## Deploy state — the ONE load-bearing dependency
**Main is code-green but Plan reds by design (R8-ST6)** on every push until the #1858 IAM
diff deploys — which also means **CI's Deploy job never ran today: the day's lambda
changes are stranded on main, undeployed** (MCP bundle + diary_claims, coach-prediction-
evaluator, daily-metrics-compute, weekly-correlation-compute, hypothesis-engine,
youtube-social-ingestion). Nothing is broken — the live fleet runs yesterday's verified
code; the new features are dormant until deployed. **RESOLVED same evening — see the Main line: CDK deploy ran, deploy_all-2 green,
fleet current 22:14Z.** Site + site-api were never stranded.

## Gotchas (durable → memory, written)
- **An undeployed IAM merge strands every subsequent CI deploy** — R8-ST6 diffs against
  the DEPLOYED stacks, so Plan reds on all later pushes and Deploy never runs. Land IAM
  merges adjacent to their CDK deploy, or accept a stranded-deploy window closed by
  deploy_all after the gate clears.
- **Never run the wholesale `capture_api_schemas.py` against a freshly-reset platform** —
  it rewrites all ~118 baselines from live shapes; Day-1-empty responses would codify
  reset-era shapes. The `/api/diary_shelf` exemption deliberately stands until data
  stabilizes (stated deviation from PR #1886's post-merge note).
- `git add -u` swept `.claude/settings.local.json` into the #1861 commit (benign
  permission lines; explicit-path staging reaffirmed) · stale `cdk/_bundle_staging/` reds
  local 6-dir ruff (git-ignored; rm -rf) · zsh doesn't word-split unquoted vars (a
  conflict-resolution loop passed a two-file list as one pathspec).

## Wrap gates
**Build beat:** `2026-07-27-grade-your-own-coach` (see beats.json).
**Docs:** carried in-PR (SCHEMA ×3, DECISIONS ×2, CONVENTIONS ×2, CONTINUITY, TESTING,
uplevel/CLAUDE/CONTRIBUTING rewire, DIARY_STUDIO_KIT new); wrap adds none beyond.
**Decisions:** ADR-099 amendment filed (#1865, PR #1876) + the #1324-addendum correction
(#1871); no further ADR needed — remaining choices were implementation posture.
**Main:** green (ea4a57f5) — POST-WRAP UPDATE: Matthew ran the CDK one-liner (stacks
UPDATE_COMPLETE 21:44/21:45Z, ExperimentCycleRead grant verified live on the
milestone-digest role); deploy_all take 2 then went green end-to-end (Deploy+Smoke+
I1/I2/I5+visual-QA; rollback skipped) after take 1 was caught pre-deploy by CI's
--strict engine-doc drift gate (three re-verify stamps for #1843's additive changes,
ea4a57f5 — NB local check_doc_index runs advisory, CI runs --strict). Fleet uniform
22:09–22:14Z incl. us-east-1; the day's features are LIVE.
**Incidents:** 1 row added — budget governor tier 1→2 (by-design band crossing under the
ADR-133 July window; ensemble/reader AI paused; self-resolves 08-01).
**Closures:** #1858 #1859 #1841 #1842 #1843 #1844 #1845 #1846 #1864 #1865 #1866 #1867
#1868 #1869 #1870 #1871 #1396 all carry the (e8) Shipped/Outcome comment (partial where
live evidence awaits the stranded deploy or an owner step — never an unverified
"realized"). Scope = this session's closures only; the overnight session's same-UTC-day
closures predate the contract and stay per the going-forward rule.
**Backlog:** Now 2 actionable stories + 1 chore (promoted #1741, #1840, #1653 by stored
rank; their score-line milestones parity-updated). Next is exhausted — #1114 is
owner-gated in practice (pick on PR #1768). Triage labels added per body evidence: #1187
gate:owner, #1739/#1740 blocked:dep. No stale Later issues (oldest touched 9d ago).
`now_liveness` still prints 1 — honest structural shortfall, reported not hidden. The 2
`score_line_canonical` advisories (#1677/#1679) are float-tolerance artifacts — a
one-line tolerance widen is noted for #1872.
**Stash/hooks:** clean.
**Labels:** OK.

## Residual / next picks
- ~~Owner CDK one-liner~~ **DONE post-wrap** (21:44Z) + deploy_all-2 green — the
  deploy chain is closed; #1858's last AC (a cycle-stamped digest write) proves itself
  on tomorrow's 17:15Z run — not-work — passive watch.
- **Owner, when ready:** publish the OSS repo (one-liner in PR #1874 body) — not-work —
  creating a public repo is Matthew's call · studio-side `PUBLISH_LOG.md` entry column
  (#1845's kit doc has the paste-in) — not-work — file lives outside the repo.
- **#1872** flip hygiene linter to blocking + delete check_story_labels.py (Later — let
  the corpus settle; also consider the 0.375 tolerance widen) · **#1873** closed-epic
  closing comments (Later).
- Vocal-metrics backfill first --apply run against the studio SRTs (#1842's script;
  dry-run verified) — not-work — local run against the private studio dir, Matthew's
  laptop session.
- Day-2 watches: first character sheet (Tue), Tuesday brief cites 321.09 with NO
  freshness advisory, first docket open once tier <2 or a real disagreement, first
  calibration write, evening intake, youtube first capture, Wednesday remediation cron —
  not-work — standing observation ritual.
- Standing alarms (#1329 checklist): budget tier 2 until 08-01 (governor by-design; the
  $85 AWS Budgets backstop deliberately still fires) — not-work — self-resolves; next
  MCP key rotation 2026-10-05 — not-work — dated owner ritual. No aged remediation
  needs-human items (Mon run was clean).
- Queue seeds for next session: `python3 scripts/backlog_next.py` — #1741 (3.00, opus),
  #1840 (2.00, sonnet), #1653 (0.75, chore, solo-wave-by-design).
- Gate:owner set unchanged: #1631 #1629 #1622 #1570 #1407 #1388 #1383 #1768 #1187 +
  digest recipients (#1623) · #1738 listen · #1571 phone test · #1114 pick · Dependabot
  #1778/#1779/#1780 — not-work — each needs Matthew's coordinated step.

Full narrative of the prior overnight session:
`git show origin/session-archive:handovers/HANDOVER_2026-07-26_CI-trust-genesis-day1-rollback-net.md`
