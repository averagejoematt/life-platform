# Restart Discovery Report — 2026-05-18 Genesis

**Produced:** 2026-05-20 by Claude Code, per `CLAUDE_CODE_RESTART_2026_05_18.md` §3
**Scope:** Read-only scan of `~/Documents/Claude/life-platform`
**Status:** Discovery complete. **Pausing at GATE 1 per spec §12 step 1.**

---

## TL;DR — three escalation triggers fire. Do not proceed past GATE 1 without explicit decisions.

The spec §3 says to pause and surface to Matthew if any of these are true:

| # | Trigger | Status | Detail |
|---|---|---|---|
| 1 | A constant like `EXPERIMENT_START_DATE` already exists with a different value | **FIRES** | Two Lambdas define `EXPERIMENT_START = "2026-04-01"` directly (`site_api_lambda.py:119`, `ai_expert_analyzer_lambda.py:122`). Plus configs `config/user_goals.json` and `config/character_sheet.json` both set `"start_date": "2026-04-01"`. Plus `site/assets/js/site_constants.js:23-24` sets `start_date / experiment_start = '2026-04-01'`. |
| 2 | Lambda hardcodes `2026-04-XX` not obviously safe to change | **FIRES** | At minimum: `lambdas/character_sheet_lambda.py:662`, `lambdas/coach_narrative_orchestrator.py:412 (phase_started)`, `lambdas/intelligence_common.py:259`, `lambdas/daily_brief_lambda.py:2071/2226/2255`, `lambdas/site_api_lambda.py:814` all hardcode `"2026-04-01"`. `lambdas/character_engine.py:946` falls back to it. Three of these are in pre-computed JSON returned to the site. |
| 3 | "307" appears in more than 30 places | **FIRES — by a lot** | **134 hits across 51 files.** Pattern is overwhelmingly `profile.get("journey_start_weight_lbs", 307)` — a fallback default — repeated in 20+ Lambdas. Plus narrative copy in `site/index.html`, `site/physical/index.html`, `site/live/index.html`, `site/data/content_manifest.json`, and `site/assets/js/site_constants.js`. |

**A fourth issue worth flagging separately (§14 below):** the live site already encodes a *prior* restart narrative ("got sick, fell off the wagon, …starting over — publicly. April 1, 2026 is Day 1. …A relapse. A relaunch."). The May 18 spec forbids public mention of any prior attempt — meaning this existing copy must be rewritten too, and the May 18 narrative cannot lean on the existing relapse framing the site currently uses.

---

## 1. Scan summary

All six scans live next to this file:

| Scan | File | Hits | Unique files |
|---|---|---:|---:|
| Anchor dates / start_date / EXPERIMENT_START / GENESIS | `_grep_anchors.txt` | 2,978 | 669 |
| `307` literal | `_grep_307.txt` | 134 | 51 |
| Day-N patterns | `_grep_dayn.txt` | 762 | 204 |
| Streak / level counters | `_grep_streaks.txt` | 1,818 | 245 |
| `*chronicle*` file names | `_chronicle_files.txt` | 292 | 292 |
| Site copy narrative | `_grep_site_copy.txt` | 26 | 12 |

