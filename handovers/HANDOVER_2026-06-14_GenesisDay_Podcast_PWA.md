# HANDOVER — 2026-06-14 (Genesis Day · autonomous podcast · Dr. Eli Marsh · baseline re-anchor · installable Cockpit PWA)

> Cycle-4 genesis day (experiment start 2026-06-14, baseline 314.52, cycle 4). A very
> large session — **10 PRs merged to `main`** (#110–#119, tip `064414f`), 0 open. The
> headline: the podcast became an **autonomous, QA-gated weekly show**, a named
> **Principal Investigator** persona joined the team, the experiment **baseline was
> re-anchored to the real genesis weigh-in**, and the site gained an **installable
> Cockpit PWA + a mobile bottom door-bar**.

**Prior:** `handovers/HANDOVER_2026-06-13_EvidenceRestore_Podcasts_LeadScientist.md`.

---

## 0. Deploy ledger — what is LIVE

| Change | PR | Live? |
|--------|----|-------|
| Evidence catalog restore + reset-proof (supplements/experiments/challenges/habits) | #110 | ✅ |
| Podcast series bible + Day-Zero guardrails; Episode 0 rewrite | #112 | ✅ |
| Episode 0 duration/byline fix (~134→~6 min, WAV) | #114 | ✅ |
| Episode 0 → Sonnet + richer bible (Elena-led, real backstory, numberless, "Matt") | #115 | ✅ |
| **Autonomous QA-gated weekly Panel pipeline** | #116 | ✅ code; **CDK deployed** (Fri cron + 900s + SNS/holds IAM) |
| **Panel ledger** (bet scoreboard, `/api/panel_ledger`) | #117 | ✅ |
| Conversational push + **ADR-087** (audio-realism ceiling) | (in #116 era / committed) | ✅ |
| **Installable Cockpit PWA** + mobile bottom door-bar + responsive polish | #118 | ✅ (site sync) |
| Mobile door-bar backdrop-filter containing-block fix | #119 | ✅ |
| **Baseline re-anchor → 314.52** (genesis weigh-in) via `restart_pipeline.py --genesis 2026-06-14 --apply` | — | ✅ Matt ran it; layer bumped, constants=314.52 |

**Layer:** bumped by the restart (constants `EXPERIMENT_BASELINE_WEIGHT_LBS=314.52`, `EXPERIMENT_START_DATE=2026-06-14`). **No open PRs.**

---

## 1. The autonomous weekly podcast ("The Panel") — the big build
Board-reviewed (Product/Technical/Personal all convened, see the `/plan` transcript). `lambdas/emails/coach_panel_podcast_lambda.py` weekly path is now a pipeline:
`_gather_week` (deterministic beats + series_state) → `_build_weekly_script` (Sonnet, the **bet/Split/scoreboard/cliffhanger** format from the bible) → `_editor_review` (Haiku judge, quality + safety floor) → `_weekly_gate` (ER-03 + the **fail-closed Compassion & Safety gate**) → `_sensitivity_hold_reasons` → **publish-or-HOLD**.
- **Compassion & Safety gate** (`_safety_gate`, deterministic, fail-CLOSED): blocked vice / body-number / grief-family-named-person / report-card tone / causal → HOLD, never publish. Tested per class.
- **Autonomy asymmetry** (Personal Board): auto-publish ordinary weeks; **hard/sensitive weeks HOLD** → non-public `panelcast-holds/` draft + SNS alert (`life-platform-alerts`). Never auto-voices grief/family.
- **series_state in DynamoDB** `USER#matthew#SOURCE#panelcast / STATE#current` (`phase_taxonomy` = `EXPERIMENT_SCOPED`, reset-safe); carries `open_bet` + `recent_topics` + `bet_ledger`.
- **Schedule:** chronicle Wed (unchanged); **Panel `cron(0 17 ? * FRI *)`**, timeout 900s. First real episode auto-generates the first post-genesis Friday.
- **Voice:** Gemini 2.5 multi-speaker single-pass (Elena + rotating coach), WAV. **Limitation tracked in ADR-087** — true NotebookLM overlap is bounded by the script→TTS split; monitor for a Google Audio-Overviews API / Studio MultiSpeaker allowlist, then swap only `gemini_tts.py`.
- **Panel ledger:** `/api/panel_ledger` (`site_api_coach.handle_panel_ledger`) → bet record; rendered on `/story/panel/`. Empty until episodes accrue.
- **Cost:** ~$1.50–3.50/mo (Sonnet writer + Haiku judge + Gemini); bounded by `bedrock_client` tier-3 + per-run call cap.

## 2. Episode 0 (the trailer) — final state
Elena interviews **Dr. Eli Marsh** (the PI), single-pass Gemini, **deterministic "I'm Elena Voss" cold open** + "Matt" enforcement (Sonnet wouldn't reliably do either), 26 conversational turns, numberless (reusable across resets), live at `/story/panel/`. Driven by `config/podcast_series_bible.json` (the editable creative spine).

## 3. Dr. Eli Marsh — Principal Investigator (PR #111, earlier)
A **non-operational** orchestrator persona (`config/personas.json`, type meta, `lead:true`) — boss of the 8 coaches, Matt's single point of contact. NOT wired into the compute engine (8-coach invariants intact). Lead of `/story/coaches/`.

## 4. Installable Cockpit PWA + mobile (PRs #118/#119)
**One responsive site, no separate mobile version.** `site/sw.js` (network-first nav + `/api/*`, cache-first assets, offline Cockpit fallback) + iOS home-screen meta + manifest categories/purpose; `start_url=/now/`. `sync_site_to_s3.sh` gives manifest+sw `max-age=300, must-revalidate`. Mobile: the three doors are a **fixed bottom app-bar** (≤600px) — fixed a containing-block trap where `.story-top`'s `backdrop-filter` pinned it to the top on Story/Home. **Matt to verify on device** (hard-refresh).

## 5. Google keys (unchanged from prior handover)
One secret `life-platform/google-tts`: `api_key`=Cloud TTS (Chirp, managed project), `gemini_key`=Gemini (a **personal** Google account — managed domain blocks AI Studio). An orphan 3rd key on the managed project can be deleted (Google console). Two keys appeared in chat → rotate when convenient.

## 6. Open items / next
- **Verify mobile on device** (door-bar bottom everywhere; Add-to-Home-Screen → standalone Cockpit, live data, offline).
- **First weekly episode** lands the first post-genesis Friday — watch for a clean publish vs a HOLD email.
- **Deferred v2 (documented):** LLM showrunner, 2nd editor loop, Step Functions decomposition, audio teaser clips, email-notify on new episodes, mobile sidebar dropdown / table card-reflow / standalone bottom-tab, ghost counterfactuals (#16, cycle-3).

## 7. Verified
Full suite green across the day; `/evidence/*` 200; `/story/panel/` plays Episode 0; `/api/panel_ledger` 200; sw.js + manifest `max-age=300`; Panel cron `FRI 17:00 ENABLED`, timeout 900s; baseline 314.52, cycle 4. Latest ADR **ADR-087**.

**Verified:** 2026-06-14.
