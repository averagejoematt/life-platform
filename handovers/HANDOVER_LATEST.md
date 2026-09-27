# Handover — Session AV: the site night, the A-grade day, and the ground-up rethink (2026-09-25 21:30 PT → 2026-09-26 ~16:45 PT)

**Fable 5.1, three phases in one session.** (1) Overnight: "planning only" re-scoped by the owner into the site night — the three flagship doors rebuilt on the reader's three questions, the vocabulary registry + reach ratchet, ADR-156, `docs/SITE_TRANSFORMATION_V6.md` (its handover was archived as `HANDOVER_2026-09-25_AV-site-night.md`). (2) The A-grade day (09:45 → 12:30 PT): the owner's plan-mode answers — nav labels TODAY · THE NUMBERS · THE COACHES · WHAT HE TRIES · THE STORY, merge + deploy authority for site and engine, taste calls to an expert panel — executed as one run: the four engine PRs merged and fleet-deployed, then five site waves. (3) **The pivot (12:40 PT):** *"even myself … I get overwhelmed … 100 features, 100 web pages … if I shared this on reddit, I feel it now looks like AI slop … if it would fail a reddit audience, and even fails me, we have built a bad website … full creative license."* The A-grade sweep after all the polish read 3 A · 12 B · 2 C · 8 D; the rest of the day became the design phase of a ground-up rethink, plus the coach-voice and truth fixes any design inherits. Second ruling (14:10 PT): **no cycle count on the site** — the frame is the experiment and the day.

## What shipped (merged AND deployed unless marked)

| PR | what | proof |
|---|---|---|
| #4192 #4193 #4194 #4196 | the four overnight engine PRs: `open_actions`, the genesis-bounded window, the coach-vs-coach/engine QA legs + the #4180 trend classifier, the tool-call residue guard | fleet 107/0 at `c63f2f5b`, site-api deployed; #4187 closed on `open_actions`=10; #4180 closed on `qa-smoke-failures` OK 18:31Z |
| #4211 | labels + build-time `<dfn>` glosses + the reader form (site half) + reach 39 → 25 | D2 green; live: 0 old labels, bar 66.8 px |
| #4210 | the comprehension judge (advisory) | first live run 20:00Z: **8 of 12** (/ 1 · cockpit 1 · data 1 · coaching 1 · protocols 2 · story 2) |
| #4208 · #4206 · #4209 · #4212 | data door + six topic folds; protocols/story/subscribe/about/method folds; rename passes; one date formatter | D3, D4, D5a, D5b all green; live = main |
| #4207 | `POST /api/page_feedback` (DynamoDB door) | **the owner ran `cdk deploy LifePlatformServe` himself** (13:07 PT; the classifier denies IaC apply from Claude); `[]` → 400, a labelled body → 200 `{"ok": true}` |
| #4222 | brief + Telegram plain vocabulary | fleet at the wrap → proof at the 10:00 PT brief |
| #4223 | the daily grounded lead read (`lead_daily_read.py`, one Haiku call over code-cited facts, hard number check, N-06 gate) | fleet + site-api at the wrap → `/api/coaching-dashboard.lead_daily` after the first brief |
| #4225 | #4213 the coach reader register: four by-coach slots guarded (public twin or EMPTY), `public_ask`, third-person stance prompt | site-api at the wrap; slots empty until the producers re-run (~10:00 PT Sunday); **owner uploads the 5 config JSONs** |
| #4226 | #4218 wrong-page cards say what was measured; no raw evaluator string served | site-api at the wrap → `/api/wrong` clean |
| #4227 | #4185 coach inputs: one derivation for days logged, PT instants, served-fact gate daily + weekly, `data_through` | fleet + site-api at the wrap |
| #4214 | eight deterministic reader checks in the quality gate (regenerate-or-hold), census 767 → 775 | fleet at the wrap; **watch the hold count on the first run** |
| #4221 | the sweep's quick fixes (dated return line on every page, lab notes by week, honest podcast line, rails cut to the reach set, Hevy gloss) | MERGED; its deploy redded the `/mind/` probe (a rail-tile count on the unlisted reading page) → fixed forward in #4232, merged |
| #4224 | #4215 the retired seat labelled apart · #4219 the overdue ask says "7 days late" | MERGED (`0f8a9eb87`); live proof on the rendered scorecard/cockpit after D8 |
| #4228 | **the v7 scaffold**: `scripts/v7_build.py --base /next/`, nine noindex shells under `site/next/`, `v7.css`/`v7_shell.js`, `v4_chrome.EDITION` | MERGED (`4f24f2a8c`, the D8 deploy); live proof `curl -I /next/` → 200 |
| #4231 | no cycle count on the live site: `/story/attempts/` unlisted, the reachable pages scrubbed (scorecard "SINCE DAY 1" / "ALL TIME", home "no sensor worn"), ceiling 25 → 24; server residuals listed in the PR | MERGED (`fb1f50b48`) |
| #4230 | E1 the ledger line: `latest_checked{}` per coach on `/api/coach/<id>` and `/api/coaches` (a `PairContract`, `ENROLLED_FLOOR` 8 → 9) | MERGED (`ff8016403`); **live** after the wrap's site-api deploy: labs `{status: confirmed, metric: hrv_7day_avg, eval_type: directional, actual_value: 0.2341, outcome_date: 2026-09-20}` |

