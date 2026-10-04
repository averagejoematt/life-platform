# Handover — Session BF: reader-truth fixes landed, the v7 cut-over withdrawn, and the living front page begun (2026-10-03 00:03Z → 10-04 ~05:20Z, Fable 5.1, owner on hand until ~04:30Z)

**Driving instruction:** "review handover and backlog and let's figure out what we should work on", then "yes do all of them" (the v7 R7 read, the reader-truth lanes before Wednesday, a closure sweep). Mid-session the owner ruled the site still misses its job and asked for a ground-up plan; he approved one look ("definitely WAY better": clean, organized, professional) and said "go ahead with the plan". The plan itself is private and off-repo; the build work it produced is epic #4580.

## Shipped: 10 PRs merged, all deployed (main green at 83cbc85d)
- **#4579** → #3761: the shirtless day-1 photograph is off every reader surface (owner ruling 10-03); Home's fold holds the clothed gym photograph; a sweep keeps it gone.
- **#4571** → #4329: R7, the five-persona read of the nine `/next/` pages (personas 8·7·7·7·7, axe 0, sweep 2 A / 5 B / 2 C).
- **#4576** → #4329: R7's ten page fixes on the preview pages.
- **#4572** → #4568: the nightly pre-draft marks a draft by its version and emits a `failed` outcome.
- **#4574** → #4569: qa-smoke judges a coach's protein figure against the window it names.
- **#4575** → #4539: Story Desk dead-men (episode-or-hold in 48 h, ledger row, Monday questions send) inside the nightly qa-smoke.
- **#4573** → #4538: one shared reader-surface check on the chronicle, recap and Panel paths.
- **#4577** → #4540: every consumer derives the plan's 1,500 kcal / 170 g floor (18 modules, 86 sites); a sweep guards the set.
- **#4578** → #4564: the AI coaches carry no "Dr." on any reader surface; the registry normalises every loaded copy.
- **#4591** → #4581: the kit — `site/assets/css/clean.css` (10.4 KB), twelve `ck-` components, an unlisted specimen at `/kit/`, the approved sources under `docs/design/v8/`.

## Verified live
- `/api/nutrition_overview` serves `protein_target_g` 170.0 and `protein_floor_g` 170.0 (190 / 170 the day before). The owner reconciled `PROFILE#v1` at 2026-10-04T03:50Z (UPDATED_OLD 1800 / 190).
- `/api/coaches` carries no "Dr." (2026-10-04 05:02Z, after CI/CD succeeded on 83cbc85d).
- `/next/` and `/next/story/about/` no longer reference the day-1 photograph; `/kit/` returns 200.
- `life-platform-qa-smoke`, `life-platform-mcp-warmer` and `wednesday-chronicle` were redeployed 03:22–03:25Z; `nightly-predraft-missing` returned to OK after the 10-04 02:00Z run (on the old code, fresh ids).
- `site/assets/js/v7_home.js` live carries the R7 "are overdue" wording.
- SSM `/life-platform/remediation-mode` = `off` (owner decision; was `shadow`).

## Decisions the owner made
- The site's job (the "cafe test"), the approved look, no shirtless photos, the v7 cut-over withdrawn (PR 4316 closed unmerged), and "go ahead with the plan": a dated living front page with depth in layers, four pages first, cut over only after his yes on every screen and five real readers.
- Merges and deploys for the epic's stories are approved; other AWS writes still need his go.

