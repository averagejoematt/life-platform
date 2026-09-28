"""redline_changelog.py — the v1 → v2 → v3 history of `training.owner_redlines` (#3753).

Moved out of `owner_redlines` unchanged (#4387, the #1665 size ratchet — the #4161
`redline_rate` precedent): history, not policy. `owner_redlines` re-exports both names, and
`owner_redlines.summary()` still carries them.
"""

from __future__ import annotations

CHANGELOG_V1_TO_V2: list[str] = [
    "rate: the 0.5–1.0 %BW band is kept as the envelope; a scheduled absolute target replaces the unresolved "
    "'top of band vs widen' question — 3.0 lb/wk (cap 3.5) above 295 lb, then 2.5 / 2.0 / 1.5 stepping at 260 / 230 "
    "/ 200 lb, and a mandatory 12-week maintenance block at 200 (all five personas; Forbes 2000; Alpert 2005)",
    "energy: a NEW floor — 1,700 kcal any day, 1,800 on a lifting day, prescribed 2,000–2,300; the measured 1,533 "
    "kcal/day was the biggest problem in the record, too LOW (four of five personas; Longland 2016; Lichtman 1992)",
    "protein: the 180 g floor stays; a 200 g target, ≥6 of 7 days, 4 feedings of ~50 g is added (Helms 2014; Areta 2013)",
    "lifting: 2–3 sessions/wk → 5–6 on a 5-week load wave with 10–16 sets/muscle (strength + transformation coach; "
    "Schoenfeld 2016/2017; Murphy & Koehler 2022) — the 2–3 rule guarded a burnout failure mode he has never had",
    "walking: the 8.5 h floor is now PERMANENT (survives the cut), target 12–15 h at ≤105 bpm; walking collapse is the " "relapse prodrome",
    "medical cover: a NEW redline — baseline labs/ECG/gallbladder ultrasound/DXA/RMR, DXA every 8–12 weeks (physician)",
    "tripwires: anchor-lift drop 10% → 7.5% and the action now changes the DIET (+200 kcal) as well as holding load; "
    "readiness floor 34 → 40 (34 is Whoop's boundary, too late to be early); protein-missed action moves to the "
    "kitchen; nine NEW tripwires added that the engine does not yet evaluate (each says so)",
]
"""History. v2 was never approved; it is kept so the v3 diff below reads against something."""

CHANGELOG_V2_TO_V3: list[str] = [
    "rate: 3.0 → 3.5 lb/wk above 275 lb (cap 4.0 above 295) — his own measured 2024–25 record (3.4 lb/wk over 32 weeks, "
    "W38 → W18; the 2026-09-20 packet's '2.7' divided by the wrong window) and clean trough labs; the taper now follows "
    "his fat fraction and the DXA gates (3.0 to 260 with 3.5 DXA-gated; 2.75 to 240), not a calendar",
    "floor: 1,700 → 1,800 on the 7-day mean (1,900 on a lifting day), no single day < 1,600 — 200 g protein + 65 g fat "
    "do not fit under 1,700; opening intake 2,100, titrated ±150 on the scale, never on an incomplete-log week",
    "lifting: six days on a wave, 10–16 sets/muscle, loads that MOVE → three or four full-body sessions, 6–10 sets/muscle, "
    "loads that HOLD, gains taken only when offered (retention was excellent last time; volume was the cost; the wave "
    "manufactures failures that raise calories for the wrong reason — Bickel 2011)",
    "walking: 12–15 h target → 13 h by week 6 with 16 h permitted in weeks 3–12; floor 8.5 h permanent, 10 h in maintenance "
    "(the engine that made the rate: 16–19 h/wk in the first nine weeks of 2024–25)",
    "landing: 12 weeks at 200 → deceleration from 240 lb in weight not weeks, rehearsal maintenance weeks at 260/240/220, "
    "land at 200–205 never 188, 26 weeks of maintenance in a 195–205 band with walking as the relapse vital sign",
    "medical: DXA 8–12 → 8 weeks fixed; ursodiol in every week the 14-day trend exceeds 3.0 lb/wk; baseline within two weeks "
    "including the week-0 DXA, RMR and gallbladder ultrasound; the stop/slow table",
    "new: fat floor 65 g and carb floor 120 g; the logging redline (7 of 7, 14 complete days before the first titration, "
    "a day < 600 kcal is dark); the adaptive-rate tripwires (loss_acceptable / excessive_clean / excessive_flagged / "
    "rate_ceiling / insufficient_adherent / insufficient_nonadherent), under_floor, walking_vs_fork, "
    "leverage_not_deterioration, lean_mass, sleep, weigh_in_dark, joy, post_goal_walking",
    "tripwire thresholds: readiness 40 on 3 days → recovery 7-day mean < 50 (5–7 days); strength → rolling 3-session e1RM "
    "median > 5 % below the 6-session baseline on 2 of 4 anchors (the engine still computes the simpler top-set drop and "
    "says so); rate_overshoot is cap-based with ursodiol on; volume_ceiling → 10 sets/muscle/wk; "
    "abstinence_violation_spiral folded into weigh_in_dark + logging_dark",
    "kept: protein 200/180 on ≥6 of 7 in 4 feedings, subtract-only authoring, the running gate (tightened), daily weighing, "
    "the Minimum Viable Week, the mood firewall, band-matched load anchoring with the detraining discount",
]
