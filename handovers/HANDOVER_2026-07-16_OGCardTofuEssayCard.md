# HANDOVER — OG share cards un-tofu'd + the career-artifact essay card (#741) — 2026-07-16

> Instruction thread: session opened "read memory and handover, what should we work on."
> Recommended #741 (publish the career artifact + measure travel) — the one `Now` story
> with shippable mechanics. On inspection its mechanics were ALREADY done (essay live,
> `/method/build/` cross-link live, traffic-digest "Travel watch" #1072 deployed), so the
> one real gap was the essay's share card. Building it surfaced a months-old production
> bug — every OG card renders tofu — which became the actual work. Matthew then said
> "can you do the deploy," which unblocked the lambda deploy (his hard boundary, explicit
> in-session words unblock).

## What shipped — PR #1193 (OPEN, 1 commit; branch `feat/essay-og-card`)

`fix(cards): repair tofu OG share cards + add the essay card (#741)`. Offline card/OG
suite **20 passed** (with `scripts` on path, as CI runs it); black + flake8 clean.

**The bug.** Every OG/social share card the platform generates has rendered as `.notdef`
"tofu" boxes since the HP-13 origin commit (`e1adce8d`) — including the one live on the
site. Root cause: the bundled `bebas-neue-400.ttf` / `space-mono-*.ttf` are subsets with
**no basic-Latin glyphs** — `A`–`Z` are absent from the cmap entirely (first cmap entries
jump `space` → `Amacron`), so `card_engine` drew boxes for all card text. Invisible for
months because visual QA inspects live *pages*, never the generated PNGs, and cards only
surface on external shares.

**The fix (one PR):**
- Repointed the shared `card_engine` (ADR-114) **and** `reading/cover_placeholder.py` at
  the v5 brand type triad the live site actually serves — **Fraunces** (display) + **IBM
  Plex Mono** 400/500 (mono) — converted `woff2→ttf` from `site/assets/fonts/v4/`. Deleted
  the 3 broken TTFs, added 3 good ones. One change fixes **all** cards (12 daily + character
  + chronicle + coach + moment) AND rebrands them from the retired Bebas/Space Mono look to
  v5.
- Added `build_essay_org_chart` → `og-org-chart.png` (editorial card: amber kicker, wrapped
  Fraunces title, mono lede) and repointed the essay's `og:image` / `twitter:image` /
  JSON-LD `image` at it.
- **Regression guard** (`tests/test_card_engine.py::test_brand_card_fonts_render_basic_latin`):
  PIL-only (no fontTools dep) — a real letter's raster must differ from an unmapped
  private-use codepoint (`U+E000`); identical ⇒ both fell back to the same `.notdef` box.
  Verified it catches the old broken font and passes the new ones.

## Deployed + verified LIVE
- `deploy/deploy_lambda.sh og-image-generator lambdas/web/og_image_lambda.py` (full-tree
  bundle staged `lambdas/fonts/` automatically, #781) → invoked → `Generated 13/13 OG images`.
- Live CDN confirmed: `og-home.png` went **10 KB (tofu) → 33 KB (real glyphs)**; every card
  renders real text; **`og-org-chart.png` is live and on-brand** (visually reviewed).
- Deployed from the branch (code-only, green, tested) — a small deviation from deploy-from-main,
  accepted to fix prod now without the merge-triggered rollback risk below. Transient
  branch/main drift closes on merge (nothing auto-deploys this lambda from main pre-merge).

## Merge intentionally HELD (the load-bearing gotcha)
Merging #1193 now would trigger `site-deploy.yml`, whose `visual-qa` job uploads
screenshots with `if: always()` + **no `continue-on-error`** (lines 187–193), and the
auto-rollback fires on `needs.visual-qa.result == 'failure'` (line 208). GitHub's
**artifact-storage quota is currently exhausted** (account-wide, recalculates ~6–12h) — the
same condition that red-X'd this PR's render gate even though its logic printed `✅ GATE
PASSED`. So a merge → QA passes its real checks but fails the artifact UPLOAD → job failure
→ **spurious auto-rollback of a healthy site + false-alarm email**. Held until the quota
clears. Safe to wait: the live essay still points at `og-home.png` (now fixed), so nothing
looks broken; the merge only swaps in the bespoke card, which already exists in S3.

## Gotchas hit
- **Artifact-storage quota red-X's healthy jobs.** A passed gate whose post-run
  `upload-artifact` step fails on quota still marks the whole JOB red. It will red *other*
  CI jobs too (any `upload-artifact` step) until it clears — those reds are noise, not code.
- **The repo's "full" legacy fonts were ALSO broken.** `site/legacy/assets/fonts/*.woff2`
  are subset to near-nothing too. Only the `site/assets/fonts/v4/*.woff2` (hashed names) are
  real full fonts — and the v5 site had already moved OFF Bebas/Space Mono to Fraunces / IBM
  Plex Mono / Instrument Sans (`tokens.css`), so the card lambda was doubly stale.
- **Two OG lambdas exist; only one is live.** `og-image-generator` (operational stack,
  handler `web.og_image_lambda.lambda_handler`) is the live card producer. `life-platform-og-image`
  (web_stack) does not exist live — don't deploy to it.
- **zsh doesn't word-split unquoted `$VARS`** — passing a `$FILES` list to black/flake8 as
  one arg failed; list files explicitly.

**Build beat:** none — PR #1193 is open; the lambda is deployed+live but the code is NOT
merged to `main`, so it fails the merged-AND-deployed eligibility bar (#736).
**Docs:** none on `main` this wrap — the card-font fix lives in open PR #1193; no canonical
current doc names the retired fonts (only `docs/archive/` + `docs/briefs/`, exempt), so no
tombstone. Any doc impact ships with the PR.

## Next picks / residual queue
- **Merge PR #1193** after the artifact quota resets (~6–12h) — swaps the essay's `og:image`
  to the bespoke card; on merge, site-deploy runs clean. Then a build beat becomes eligible.
- After that, **#741's only remaining scope is the external publish** (blog + CFP/HN) —
  Matthew's action, permission-gated.
- **Follow-up (filed as a clause, not an issue yet):** `build_builders` in `og_image_lambda.py`
  hardcodes stale figures — `116 MCP TOOLS / 59 LAMBDAS / $13` vs real ~64 / ~94 / $85. The
  #1189 `check_doc_facts` gate scans docs, not in-lambda card literals, so it's unpoliced.
- **Also open, awaiting Matthew's merge:** PR #1190 (no-FDA TCC posture docs, `docs/option-c-no-fda`).
- Standing from prior sessions: #1187 podcast music, #1114 portraits v2, #1148 coach traits;
  `/fullreview` 17-lens relaunch after weekly reset (~07-18).

Prior session: `handovers/HANDOVER_2026-07-13_DocAccuracyDriftGuardrails.md`.