## Gotchas
- **A closure sweep found none of the nine shipped Story Desk stories closable** — each has an unmet box (table on #4531). The Panel's state reads still have no tombstone or cycle filter (#4536); the legacy chronicle editor pass is still the live fallback (#4535).
- **The season promote bypassed `chronicle-approve`'s side effects for week 4**: no delivery email, no share kit. Four alarms trace to it (#4593).
- **AI "cold readers" do not predict the owner.** A 27-agent prototype run scored everything 22–24 and he rejected all six pages. Calibrate on something he can open; go deep on one screen.
- **A merge train launched seconds after a push sees zero checks** and stops; wait for the runs to attach.
- **A sibling PR can re-add what a sweep removed** between a lane's last run and its merge (#4574 added a "Dr." in a comment; #4576's test expected one). Re-run the lane's own guard on the merged tree.
- The projection of 256 USD for October is inflated by a 42.70 USD one-day jump on 10-01/02 that coincides with the season rebuild run from a workstation (inference from the dates; #4589 attributes it).

## Residual / next picks
- **#4592** (open PR for #4582, `/api/edition`): held at the merge checklist — register `site_api_edition.py` in `WEEK_SURFACES` (or `UNREGISTERED_PRODUCERS`) for `tests/test_week_agreement_3615.py`, and freeze or register `_TODAY` for `tests/test_wallclock_fixture_bombs_2376.py`. Then merge and `deploy_site_api.sh`.
- **#4583** the daily coach voice, **#4584** the Tuesday question, **#4585** the coaches' record beside a simple guess, **#4589** the cost attribution and cuts — the next lanes.
- **#4586** four pages on preview from the kit and `/api/edition`; the owner reviews one screen at a time.
- **#4587** five real readers and **#4590** the interview — owner-gated.
- **#4581**: the chart's two labels render at about 7 px on a phone in the kit; fix when the first page is built.
- **#4593**: share the publish-time side effects between approve and promote; build the week-07 share kit.
- **#4540**: stays open as the carrier for one ruling — protein floor 170 g (the plan) or 180 g (`training/owner_redlines.py`, the MCP default, the critics).
- **#4564**: one persona is still titled "Psychiatrist"; live proof of plain names in the next daily brief and Panel episode.
- **#4568**: live proof needs a night whose date already holds an archived draft.
- **#4569**: confirm the two `cross_surface` legs are absent from the 2026-10-04 18:30Z qa-smoke run.
- **#4539**: the Monday 2026-10-05 18:30Z run is the first real read of `story_season:monday_questions`.
- **#4546**: `ALLOWED_SENDERS` does not include the address the questions email is sent to; a reply from that inbox is dropped.
- **#4531**: nine stories with named unmet boxes; the first live desk week is Wednesday 2026-10-07 — read `desk_findings_json` before approving.
- not-work — the S3 delete and CloudFront invalidation for the two day-1 image objects: an owner AWS write, commands given in session.
- not-work — whether to email the rebuilt week 4: an owner decision recorded on #4593.
- not-work — whether a doctor reviews the plan: only the owner knows; the site needs one true sentence.
- not-work — #4257 (#4544 steps 2–3), #4259 worktree archive ruling, #4261, #4191, #4076, #4431: owner acts or rulings, unchanged.

**Build beat:** none — the reader-visible changes are truth fixes on preview pages and a parts catalogue; the front page they serve has not shipped
**Docs:** docs/alarm_citations.json and docs/OPERATING_KNOWLEDGE_LEDGER.md (this wrap); docs/design/v8/, docs/DESIGN_SYSTEM_V5.md, docs/CONVENTIONS.md §9, docs/PROPORTIONALITY.md, docs/content/STORY_DESK.md, docs/engines/SCORING.md and COACH_STANCE.md rode their PRs
**Decisions:** none filed — the withdrawal of the v7 cut-over amends ADR-157; the amendment is carried by #4588 and lands with the cut-over it replaces
**Main:** green (83cbc85d)
**Incidents:** none
**Stash/hooks:** clean
**Closures:** #4329, #4330 commented · DoD: scanned 2, hits 1 (#4330 post-close comment, advisory), blocking=none
**Backlog:** Now live — epic #4580 filed with ten stories (#4581–#4590); #4593 filed (Next); no promotion made
**Alarms:** 3 lit (`qa-smoke-failures`, `qa-smoke-warnings`, `chronicle-delivery-heartbeat`) and 2 flaps (`swallowed-permission-denial`, `nightly-predraft-missing`), all cited — #4593 and #4568
**CI warnings:** 5 — all `SKIPPED in CI — no playwright/chromium`, #3640's deliberate skip notice; no action
**Ledger:** Story Desk dead-men row added in #4575; the kit's drift checks extend the existing css-tokens gate
