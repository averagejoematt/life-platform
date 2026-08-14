# Handover — 2026-08-14: the first bug bash — six hostile stations, and the gate that passes its own bar while guarding nothing

**Session:** interactive, Opus. Driver + 6 station agents + 1 issue-filer.
**Driver:** "Do I have a good skill to do a full deep review and qa and bug bash — if not can you plan a session like that", then "just run the session", then "yes do all" (authorising production writes), then "yes do 1-3" (cleanup, file, fix).

**Build beat:** none — PRs #2648 and #2684 are OPEN; nothing merged or deployed this session, and the beat gate is merged-and-live only.
**Docs:** `docs/CONVENTIONS.md` §9a (new — the fixture-must-be-the-wire rule), `docs/INCIDENT_LOG.md` (+1 P1 row)
**Decisions:** none needed — the session applied existing contracts (ADR-104 honest numbers, ADR-099 filing, ADR-065 IAM denylist, ADR-032/033/046 S3 delete protection). The one durable rule earned is a CONVENTIONS §9a entry, not an ADR: it sharpens #2578's bar rather than establishing new governance.
**Main:** green (`45253dfa`)
**Stash/hooks:** clean — `git stash list` empty
**Closures:** none — no issues closed this session (39 filed, 0 closed)
**Incidents:** 1 row added — the between-chronicle privacy no-op + the dead AI-quality canary, both from #2503's missing IAM grant
**Alarms:** clean — every alarm red >72h cites an issue or incident row
**CI warnings:** 6 — 5 are the CDK Lambda-config drift already filed as #2468 (note: it is now **five** stacks, not the four the issue title says — Serve, Operational, Email, Compute, Ingestion); 1 is the content-policy-scan skip already filed as #2644. No new issue; both are known and owner-gated.
**Backlog:** Now holds actionable work after this session's filing (9 P1s landed on Now); no `Later` staleness findings printed. Hygiene gate green at 79 open issues.

---

## What this session was

There was no bug-bash ritual. There were seven review skills — `/platform-review`, `/fullreview`, `/craft-review`, `/sdlc-review`, `/accuracy-review`, `/qa`, `/site-review` — and **every one of them is read-only by charter**. `/platform-review`'s brief says it outright: *"read-only always — no Lambda/Bedrock invocation, no AWS mutation."* 824 test files run against mocks. Nothing had ever sent a malformed date to `/api/*`, a prompt injection to `/api/ask`, or a double vote to a write endpoint.

So the session ran the missing ritual: **exercise the live system adversarially**, six stations in parallel, then verify, then file, then fix.

## Findings — 39 issues filed under `review:bugbash-2026-08-14`

**Epics:** #2645 gate calibration · #2646 public-API unhandled input · #2647 MCP argument validation

**The P1s:**
- **#1221 reopened** — rate-limit identity is client-forgeable across the whole site API. Three limiter families bypassed (conditional-put vote dedup, DDB `_rate_check`, in-memory nudge). Mechanism test rules out coincidence: *same* forged IP → 429, *new* forged IP → 200. Every public vote count is stuffable; `generated/findings/` and `generated/board_questions/` are unbounded write targets. Verified premise: `/api/*` carries `OriginRequestPolicyId: null`, so `CloudFront-Viewer-Address` never reaches the Lambda — that, not another hop index, is the fix.
- **#2654 / #2655** — `between-chronicle`'s privacy scrub is a live no-op (fail-open `except Exception` over a deliberately fail-closed contract, with all three vocabulary channels dead), and `ai-quality-canary` has failed 100% of runs since 2026-08-10. Both are #2503 casualties. With #2644 that is **four** silent breakages from one change.
- **#2656 / #2657** — unauthenticated 502s on `/api/vitals` (string-compared date clamp) and `/api/changes-since` (guard wrapping only `int()`). **Fixed in PR #2648.**
- **#2679** — every capture door 502s on a non-string JSON value; the module already owns the type guard it doesn't call.
- **#2658** — `/api/predictions?limit=abc` returns **HTTP 200** with the coach ledger zeroed (80 this cycle, 2,580 lifetime → all empty). Honest-numbers surface.
- **#2659** — MCP negative relative windows leak raw DDB `ValidationException` and tell the caller a permanently-failing request is transient. 6 of 6 tools tried.
- **#2668** — the daily brief's IC-3 analysis pass has failed 10 of the last 12 days on JSON truncation at `max_tokens=600`, as a WARN, with `Errors` at 0.0.
- **#2670** — `qa-smoke-failures`/`-warnings` continuously in ALARM 14 and 27 days, so neither can make an OK→ALARM transition and neither can ever signal a new failure.
- **#2680** — CloudFront rewrites every API `403` to `200 OK` + the homepage. A tamper-rejected signed write reports success on the wire; this also swallows the SEC-04 origin-secret rejection.

