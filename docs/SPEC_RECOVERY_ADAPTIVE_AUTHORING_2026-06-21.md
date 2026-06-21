# Build Outline & Design Brief — Recovery-Adaptive Night-Before Authoring — v1.0

> **Destination in repo:** `docs/SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md`
> **Date:** 2026-06-21 · **Version:** 1.0
> **Status:** Pre-build outline. Build instructions → `docs/specs/CLAUDE_CODE_PROMPT_RECOVERY_ADAPTIVE_AUTHORING_v1.md`.
> **Boards consulted:** Personal (Sarah Chen, Iris Tanaka, Maya Rodriguez, Marcus Webb, Henning Brandt), Technical (Priya, Jin, Omar, Henning).
> **Related:** `docs/SPEC_HEVY_NOTES_FEEDBACK_LOOP_2026-06-21.md` §14.3 (this supersedes that stub), `TRAINING_CALIBRATION.md` (subtract-only autoreg, autoregulation gates), the `get_muscle_volume` staleness bug (§14.4 of the notes brief — a hard prerequisite here).

---

## 1. Problem statement (the real constraint)

Routines are authored the **night before** but executed the **next morning**, against a recovery signal that did not exist at authoring time. Matthew's morning is **wake → car → gym** — he has **no opportunity to interact with the platform** before training, and explicitly does not want to invent on-the-fly audibles. Therefore:

> **The routine in his hand must be fully correct and self-adapting at 5am with zero morning platform interaction.**

Today (2026-06-21) failed this twice:
- **Stale-author bug.** The routine was built on a night-before `get_muscle_volume` read that hadn't aggregated the latest sessions → it called calves "lagging" (they were optimal) and core "zero" (it was covered, mis-mapped to `Other`). The *baseline* was wrong before recovery even mattered.
- **Static-tier bug.** The routine was hard-stamped `recovery_tier=yellow` off Jun 20's reading. He woke GREEN 95%. The routine couldn't see the morning, and he couldn't fix it in the car.

Result: a sunk-cost session miscalibrated on two axes. This spec makes both impossible going forward, with the work-week (low-time) case as the design target.

---

## 2. Core principles (non-negotiable)

