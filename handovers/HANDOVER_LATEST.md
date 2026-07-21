# HANDOVER — Backlog paydown: a false closure caught, the Glass Engine shipped — 2026-07-21

> Instruction thread: "read memory handover and all open issues and lets see what we
> recommend doing in this session to pay down the backlog using opus model" → then
> "yes and you do it if you can", "you are approved to merge", "Take more", "ok".
> Authorization arrived incrementally; every merge and the one deploy was explicitly
> approved. The `cdk deploy LifePlatformOperational` was deliberately NOT read into
> "ok" — IAM grants are user-named (memory rule), so it stays in the owner queue.

## Outcome — 3 PRs merged + deployed, 2 issues corrected off false evidence, main un-redded

**The find that shaped the session.** The recommendation pass turned up that **#1334 and
#1453 were closed on 2026-07-19 citing "SHIPPED via PR #1491 (merged)" — and PR #1491 was
never merged.** It was open, `DIRTY`, and none of its code was on main:

```
git grep -c "check_github_quota" origin/main -- deploy/drift_sentinel.py   → (nothing)
git grep -c "quota_html" origin/main -- remediation/drift_report.py        → (nothing)
```

The capability those issues claimed to ship is a **warn at 70% of the 3,000-minute Actions
allowance** — precisely what would have caught #1544 (minutes exhausted → 6 silent merges →
CI dead for a day → forced public repo flip) before it bit. The backlog believed that guard
existed. It did not.

**1. #1491 rebased + merged** (`c4ebefae`). Four conflicts, all the same shape: main's
#1320/#1544 GitHub-posture checks had taken the exact slots #1491 wanted. Resolution was
additive — posture keeps checks 6/7, quota became check 8. Both #1334 and #1453 now carry a
correction comment with commands a reader can run.

**2. The Glass Engine, #1397** (PR #1616 + follow-up #1617) — new `GET /api/receipts` +
`/method/receipts/`. Live at build `787f95f`. Every figure reads from what `cost_governor`
already writes; the governor's math is deliberately NOT reimplemented (a second
implementation could disagree with the governor, and then the page that exists to make
spending legible would be the thing lying about it). Two honesty properties, both tested:
a stale/missing breakdown **omits every dollar figure and states the reason** rather than
freezing at last-known values, and per-feature usage is reported in **tokens, not dollars**
because the per-Lambda metric stream carries no model dimension.

**3. main un-redded** (`98c49d27`). The 2026-07-20 wrap wrote its residuals under an
`## Owner queue` heading; `check_residual_queue.py`'s `SECTION_HEADER` only matches
`.*residual.*next.?pick`, so the #1340 gate found no section at all and
`test_residual_queue_gate_1340` failed on **every** main Unit Tests run since `68b9f0ca`.
Renamed to the canonical heading and converted the numbered items to `- ` bullets — which
also means they are now actually *subject* to the gate rather than invisible to its splitter.

## Verified

- Full suite **6356 passed** / 55 skipped / 10 xfailed; **84 JS tests** (`node --test`).
- 30 new tests: 14 Python (`test_receipts_endpoint.py`) + 16 JS (`evidence_receipts.test.mjs`).
- site-api deployed (`CodeSha256 mrTcy4K6RotR7DQ6GyqTquhH6YtGrwf1d3lpmb4OGMk=`), `/api/receipts`
  200 live, schema baseline captured from live.
- Site deploy **completed success** on `787f95f1` — smoke + visual-QA green, no auto-rollback.
  `version.json` build `787f95f` == git HEAD.
- Render-QA: 4 payload states × both themes × 1280/390 pre-merge (mocked), then again against
  **live**. Zero console errors, zero horizontal overflow in all runs.

## Gotchas hit (durable)

- **A keep-both conflict resolution silently ate a `return`.** Concatenating both sides of the
  big `drift_sentinel.py` hunk dropped `check_github_push_runs`'s `return result` — the trailing
  return was shared context both sides claimed. Seven of main's own tests went red with
  `'NoneType' object is not subscriptable`. A marker-grep would have passed; only running the
  tests caught it. Same family as the committed-conflict-marker class, one level subtler.
- **ESM static imports resolve before a registered loader runs.** A `tests/js/` file that
  statically imports a module carrying root-relative `/assets/js/…` specifiers fails with
  `ERR_MODULE_NOT_FOUND` even though `./support/loader.mjs` is imported first — linking happens
  before evaluation. The house fix is top-level `await import()`.
- **Regenerating evidence pages without the chrome sweep is a sitewide regression.**
  `v4_build_evidence.py` alone stripped `<aside class="loop-forward">` from every page;
  `scripts/v4_apply_chrome.py` restores it. Run the pair, never the builder alone.