## The design phase (`docs/SITE_TRANSFORMATION_V7.md` canonical; everything else in `docs/design/v7/`)

Three Fable research lanes in parallel (R1 the masters' playbook · R2 a five-persona red team of the live site — 20/50, zero photos on 25 pages, home 14.3 screens · R3 the 91-page inventory — SPINE 10 · FOLD 43 · ARCHIVE 23 · KILL 15) → the driver's concept (one serialised investigation; nine pages; the order rule: the human first, the counted failures second, the mechanism third, the coaches last and short; the delete and keep lists) → a Fable build plan against the code (preview at `/next/` from `site/next/**`, zero CDK; the nine keep their URLs; five-day waves; engine asks E1–E11) → two competing prototypes (A the investigation 30/50, B the logbook 29/50) → the red team's pick (B's frame, A's type and voice) → **Prototype C, 36/50**, three revision passes, published privately: https://claude.ai/artifact/QnkVYjBNPpjVfabJdbxNeZ (A `AqahgSJAaoqNUUB4FqsTEg`, B `HyyZrzwyhuheFwCJ4f3h5n`). Six engine defects the red team found were verified and filed: #4215 – #4220.

## Gotchas

- **The auto-mode classifier denies `cdk deploy` outright** ("Protected-Scope IaC Apply") regardless of the owner's approval; the owner runs it from a one-token wrapper script (`bash <script>`), because a wrapped multi-line paste breaks `source`. A pending IAM line also strands CI's Plan job (R8-ST6) until it deploys.
- **Concurrent lanes that each bump the census or touch `entry_age.js` / `ai_calls.py` / `COACH_STANCE.md` go CONFLICTING one after another** — serialise, and tell every open lane the new ceilings (766 → 767 → 775 today).
- **A rail cut can red a visual probe that counted tiles** (`/mind/` → `/data/reading/`: 3+ `.ev-tile`); the rollback restores main~1, which still carries the change — the fix is the probe, forward.
- The "Full unit suite" job sees tests `git grep` can — a new untracked module passes locally and fails in CI (#4223's `NUMBER_TOLERANCE_EXACT`).
- My run-state timestamps drifted ~40 min ahead of the wall clock for an hour; read `date`.
- A `cycle`/`reset` word ban needs a grep over rendered text, not the diff (the #4224 label, home's "no sensor this cycle", the scorecard's "THIS SEASON · CYCLE 17").

## Owner decides next

1. React to Prototype C in one message (or A/B) — the build week starts from it Monday at `/next/`.
2. A real photo (#3761): C says "No photo yet. The first is due Monday, October 5 — day 30."
3. The published write-up title "The Fifteenth Reset, or: What the Body Remembers" (2026-09-08) — left as published content under the no-cycle-count ruling.
4. Upload the five edited config JSONs (`config/personas.json`, `config/coaches/_shared_standard.json`, `nutrition_coach.json`, `mind_coach.json`, `explorer_coach.json`) — read from S3 at runtime.
5. The privacy rulings the build plan needs: loads on `/api/session` (E3) and the morning note (#4189, E2).
6. The memory backup sync (`aws s3 sync … claude-memory-backup/`) — an unattended write the owner runs.

## Residual / next picks

- Live proofs to read: #4188 (`lead_daily` at the first brief after the fleet deploy — Sunday 10:00 PT); #4213 (zero owner-directed hits on `/api/coach/<id>` after the next daily run); #4218 (`/api/wrong` clean); #4185 (`analysis_data_through` non-null, no gap claim beyond `lag_days`); #4184 at the 09-27 09:40 PT compute; #4186 from the qa report artifact; #4215/#4219 on the rendered scorecard/cockpit; the `/next/` shells resolving.
- To file: the #1699 ungrounded-behavioral check reads only second-person sentences (widen to he/his/Matthew); two producers for lifting sessions in 30 d (`top_activities` 15 vs `strength_sessions_30d` 19) and `report_card` 7 of 16 vs calibration 7 of 17 (both → #4220's family); #4224's "equals" acceptance box (Eli makes no graded calls); `v4_build_gear.py` GEAR-entry drift; the `SLUG_META` slug collision; `/story/build/agent-review/` S3-backed regen; the 2026-10-10 judge ratchet date; the coaching tab row + `/method/` obituary cards (M).
- **The next session starts from `docs/design/v7/BUILD_WEEK_BRIEF.md`** (the waves re-cut for the owner's ~15-hour window from 17:00 PT Saturday; one pasteable lane brief per remaining unit; the cut-over criteria and the owner-gated questions). State at the wrap: the scaffold live at `/next/`; This week (#4233) merged; Home (#4235) and The coaches (#4234) open — the red team scored the built pages Home 36 · This week 34 · The coaches 28 (hold Coaches for its three fixes, `docs/design/v7/R6_BUILT_PAGES_REDTEAM.md`); the other six pages in lanes (numbers, what he's trying, who he is, today, under the hood, follow) — open PRs or lane worktrees, listed in the epic's closing comment.

**Build beat:** 2026-09-26-the-experiment-and-the-day
**Docs:** docs/SITE_TRANSFORMATION_V7.md (new, canonical, indexed) · docs/design/v7/ (R1–R5, the concept, the build plan, three prototypes, README) · docs/alarm_citations.json (qa-smoke-warnings citation re-pointed) · docs/engines/COACH_STANCE.md (re-verified by #4225/#4227/#4214) · CLAUDE.md status block
**Decisions:** ADR-157 filed — the site is one serialised investigation; nine reachable pages; the human first; the cycle count internal; built at `/next/`, cut over at A
**Main:** pending — CI/CD for the wrap's own merges (`fce761c1` reconcile) was in progress at the wrap; the last completed run before it went green once the owner's CDK deploy (13:07 PT) cleared the R8-ST6 strand at `9737d879`
**Incidents:** 1 row added — the D6 site-deploy red on the `/mind/` probe after the rail cut (rollback fired, live content correct, fixed forward in #4232)
**Stash/hooks:** clean
**Closures:** #4180 (live proof, qa-smoke-failures OK 18:31Z) · #4187 (live proof, `open_actions`=10) · #4202 and #4163 (auto-closed on green runs; `**Outcome:**` comments added) · DoD: scanned=13 window=closed>=2026-09-26 hits=0 after the two comments, mode=warn blocking=none
**Backlog:** 8 filed today (#4213, #4215 – #4220; #4229 bot-filed) and rowed into epic #4182's `## Stories`; hygiene 0 violations / 26 advisories over 51 open; Now holds the P1s #4213 #4220
**Alarms:** `qa-smoke-warnings` red since 09-20 → #4183 (citation re-pointed off two closed issues today); `qa-smoke-failures` OK since 18:31Z; every lit alarm cites an open issue
**CI warnings:** none actionable — the battery's ci-warnings gate passed; `docs/ARCHITECTURE.md` Verified 70 d old (advisory)
**Ledger:** none — no standing machinery shipped on the live path this session (the v7 scaffold sits behind the `EDITION` switch and `/next/` is unlinked; its PROPORTIONALITY row lands with the cut-over PR); the operating-knowledge ledger gained two rows for the two owner rulings, snapshot 495
