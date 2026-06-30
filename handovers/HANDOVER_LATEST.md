# HANDOVER — Backend serial phase 4: historical-window APIs — 2026-06-29

The **last** backend serial phase. **The backend serial arc is now COMPLETE — all four phases live.**
Let a reader arriving months in see the platform **AS OF a past date**, extending the `?date=`
time-travel pattern `handle_character` already used to the data/waveform surfaces.

**1 feature PR: #278 (MERGED + DEPLOYED).** Matthew authorized the deploys. **main == live, 0 open PRs.**

---

## 1. What shipped (all live, verified)

Two endpoints get an `?date=YYYY-MM-DD` parameter — both already keyed by `DATE#`, so it's **zero new
compute**, just anchoring the window to a past date:

- **`/api/observatory_week?domain=X&date=Y`** (`site_api_data.handle_observatory_week`) — the flagship
  7-day waveform, all 6 domains in one edit. The top block anchors the window to the date;
  `include_pilot=bool(date)` is threaded into all 8 `_query_source` calls. ⚠️ A local-var-name
  collision (`start_date`/`end_date` are also used in `handle_changes_since`) meant the threading
  initially leaked two `include_pilot=ip` into that function where `ip` is out of scope — **caught and
  reverted** (verified each `include_pilot=ip` is inside `handle_observatory_week`).
- **`/api/vitals?date=Y`** (`site_api_vitals.handle_vitals` + a new `/api/vitals?date=` dispatch branch
  mirroring character's) — the cockpit. New shared `site_api_common._latest_item_asof(source, date)`
  gives the latest weigh-in **on-or-before** the anchor (the time-travel counterpart of `_latest_item`).

**As-of semantics mirror `handle_character` exactly** (consistency): most-recent-on-or-before · future
dates **clamp to today** · pre-genesis **honest-null 200, never 503** · `include_pilot=bool(date)` (so
prior-cycle history is visible only when time-travelling; the live view stays phase-clean) ·
`time_travel` flag · **immutable-past day cache (86400s)**. **Read-only — serves stored records
verbatim, gaps stay gaps, never interpolated.**

**Front-end (`cockpit.js`):** the date-scrubber time-travel mode **used to HIDE the vitals band** ("no
raw vitals on the dated sheet → hide it", because no historical vitals endpoint existed). Now it fetches
`/api/vitals?date=` and shows the **REAL readings from that morning**, plus a **chronicle cross-link**
("Read Week N →") via a `postFor`-style `nearestPost()` lookup (reuses `/journal/posts.json`).
`renderReadiness` self-hides if the date has no readings.

**⚠️ Plan correction worth remembering:** the planning agent assumed `evidence.js`'s silhouette scrubber
was the time scrubber to wire. It is **WEIGHT-keyed, not date-keyed** (drag to morph the body at weight
W) — so it's correctly NOT wired. The real time-scrubber is the cockpit's `/now/?date=`.

New `tests/test_historical_window.py` (10). Updated ONE rigid `_query_source` mock in
`test_vitals_frame.py` to accept the new `include_pilot` kwarg (the rest use `*a, **k`).

## 2. Deploy (site-api only — NO layer dance, NO CDK)

- **site-api** via `deploy/deploy_site_api.sh /api/vitals` (full `web/` package + handler-import verify →
  200). The script does a direct `update-function-code`, so `cdk diff` doesn't apply; it ships the
  current `web/` which equaled `origin/main`.
- **Front-end** via `sync_site_to_s3.sh` (clobber guard passed; CloudFront invalidated).
- No CDK / layer / constants change — read-only DDB the lambda already has.

**VERIFIED LIVE (6 curls):** the historical-vs-current divergence proves real past records are served —
vitals weight **305 lbs on 2026-06-20 vs 301 now**, recovery **60 vs 84**; observatory_week historical
period `[2026-06-14 → 2026-06-20]` vs live `[2026-06-22 → 2026-06-29]`; pre-genesis (2026-04-01) →
**HTTP 200**; future date (2099) → **clamps to today**. **main == live, nothing left behind.**

## 3. 🎉 The serial vision is COMPLETE

All four backend serial phases built, shipped, deployed, verified — each composed on the one before:
- ✅ Phase 1 — coach stances (evolving evidence-derived read; PRs #270/#271)
- ✅ Phase 2 — coaches react to active site protocols (PRs #273/#274)
- ✅ Phase 3 — Elena "previously on" recaps (PR #276)
- ✅ Phase 4 — historical-window APIs (PR #278)

The platform now reads like the evolving serial: coaches whose read evolves and reacts, a narrator who
catches you up, and the ability to walk backwards and see any past day as it actually was.

## 4. ⚠️ OUTSTANDING — next sessions

- **SS tail (B/C, lower priority):** SS-08 monthly "what changed" · SS-09 podcast format rotation ·
  SS-11 editorial-image guard. These are self-sustainability maintenance, not serial features.
- **Watch:** the phase-3 spelled-number recap gap (the digit-based raw-vitals guard misses
  "recovery of *twelve*"); labs_coach `grounding_flag` across weekly summarizer runs.
- **Available but unwired:** `/api/observatory_week?date=` is live and usable by any consumer; only the
  cockpit `/now/?date=` view consumes the historical vitals so far. A future UI (e.g. a week scrubber on
  a domain page) could consume the dated observatory endpoint.
