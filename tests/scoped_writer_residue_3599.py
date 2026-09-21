"""tests/scoped_writer_residue_3599.py — the dated waiver ledger for #3599 box 2.

WHAT A LINE HERE MEANS
  "This writer lands a row on an EXPERIMENT_SCOPED `USER#matthew#SOURCE#*` partition
  without going through `experiment_stamp_for` / `experiment_stamp` / `tag_record`, we
  looked at it on the seed date, and here is why it is not being converted TODAY."

  It is not a pardon. Every line carries:
    * `provenance` — `none` (no phase attribute at all) or `hand-stamped` (a literal
      `phase` the writer types itself, the #3598 shape). If the observed class stops
      matching, the gate reds: a `none` waiver quietly becoming a hand-stamp is a
      different decision and gets re-read.
    * `expires`    — after this date the line stops working and the gate reds.
    * a CONDITION that is re-derived, never restated: all ten partitions below sit under
      `pk_census.TAGGER_REACHABLE_PREFIX`, so `deploy/restart_phase_tag.py` stamps them at
      the NEXT reset and an in-cycle unstamped row is the correct state, not a defect.
      `test_the_waiver_condition_is_re_derived_from_the_tagger_constant` reds if the
      tagger's reach is ever narrowed — at which point every line here is false.
  And the gate consumes the SHRINK list: a line whose writer starts stamping, or
  disappears, is named by the guard until it is deleted (`STALE`). That is the clause the
  2026-09-05 RCA says four earlier ledgers in this repo lacked (a11y-3 / OBS-7 / the alarm
  citations / pair_seam_residue at 285 rows) — they went stale in the GOOD direction and
  disarmed their own gates.

WHAT IS STILL EXPOSED WHILE A LINE IS LIVE
  One shape, named: a row written in the COUNTDOWN WINDOW — after the wipe, before
  genesis — is dated before `EXPERIMENT_START_DATE` and the tagger has already run, so it
  is served as current forever. That is #3513's defect exactly (measured live at 109 rows
  on `SOURCE#insights` before it was fixed). The eight `none` writers below are each one
  reset-day invocation away from it.

SEEDED FROM A MEASUREMENT, NOT A GUESS
  2026-09-20 PT (the live scan behind the census it grades against is stamped 2026-09-21Z):
  `scan_repo()` found 17 scoped-source writers — 7 already stamped (including
  #3513's two converted insight writers), 8 `none`, 2 `hand-stamped`. The ten below are the
  installed base at the seal. There is no path to green for an eleventh except stamping it
  or adding a line here in the diff, dated, with a reason.
"""

from __future__ import annotations

SEED_DATE = "2026-09-20"  # Pacific, the frame date.today() reads in this gate (the scan itself is stamped 2026-09-21Z)

# One quarter. Long enough that a conversion is scheduled work rather than an emergency,
# short enough that nobody inherits this ledger without re-deciding it.
_EXPIRY = "2026-12-31"

SCOPED_WRITER_RESIDUE: dict = {
    "deploy/restart_ledger_reset.py::main": {
        "sources": ("ledger",),
        "provenance": "none",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "Written BY the reset, at the instant the phase flips. `LIFETIME#aggregate` and "
            "`CYCLE_TOTALS#NNN` are the durable roll-up the wipe's `pregenesis` mode deliberately "
            "skips (both sks are undated), so a phase stamp here would assign one cycle's label to "
            "a row that spans all of them. Converting this one is a taxonomy question (should the "
            "LIFETIME sk class be CROSS_PHASE?), not a writer fix."
        ),
    },
    "lambdas/emails/anomaly_detector_lambda.py::write_anomaly_record": {
        "sources": ("anomalies",),
        "provenance": "none",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "A 90-day TTL'd investigative record (R17-17), keyed `DATE#<date>` on a tagger-reachable "
            "partition: the next reset stamps it and the TTL removes it inside a cycle either way. "
            "Lowest-value conversion of the eight — no reader surface serves it."
        ),
    },
    "lambdas/emails/chronicle_recap.py::_write_recap": {
        "sources": ("chronicle",),
        "provenance": "none",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "The recap pointer (`RECAP#latest`) plus its dated history row. #3485 stamped the "
            "derived recap on the APPROVE path and this second writer to the same partition was not "
            "converted — the highest-value line in this ledger, because the public /api/recap reads "
            "the pointer and an unstamped `RECAP#latest` is the surface that survived a reset in the "
            "2026-09-05 RCA."
        ),
    },
    "lambdas/emails/chronicle_store.py::store_installment": {
        "sources": ("chronicle",),
        "provenance": "none",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "The weekly installment row (`DATE#<date>`), written in draft state and later published "
            "by the approve Lambda. Conditional-put protected (#2254) and status-keyed, which is the "
            "same selector the #3485 writer-vs-reset defect ran through — convert it together with "
            "the approve-path recap so the pair keeps one provenance story."
        ),
    },
    "lambdas/emails/chronicle_store.py::write_raw_cache": {
        "sources": ("chronicle",),
        "provenance": "none",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "A TTL'd crash-recovery cache of the gated generation (#2669) — read only by a retry of "
            "the same invocation, never by a reader surface, and expired by TTL well inside a cycle."
        ),
    },
    "lambdas/emails/nutrition_review_lambda.py::store_weekly_summary": {
        "sources": ("nutrition_review",),
        "provenance": "none",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "The weekly nutrition summary row (`DATE#<week_end>`), written fail-soft inside a "
            "try/except. Dated sk on a tagger-reachable partition; the countdown-window write is the "
            "only exposure, and this Lambda runs weekly rather than daily, so that window is narrow."
        ),
    },
    "lambdas/emails/podcast_script_v2.py::write_show_memory": {
        "sources": ("panelcast",),
        "provenance": "none",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "The capped show-memory ledger (callbacks + guest history, one undated singleton sk). "
            "Undated, so the wipe's `all` mode for panelcast reaches it and the pregenesis-date "
            "question never arises; the missing stamp costs provenance, not correctness of the wipe."
        ),
    },
    "lambdas/intelligence/challenge_generator_lambda.py::store_challenge": {
        "sources": ("challenges",),
        "provenance": "none",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "The generated challenge row. Its own collision handling already reasons about "
            "tombstoned prior-cycle rows, so the writer is reset-aware without carrying the stamp — "
            "convert it by routing the put through `experiment_stamp_for`, which is a small change "
            "that wants its own test of the collision path."
        ),
    },
    "lambdas/emails/chronicle_approve_lambda.py::_commit_recap": {
        "sources": ("chronicle",),
        "provenance": "hand-stamped",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "#3485 made this writer INHERIT the installment's phase/cycle rather than re-read SSM — "
            "a recap's cycle is its installment's cycle, and this Lambda's role holds no "
            "experiment-cycle grant. That is a deliberate design, recorded here rather than made "
            "invisible by a green: it is a hand-written phase key, so it cannot benefit from a later "
            "fix to the shared helper."
        ),
    },
    "lambdas/emails/coach_panel_podcast_lambda.py::_state_write": {
        "sources": ("panelcast",),
        "provenance": "hand-stamped",
        "seeded": SEED_DATE,
        "expires": _EXPIRY,
        "reason": (
            "Writes a hardcoded `phase='experiment'` on the panel state singleton — the exact shape "
            "#3598 retired the constant default for: written in the countdown window it claims the "
            "experiment it precedes. Not a defect today (the sk is an undated singleton the wipe "
            "reaches in `all` mode), and the first of the two hand-stamps that should be converted."
        ),
    },
}
