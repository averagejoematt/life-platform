# Handover — 2026-08-22 ~08:20 → ~11:20 PT: the plan's metric was wrong, and five instruments were lying

**Session:** Opus 5, interactive. The driving instruction was *"Make a plan for an effective
next autonomous session — pay down as many of our open issues as possible — opus or below only
— no fable"*, then a series of `yes` / *"do what the best engineers would recommend"* approvals
that turned the planning session into an executing one. Previous wrap archived as
`HANDOVER_2026-08-21_deploy-plane-unblock.md`.

**Build beat:** none — nothing reader-visible shipped. The two merges are a CI pin and an
internal privacy-tier guard; the one reader-facing defect found (#2972) is still open and is a
*defect leaving* the site, which `docs/content/BUILD_DISPATCH_CHECKLIST.md` does not want as a
beat.

**Docs:** `docs/INCIDENT_LOG.md` (+2 rows, derived Patterns section regenerated 153→155),
`docs/PROPORTIONALITY.md` (privacy-tier gate row), `docs/SCHEMA.md` (the Tier-2 paragraph now
points at the registry that replaced it), `docs/alarm_citations.json` (#2976 flap citation).
The session plan itself was written to `handovers/NEXT_SESSION_PLAN.md`, which `.gitignore`
keeps off `main` (#1650) — it is laptop-local scratch, so everything durable from it is
reproduced in this handover rather than referenced.

**Decisions:** none needed — no governance-consequential choice was made. The #2841 decision
(umbrella vs. dated acceptance) is recorded on the issue and in `#2978`, and CONVENTIONS §8b
already carried the rule.

**Incidents:** 2 rows added — main red 1h58m on two independent stale-derived-artifact defects
(the second landing on an innocent commit, filed as #2975); and two production-approval leases
rejected as superseded after the deploy had been done manually and verified.

**Main:** red — the newest *completed* CI/CD run is `caa7e6ae`'s, which failed on the literal
drift since fixed by `3eb9f2583`. Every gate has since passed on HEAD: run `32587130309` on
`a2e02465` shows reconcile / lint / deploy-critical / **Unit Tests** / Plan all green, with only
the Deploy job parked — and that deploy was performed manually and verified, so the lease was
rejected rather than left to strand. Docs CI is green on HEAD.

**Alarms:** clean after adding one citation — `ingest-liveness-unhealthy` fired **and cleared**
inside the 72h window (the #2912 flap detector's catch), cited to #2976 with the live
measurement that explains it.

**CI warnings:** none to triage — the newest completed main run isn't green, which is (e2)'s
business, not (e11)'s.

**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.

**Backlog:** Now live at 13 actionable; no stale `Later` issues. Fixed 12 hygiene violations I
had introduced — 9 score lines written with ASCII `x`/`->` instead of canonical `×`/`→`, 2
`## Outcome` blocks naming an unsanctioned audience ("Readers"), and epic #2799's `## Stories`
missing its 6 new children.

**Closures:** #2759, #2803 commented (the two that auto-closed via `Fixes` with no comment);
#2841, #2753, #2802 carried their verdicts at close time.

**Ledger:** privacy-tier field registry + consumer gate row added to `docs/PROPORTIONALITY.md`
(#2803) — posture, rent, and a stated demote trigger, honoring the issue's ADR-103/144 pricing
caveat.

---

## What shipped

| PR | what | state |
|---|---|---|
| **#2966** | the npm leg of #2759 — `remediation/package.json` as version of record, Dependabot npm ecosystem, bare-`npm install -g` guard | merged `cbbc08ce2` |
| **#2980** | #2803 — privacy tier becomes structure: `field_tiers.py`, an AST-derived consumer registry, `TIER2_STRIP_FIELDS` converted from literal to derivation | merged `a2e024656`, **deployed + verified live** |

Plus two direct commits to main: `caa7e6ae2` (the `#1957` alarm-matcher fix that greened main)
and `3eb9f2583` (INCIDENT_LOG regeneration), and `1688a62b0` (the #2841 tracker pointer).

**Closed:** #2759, #2841, #2803, and epics **#2753** and **#2802** — both with their own
acceptance verified against live code, not inferred from child state.

**Deployed:** `life-platform-site-api` 17:52:06Z and `life-platform-mcp` 17:53:31Z against a
17:14:22Z merge, ancestry-gated preflight and postflight.

## The thing worth carrying forward

**The plan's success metric was wrong.** It said "pay down as many open issues as possible";
open went **74 → 78**. Almost every issue filed describes something that was already broken and
invisible, so a drain-shaped goal structurally cannot see the work. Next session's goal is
better written as *leave the board more honest than you found it*.

Five instruments were found lying, and two of them were mine:

1. **Three alarms lit while healthy** — dropbox recovered at 13:33Z and stayed lit because
   `IngestAuthHealthy` is only ever emitted as `0`; there is no `1.0` anywhere in August
   (#2976).
2. **The AI oracle silently skips 2 pages** — `Home` and `Protocols hub` return a Bedrock
   `ValidationException` and are counted among the passes (#2973).
3. **CI Bedrock spend bills without recording** — the visual-qa role lacks `PutMetricData`,
   plausibly feeding the very drift #2883 is trying to close (#2974).
4. **The truth-ledger baselining path silently no-ops** — it writes only `high` findings, so a
   deliberate baselining run on a finding the oracle grades `medium` that day records nothing
   *and prints "rewritten"* (#2981).
5. **My own PR monitor reported "6 of 6 checks failing"** when nothing was failing — its jq
   treated empty-string conclusions as non-null. Rewritten to key on `.status == "COMPLETED"`.

And twice a verification I ran measured nothing and returned clean: an MCP probe that got a
401 with no data (re-done by executing the downloaded live artifact), and a fallback-chain
measurement that read *truncated* text, where truncation had removed the very pronoun that
made it a violation.

## The #2972 reversal — read this before touching it

I built a read-time guard for the public board's audience violations, measured it, and threw
it away. Two disqualifying defects:

- It would have **blanked all seven coach blurbs** on the flagship page.
- It checked text *after* `truncate_at_word(…, 200)`, so a 200-char slice of addressing prose
  passes a check its source fails — it would have laundered the defect it existed to catch.

The real diagnosis: **`position_summary` is empty in 175 of 175 rows.** The board falls through
to `content`, which is written *to* Matthew because that is what it is. `position_summary` *is*
written — to `USER#matthew` / `SOURCE#coach_thread#…`, a different partition — and **that copy
is direct-address too** (8 of 8 sampled). So no producer anywhere writes reader-facing coach
prose, and no read-time guard can fix it.

**I withdrew my own "do not baseline it" instruction** on the issue. That was written believing
this was fresh deploy-caused breakage; 175/175 rows and weeks of history say it is standing
debt, which is exactly what the #2956 ledger exists to hold.

## Residual / next picks

- #2972 — the producer must emit reader-facing coach prose; corrected diagnosis and revised
  acceptance are on the issue
- #2981 — the baselining no-op blocks acknowledging #2972 as debt; fix this first, it is the
  cheaper of the two and unblocks the publish path
- #2975 — the incident-log guard's lane placement; every wrap adding rows reds a later
  innocent commit until this lands
- #2982 — the `test_count` policy conflict; **option A as filed is too blunt** and the refined
  option is in the issue comment, verified against the three real coupling points
- #2976, #2973, #2974, #2977 — the instrument defects above
- #2797 — the epic will NOT close on #2803 alone: six folded findings remain, and one
  (`segmental-fields-unverified-live`) is **blocked on a future weigh-in**, so it cannot close
  today at any effort. Splitting that item out is the recommended next move
- not-work — **the epic-tail method itself has a blind spot**: deriving an epic's remaining
  work by grepping `#NNNN` out of its body cannot see *folded findings* (prose bullets with no
  issue number), so any epic carrying them looks closer to done than it is. That is how the plan
  claimed #2803 would close #2797. Verify an epic's own `## Done when` + folded list before
  closing it — the rule held for #2753 and #2802 and caught me on #2797
