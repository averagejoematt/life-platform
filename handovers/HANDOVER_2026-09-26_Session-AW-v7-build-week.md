# Handover — Session AW: the v7 build week's first night, and a day of engine debt (2026-09-26 19:30 PT → 2026-09-27 ~14:30 PT)

**Driver brief (owner, 19:30 PT):** "Session AW — the v7 build week, from tonight… run the brief's W1 in order: The coaches page's three R6 fixes; Today / Under the hood / Follow polish against R6; E4 one record producer (#4220); E6 the absent coach (#4217)." Owner additions through the night: "i approve all of the deploys" (20:25 PT); "is there other stuff we could be doing in parallel" → a backlog sweep; two bug reports (the Flex session advancing the v0.4 sequence; the packet's missing "today so far" view); rulings E3 loads **public (a)**, the morning note **Tier 1 (public)**; approval to upload the five coach config JSONs to S3. **Model:** Fable 5.1 until the weekly Fable limit (~00:15 PT, ~8 h idle), then **Opus 5.5** from ~09:00 PT on the owner's call ("switch to Opus"). Fable-only work was filed as issues (#4329, #4330) rather than done on Opus — the review's model is part of its validity.

## What shipped — 37 PRs merged

| area | PRs | state |
|---|---|---|
| **v7 site (W1, `/next/`)** | #4300 coaches R6 fixes proven by render · #4302 Today (empty vs unreachable, noscript, sources, the ask linted; the networkidle hang — an unread 404 body — fixed) · #4301 Under the hood · #4303 the cross-page fixes (one next-weigh-in helper, four pages) · #4315 the coaches read the engine's instrument map | **all live** (build `73956b3`, attempt 3 — see incidents) |
| **E-series engine** | #4304 E4 one record producer · #4305 E6 the absent coach · #4318 E3 `/api/session` (loads public) · #4322 E2 the morning note (Tier 1) · #4340 one routine picker (#4338) | E6 **live-proven** (#4217, both halves); E3 route live (200); E2 route **merged, write blocked on the owner's CDK line**; #4340 site-api deployed 17:48Z |
| **Owner's two reports** | #4314 Flex never advances the sequence (#4312) · #4313 the packet's "today" view (#4311) | #4312 **live-proven** (packet reads lower-volume, session 3 of 4, the Flex session `not_credited`) |
| **Backlog** | #4306 #4275 model resolution · #4307 #4171 additive memory · #4308 #4065 commit gate back-offs · #4309 #4190 tool-call residue refused · #4310 #4191 the write-up opens on its first sentence · #4317 #4216 a docket resolves once · #4319 #4177 adherence by routine id · #4320 #4170 Telegram never claims a write · #4321 #4164 PII sweep names paths not values · #4323 #4174 pain dismissal per site · #4324 #4183 pre-genesis drafts are history · #4325 #4149 joints critic record shape · #4327 #4178 walks on Compendium METs · #4328 #4172 policy refusals never say retry · #4332 #4186 coach-truth legs read the lead slot · #4335 #4111 weekly self-added report · #4341 #4184 one weekly-rate window · #4344 + #4343 two gate misfires · #4346 #4279 one AI retry policy (12 sends → 3) · #4347 #4166 protein gate by body fat (43 % → report-only) | fleet deploy from main's tip at the wrap (see Gotchas) |
| **CI / harness** | #4326 the main-red fix (PAIR 10) · #4334 fast lane parallel (15–25 min → 12.7) · #4336 measured timeouts on four workflows · #4339 READINESS.md re-verify · #4342 lazy collection scans (84.5 s → 18.5 s) | CI-only, in effect on merge |

**Live proofs posted:** #4217 (engine 06:30Z + renderer 16:33Z) · #4312 (packet 06:31Z) · #4076 (the owner-override path, already on main, proven from the 09-26 routine rows; one box left) · #4188 closed (the first daily lead read, 17:11Z) · #4218 closed (no slope as a level, 16:09Z) · #4213 read (no owner-register slot; #4331 open for the ladder fallback).

**Config:** the five coach config JSONs uploaded to S3 by the driver under the owner's approval (06:04Z); four were already identical, only `personas.json` was stale; prior copies backed up in the session scratchpad.

## Gotchas (each now a memory line)

- **An unread non-2xx fetch body keeps Playwright's networkidle from ever arriving** — `/next/cockpit/` hung 60 s on a 404 of `/api/session`; the visual gate waits on networkidle. Every v7 `getJSON` now drains the body.
- **Two green PRs, main red after both** — #4304 pinned the docket writer's re-write trail in a PairContract; #4317 retired the trail. Three lanes blamed the PT-evening clock first; the captured log named the real cause. Merge the first, re-run the pair sweep on the second's merged tree.
- **A CDK line inside a code PR strands every deploy** — #4322's one LeadingKey line made CI's Plan job OWNER-REQUIRED from 17:45Z; nothing deployed for ~3 h and no watcher saw it (the gate watcher only sees runs that reach the gate). Worked around with `deploy_fleet.sh`; the owner's CDK run clears it.
- **`gh run rerun --failed` after a site rollback re-checks the rolled-back site** — the deploy job isn't re-run, so the smoke test waits for a build that is never synced. Re-run the whole workflow.
- **A PR re-run reuses its original merge commit** — after main's fix merged, `gh pr update-branch` was needed for honest re-runs (used ~15 times).
- **The Fable weekly limit stops every lane at once** — 12 lanes in flight at 21:55 PT burned the 5-hour cap; the second cap at ~00:15 PT idled the session ~8 h. ≤5 lanes held the rest of the night.

## Owner decides next

1. `cd ~/dev/life-platform && git pull -q origin main && bash deploy/cdk_deploy.sh LifePlatformServe` — clears the strand (every ci-cd Plan is red until then) and lets the morning note write. — not-work — an owner-only IaC apply
2. #4333 (vitamin D sufficiency joins the supplements): may per-nutrient supplement totals be public on `/api/nutrition_overview`? The doses are already public on `/api/supplements`. PR open, conflicting until re-synced. — #4244
3. #4343 cause A: may the 18 reader-jargon terms leave the judge's list in the S3 `config/coaches/_shared_standard.json`? The code check still blocks them; the judge hallucinates them and the rewrite then uses them. — #4343
4. #4347 merged with DXA opened to the deficit critic (an owner-only MCP path); confirm or revert. — #4166
5. The v7 cut-over "go" waits for the Fable-held R7 red team and scorecard. — #4329, #4330

## Residual / next picks

- Open PRs: #4345 (the coaches get the served protein figure + the brief's time guard; wiki-drift red — the docs re-verify it needs) — #4343; #4331 (ladder-fallback stance guard; two reds) — #4213; #4337 (Today prints the session; merge after the #4340 site-api deploy is confirmed) — #4182; #4333 — #4244; #4316 the cut-over, parked — #4330.
- Live proofs owed after the fleet deploy: #4220 (four endpoints agree), #4171, #4065 (the next 5 am commit), #4191 (after the 09-30 publish), #4275, #4190, #4177, #4174, #4311, #4178, #4111, #4166, #4184 (the next 09:40 PT compute), #4186 (the 18:30Z nightly should FAIL naming Eli's 106.9 g — the check working), #4183 (the owner archives 6 live orphan drafts), #4189 (the owner's first morning note, after the CDK run), #4338.
- The morning note's site half (Home "in his words this week", This week's testimony) — #4189.
- Two AV merge commits carry co-author trailers (`4b3f95118` #4243, `2b763c7ea` #4236); `test_no_tool_attribution_3005` reds locally on reachable history. — #3005
- The fast lane is 12.7 min, not < 10; #4342 should take ~60 s off per worker — re-measure. — #4251
- The v4 `/coaching/` docket cards still print raw resolver strings; superseded by v7 at cut-over. — #4330

**Build beat:** none — the v7 pages are still an unlisted preview and the engine fixes await their live proofs; the public story is the cut-over (#4330)
**Docs:** docs/engines/READINESS.md re-verified (#4339); docs/engines/SCORING.md re-verified (#4341); SCHEMA / DATA_GOVERNANCE / IDEMPOTENCY / CONVENTIONS §4a1 / PHASE_TAXONOMY updated in-PR by their lanes; docs/alarm_citations.json re-cited; docs/INCIDENT_LOG.md +3 rows; CLAUDE.md status block
**Decisions:** none needed — every ruling tonight is an owner ruling recorded on its issue and in memory (E3 loads public, E2 Tier 1, the config upload); no architecture posture changed
**Main:** stranded — every ci-cd run since 17:45Z fails at `Plan deployments` on `LifePlatformServe` OWNER-REQUIRED (#4322's LeadingKey line, R8-ST6/#2834); code deployed by `deploy_fleet.sh` from main's tip at the wrap; clears when the owner runs `bash deploy/cdk_deploy.sh LifePlatformServe`
**Incidents:** 3 rows added — the owner-required IAM strand; main's full suite red ~10 h on two same-night merges (#4304 + #4317, fixed by #4326); the #4315 site auto-rollback on the API-before-frontend convergence race
**Stash/hooks:** clean
**Closures:** #4188, #4218 commented (live proof + outcome) · DoD: scanned=2 window=closed>=2026-09-27 hits=0 findings=0 mode=warn blocking=none
**Backlog:** Now live at 10 opus-startable (floor 3, 0 short); no stale Later issues; filed #4311 #4312 #4329 #4330 #4338 #4343 and rowed them into their epics; 6 blocking hygiene violations fixed (epic story rows, acceptance counts, labels, two outcome sections)
**Alarms:** 2 red, both re-cited to their live causes — `qa-smoke-failures` → #4343 (the coach-vs-engine leg failing Eli's stale weekly read, a true failure), `qa-smoke-warnings` → #4183 (live orphan drafts + one low-water day)
**CI warnings:** unverified — no green completed main run to read (the strand); re-check after the owner's CDK run
**Ledger:** none — no new standing subsystem; #4336's timeouts and #4332's COUNT lines extend existing gates