- **A live capture rewrites all 107 API baselines.** Only the new one belonged in the PR; 28
  others carried real post-reset shape drift (overwhelmingly additive) that is not reviewable
  inside a feature diff.
- **An IAM hypothesis that looked certain was wrong.** `role_policies.py` scopes site-api's SSM
  read to `budget-tier` only while the handler also reads `budget-breakdown` — which read as a
  live defect. `simulate-principal-policy` said both were **allowed**; the grant lives in
  `cdk/stacks/lambda_helpers.py:261`. Verify the capability, not the file.

## Live state at wrap

- **Budget: tier 2, projected $96.09 against an $85 ceiling (113%).** Reader narratives
  (coach commentary, State of Matthew, chronicle) are paused by the governor. Matthew has said
  the overrun is acceptable this cycle — but accepting it does not un-pause anything, because
  tier derives from projection ÷ ceiling. Raising `MONTHLY_CEILING_USD` is the only lever.
- Cycle 9, genesis 2026-07-20. Board **76 open** (filed #1613, #1618).
- Dark sources: hevy resolved as **human-side — Matthew hasn't trained**, not a defect.
  notion (2026-05-25) and strava (#1330) unchanged.

---

# SECOND THREAD (same day) — social distribution: three boards, one denial

> Instruction: "with my averagejoematt.com domain is it possible within AWS to create an
> email address?" → widened to social handles, then "put plan together and create all issues
> in git and then we will wrap. And use external product and board counsel to put a plan
> together on what things matter in this journey."

**Zero repo code changed in this thread.** Output was live DNS, 15 GitHub issues, and one
memory topic. No PR, no deploy, no beat.

## Shipped (infra + backlog, not code)

**Mail on `averagejoematt.com` is live** — `matt@averagejoematt.com` forwards to Proton via
**SimpleLogin** (Proton's alias service), which `mattsusername.com` was already running.
Records added to Route 53 zone `Z063312432BPXQH9PVXAI`, all verified resolving from both the
authoritative NS and 1.1.1.1: MX (`mx1`/`mx2.simplelogin.co`, 10/20) · apex TXT carrying BOTH
`sl-verification=…` and `v=spf1 include:simplelogin.co ~all` on one RRset · three DKIM CNAMEs
(`dkim`/`dkim02`/`dkim03._domainkey`) · `_dmarc` at `p=quarantine; adkim=s; aspf=s`.
No SES, no Lambda forwarder — the existing paid alias service already did it.

**Epic #1619 + 14 stories filed** from a three-board review (Product / Personal / Technical,
`docs/BOARDS.md`), label `review:social-boards-2026-07-21`.

## The verdict that shaped it

Matthew asked for milestone/achievement/weigh-in autoposting. **The Personal Board denied it
on the merits — not deferred pending guardrails.** The reasoning, which the Chair adopted:
the injury in the documented downturn pattern is not the regression, it is the *outstanding
public victory-claim the regression contradicts*. An automated milestone bot manufactures
~50 standing claims/year without conscious participation; guardrails reduce the rate, not the
kind. Worst case is the bot celebrating during a downturn — the platform's founding failure
with a megaphone. Rationale kept at that level here and in the issues; detail lives in
`docs/PLATFORM_CONTEXT.md` (PRIVATE).

Three independent supports: `handle_achievements()` is stateless so badges **un-earn and
re-earn** on normal 2–3 lb swings (#1624); a bare "10 lbs down" is an unlabeled point estimate
ADR-105 would red; and ADR-104 fails in *both* directions — wins-only is a highlight reel,
symmetric auto-setbacks are harmful on acontextual public surfaces. **When both branches of a
feature fail the honesty ADR, the feature is the problem.**

**Approved instead:** content posting (chronicle/podcast/essay drops — the surface that already
contains the down-weeks), and **a private digest to 5–8 named humans** (#1623) adopted as the
priority, because *the notes stopping* is a far better downturn signal than public silence.

## Gotchas hit (durable)

- **Namecheap is registrar-only for `averagejoematt.com`; Route 53 serves the DNS.** Its
  "Advanced DNS" screen is inert — records entered there are silently ignored. Nearly edited
  the wrong system. → memory `reference_averagejoematt_dns_and_mail.md`.
- **SPF must join the apex TXT RRset, not replace it** — a separate change would have wiped the
  SimpleLogin verification string.
- **X repriced to pay-per-use (Feb 2026): $0.20/post when the post carries a link**, and every
  post this platform would make carries one. At 2/day that is 14% of the $85 ceiling — and it
  is a third-party bill Cost Explorer cannot see, so `budget_guard` structurally cannot gate
  it. ADR-063's "one budget covers ALL spend" goes false the day X ships (#1631).
- **`create_platform_lambda` defaults to AWS's 2 async retries** — POST succeeds, response
  parse throws, Lambda re-invokes, **posts again**. `retry_attempts=0` is four characters and
  does more real safety work than the whole claim protocol (#1629).
- **`social` is already taken** — `lambdas/web/site_api_social.py` + `mcp/tools_social.py` mean
  *social connection*, the loneliness pillar. Any syndication code must not reuse the word.

## Residual / next picks

- **#1613** — the CI-minutes 70% warn is installed but **inert**: the billing API needs a
  `user`-scoped PAT, and `_gh_api_json` doesn't read the token-preference path the posture
  checks use, so adding `GH_POSTURE_TOKEN` alone would not light it up. Until it lands, treat
  CI-minutes metering as observability, not an alarm.
- **#1618** — `/method/receipts/` plots month-to-date only, so the curve reads "on budget"
  while the readout says 113%. A dashed projection segment reconciles them.
- **#1589** — closes once `cdk deploy LifePlatformOperational` lands (canary IAM); that same
  deploy clears main's by-design R8-ST6 Plan red. (user-NAMED IAM)
- **Budget ceiling decision** — not-work — an owner call: leave tier 2 to ride out the month,
  or amend ADR-133 + bump `MONTHLY_CEILING_USD` (~$110 → tier 1, reader narratives back on).
- **API baselines are 2 days stale** — not-work — 28 snapshots carry real post-reset shape
  drift; a standalone refresh commit, deliberately not bundled into a feature PR.
- **#1330** strava token-health (gate:owner) and **#1029** re-entry hardening remain the
  standing owner-gated security items.
- Standing alarms: no unactioned digest-routed freshness alarm or manual-rotation secret
  reminder surfaced this session. not-work — a #1329 checklist confirmation, nothing to file.

_Second thread (social distribution):_

- **#1622** is the gate for the whole syndication lane — a 30-day manual-script trial, and
  **#1629's Bluesky poster does not start until it is used ≥15/30 days.** Automate a proven
  habit, never a hoped-for one; the remediation agent (ADR-129/103) is the cautionary mirror.
- **#1624** — `handle_achievements()` statelessness is a live site correctness defect
  independent of any social plan, and a hard prerequisite for **#1626**'s milestone ledger.
- **#1627** — the downturn leading-indicator detector arrived sideways as a guardrail, but
  sleep-midpoint variance leading by 1–3 weeks may be the most valuable thing in the batch.
  Worth re-ranking on its own merits rather than as a social dependency.
- **#1402** — overlaps the new epic (it specs the daily-card poster this verdict partly
  denies). Commented, not closed. not-work — a triage call for Matthew: close as superseded,
  or narrow to its card-rendering half.
- **TikTok handle** — the registered handle is `avereagejoematt` (extra `e`). not-work — an
  owner fix; **#1620 must not link it until corrected.**

**Build beat:** `2026-07-21-the-glass-engine`
**Docs:** none needed — no deploy path, data model, engine, MCP tool, secret or site-authoring
contract changed; the new page registers through the existing evidence REGISTRY, and
`sync_doc_metadata.py` carried the endpoint/test-count literals.
**Decisions:** none needed — the `/method/receipts/` path choice over the issue's
`/build/receipts/` is an IA placement within the documented Home + 5 doors, not a new posture;
the tokens-not-dollars call applies ADR-104 rather than amending it.
**Main:** red — the by-design R8-ST6 Plan gate on the `AiReviewPackRole` + canary-secret IAM
diff, pending Matthew's `cdk deploy LifePlatformOperational`. Lint, Unit Tests, and
Deploy-critical all green on `787f95f1`; Unit Tests went green again this session.
**Incidents:** 1 row added — budget tier escalated to 2 with month-end projected over the
ceiling (113%).
**Stash/hooks:** clean (stash empty; hook freshness 🟢).

_Second-thread gates (social distribution):_
**Build beat:** none — zero repo code changed; the thread produced live DNS, 15 issues and one
memory topic, none of which is merged-and-deployed public build work.
**Docs:** none needed — no repo doc surface touched; the DNS/mail reflex went to memory
(`reference_averagejoematt_dns_and_mail.md`), which is outside git by design.
**Decisions:** none needed this session — the governance call (amending the documented
anti-auto-posting stance at `chronicle_share_kit.py:19`) is deliberately deferred to **#1630**
so the ADR lands with the implementation rather than ahead of it.
**Incidents:** none.

Prior session: `HANDOVER_2026-07-20_OpusNoFable.md`.
