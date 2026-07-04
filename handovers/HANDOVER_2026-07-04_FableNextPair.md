# HANDOVER — the fable Next pair: TSB gets a real scale (#490) + journal extraction v2 (#505) — 2026-07-04 (session 9)

Both workable `model:fable` stories on the **Next** milestone are MERGED + DEPLOYED +
LIVE-VERIFIED: PRs **#562** (#490, layer **v103**) and **#563** (#505, layer **v104**),
plus three repair PRs the session surfaced (**lint fix on main**, **#564** QA 429
re-probe, **#565** reading-shelf clock time-bomb). Issues #490 and #505 auto-closed.
**#530 was deliberately not started** — the rigor chain (ADR-105 → #529 stats_core,
model:opus) wants its own session per the session-8 handover. Remaining open fable
stories are all **Later**: #550 / #547 / #541 / #540 / #539 / #506 / #498.

---

## What shipped

### #490 — TSS-like load scale, walks count, TSB provenance (PR #562, layer v103)
- **`lambdas/training_load.py`** (NEW, shared layer): one TSS-like scale
  (100 pts ≈ 1 h at threshold). Per-activity: kJ/7.2 when power data exists →
  walk/hike moving-time fallback (25/h, the C-6 fix) → hrTSS-lite (IF² × 100,
  IF clamped 0.4–1.1) → 50/h default; Hevy lifts 50/h (was a saturating
  25 kJ/min ≈ 1,500 kJ/h). Strava + Hevy **additive** per day; Strava
  WeightTraining echoes skipped when Hevy has the session; multi-device
  duplicates dedup inside the module (harmless at 0 kJ, double-count under a
  duration proxy).
- **All five independent Banister implementations converge on it**:
  daily-metrics-compute (canonical wrappers kept), daily-brief fallback,
  digest_utils (weekly + monthly), weekly-digest local copy, and
  dashboard-refresh's private HR heuristic (which could previously overwrite
  the morning compute on a different scale mid-day).
- **Band consumers now correct by construction** (readiness `60+2t`, character
  `_in_range_score(-10,25)`, MCP `70+2.5t`); fixed the unreachable
  "very fatigued" branch (−25 checked after −10) in tools_health/tools_training.
- **M-3 provenance surfaces everywhere TSB renders**: basis dict gains
  `unit: tss_proxy` / `proxy_share` / confidence (`power|duration_proxy|mixed`);
  MCP readiness `training_form.raw.load_basis` (+note); cockpit snapshot
  readiness labels **"training balance (duration-proxy)"** + `tsb_basis` field;
  daily-brief + monday-compass coach prompts and the brief HTML append
  "(duration-proxy basis)" via `training_load.basis_note`.
- **Live re-probe**: tsb **−87 → −6** (ctl 24.8 / atl 30.8), `strava_duration_days`
  **0 → 11** over the window, readiness TSB component **0 (pinned) → 48**,
  cockpit label live on `/api/snapshot`.

### #505 — journal extraction v2 (PR #563, layer v104)
- **One Haiku pass** (J-6): the defense pass folded into the main call
  (`defense_patterns`/`primary_defense` ride `FIELD_MAPPING`); dead fields
  dropped (`enriched_emotional_depth` — zero readers; `enriched_defense_context`
  — challenge mining re-pointed). `max_tokens` 1000→1400 (fence-truncation gotcha).
- **The extraction trio**: `enriched_entities` / `enriched_behaviors` /
  `enriched_causal_hints` — every hint `{cause, effect, quote}` with the
  **verbatim sentence**, and a deterministic grounding gate
  (`_ground_causal_hints`: normalized substring check) drops ungrounded hints
  pre-write (ADR-104 pattern). `enriched_schema_version=2` stamps every write;
  v1 entries self-heal via the daily window + Sunday sweep.
- **Dead scaffolding deleted** (J-2): `call_anthropic_raw` accepts a **plain
  Messages dict** (legacy urllib Request kept for the ~20 other callers); the
  enricher's `get_anthropic_key` sentinel + `ANTHROPIC_API`, and the analyzer's
  **live** ai-keys Secrets fetch, are gone. `needs_ai_keys` IAM flag kept — it's
  the whole AI-calling bundle (Bedrock + PutMetricData), not just the secret.