## The finding that matters most (now CONVENTIONS §9a)

`tests/test_client_ip_extraction.py` is **green, non-vacuous, and worthless**. Its author wrote `test_non_vacuity_old_leftmost_logic_would_have_failed` specifically to prove it isn't hollow — so it **passes #2578's "prove every armed gate can fail" bar honestly** — and it still guards nothing, because its fixture hand-builds `X-Forwarded-For: "evil-spoof, 203.0.113.9"`, encoding an assumption about CloudFront that this distribution contradicts.

**Mutation-provable ≠ true.** The gate census's missing axis is not *can this fail*; it is *is the fixture the wire*. #1221's own title has described the live bug accurately the entire time it sat closed.

## What shipped

- **PR #2648** (open) — the two 502 classes. Tests drive the real `lambda_handler` and assert *rejection precedes data access*; mutation-proved at 11-of-14 failing against pre-fix code. Site-api subset: 1,245 passed.
- **PR #2684** (open) — `s3:GetObject` on `config/content_filter.json` for the two roles that lost it. **Needs an owner-run `cd cdk && npx cdk deploy LifePlatformEmail LifePlatformOperational`.**

## Cleanup from the write station

Station 3 made 46 requests / 23 successful production writes, all ledgered. Cleaned this session: **7 DDB items deleted** (each inspected for the `BUGBASH-20260813` marker first; the one unmarkered row confirmed by timestamp + uniqueness) and **4 counters decremented to zero**, including a deliberately no-TTL replicator row that would never have expired. All verified post-delete.

**Not cleaned:** 4 S3 objects under `generated/findings/` + `generated/board_questions/`. The ADR-032/033/046 bucket policy denied every `DeleteObject` — the guard working correctly. Keys are in the ledger.

## Gotchas hit (driver errors, caught before publishing)

1. **`aws lambda list-functions --no-paginate` returns the FIRST PAGE ONLY** — 50 of 110. It nearly produced "strava has no ingestion Lambda". `--no-paginate` does not mean "give me everything."
2. **A trailing `echo`/`tail` in a bash chain masks the real exit code** — a background task reported "exit code 0" for a pytest run that exited 1. Read the actual `$?`, not the harness's summary.
3. **A malformed `--query` produced a false finding** — my first IAM sweep reported both public Lambdas couldn't read the vocabulary. False; site-api and site-api-ai both hold `S3ConfigRead`. A station agent's read was right and mine was wrong.
4. **I wrote the disposition map before the last station finished** and never went back — six findings including a P1 were invisible to the filer until it flagged the gap.
5. **macrofactor's 51-day silence is genuinely behavioural**, not an outage. Chased hard as an ADR-104 violation; refuted (S3-event-triggered by design, poller healthy 53×/day, secret valid).

Three of my own hypotheses died under verification. One station agent refuted me with a better experiment than I had run.

## Residual / next picks

- Second PR for the two remaining code-fixable P1s: the coach-ledger zeroing (#2658) and the capture doors (#2679). Small, same module family as #2648, test pattern established.
- The four infra changes needing an owner deploy: #1221 (CloudFront origin request policy), #2680 (403→200 rewrite), #2654/#2655 (PR #2684 is ready).
- `not-work — owner decision` : whether to grant a temporary bucket-policy exception to delete the 4 stranded `generated/*` bug-bash objects, or leave them as inert test rows.
- `not-work — owner decision` : #2468's title says four stacks; it is now five. Retitle or leave.
- Package this ritual as `.claude/commands/bugbash.md` so it is repeatable — the six-station shape, the marker+ledger discipline, and the "which gate should have caught this" phase all earned their keep (#2645 is the closest epic home).
