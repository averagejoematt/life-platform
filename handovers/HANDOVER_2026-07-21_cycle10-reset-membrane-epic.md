# HANDOVER — Cycle-10 reset + non-fable paydown + the Social Membrane epic — 2026-07-21

> Instruction thread: "Goal 1 — re-anchor the experiment to 2026-07-22 (cycle 10); full dry-run,
> report every gate, stage the apply (OWNER), record the tier-1 truth-gate loud-skip honestly.
> Goal 2 — pay down non-fable backlog (#1618/#1634/#1639/#1640/#1620…), gate:owner to code-complete,
> verify every agent finding, batch merges into one ask." → "yes go ahead do it, but i do want that
> article still readable" (reset apply) → "yes i approve you to keep going" (commit + deploys) →
> `/plan` "how we INGEST socials — both ways… create all issues… imagine product leaders" → plan
> approved → wrap (sequenced after the parallel eng-excellence session).

Ran concurrently with the eng-excellence/craft-review session (its handover archived to
`HANDOVER_2026-07-21_eng-excellence-craft.md`; its PR #1647 + epic #1648 carried forward below).

## What shipped (all merged to main AND deployed/verified live)

**Cycle-10 experiment reset → genesis 2026-07-22 (Wed)** (`b206bf21`, `restart_pipeline.py --apply
--override-weight-lbs 321.38`; no 07-22 weigh-in existed, honest last-known 07-20 baseline used).
Clean-prologue start — "Before the Numbers" preserved as the genesis−6 lead-in (readable, Prologue·PartI).
- **Semantic gate 7/7** (authoritative — character zeroed, pre_start flags, **0 poisoned rows / 32 raw-timeseries sources**). Ledger rolled → **$0**. SSM cycle=10, constants=2026-07-22 fleet-wide. Live `/api/journey` confirms `day_n:0, pre_start:true, days_until_start:1, start_weight:321.4`.
- **Rendered gate: 2 verified FALSE-POSITIVES** — `/api/vitals` + `/panelcast/episodes.json` tripped the "outgoing-genesis literal (2026-07-20)" scan, but 07-20 is *legitimately* the last-data `as_of_date` AND the genesis−2 prequel date. A 2-day-gap reset collides the outgoing genesis with real new-cycle dates; the literal scan can't tell them apart. Semantic gate is authoritative.
- **Truth gate: LOUD-SKIPPED at budget tier 1** (July window) — the AI reader-truth layer did NOT run this reset. Recorded in `_verify_truth_report.txt` + RESET_LOG. **Not a green.**

**#1644 (#1634) — canary judge false-positive fix** (`0fc5acda`). The advisory Haiku judge FP'd on "Dr. Sarah Chen" (a sanctioned coach persona) as an AI-vendor break. Rewrote the prompt to the real contract (vendor/model ≠ coach persona), `_persona_names()` **derives from `persona_registry`/`config/personas.json`** (not hardcoded), deterministic verdict authoritative (ADR-105), judge stays advisory (ADR-108). Deployed `LifePlatformOperational`.

**#1645 (#1640) — OG share cards signed with the AJM dial mark** (`cde14687`). Mark wired into the shared `card_engine.base_canvas()` (covers all 13 cards, transcribed from `mark-a.svg` as Pillow primitives, no rasterizer). Deployed + invoked `og-image-generator` → **13/13 regenerated**, dial mark confirmed live top-right.

**#1646 (#1618) — receipts projection curve** (`96d1278a`). `/method/receipts/` now draws solid MTD + a dashed governor projection to month-end (from `projected_month_end_usd`, no JS re-extrapolation), caption = "governor ESTIMATE" (ADR-105). site-api deployed (`month_end_date` field) + site auto-deploy. Render-QA'd live both themes: projection $94.6 under the $115 July ceiling (tier 1) — no crossing, the honest depiction.

**#1667 (#1639) — full head-chrome on every content page** (`260e03d3`). Single-source `scripts/v4_chrome.py head_chrome()` + `--check` gate; **79 pages** got the manifest/apple-touch/theme-color/SVG-favicon block (not 61 — that was manifest-only; SVG favicon was on 0). Site-only, auto-deployed.

Two doc-sync reconciles handled the cumulative `test_count` (4857→4866 after the batch, →4870 after #1667).

## Also done (no merge)
- **The Social Membrane** — `/plan` for bidirectional social (ingest own posts → coach signal + display, not just outbound). **Epic #1668 + 11 stories #1669–#1679** filed (Now/Next/Later). The loop-breaker Matthew flagged ("don't re-ingest the platform's own outbound posts → spanning-tree echo") is a foundational story: **#1670 the provenance membrane**. Cross-linked to the pre-existing **outbound** epic **#1619** as its inbound counterpart — one bidirectional program. Locked decisions: all-platforms/auto-where-possible, auto public feed behind a fail-closed sensitivity gate, facades-now/native-later, membrane is foundational. Plan file: `~/.claude/plans/quizzical-riding-chipmunk.md`.
- **#1643 filed** — `restart_site_copy_sync.py:82` regen-invokes non-existent `life-platform-daily-brief` (real name `daily-brief`) → the benign `err(254)`.

## Gotchas hit
- **Small-gap reset → rendered-gate false-positives.** When genesis moves only a few days, the outgoing genesis literal collides with legitimate new-cycle dates (last-data `as_of_date`, the genesis−2 prequel). The rendered gate's string scan false-fails; the **semantic gate is the authoritative correctness signal** (it checks meaning, not literals). Don't rollback on a rendered-gate-only fail — diff the actual served JSON first. → memory `reference_small_gap_reset_false_positive`.
- **Agent self-reports still need verification.** All 6 worktree-agent findings independently `git grep`-verified before relaying — all held this time, but the OG agent correctly flagged the issue's "13 cards" vs stale docstring "6"/"12"; the head-chrome agent corrected "61"→"79". Verify counts, don't relay them.
- **Concurrent-session shared-tree race (again).** My reconcile `git add -A` (214b7d58) swept in the parallel session's staged `git mv` (their handover archive). No damage, but it's the standing shared-index hazard — wrapping each session from its own worktree would avoid it (noted as a hygiene consideration, not filed).
- **`node --test tests/js/` with a dir arg fails; CI runs bare `node --test`** (carried from prior session, hit again).

## Gate outcomes
- **Build beat:** `2026-07-21-receipts-honest-projection` (the #1618 curve — the platform's honesty ethos made visible; OG marks / head-chrome / reset mentioned in a clause).
- **Docs:** none needed beyond the reset's own auto-sync (CHANGELOG/SCHEMA/RESET_LOG in `b206bf21`) + the two `test_count` reconciles. The 4 code PRs touch no canonical wiki page.
- **Decisions:** none needed — the reset is routine under ADR-077; the Social Membrane is a filed plan/epic, not a shipped governance choice (its ADR, if any, lands with #1678's CSP amendment).
- **Main:** red — the latest completed non-cancelled CI/CD run (`953566a2`) is parked/FAILED at the manual production Deploy gate; superseding commits' runs auto-cancelled. My automated gates (Lint/Test/Plan) are green; this is the standing manual-gate park, not a test break.
- **Incidents:** none — no auto-rollback fired (all site-deploys green), no main-red>1h beyond the standing manual-gate park, no data gap; the tier-1 truth-gate skip is the pre-existing July-window condition (logged in RESET_LOG, not a new incident).
- **Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.
- **Labels:** OK — 97 open type:story issues all carry `model:*`.

## Residual / next-picks
- **PR #1647 (eng-excellence /craft-review skill + ENGINEERING_STANDARDS.md) OPEN** — owner-merge, then drain epic **#1648** (18 stories #1649–#1666) via `/uplevel` (Now tranche #1649/#1651/#1652/#1657/#1659/#1660). (#1647, #1648)
- **The Social Membrane** — start the foundation: **#1669** (inbound ingestion framework + YouTube) + **#1670** (provenance membrane, ships together). (#1668/#1669/#1670)
- **#1620** — outbound social links + follow affordances; the outbound half of #1619/#1668; runs the `v4_apply_chrome` HTML sweep so land it AFTER any reset/head-chrome sweep. (#1620)
- **#1643** — fix the stale `daily-brief` regen name in `restart_site_copy_sync.py`. (#1643)
- **AiReviewPack (#1594) first fires Sunday 18:00 UTC** — a new weekly QA email to Matthew; review/mute before then if unwanted. `not-work — owner review of a just-activated schedule`.
- **Standing alarms:** none newly outstanding; budget **tier 1** (July window working as designed, not an alarm). `not-work — standing-alarms checklist, nothing to action`.
