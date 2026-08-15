# Handover — 2026-08-14 (eve): working the bug-bash queue — and shipping a security fix that disabled the control it was fixing

**Session:** interactive, Opus. Driver only, no subagents (the brief forbade them).
**Driver:** a scoped work order — land the two open bug-bash PRs first, then work the ranked non-fable `Now` queue (#2658, #2679, then by score), with a standing discipline block: every fix ships with a regression test watched failing pre-fix, read `CONVENTIONS.md` §9a before any test crossing a service boundary, verify with a command rather than a code reading. Plus one decision to put to Matthew: whether to pull `model:fable`-labelled #1221 into scope.

**Build beat:** `2026-08-14-the-fix-that-broke-the-thing-it-fixed`
**Docs:** `docs/INCIDENT_LOG.md` (+1 P2 row, `Last updated:` bumped) · `docs/CONVENTIONS.md` §9a (resolution paragraph — names the replacement guard and states why an index assertion is a claim about infrastructure while an invariant over adversarial inputs is a claim about code)
**Decisions:** none needed — the session applied existing contracts (ADR-104 honest numbers, ADR-099 filing + closure, ADR-065 IAM denylist, §9a fixture-is-the-wire). The rate-limit ordering choice is recorded in the module docstring and pinned by a test, not governance.
**Main:** green (`4b6cfd6a`)
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢
**Closures:** #2656, #2657, #2658, #2679 commented (all `realized`, each with live post-deploy evidence). #1221 auto-closed by accident and was **reopened** — see gotchas.
**Incidents:** 1 row added — a security fix that disabled rate limiting on the public write surface for ~40 min, caught by a live post-deploy probe rather than by any test or alarm.
**Backlog:** Now live at 21 actionable (23 total); no stale `Later` issues; no promotions needed.
**Alarms:** 0 uncited — every alarm red >72h cites an incident row or issue, and none red >14d lacks a filed issue.
**CI warnings:** 8 — 6 × `cdk deploy <Stack>` config drift → **#2468** (updated in-session: it is now six stacks, not four; Mcp and Serve joined, and Email/Operational still drift *after* today's owner deploy, so their residual is Lambda config, not the IAM this session shipped); 1 × content-policy-scan skipped → **#2644** (pre-existing, needs the CI secret); 1 × Unit Tests 1247s over the 1200s budget → **#2692 filed** rather than raising the budget a fourth time unmeasured.

---

## What shipped and is live

All merged, deployed, and verified against the wire — not from a green check.

| PR | Issue | What | Mutation proof |
|---|---|---|---|
| #2648 | #2656, #2657 | two unauthenticated 502s (`/api/vitals`, `/api/changes-since`) | 11/14 pre-fix (inherited, opened before this session) |
| #2685 | #2658 | coach ledger answered 200 with a zeroed scorecard on failure | **30 of 33** |
| #2687 | #2679 | capture doors 502'd on a non-string field or non-object body | **93 of 127** |
| #2689 | #1221 (partial) | rate-limit identity — Lambda half | 20 of 26 |
| #2691 | #1221 (correction) | **restores XFF fallback after #2689 disabled enforcement** | — |

Also merged: **#2684** (owner-deployed) — the content-filter IAM grants.

**Each issue's filed scope was smaller than the real defect, and in two cases fixing only what was filed would have closed the issue with the symptom still reachable:**

- **#2658** — `_parallel_fetch` catches each partition error *individually*, so a **total** DynamoDB outage produced a fully zeroed scorecard at HTTP 200 by a path the reported `limit=abc` fix never touches. Also found: `limit=-5` reached `all_predictions[:limit]`, a negative slice, silently dropping the five most recent calls.
- **#2679** — the issue named four doors; deriving the set from `_SIMPLE_ROUTES` + an AST sweep found **eleven**, including `/api/cohort_submit` (fully type-guarded on its `value`, but still missing the body-object check). `/api/replicate_certify` is deliberately excluded — it reads no body at all.
- **#1221** — reproduced live, then the fix regressed it. See below.

## The headline: a security fix that disabled the control it was fixing

#1221 was confirmed live first (three runs against `/api/submit_finding`, limit 3/hour, malformed body so nothing is stored):

```
forged XFF 203.0.113.77  x5  ->  400 400 400 429 429    bucket armed
forged XFF 198.51.100.42 x2  ->  400 400                FRESH bucket — evaded
no header at all         x5  ->  400 400 400 429 429    a third bucket
```

Only one model fits: **CloudFront forwards the client's `X-Forwarded-For` unchanged**, adding its own only when absent — so the last hop *is* the caller's value and no hop index is safe. That is why the 2026-07 "fix" (first-hop → last-hop) could not have worked, and why the issue's own title described the live bug for the month it sat closed.

#2689 removed XFF entirely and fell back to `requestContext.sourceIp`, reasoning it is coarser but un-forgeable. **Deployed, then re-measured: `400 429 400 400 400 400`.** One 429 in six means the identity was changing between requests — `sourceIp` is the CloudFront *edge* address and is not stable per viewer, so nearly every request minted a fresh bucket. For ~40 minutes every IP-gated write was effectively unmetered.

**Nothing owned by this repo could have caught it.** 18,421 tests passed, every deploy gate went green, smoke and visual/AI QA passed. The defect lives in the relationship between the code and the edge — which every fixture *asserts* rather than *observes*. That is the §9a class this same session had just documented, and it bit anyway.

#2691 restored the order `CloudFront-Viewer-Address` → `X-Forwarded-For` last hop → `sourceIp`, and verified live: fixed-forged and ordinary traffic both back to `400 400 400 429 429`; rotating the header still returns 400, which is the known-open bypass. A test now pins the **order** so a future "hardening" cannot silently re-disable enforcement.

## Gotchas (all mine, all worth carrying forward)

1. **The evidence was in front of me.** #1221's body records that `site_api_ai_lambda`, keying on raw `sourceIp`, produced *17 consecutive POSTs → 0 × HTTP 429*. I read that as "that limiter is broken" instead of "`sourceIp` is not an identity" — and skipped testing stability because I thought it needed Bedrock spend, when `/api/submit_finding` answers it for free and I was already probing it.
2. **Auto-close ignores English, again (2nd time in 4 days).** #2691's body opened with "no auto-close keyword — the bypass is still open by design" and then, three paragraphs later, used the phrase *"sufficient to close #1221"* in ordinary prose. That closed a P1. Memory updated with the variant and the one-line grep that catches both occurrences: `grep -oiE "(close[sd]?|fix(e[sd])?|resolve[sd]?) #[0-9]+"`.
3. **A green Deploy job is not a deployed fix.** First post-deploy probe of #2656 showed `9999-99-99` returning 200 — a CloudFront cache hit (`Age: 1271`, `max-age=86400`) serving the pre-fix response. Cache-busted, it was a clean 400. Trusting either the green job *or* that first curl would have been wrong, in opposite directions.
4. **`$FILES` word-splitting faked a mutation proof.** An unquoted variable made `git checkout HEAD -- $FILES` fail while a later `echo` reported "127 passed" — a meaningless green. Re-ran with explicit filenames and a `set -e`.
5. **~50% of grep-derived findings were false.** Four sibling `limit` handlers looked identical to #2658's bug; all four already had the correct `except (TypeError, ValueError)` guard. Reading them beat filing them.
6. **`int("٣") == 3`** — Python accepts any Unicode decimal digit, so that input was never invalid. My own test caught the wrong assumption before it became a pinned contract.
7. **Merge order matters when PRs share an auto-stamped literal.** All three touched `site_api_common.py`'s `test_count`; the third went `CONFLICTING` and needed a rebase + `sync_doc_metadata` restamp rather than a hand-picked number.
8. **A superseded gated run is a live hazard.** `df8f85bb` sat waiting carrying only #2685; approving it later would have deployed older code *over* the newer fleet. Rejected it explicitly (deploy-group lease).

## Residual / next picks

- **#1221** — the origin request policy. **Owner-run infra, and larger than the acceptance line reads:** CloudFront rejects `ForwardedValues` alongside `OriginRequestPolicyId`, and every `/api/*` behaviour in `web_stack.py` uses the legacy form. Landing it means migrating ~20 cache behaviours onto explicit cache + origin-request policies while preserving each one's query-string/TTL semantics. Managed policy carrying the header: `Managed-AllViewerAndCloudFrontHeaders-2022-06` (`33f36d7e-f396-46d9-90e0-52428a34d9dc`). Also still open on that issue: AC5, `board_ask`'s Bedrock fan-out counted against the same limit.
- **#2654** — between-chronicle's `_scrub` fail-open is **unchanged**. The IAM grant means the vocabulary now loads, so the live unscrubbed-mail path is closed in practice, but the structural `except Exception` will convert the next unrelated failure into the same silent outcome. End-to-end proof needs an invoke with sending disabled — the function carries `EXTERNAL_EMAILS_ENABLED`.
- **#2655** — `_from_s3_boto` still swallows `AccessDenied`, no DLQ, and `ai-canary-heartbeat` is still in ALARM. Its schedule is `MON,WED,FRI 16:20 UTC`, so **Monday's run is the first real observation** post-grant.
- **#2686** — 14 `200-on-except` sites in `web/`, triaged in the issue into six that render zeroed counts as if measured vs. legitimately shaped-empty.
- **#2688** — #2679's class in `site_api_ai_lambda` (`/api/ask` returns 500 on a mistyped field). #2687's guard structurally cannot see it — different Lambda, different route table.
- **#2692** — Unit Tests wall-clock crossed its budget a fourth time; measure before raising it again.
- **#2468** — six stacks now carry Lambda config drift CI cannot ship; needs an owner `cdk deploy`.
- **#2680**, **#2644**, **#1738**, **#1571** — untouched, owner-gated or CI-secret-gated per the brief.
- `not-work — the ~24h CloudFront cache on pre-fix `/api/vitals?date=<impossible>` 200s will expire on its own; invalidating `/api/vitals*` is available if a stale reader is ever observed, but the URL class is narrow enough that it was flagged rather than acted on.`
