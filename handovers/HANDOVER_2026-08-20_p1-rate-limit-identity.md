# Handover — 2026-08-20 eve → 2026-08-21 (~17:07 PT → ~07:3x PT): the only P1 is closed, and I closed it once by accident first

**Session:** Opus, owner-directed (plan `quizzical-wandering-dawn.md`, model ceiling Opus). Boot was
**charter + `blast_radius.py`**. **No `model:fable` issue touched** — by design. Previous wrap archived
as `HANDOVER_2026-08-20_deploy-plane-cluster.md`.

**Build beat:** none — the work is a CloudFront policy migration, a rate-limit identity change and an
AI fan-out charge. Per `docs/content/BUILD_DISPATCH_CHECKLIST.md` a beat must be merged **and**
deployed work a reader can see. A reader sees nothing here; the only user-visible effect is that a
full coach panel now costs its true price (below).

**Main:** green — the last CI/CD run (`7d1abf93`, the capture-door fixture fix) passed every job,
Deploy correctly skipped on a tests-only diff. HEAD `e90a4f65` is docs-only and therefore mints no
CI/CD run: a **path-filter skip**, classified as such by `--head-coverage-check` (`Docs CI` and
`Remediation Agent` both ran and both passed), not the swallowed-push shape.

**Closures:** #1221 (P1) `realized`, #2931 (auto-filed, cleared). **Count: 86 → 86 — a net drain of
ZERO.** Two closed, two filed: **#2931 was auto-filed mid-session** and **#2932 I filed at wrap**.
Reporting "two closures" without the two filings would have claimed a drain that did not happen. What
actually changed is the *composition*: the only P1 is gone, and a latent silent-data-loss hazard that
was invisible before is now on the board.
`model:fable` **25, untouched.** **PRs:** #2928, #2929, #2930 merged.
**Deploys: TWO, both owner-approved** — `LifePlatformWeb` (02:10Z) and a deliberate fleet
`deploy_all=true` (09:00Z). **Gates: 4 rejected, none left parked.** Stash clean. Alarms 0 uncited.

---

## #1221 closed `realized` — the bypass is shut in production

The only P1 on the board, and live-exploitable when the session started: per-IP rate limits on every
IP-gated write (subscribe, votes, follows, nudges, checkins, board_ask) could be defeated by rotating
one header.

**The code half had already shipped.** `client_ip.py` preferred `CloudFront-Viewer-Address` — a header
CloudFront sets from the TCP peer that a client cannot forge. **Its preferred source never arrived:**
all 21 cache behaviours used legacy `ForwardedValues`, which forwards only the headers it names, and
that was not one of them. So it always fell through to `X-Forwarded-For`, which this distribution
forwards **unchanged from the client**.

### Box 1 — proved by behaviour, not by template

Six POSTs, six **different** forged `X-Forwarded-For` values, after the policy deploy:

```
203.0.113.11  400      203.0.113.14  429   <-- armed, despite a brand-new forged IP
203.0.113.12  400      203.0.113.15  429
203.0.113.13  400      203.0.113.16  429
```

Re-confirmed in a second independent hourly window. Before the deploy every rotation minted a fresh
bucket and `429` never appeared at all.

### The design constraint that shaped the whole PR

**`CloudFront-Viewer-Address` is in both origin-request policies and in NO cache policy.** Under
`ForwardedValues` one header list did both jobs; policies split them. The value is unique per viewer,
and `/api/*` is the **only cached** `/api` behaviour (`0/300/3600`) and the busiest read path — putting
it in the cache key would have turned one cached object into one-per-client. A latency and cost
regression, shipped in the name of a security fix. `tests/test_cloudfront_viewer_address_policies_1221.py`
enforces both halves with mutation proof.

Six behaviours, four distinct cache-key shapes, three Lambda-FURL origins (so
`OriginRequestHeaderBehavior.all()` was unusable — it forwards `Host`). `web_stack.py` went
**1084 → 1071**; the migration removed more than it added.

### Box 5 was larger than filed, and the code disagreed with itself