1. **Author tier-agnostic. Never bake one night's tier into the prescription.** The routine carries *all* recovery branches; the morning selects one.
2. **Self-selection on a wrist-visible signal.** The only morning input is a glance Matthew already takes — his **Whoop recovery colour** (on the band/app at wake). No platform interaction, no compute dependency, no network race.
3. **Safe default always present.** Missing/ambiguous morning signal (didn't wear the band, sync lag) → the **YELLOW/baseline** branch, which is always written and always safe to just do.
4. **Subtract-only preserved (reconciles `TRAINING_CALIBRATION.md`).** Author the **GREEN session as the ceiling**; YELLOW and RED are *defined subtractions* from it. On the day, within the selected branch, Matthew only ever goes **down**. A pre-authored green branch is "the plan for a green day," not a same-day ego-add — so subtract-only holds.
5. **Freshness-gated authoring.** Before authoring, verify the volume / recent-workout / recovery inputs **include the latest sessions** — completeness, not just max-date recency (the §14.4 failure-class, same as the Strava high-water-mark blindness). If inputs are stale/incomplete, **block or flag** — never author on them.
6. **Branch only the levers that should move.** Not every exercise. Branch the **intensity/quality levers** (cardio character, top-set RPE cap, optional volume) and keep it to **three branches max** so cognitive load at the gym is near-zero.

---

## 3. The branch rubric (standardised — he learns the format once)

Every adaptive routine writes the same three-line block into the relevant exercise cues. Keyed to **Whoop recovery bands** (Whoop's own thresholds, because that's what's on his wrist):

| Branch | Whoop band | Meaning | What moves |
|---|---|---|---|
| 🟢 **GREEN** | 67–100% | Primed — take the ceiling | Quality unlocked: intervals instead of steady; top-set RPE cap +1; the optional set/exercise is *on* |
| 🟡 **YELLOW** | 34–66% | Baseline — the default plan | The prescription as written; optional work optional |
| 🔴 **RED** | 1–33% | Subtract to the floor | No intervals (Z2 only); cut top sets; lighten or convert to mobility/technique; or the rest-day call |

**Two hard rules baked into the rubric:**
- **Trust the *lower* of (wrist colour, how you feel).** Feel can **downgrade** a branch, never upgrade it. Whoop green but you feel wrecked → train yellow/red. Whoop yellow but you feel great → still yellow. (Subtract-only extended to the subjective — prevents ego-lifting and covers the illness/life-stress Whoop misses.)
- **The GREEN branch is the ceiling, not a PR attempt.** On a deep-deficit or late-in-week day, GREEN means "quality maintenance," not "add load" (Marcus / week-position, §4).

The block reads, in-app, like:
> *🟢 intervals 6↔8, 25 min · 🟡 steady L10, 25 min · 🔴 easy L6 spin, 15 min or skip. Use the lower of band/feel.*

---

## 4. Week-position & fuel awareness (the authoring must know where he is)

Static branches aren't enough — the *floors rise* as the week accumulates:
- **Consecutive-day count.** By day 5–6 of a streak, GREEN requires a genuine green *and* bias toward the YELLOW/RED structure; the ceiling lowers. Authoring reads the recent-workout history (freshness-gated) and sets the week-position.
- **Deficit state.** On a deep cut (current: ~1,474 kcal, protein short), the GREEN ceiling is "quality," and RED triggers earlier. Marcus's lever, encoded as a ceiling cap, not a vibe.
- **Connective-tissue ramp.** Early in a return block, novel-pattern lifts cap their GREEN branch lower regardless of recovery (Iris) — recovery being green doesn't clear a tendon that's three sessions into re-loading.

---

## 5. Edge-case table (this is the "edge-case-proof" core)

| # | Edge case | Handling |
|---|---|---|
| E1 | Morning recovery not computed yet (early riser / Whoop sync lag) | Self-selection uses the **wrist colour** (computed on wake, no platform). If even that's absent → **YELLOW default**. Routine never depends on platform compute in the morning. |
| E2 | Didn't wear the band / no recovery at all | **YELLOW default**, explicitly stated in the cue. Never leaves him planless. |
| E3 | Author-time data stale/incomplete (today's bug) | **Freshness/completeness gate blocks authoring** or flags loudly; dry-run shows "inputs current through \<session/date\>". No routine ships on stale volume/recovery. |
| E4 | RED morning | Pre-authored floor: Z2/mobility/technique, top sets cut, or the explicit rest call — so he isn't *inventing* a deload while exhausted. |
| E5 | Conflicting signals (green band, wrecked body — or vice-versa) | **Lower of (band, feel)** rule in the rubric. Feel only downgrades. |
| E6 | He trains a different session than authored (equipment busy, etc.) | Authoring tolerates it; the divergence is captured by `deviation` (notes-loop §14.1). Authoring never assumes the performed = authored. |
| E7 | Weekly authoring (Sunday sets the week; low weekday time) | Each day authored **independently & self-contained** with its own branches — no day depends on a prior day's *actuals* being known at author time. A 60-second nightly "still valid?" check (below) is the only weekday touch. |
| E8 | Cumulative fatigue across a 6-day block | Week-position (§4) raises floors automatically for later-week sessions at author time. |
| E9 | Recovery whiplash (green today after yellow yesterday) | Self-selection is per-day; no carryover assumption. Handled by design. |
| E10 | Composite readiness ≠ Whoop colour | Branches key to the **simple wrist band only** (what he can see at 5am), never the composite he can't. Bands documented in the rubric so it's unambiguous. |
| E11 | Overnight re-stamp (if built, §6B) runs late / fails | Pure sugar. The conditional branches are **always present** as the fallback; a missed re-stamp just means he self-selects. No hard dependency. |

---

## 6. Architecture — two layers

### Part A — Authoring protocol (works THIS WEEK, zero build)

A change to **how Claude authors** in `manage_hevy_routine`, usable tonight:

1. **Freshness pre-check (mandatory first step).** Before drafting, confirm volume + recent-workout + recovery inputs include the latest sessions (completeness check, §5/E3). If stale → stop, flag, refresh. *This alone prevents today's calf/core error.*
2. **Author tier-agnostic with the §3 rubric.** Author the GREEN ceiling; write the 3-line branch block into each branchable lever's cue; YELLOW/RED as explicit subtractions. No `recovery_tier` stamp drives the prescription.
3. **Apply week-position + deficit + tissue caps** (§4) to set the ceiling and floors.
4. **Night-before preflight he can eyeball in 30s.** The dry-run shows the session + the branch block + an "inputs current through X" line, so he sleeps trusting it.
5. **Weekly mode (Sunday authoring).** Author the week's sessions as independent self-contained adaptive routines; each weekday night is a 60-second "anything from the last 24–48h change tomorrow's plan?" confirmation, not a re-author.

### Part B — Platform hardening (Claude Code build)

1. **Enforce the freshness/completeness gate inside `manage_hevy_routine`** (draft path) — refuse to compile a routine whose volume/recovery inputs don't cover the latest ingested sessions; return the gap. Makes E3 structural, not dependent on Claude remembering.
2. **First-class conditional-cue support** — a `branches` field on exercises so the GREEN/YELLOW/RED block is structured data, rendered consistently into Hevy notes (not free-text each time).
3. **Week-position computer** — a helper that returns consecutive-day count, deficit state, and tissue-ramp position for the authoring path to consume.
4. **(Optional) overnight re-stamp Lambda** — post-Whoop-sync, *if* morning recovery lands before a configurable cutoff, update the routine to pre-highlight the matching branch (and optionally re-title). **Guardrails:** never removes the other branches (Part A always intact); idempotent; no-op if data late; logs the action. Pure enhancement — do not let anything depend on it.

---

## 7. Board sign-offs

- **Sarah Chen (periodization):** "Branching the *intensity lever* on morning recovery is textbook autoregulation — you're just pre-computing both paths because he can't decide at 5am. Right call."
- **Iris Tanaka (joints):** "RED must be pre-authored, not improvised by a depleted person — and a green band never clears a novel-pattern tendon. Tissue cap on the GREEN branch is the line I won't move."
- **Maya Rodriguez (adherence):** "Self-select on the wrist colour is the most this guy will do at 5am, and it's enough. Don't add a step. And never make GREEN feel like a punishment-day — momentum is the asset."
- **Marcus Webb (nutrition):** "Encode the deficit as a ceiling cap. On 1,400 kcal, GREEN is quality, not load. Bake it in so it isn't forgotten on a motivated morning."
- **Henning Brandt (rigor):** "The freshness gate is the headline. Today's miscalibration was a *completeness* failure, not a recovery failure. Author on incomplete data and the branches are just well-dressed garbage. Gate first, branch second."
- **Priya / Jin (Tech):** "Gate belongs in the tool, not in Claude's discipline. The re-stamp is nice but must be fail-open to the branches — no morning hard dependency, no race."

---

## 8. Decisions — Matthew to lock

- [ ] **Branch signal** — Whoop recovery band (recommended; wrist-visible) vs the composite readiness. *Default: Whoop band.*
- [ ] **Band thresholds** — Whoop default 67/34 (green/yellow/red). *Default: Whoop's own.*
- [ ] **Branch count** — 3 (green/yellow/red) vs 2 (go/scaled). *Default: 3.*
- [ ] **RED policy** — does RED ever mean *rest*, or always *reduced session*? *Default: reduced session, with rest as an explicit option on RED + late-week.*
- [ ] **Overnight re-stamp (Part B4)** — build it, or rely on self-selection only? *Default: self-selection only for v1; re-stamp is a later optional.*
- [ ] **Weekly authoring cadence** — author the full week Sundays + 60s nightly check, vs author each night. *Default: weekly + nightly check (fits the low-time work week).*

---

## 9. Doc-update implications

CHANGELOG + PROJECT_PLAN always; DECISIONS (ADR: "recovery-adaptive authoring — author tier-agnostic with morning self-selection; freshness-gate the authoring inputs"); TRAINING_CALIBRATION.md (the branch rubric + the "lower of band/feel" rule become part of the autoreg standard); MCP_TOOL_CATALOG + RUNBOOK if `manage_hevy_routine` gains the gate + `branches` field; the §14.4 `get_muscle_volume` bug is a hard prerequisite and should land first or in parallel.

---

## 10. Appendix — Data-integrity completeness bugs (shared root, surfaced 2026-06-21)

Three bugs this session share one root: **reads report 'fresh/complete' off a high-water-mark (newest record) and are blind to gaps behind it.** The authoring freshness gate (§6) is the consumer-side defence; these are the source-side fixes. Captured so none is lost.

**B1 — Strava walk ingestion gap.** Strava (source of truth) had 6 walks Jun 14–20; the platform stored only 2 (the 14th + 20th). Both read paths (`search_activities`, `get_weekly_summary`) agreed — so it's an ingestion gap, not a query bug. Same-day discriminator: on the 16th the Hevy weight session ingested but both Strava walks did not → per-activity, likely **Walk-type, failure** (the one clean walk carried an `enriched_name`; the others didn't), consistent with enrichment dropping Walk activities and `di1-movement-integrity` being built-but-undeployed. **Diagnostic (run via Claude Code):** pull Strava activity IDs Jun 14–20 from the API → diff against the DDB Strava partition for the window → read ingestion + enrichment Lambda logs for the missing IDs to decide *webhook-never-received* vs *received-but-dropped-in-enrichment*. Do **not** backfill until root cause is shown.

**B2 — `get_muscle_volume` staleness + core-mapping.** (Full detail: notes brief §14.4.) Night-before pull undercounted (calves 10/'lagging', core 0); morning re-pull corrected (calves 14/'optimal', most groups jumped) — latest sessions weren't aggregated. Plus anti-rotation/standing core maps to `Other`, so `core_sets` reads 0 falsely. Poisoned today's prescription directly.

**B3 — `get_freshness_status` high-water-mark blindness (the shared root).** Freshness reported Strava GREEN/live off the newest record (the 20th) while four mid-window walks were missing. **Fix:** freshness must detect *gaps behind the high-water mark*, not just recency — a missing mid-window day must surface, not read green. Generalised fix that also backs the authoring gate (§6) and the meal-layer format-drift guard. Highest-leverage of the three.

**Recommended order:** B3 first (shared instrument) → B2 (poisons coaching synthesis) → B1 (needs the diagnostic to localise).

---

*v1.0 — authored 2026-06-21 off the lived failure (sunk-cost session, stale-author + static-tier). Designed for the wake→car→gym constraint and the low-time work week. Redline freely.*