- **Floors aligned** (J-5): both lambdas `MIN_TEXT_WORDS = 20` (enricher was 20
  *chars* — baseline discrepancy #7 explained).
- **Consumers wired so the trio isn't born dead** (the J-6 lesson):
  `get_journal_insights` → `top_entities`/`top_behaviors`/`causal_hints`;
  `search_journal` indexes the new lists; challenge mining reads
  behaviors + causal_hints.
- **Corpus re-enriched live**: 62 found / 54+5 enriched / 0 errors after one
  retry (`{"date": "2026-02-16", "force": true}`); grounding gate fired **11×**
  on the sweep; 34 records carry entities, 36 carry grounded hints; analyzer
  invoked post-change: 200, 0 errors, no Secrets fetch.

### The repair tail (all merged to main)
- **Import-sort lint** (direct push `3dbe2587`): #562 left daily_brief's import
  block unsorted → ruff I001 redded main. Email stack redeployed so main == live.
- **#564 — QA 429 re-probe**: the gating visual-QA sweep flaked on 429s (its
  parallel page loads exceed site-api's reserved concurrency of 20; a different
  endpoint lost the race each run). A 429 now gets one sequential re-probe —
  recovered throttles downgrade to warnings, persistent 429s still fail.
- **#565 — reading-shelf clock time-bomb**: the privacy test asserted
  `"0.9" not in blob` over a body whose `_meta.generated_at` fractional seconds
  contain "0.9" ~1 run in 10. Assertion now runs on the payload minus `_meta`.
- **I22**: live site SHA was pre-merge — `sync_site_to_s3.sh` run from main.
- **Final state**: main CI **green end-to-end** (run 28717339526); whole fleet
  on layer **v104** (Web + Operational stacks deployed too); LV6/I2 green.

## Gotchas (this session's tuition)

1. **The MCP stack is `LifePlatformMcp`, not `LifePlatformMCP`** — `cdk deploy`
   with a non-matching name silently deploys only the names that match (exit 0,
   two ✅ lines). The tell: the "deployed" lambda still shows the old layer ARN.
2. **Run FULL ruff before merge** (again) — I linted only the files I created;
   the import I added to daily_brief broke isort ordering and redded main.
   `ruff check lambdas/ mcp/ tests/` is cheap; run it on the whole tree.
3. **`aws lambda invoke` with a JSON payload needs `--cli-binary-format
   raw-in-base64-out`** (CLI v2). Without it: `Invalid base64` — and if stderr
   is swallowed, it looks like a lambda failure.
4. **LV6 + I2 red between the constants bump and the layer publish** is the
   expected state, not a failure — they flip green the moment Core deploys.
5. **The pre-commit test-count bump chases you a commit behind** (known; bit
   twice) — `git status` after every commit, amend `site_api_common.py` in.
6. **QA sweeps of the live site inherit the site's own rate limiting** — a
   gating browser sweep that bursts 32 pages of API calls WILL trip a
   reserved-concurrency 429 eventually; re-probe before failing.

## Watch
- **Wednesday 07-09 chronicle**: first with #505's grounded hints in the corpus
  (plus session 8's two Elena promises coming due).
- **Sunday 07-06 summarizer**: first interaction-folding run (session 8) — now
  also first to read v2-enriched entries.
- **Weekly-correlation `tsb_vs_recovery`**: straddles the kJ→TSS discontinuity
  for ~2 weeks of windows; a weird r this week is the scale change, not a bug.
- `slo-source-freshness` 7-day OK window (from 07-04, session 7).

## Next
- **The rigor chain, dedicated session**: ADR-105 (#554 write-first) → #529
  stats_core (opus) → **#530 hypothesis engine v2 (fable, Next)**.
- Fable Later flagships when Next thins: #541 forecast engine, #540 inter-coach
  dialogue, #506 journal Phase 2 (builds directly on the causal-hints corpus),
  #539 N-of-1 engine, #547 podcast v2, #550 scenario explorer, #498 registry
  enumerations.