Two notes on noise:
- 259 of 292 "chronicle files" are CDK asset duplicates under `cdk/cdk.out/` — the original `find` `-prune` matched `./cdk.out` (which doesn't exist) instead of `./cdk/cdk.out`. Live chronicle code is just the 3 Lambdas + handful of deploy scripts (see §6).
- Anchor scan is dominated by historical doc reviews (`docs/reviews/REVIEW_BUNDLE_*.md`) — 7 of the top 8 files. Real live code touch is much smaller (see §3).

---

## 2. Top-5 highest-touch live files (the ones the migration will spend real time on)

Filtering out archive/, cdk.out/, handovers/, docs/reviews/, docs/archive/, __pycache__:

| Rank | File | Why it's hot |
|---|---|---|
| 1 | `lambdas/site_api_lambda.py` | 23 Day-N hits, 15 "307" hits, 77 streak hits, ~30 `EXPERIMENT_START` references. The single biggest surface area for the migration. |
| 2 | `lambdas/ai_expert_analyzer_lambda.py` | 19 Day-N hits, defines its own `EXPERIMENT_START = "2026-04-01"`, uses it across coach prompt scaffolding. |
| 3 | `mcp/tools_habits.py` | 103 streak hits — this is where `get_habits` / `get_vice_streaks` / streak-counter logic lives. The wipe in spec §6 lands here. |
| 4 | `lambdas/daily_brief_lambda.py` | 50 streak hits + 3 hardcoded `"2026-04-01"` fallbacks + 2 fallbacks to `307`. Daily user-facing email, so any miss here is immediately visible. |
| 5 | `lambdas/character_engine.py` | 41 streak hits + the `experiment_start` config-default fallback (line 946) + a `start_weight_lbs` fallback to 307 (line 354). Drives the character sheet rebuild in §6. |

Honourable mentions for the migration: `lambdas/daily_metrics_compute_lambda.py` (43 streak hits), `lambdas/daily_insight_compute_lambda.py` (11 Day-N hits), `lambdas/wednesday_chronicle_lambda.py`, `lambdas/weekly_digest_lambda.py`, `lambdas/output_writers.py`, `lambdas/ai_calls.py` (injects "307" into multiple LLM prompts).

---

## 3. Active sites where the genesis date is encoded (the actual migration target list)

**A. Python — explicit `EXPERIMENT_START = "2026-04-01"` constants:**
- `lambdas/site_api_lambda.py:119`
- `lambdas/ai_expert_analyzer_lambda.py:122`

**B. Python — hardcoded `"2026-04-01"` string literals (must change or migrate to constant):**
- `lambdas/character_sheet_lambda.py:662` — `"started_date": "2026-04-01"` in compute output
- `lambdas/site_api_lambda.py:814` — `"started_date": "2026-04-01"` in `/api/*` payload
- `lambdas/daily_brief_lambda.py:2071, 2226, 2255` — `profile.get("journey_start_date", "2026-04-01")` fallback (3 sites)
- `lambdas/intelligence_common.py:259` — `"start_date": "2026-04-01"` in intelligence-layer baseline
- `lambdas/coach_narrative_orchestrator.py:412` — `"phase_started": "2026-04-01"`
- `lambdas/character_engine.py:946` — `config.get("experiment_start", "2026-04-01")` fallback

**C. Config files (JSON — likely loaded at runtime):**
- `config/user_goals.json:9` — `"start_date": "2026-04-01"`
- `config/character_sheet.json:9` — baseline `"start_date": "2026-04-01"`

**D. Frontend JS — the "single source of truth for factual content" per its own header:**
- `site/assets/js/site_constants.js:23-29` — `start_weight: 307`, `start_date: '2026-04-01'`, `experiment_start: '2026-04-01'`, plus all the hero/CTA copy (see §4).

**E. Static HTML — old narrative bound in markup:**
- `site/index.html:552` — `Day <span id="fp-day-strip">—</span> of 365`
- `site/index.html:683` — `Started at 307 lbs. Built this entire platform with Claude as a development partner.`
- `site/physical/index.html:339, 352, 412, 830` — Day-of-365 strip + `Day 1 · 307 lbs` chart anchor + JS that prints `Day 1 · {vals[0]} lbs`
- `site/live/index.html:105, 118, 174, 415` — same pattern as physical/
- `site/nutrition/index.html:379, 392` — Day-of-365 strip
- `site/mind/index.html:313, 326` — Day-of-365 strip
- `site/glucose/index.html:328, 701` — `Day 1 · — %` + JS that prints `Day 1 · {first}%`
- `site/builders/index.html:291` — `He started this platform on February 22, 2026.` (build-date narrative; not strictly the April 1 launch, but coupled)
- `site/data/content_manifest.json:45` — sidebar text `Started at 307 lbs. Goal: 185.`

**F. Tests:**
- `tests/test_shared_modules.py` — 40 anchor hits. Need to confirm whether these reference `EXPERIMENT_START` values or just contain date strings as fixtures. Worth a closer pass before the constants migration in §2.

---

## 4. The "307" pattern — what it actually is

The vast majority of 307 references aren't narrative copy. They're the `profile.get("journey_start_weight_lbs", 307)` default pattern, repeated across 20+ Lambdas:

```
lambdas/ai_calls.py                        2x (LLM prompt context)
lambdas/partner_email_lambda.py           1x
lambdas/character_engine.py                1x
lambdas/daily_brief_lambda.py              2x
lambdas/dashboard_refresh_lambda.py        3x
lambdas/html_builder.py                    1x
lambdas/nutrition_review_lambda.py         1x
lambdas/output_writers.py                  2x
lambdas/site_api_ai_lambda.py              3x  (incl. one bare `ctx["start_weight"] = 307`)
lambdas/site_api_lambda.py                ~10x (incl. one bare `ctx["start_weight"] = 307`)
lambdas/weekly_digest_lambda.py            4x  (incl. narrative "Goal: lose ~117 lbs (307→185)")
lambdas/weekly_plate_lambda.py             1x
lambdas/wednesday_chronicle_lambda.py      3x
```

Plus two genuinely narrative-coupled cases that must be rewritten by hand, not regexed:
- `lambdas/site_api_lambda.py:1885` — `"body": "Started at 307 lbs. Built the platform from scratch. Committed publicly."`
- `lambdas/site_api_lambda.py:1919` — `"body": f"Down {int(lbs_lost)} lbs from 307. {round((lbs_lost / (start_weight - goal_weight)) * 100)}% of the way to goal."`
- `lambdas/site_api_lambda.py:769` — `weight_series = [("2026-04-01", 307.0)]` — hardcoded historical first-data fallback (the "if no Withings data exists, use this point" line)
- `lambdas/weekly_digest_lambda.py:825, 932` — `Goal: lose ~117 lbs (307→185)` and `JOURNEY STAGE: Week 1 of transformation | 307→185 lbs` injected into prompt scaffolding
- `lambdas/ai_calls.py:1525, 2035` — prompt context strings `"307->185 lbs"` and `"Target weight: 185 lbs (starting 307, currently ~295)"`

**Per spec §1 row 3:** "Starting weight baseline → Withings reading on Monday May 18, 2026 (whatever it is). No fallback to 307." That means every `, 307)` default should be removed (rely on `profile.journey_start_weight_lbs` being correctly populated) OR replaced with a constant sourced live from May 18's Withings reading. Decision needed (see §15).

---

## 5. The existing "restart" narrative on the live site — IMPORTANT

`site/assets/js/site_constants.js` is documented as *"single source of truth for all factual content on averagejoematt.com"*. Its current journey block reads:

```javascript
journey: {
  start_weight:  307,
  goal_weight:   185,
  start_date:    '2026-04-01',
  experiment_start: '2026-04-01',  // Day 1 of the public experiment
  build_date:    '2026-02-22',     // Day platform build began
  phase:         'Launch',
  hero_tagline:  'Day 1. For real this time.',
  hero_short:    '307 → 185. 26 data sources. Every number public.',
  hero_copy:     'I built an AI health platform, got sick, fell off the wagon, and the system I built didn\'t catch me. So I\'m starting over — publicly. April 1, 2026 is Day 1. Every number, every failure, no filter.',
  cta_sub:       '307 lbs. A relapse. A relaunch. Day 1.',
},
```

Two things to flag:

1. The site **already** publicly references a prior attempt ("got sick, fell off the wagon", "starting over", "relapse", "relaunch", "For real this time"). The May 18 spec §1 row 6 and §15 say: *"No mention of any prior attempt anywhere on the public site."* So this isn't a small copy tweak — every word of `hero_copy`, `hero_short`, `cta_sub`, and `hero_tagline` has to be rewritten from a clean-slate posture. The current voice cannot survive contact with the new policy.

2. The May 18 restart is the **second** public restart this site has staged (April 1 was framed as a restart from the earlier build-phase attempt). Worth knowing for editorial framing — and worth confirming Matthew wants to land the "this is genesis" framing knowing both subscribers and the existing site copy currently say otherwise.

---

## 6. Chronicle code surface

Live chronicle code (excluding cdk.out, archive, handovers):

```
lambdas/wednesday_chronicle_lambda.py        — main generator (3 "307" fallbacks inside)
lambdas/chronicle_email_sender_lambda.py     — sends the email
lambdas/chronicle_approve_lambda.py          — human-in-the-loop approve gate
patches/remove_chronicle_record.py           — utility
docs/archive/wednesday-chronicle-design.md   — historical design doc
docs/archive/2026_q2_specs/SPEC_CHRONICLE_REDESIGN_2026_05_03.md
docs/archive/2026_q2_specs/elena_special_edition_chronicle_2026_05_03.md
deploy/run_chronicle_workflow_2026_05_03.sh
deploy/publish_special_edition_chronicle_2026_05_03.py
deploy/pause_wednesday_chronicle_2026_05_03.py
deploy/investigate_gap_chronicles_2026_05_03.py
deploy/cleanup_gap_chronicles_2026_05_03.py
```

Note: a `deploy/pause_wednesday_chronicle_2026_05_03.py` already exists from a prior pause cycle. Confirms memory that EventBridge for `wednesday-chronicle-schedule` is currently paused — spec §7c is consistent with that.

I did not enumerate the published chronicle entries themselves (S3 `blog/` prefix). That happens at step §7 of the runbook, not at discovery.

---

## 7. Where the spec's recommended constants module should live

Spec §2 says: *"Add to `lambdas/shared/constants.py` (or wherever the project's primary constants module lives — discover first)."*

Discovery result:
- **There is no `lambdas/shared/` directory.** The shared Lambda layer modules live flat under `lambdas/` (e.g., `lambdas/ai_calls.py`, `lambdas/scoring_engine.py`, `lambdas/intelligence_common.py`).
- **There is no `lambdas/constants.py`.** No shared runtime constants module exists at all.
- The only `constants.py` in the repo is `cdk/stacks/constants.py`, and it holds CDK/infra constants (e.g., `SHARED_LAYER_VERSION = 51`). Not a fit for runtime use.

**Decision needed (§15 question A):** where should `EXPERIMENT_START_DATE` + `day_n()` live? Options:
- `lambdas/constants.py` — new flat module, consistent with how other shared modules sit
- `lambdas/experiment_constants.py` — narrower name
- Extend `lambdas/intelligence_common.py` — already imported in many places that need it
- Put it in `config/user_goals.json` only, and read it via the existing config loader (no new Python module — pure data; consistent with current pattern but loses the `day_n()` helper)

Recommendation: new `lambdas/constants.py`, exported as part of the v52 layer build. Mirrors `cdk/stacks/constants.py` but for runtime. Lowest-disruption.

---

## 8. EventBridge state — flagged but not verified at discovery

Spec §7c assumes `wednesday-chronicle-schedule` is paused. Memory and the presence of `deploy/pause_wednesday_chronicle_2026_05_03.py` corroborate. **Not verified in this discovery pass** (would require an AWS call, out of scope for §3). Will confirm before §7 reaches the re-enable gate.

---

## 9. Site CDN / cache implications — flagged for §8

Site is on CloudFront `E3S424OXQZ8NBE` (per spec §8 preamble). Any change to `site/assets/js/site_constants.js` or the HTML files needs a CloudFront invalidation post-deploy. Site-api Lambda responses likely also have cache headers — those need to be considered separately during §4c/§8b rollout. **Not action-needed at GATE 1.**

---

## 10. Tests that will break (preview)

These files contain anchor-date hits and almost certainly assert on the current `2026-04-01` value:

- `tests/test_shared_modules.py` — 40 anchor hits
- `tests/test_mcp_registry.py` (referenced by spec §13) — needs re-run after MCP changes
- A grep of `tests/` for `2026-04-01` and `307` was not part of §3's command set; flagging for the §4c step.

---

## 11. MCP tool catalog impact

Per CLAUDE.md, the MCP tool count is 135 tools across 26 modules, with V2 P4.1 pruning planned because only ~11 are used per 30-day EMF. The spec §10 doc-update matrix calls for adding `phase=experiment` documentation to MCP tools. **No risk surfaced at discovery.**

---

## 12. Things that look already-aligned

Some good news:
- The site-api Lambda already gates many endpoints with `if date_str < EXPERIMENT_START: return ...` (e.g., lines 856, 964, 3172). The skeleton for phase filtering already exists; the spec §4c retrofit is mostly a rename + change of the underlying constant value, not a new pattern.
- `lambdas/site_api_lambda.py:769` already has a comment acknowledging the 307 fallback: `"Matthew's journey start weight fallback; only used when no Withings data exists"`. Indicates prior awareness that this is a temporary scaffold.
- The phase=pilot tombstone pattern is already established in the codebase (`patches/remove_chronicle_record.py` exists; ADR-046/032/033 enforce no-delete on S3). The new `phase` attribute lands cleanly.

---

## 13. What was *not* checked in §3 (deferred to later gates)

- DDB partition snapshot / row counts — needed for the wipe in §5 but out of scope for discovery
- S3 `blog/` and `generated/` inventory — needed for §7a (chronicle hide)
- Subscriber list state — needed for §11
- Whether `og-image-generator` reads `EXPERIMENT_START` or computes Day-N another way — needed for §8d
- Tests subdirectory hard-coded date inventory

These are normal next-step work, not blockers.

---

## 14a. Decisions locked in by Matthew (2026-05-21)

| # | Decision | What it means for §2 onward |
|---|---|---|
| A | **New `lambdas/constants.py`** | Create flat module, mirror into v52 layer. `EXPERIMENT_START_DATE` + `day_n()` live here. Other Lambdas import from `lambdas/constants.py`. |
| B | **Config-as-source-of-truth** | Update `config/user_goals.json` (`start_date = "2026-05-18"`, `journey_start_weight_lbs = <May 18 Withings reading>`) and `config/character_sheet.json` baseline. Then sweep all 134 `, 307)` inline fallbacks and 6 hardcoded `"2026-04-01"` literals so they read from config (or from the typed re-export in `lambdas/constants.py`). No inline defaults remain. |
| C | **Split `site_constants.js`** | The *values* block (`start_date`, `start_weight`, `experiment_start`) updates in §2 alongside the configs (probably via a generator script that reads `config/user_goals.json` and writes the JS). The *copy* block (`hero_tagline`, `hero_copy`, `hero_short`, `cta_sub`) gets rewritten in §8a with Elena-voice clean-slate framing. |
| D | **Full scrub** | Scrub everything pre-May-18 from public copy — `site/builders/index.html` Feb-22 reference included. Chronicle handling: for the existing posts (i) keep the first 1–2 "starting" entries but re-date their published timestamps to the week of May 18 (per spec §7b); (ii) anything more recent that uses restart/start-over/relapse framing gets removed from the live site and tombstoned with `phase=pilot` + `hidden=true` so it's recoverable later but invisible publicly. |
| E | **Default-deny tombstone rule** | A category is *coach-running-state* if it's computed by a Lambda and feeds back into coach behavior — tombstone. It's *durable user-fact memory* if you write it yourself or it captures an immutable reference point — keep (tagged `phase=pilot`). **Tombstone:** `failure_pattern`, `what_worked`, `coaching_calibration`, `personal_curves`, `weekly_plate`, `journey_milestone`, `insight`, `experiment_result`, `intention_tracking`. **Keep + tag pilot:** `baseline_snapshot` (and write a fresh May-18 record), `re_entry`, any Cycle markers. Wipe script defaults to tombstone for any category not explicitly in the keep-list, so future IC categories are caught by default. |

---

## 14b. Original ambiguities (now resolved — kept for trace)

Five decisions that the spec doesn't fully answer:

**A. Where does `EXPERIMENT_START_DATE` live in code?**
See §7 for options. Recommendation: new `lambdas/constants.py`.

**B. What happens to the `, 307)` defaults?**
Three options:
1. Remove them — let `profile.get("journey_start_weight_lbs")` return None and force callers to handle missing data. Cleanest, but every site_api endpoint that previously rendered "307" will now render "—" until the May 18 Withings sync lands.
2. Replace with a new constant `EXPERIMENT_BASELINE_WEIGHT_LBS = <may_18_value>` after the Withings reading is captured. Symmetric with how `EXPERIMENT_START_DATE` is handled. Requires §2 to wait until after Matthew weighs in May 18 morning.
3. Update `config/user_goals.json` to set `journey_start_weight_lbs` to the May 18 reading, and *trust* the config — drop the inline defaults entirely. Closest to existing patterns; one source of truth for both date and weight.
Recommendation: **option 3** — update `config/user_goals.json` (`start_date` + `journey_start_weight_lbs`) and `config/character_sheet.json` baseline together with §2, then sweep out the `, 307)` and `"2026-04-01"` inline fallbacks in §4c. The configs become *the* source of truth, the Python constants become a typed re-export of them for code that needs strict typing.

**C. Should `site_constants.js` be treated as code (rewrite in §8) or config (update in §2)?**
It is technically JS but documented as a content source-of-truth. The hero copy needs Elena-voice rewriting, which feels like §8a work. The `start_date / experiment_start / start_weight` *values* though feel like §2 work. Recommendation: split it — values updated in §2 (or via a deploy script that reads `config/user_goals.json`), copy rewritten in §8a. Confirm.

**D. What about the existing "restart" narrative on the live site?**
The April-1 hero copy explicitly references a prior failure. Per spec §1 row 6 / §15, May 18 must show no acknowledgement of *any* prior attempt — but right now the site is publicly acknowledging one. Two possibilities:
1. The May 18 rewrite scrubs both the April-1 launch *and* the pre-April-1 build phase from public copy. Genesis as if nothing existed before. Subscribers see the change with no explanation.
2. The May 18 rewrite scrubs only references-to-prior-attempt, but leaves the build-history page (`site/builders/index.html` mentions "started this platform on February 22, 2026") because that's about the *platform*, not the *experiment*.
Recommendation: **option 2** — separate platform-build history (visible, factually about Claude-Code partnership) from experiment-attempt history (hidden). The "Day 1. For real this time" hero must go either way. Confirm.

**E. Coach-running-state vs durable platform_memory.**
Spec §5 last row says: *"Tombstone coach-running-state; keep durable user-fact memory."* Need to confirm with Matthew which `category` values count as "coach-running-state" before the wipe script runs. Not blocking §2, but blocking §5. Flagging now so he can think about it.

---

## 15. Recommended next 3 steps (after GATE 1 approval)

1. Resolve §14 questions A–E with Matthew.
2. Update `config/user_goals.json` + `config/character_sheet.json` baselines (or the agreed source-of-truth) with `start_date = 2026-05-18` and `journey_start_weight_lbs = <pending May 18 Withings reading>`. If Matthew has the May 18 reading already, plug it in; if not, gate §2 until he runs a sync.
3. Create `lambdas/constants.py` with `EXPERIMENT_START_DATE` + `day_n()` per spec §2, and publish layer v52.

Then we proceed to §3-of-runbook (which is the *fourth* gate, since we've now finished §1-of-runbook which is this discovery).

---

## 16. Files referenced

- Raw scans: `_grep_anchors.txt`, `_grep_307.txt`, `_grep_dayn.txt`, `_grep_streaks.txt`, `_chronicle_files.txt`, `_grep_site_copy.txt` (all in this directory)
- Spec: `~/Desktop/CLAUDE_CODE_RESTART_2026_05_18.md`
- Repo CLAUDE.md (architecture context): `~/Documents/Claude/life-platform/CLAUDE.md`

---

**End of discovery. Awaiting GATE 1 sign-off + answers to §14 A–E before touching code.**