`BOARD_RATE_LIMIT = 5` bounded *requests*. One board_ask makes one Bedrock call **per persona**, the
**caller** picks the persona list, and the rate check ran *before* that list was resolved:

```
COACH_ROSTER    7 coaches
OLD ceiling     5 x 7 = 35 Haiku calls/IP/hour   for 5 tokens
NEW ceiling     5     =  5 Haiku calls/IP/hour
```

Two numbers in the code were wrong: the constant's comment said "up to 6 Haiku calls", and the
`personas[:8]` cap never binds because the roster holds 7. The limiter's own docstring already flagged
board_ask as cost-bearing (`fail_open=False`, *"never unmetered"*) while the metering was off by 7x.

**The fix is not "move the rate check down"** — that would leave the follow-up path uncharged, and a
follow-up genuinely *is* one Bedrock call. So one token is still charged up front and the remaining
fan-out is charged once the list is final, via a new `cost=1`-default on the shared limiter.

**Verified live at zero cost:** a full 7-coach panel costs 7 against a limit of 5, so it is refused
*before* any paid call — `HTTP 429`, `{"Endpoint": "board_ask", "RateLimitHit": 1}`, and **no Bedrock
invocation in the window**.

**User-facing effect, stated plainly:** a full panel now consumes 7 of 5 hourly tokens — one panel per
hour, where before it was five. If that proves too tight, raise `BOARD_RATE_LIMIT` deliberately with
the cost visible; do not un-meter the fan-out.

## What I deliberately did NOT verify

- **Box 2's fail-closed branch is not externally reachable.** Every request arrives through CloudFront
  with the header, and direct Function-URL access returns **403** (origin-secret guard armed,
  verified). Covered by unit tests, not a live probe. Said so on the issue rather than implying
  end-to-end proof.
- **Box 4's other two limiter families are structural, not live.** Arming `/api/ask` costs real Bedrock
  calls and posts junk questions to a live site; `/api/nudge` validates category *before* the rate
  check, so any probe reaching the limiter writes real data. Spending the AI budget to re-prove a
  property of the identity function already proved at the edge was not a trade worth making unasked.
  All three consume the same helper, enforced fleet-wide by AC4's AST guard.

## Four self-inflicted failures, all caught

1. **I closed #1221 by accident, mid-series.** PR #2928's body read *"`Fixes #1221` is **not** claimed
   here"* — **a negated closing keyword still closes**; the parser does not see the negation. Reopened
   within a minute. The trap is in my own memory and I briefed three workers on it the same day. The
   remaining PRs used `Part of #N`.
2. **A production gate sat 2.1h** and the platform **auto-filed #2931** about it — the wedge detector,
   urgent-alarm dispatch and issue-filing all worked with no human involved. I was the human who did
   not action it. This was the **second** time in two sessions, after I wrote *"sweep in a loop, not
   once"* into the last wrap and then swept once. Applying it properly found a **second** gate queued
   behind the first — the exact shape a single sweep misses.
3. **#2930's real lane failed on a docstring.** `THE FIX` is seven characters, so its `=======`
   underline is **byte-identical to a git conflict marker** and `test_no_conflict_markers` fired. The
   gate was right; it cannot distinguish them and should not try.
4. **`DEPENDENCY_GRAPH.md` went stale again** at wrap time — the sixth instance of the #2924 class.
5. **A third fixture-not-the-wire file, found only because I dispatched a CI run I did not strictly
   need.** `test_capture_door_idempotency_2682.py` went red on the fail-closed flip: its `_post`
   helper supplied the caller IP only via `x-forwarded-for`/`sourceIp`, so every reader collapsed to
   the sentinel. I had fixed exactly this in two other files earlier in the session and did not sweep
   for a third. Fixed; the fixture now carries the trusted header **alongside** a *different*
   forgeable value, so it proves the trusted one wins.
6. **A gate sweep returned a false "empty"** — the unquoted `?` in `gh api ".../runs?status=waiting"`
   made zsh glob-fail, so the variable was empty because the command never ran. Re-ran quoted: still
   empty, genuinely. *An empty result from a command that did not execute reads exactly like a clean
   state* — the same instrument-defect class I keep filing against.

## Two premises were stale, one of them mine

