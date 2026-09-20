# Progress photo protocol

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-09-20 (#3761)

This is the capture procedure for the weekly front/side/back progress-photo set
(#3743/#3758). It documents *how the protocol works* — the same class of public,
procedural material as `docs/coaching/routines/` — not any personal photo content,
which stays owner-only per `docs/DATA_GOVERNANCE.md`. The driver keeps a working
copy of this note beside the rest of the owner-private coaching corpus at
`s3://matthew-life-platform/config/coaching/PROGRESS_PHOTO_PROTOCOL.md`; this repo
copy is the source of truth.

## When

**The experiment's week-close day** — the day `day_n % 7 == 0` for the running
cycle's genesis (`EXPERIMENT_START_DATE` in `lambdas/common/constants.py`),
derived by `pacific_time.week_close_day()`. **Not a weekday literal**: genesis
moves on every experiment reset (seventeen cycles so far — see
`docs/PHASE_TAXONOMY.md`), so the protocol day is whatever weekday day 7 lands on
for the *current* cycle, and it silently changes at the next reset. For cycle 17
(genesis 2026-09-06, a Sunday) the protocol day is **Saturday**; if a set is
missed, **Sunday morning** is the fallback, still counted against the same
protocol day (see the Telegram reply's day-offset, below).

Do not hardcode a weekday anywhere that reads this file. If the coaching system
ever needs "is today the protocol day", it calls `week_close_day()` — the same
derivation `recap_card_lambda.py` uses to decide when the weekly recap card
renders — so the photo protocol and the weekly card can never disagree about
where a week ends.

## Time window

First thing in the morning: after the bathroom, before food or water. This
matches the weigh-in window (`docs/coaching/TRAINING_CALIBRATION.md`'s fasted
condition) so the photo and that morning's weight are comparable states, not
just comparable dates.

## Lighting

Consistent, diffuse, front-facing light — a window with indirect daylight, or an
overhead bathroom light used every time. Avoid a single hard side light (it
exaggerates or hides definition depending on angle) and avoid changing the light
source week to week; the comparison this protocol exists for is ruined by a
lighting change more easily than by a real body change.

## Distance and framing

Same spot, same camera distance, every week — full body head-to-feet, camera at
roughly chest height on a fixed stand or propped against something stable (not
handheld — handheld introduces angle drift the comparison can't correct for).
Mark the floor position with tape if the same spot isn't otherwise identifiable.

## The three poses

In order, one photo each: **front, side, back** (`lambdas/coach/progress_capture.py`'s
`POSES`). Side is a single consistent side (pick one and keep it — left or
right, whichever is more comfortable — and never alternate).

## Clothing

The same minimal, fitted clothing every time — whatever shows the outline
clearly without asking for anything more revealing than that. Whatever is
chosen for week 1 is what every subsequent week wears; a clothing change is a
confound of exactly the kind lighting and distance are also trying to eliminate.

## Capture path

Telegram, to the headcoach bot, one photo per pose with caption `/progress
front` (or `side` / `back`). An optional trailing date back-dates a set:
`/progress front 2026-09-06`. The bot replies with the pose, the date, the
experiment week, and how many days that capture is off the protocol day for its
week (`0` → "on the protocol day") — see `progress_capture.expected_capture_day()`.
Full behavior and refusal paths: `lambdas/coach/progress_capture.py`.

## Changelog

- **2026-09-20 (#3761):** first version. Aligned the protocol day to the derived
  week-close (`week_close_day()`) instead of a hardcoded weekday, and added the
  Telegram reply's days-off-protocol-day line.
