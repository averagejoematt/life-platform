# Form references: PROPOSED (#5779)

> **Status:** proposed, not adopted - nothing here is read by any code. **Owner:** Matthew. **Checked:** 2026-11-11.
> **Part of:** epic #5770 (exercise library, PR #5804). Companion to [FILM_A_SET_DESIGN.md](FILM_A_SET_DESIGN.md).

`config/movement_catalog.json` `form_reference_urls` is empty for every movement. The only reader is
`lambdas/training/note_requests.py::approved_reference_urls`, which returns an item only when it is
`{"url": "https://...", "approved_by_owner": "<YYYY-MM-DD>"}` and the URL is https. So the approval step is
mechanical: for each row he accepts, the driver writes that object with the date of his approval. **Nothing was
written to `movement_catalog.json` by this PR**, and none of these URLs carries an approval stamp yet.

## How the list was chosen

- **Which movements:** the 30 history movements with the most exposures in `config/exercise_library.json`
  (PR #5804, `history.exposures`), skipping non-lifting entries (Stretching 55, Cycling 42, Treadmill 20) and
  movements with no verifiable page (below). `catalog key` is resolved by exact title against
  `config/movement_catalog.json`, which is the key the `form_reference_urls` field lives under (the library id and
  the catalog key differ for some movements).
- **Source rule:** a stable, non-social-media article page that explains setup, execution and common faults for that
  movement. No YouTube, Instagram, TikTok, X or Reddit.
- **Verified:** each URL was fetched on 2026-11-11 with `curl -L` and a browser User-Agent; the row is kept only if
  the final status is 200, the URL did not redirect elsewhere, and the page title names the movement. (WebFetch was
  not available to this lane; `curl` is the equivalent check and the redirect/title test is stricter than a
  status code alone, because a bad slug on some sites returns 200 with an index page.)
- **Fit column:** `exact` = the page is that movement; `near` = same pattern, different implement or an overview
  page (read the note); `loose` = an adjacent movement or an article, included only so the owner can veto it.

## An honest caveat on the source

Every verifiable URL is from one publisher, **StrengthLog** (strengthlog.com), a training-app publisher whose
exercise pages are written to a house template. It is not an academic body or a standards organisation, and it is
commercial. I tried the sources the brief named as the preferred type and could not verify them from this
environment: ExRx.net, Starting Strength, NSCA, Muscle & Strength and Verywell Fit all answer `403` (a bot
challenge) to a scripted fetch, so they were **dropped, not assumed good**. ACE's exercise library resolves, but
its pages are keyed by a numeric id the index does not list in static HTML, so I could not map ids to these
movements reliably. If he prefers a second opinion on the big lifts, the owner can open ExRx or ACE in a browser
and name the pages; they would then be added with the same verify step.

## The 30

| # | Exposures | Movement (library title) | Catalog key | Fit | Proposed URL | Verified |
|--:|--:|---|---|---|---|---|
| 1 | 133 | Bench Press (Barbell) | `barbell_bench_press` | exact | <https://www.strengthlog.com/bench-press/> | 2026-11-11, 200 |
| 2 | 99 | Squat (Barbell) | `squat_barbell` | exact | <https://www.strengthlog.com/squat/> | 2026-11-11, 200 |
| 3 | 96 | Face Pull | `face_pull` | exact | <https://www.strengthlog.com/face-pull/> | 2026-11-11, 200 |
| 4 | 87 | Deadlift (Barbell) | `deadlift_barbell` | exact | <https://www.strengthlog.com/deadlift/> | 2026-11-11, 200 |
| 5 | 80 | Hammer Curl (Dumbbell) | `hammer_curl_dumbbell` | exact | <https://www.strengthlog.com/hammer-curl/> | 2026-11-11, 200 |
| 6 | 75 | Shrug (Barbell) | `shrug_barbell` | exact | <https://www.strengthlog.com/barbell-shrug/> | 2026-11-11, 200 |
| 7 | 74 | Incline Bench Press (Dumbbell) | `incline_db_press` | exact | <https://www.strengthlog.com/dumbbell-incline-press/> | 2026-11-11, 200 |
| 8 | 72 | Lat Pulldown (Cable) | `lat_pulldown` | near | <https://www.strengthlog.com/lat-pulldown-types/> | 2026-11-11, 200 |
| 9 | 71 | Lateral Raise (Dumbbell) | `db_lateral_raise` | exact | <https://www.strengthlog.com/dumbbell-lateral-raise/> | 2026-11-11, 200 |
| 10 | 64 | Bicep Curl (Dumbbell) | `db_curl` | exact | <https://www.strengthlog.com/dumbbell-curl/> | 2026-11-11, 200 |
| 11 | 60 | Triceps Pushdown | `cable_tricep_pushdown` | near | <https://www.strengthlog.com/tricep-pushdown-with-bar/> | 2026-11-11, 200 |
| 12 | 60 | Leg Extension (Machine) | `leg_extension_machine` | exact | <https://www.strengthlog.com/leg-extension/> | 2026-11-11, 200 |
| 13 | 59 | Incline Bench Press (Barbell) | `incline_bench_press_barbell` | exact | <https://www.strengthlog.com/incline-bench-press/> | 2026-11-11, 200 |
| 14 | 53 | Bulgarian Split Squat (Dumbbell) | `bulgarian_split_squat_dumbbell` | near | <https://www.strengthlog.com/bulgarian-split-squat/> | 2026-11-11, 200 |
| 15 | 50 | Shoulder Press (Dumbbell) | `db_shoulder_press` | exact | <https://www.strengthlog.com/dumbbell-shoulder-press/> | 2026-11-11, 200 |
| 16 | 43 | Side Bend (Dumbbell) | `side_bend_dumbbell` | exact | <https://www.strengthlog.com/dumbbell-side-bend/> | 2026-11-11, 200 |
| 17 | 41 | Dumbbell Row | `one_arm_db_row` | exact | <https://www.strengthlog.com/dumbbell-row/> | 2026-11-11, 200 |
| 18 | 39 | Seated Leg Curl (Machine) | `leg_curl` | exact | <https://www.strengthlog.com/seated-leg-curl/> | 2026-11-11, 200 |
| 19 | 38 | Standing Calf Raise (Machine) | `standing_calf_raise_machine` | loose | <https://www.strengthlog.com/standing-calf-raise/> | 2026-11-11, 200 |
| 20 | 31 | Lat Pulldown - Close Grip (Cable) | `lat_pulldown_close_grip_cable` | exact | <https://www.strengthlog.com/close-grip-lat-pulldown/> | 2026-11-11, 200 |
| 21 | 31 | Kettlebell Swing | `kettlebell_swing` | exact | <https://www.strengthlog.com/kettlebell-swing/> | 2026-11-11, 200 |
| 22 | 29 | Bicep Curl (Barbell) | `bicep_curl_barbell` | exact | <https://www.strengthlog.com/barbell-curl/> | 2026-11-11, 200 |
| 23 | 26 | T Bar Row | `t_bar_row` | exact | <https://www.strengthlog.com/t-bar-row/> | 2026-11-11, 200 |
| 24 | 25 | Shrug (Dumbbell) | `shrug_dumbbell` | exact | <https://www.strengthlog.com/dumbbell-shrug/> | 2026-11-11, 200 |
| 25 | 24 | Pullover (Dumbbell) | `pullover_dumbbell` | exact | <https://www.strengthlog.com/dumbbell-pullover/> | 2026-11-11, 200 |
| 26 | 24 | Front Raise (Dumbbell) | `front_raise_dumbbell` | exact | <https://www.strengthlog.com/dumbbell-front-raise/> | 2026-11-11, 200 |
| 27 | 20 | Deadlift (Trap bar) | `deadlift_trap_bar` | loose | <https://www.strengthlog.com/trap-bar-deadlift-benefits/> | 2026-11-11, 200 |
| 28 | 20 | Bent Over Row (Barbell) | `bent_over_row_barbell` | near | <https://www.strengthlog.com/barbell-row/> | 2026-11-11, 200 |
| 29 | 19 | Overhead Press (Barbell) | `overhead_press_barbell` | exact | <https://www.strengthlog.com/overhead-press/> | 2026-11-11, 200 |
| 30 | 19 | Incline Chest Fly (Dumbbell) | `incline_chest_fly_dumbbell` | near | <https://www.strengthlog.com/dumbbell-chest-fly/> | 2026-11-11, 200 |

Notes on the non-exact rows:

- **Lat Pulldown (Cable)** - the site's `/lat-pulldown/` redirects to a "Lat Pulldown Types" overview; it covers the
  pattern but is not a step-by-step page. Near.
- **Triceps Pushdown** - the page is the straight-bar version; the catalog title does not say bar or rope. Near.
- **Bulgarian Split Squat (Dumbbell)**, **Bent Over Row (Barbell)** (page is "Barbell Rows"), **Incline Chest Fly
  (Dumbbell)** (page is the flat dumbbell chest fly; the bench angle differs) - same pattern, different variant. Near.
- **Standing Calf Raise (Machine)** - the page is the free/standing version, not the machine. Loose.
- **Deadlift (Trap bar)** - the only trap-bar page is an article on benefits versus the barbell deadlift, not a
  how-to. Loose; the owner may prefer to leave this one empty.

## Movements in the top 30 with NO reference proposed

Dropped because no page could be verified as that movement: Cable Fly Crossovers (63; the site's crossover slug
redirects to a biceps-curl variant, which is a different movement), Seated Cable Row - Bar Grip (41), Bench Press
(Dumbbell) (36), EZ Bar Biceps Curl (31), Decline Bench Press (Machine) (31), Glute Kickback (Machine) (29; the
site only has the cable version), Military Press (22), Scarecrow (24) and Shoulder Pushdown (24).

## What the owner decides

1. Accept, strike, or substitute each row. Only accepted rows get an `approved_by_owner` date.
2. Whether one publisher is acceptable, or he wants a second source named for the big five (bench, squat,
   deadlift, overhead press, row).
3. Whether `loose` rows go in at all.

Approved entries are written as, for example:

```json
"form_reference_urls": [{"url": "https://www.strengthlog.com/squat/", "approved_by_owner": "YYYY-MM-DD"}]
```

Links rot. Re-run the fetch check when the list is approved and again at each library review; a link that stops
resolving is removed rather than left to send him to a dead page.