- **Box 3's** — the guard test supposedly "encodes the false premise". It did not; it had already been
  rewritten and says so. What it still pinned was the forgeable interim, which box 2 replaced. The real
  wire problem was two **fixtures** (`test_board_followup_sessions.py`, `test_e2e_write_paths.py`)
  supplying the caller IP only via `sourceIp`/`x-forwarded-for` — a shape production no longer
  produces. Both now carry the trusted header **alongside** the forgeable pair, so they prove it
  *wins* rather than that it works unopposed.
- **#2829's**, from the previous session — reading the `cdk diff` showed it tried to CREATE three
  alarms that already exist, which **blocked #1221's own deploy**. Applying the rescope (drop the three
  adoptions, keep the `email-subscriber-errors` routing) unblocked it, and that routing — #2829's
  actual title bug — shipped in the same deploy. The alarm now carries its SNS action.

## The wrap found a real hazard — #2932

Chasing failure 5 above past "make the test green" turned up a genuine second-order consequence of
box 2. Fail-closed is right for a **rate limiter** — one shared bucket is a safe failure. It is wrong
for the three **capture doors**, which key their idempotency id on the same identity
(`sha256(f"{ip_hash}:{content}")[:12]`) and write with `attribute_not_exists(sk)`. Under the sentinel
every caller shares one `ip_hash`, so **two different readers submitting the same idea collapse onto
one row** and the second is silently swallowed as a duplicate.

**Latent, not live** — verified on `E3S424OXQZ8NBE` that the `/api/*` behaviour serving all three
doors carries ORP `833950c4-…` (whitelists `CloudFront-Viewer-Address`; the paired cache policy
`8dad644a-…` correctly does not). So identities are real today. **Nothing enforces that coupling**:
the 15 behaviours still on `ForwardedValues` do not forward the header, and a future `/api/` write
route added under one of them degrades to one-identity-for-everyone with no test, alarm or log. Filed
**#2932** with both candidate fixes — a derivation guard for the coupling, and making the sentinel
non-colliding for id derivation so the failure is loud rather than silent.

*One helper, two callers, opposite needs from the same failure mode.* Worth carrying: a safe default
for one consumer can be a silent-data-loss default for another.

## Residual / next picks

- #2932 — the capture-door identity collapse above; latent today, silent when it fires.
- #2924 — the 168-test pre-merge proxy is undocumented, underived, and has now gone green through
  **six** main-reds, including this session's `DEPENDENCY_GRAPH` staleness.
- #2829 — still open: the three orphan adoptions need `cdk import`, not synth-and-deploy. Two of the
  three already route; only `cf-auth-errors` is genuinely silent.
- #2921 — `/api/sleep_detail` interleaves Eight Sleep and Whoop in one object.
- #2918 — two of six AI validation results never report `BLOCKED`, including the TL;DR headline.
- #2919 — `pattern_coach` (3.89:1) and `career_coach` (3.69:1) fail the WCAG AA contrast floor.
- #2912 — an alarm that flaps for 60s is invisible to the >72h citation gate.
- #2809 — `partial`; needs a post-genesis Withings weigh-in (every current row is `phase=pilot`).
- #2708 — `partial`; the chronicle runs Wednesdays, next 2026-08-26.
- `BOARD_RATE_LIMIT` may want raising now that a panel costs its true price — not-work — a product
  call for Matthew, deliberately not made unilaterally.
- A Withings weigh-in — not-work — owner action; also unblocks #2809.
- The #2831 API-before-frontend check is advisory — not-work — promoting it needs an owner-run
  `scripts/apply_branch_protection.py --apply`.

## Owner asks

1. **A Withings weigh-in** — newest row is still `DATE#2026-08-16`.
2. **`BOARD_RATE_LIMIT`** — 5 Bedrock calls/IP/hour now means one full panel per hour. Raise it?
3. The coach-colour call: `sleep_coach` is `#818cf8` on accessibility grounds (6.21:1 vs 4.37:1).
4. `gate:owner`: **#1738, #1571, #1677, #1631**; **#2833/#2834** are `model:opus` + `gate:owner`.
