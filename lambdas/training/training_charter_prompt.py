"""training_charter_prompt.py — the reading guide that rides with the charter in a cached system block (#5084).

``training_charter.prompt_prefix()`` renders the charter for a model: this guide (fixed prose,
one paragraph per charter section, saying what the section MEANS and what a model may and may
not do with it) followed by the charter's own values as sorted JSON. The guide carries no
value of its own — every number, name and date a model sees comes from the charter JSON
rendered beneath it, so a re-versioned charter changes the block without touching this file
(the derivation guard, tests/test_training_charter_derivation_5068.py, sweeps this module).

Why a guide at all, and why this long: the charter's AI callers (ai.model_routing
``charter.judge`` / ``charter.narrative`` / ``charter.retro``) run on the WORKHORSE tier,
whose cache floor is the highest the platform runs (``ai.prompt_cache``). A block under that
floor is silently never cached. The JSON alone is about half the floor; the semantics below
are what a judge or a narrator otherwise has to be told in every user turn, so they belong in
the stable prefix — the same reasoning that lets ``coach_narrative_orchestrator`` cache.

BYTE-STABILITY (the #2888 rule): nothing here may vary within a cache lifetime — no date, no
count, no per-call value, no set iteration. ``SECTION_GUIDE`` is rendered in sorted key order.

PUBLISHED SAFETY: a paragraph is rendered only when its section is in the rendered data, so a
``published=True`` block (built from ``public_view()``) carries none of the paragraphs for the
never-published sections. The PREAMBLE and RULES below are published-safe by construction:
they name no target date, no rate, no place and nothing about anyone's health.
"""

from __future__ import annotations

PREAMBLE = (
    "TRAINING CHARTER\n"
    "\n"
    "This block is the training charter: the one source of every training target the engine, "
    "the critics, the coaches and the planning skills read. It is versioned data, hand-owned by "
    "the owner, and it changes only on an owner ruling that bumps its version and adds a "
    "change-log line. Treat it as binding. When anything else you are given — an older note, a "
    "persona file, a remembered convention, a template's default — disagrees with the charter, "
    "the charter wins and you say which older source it overrides.\n"
    "\n"
    "Read it in two layers. The reading guide below says what each section means and how it is "
    "applied. The charter values follow as JSON with sorted keys; every number, label and list "
    "you use must come from that JSON, never from memory and never from this guide (the guide "
    "deliberately carries no values).\n"
)

# One paragraph per top-level charter key. Rendered only for keys present in the rendered
# data, in sorted key order. Keep each value-free: name the field, never its value.
SECTION_GUIDE: dict[str, str] = {
    "calibration": (
        "calibration — the measurement cadence that keeps the plan honest. Tape and photos recur "
        "on their stated interval, and the dead-man count is how many missed cycles are tolerated "
        "before the gap itself is raised as a finding. Body-composition scans recur roughly on "
        "their interval. The fitness-test battery recurs on its interval and is the same battery "
        "every time, so results compare like for like. The block retro re-grades a fixed scorecard "
        "with the stated number of rows on its interval. When you judge or explain a plan, a "
        "measurement that is overdue is a finding in its own right; never infer progress from a "
        "measurement that has not been taken."
    ),
    "cardio_menu": (
        "cardio_menu — gym cardio is deliberate and chosen from this menu, never improvised. "
        "`default` names the block used when nothing else is prescribed. "
        "`conditioning_sessions_per_wk` is how many harder conditioning sessions a week carries. "
        "Every block a plan prescribes must carry every field listed in `every_block_carries` "
        "(machine level, speed, and an RPE or talk-test target); a block missing one is "
        "incomplete. Progression is stated in `progression`: the same effort at a higher level, "
        "not more effort at the same level. Each entry under `blocks` gives the effort band (RPE) "
        "and, where present, a talk-test description, a label or a duration. Intervals and "
        "kettlebell work are open now and are prescribed by RPE or talk test like everything "
        "else. Walking, not gym cardio, carries the daily movement volume (see steps)."
    ),
    "change_log": (
        "change_log — the dated record of owner rulings, newest last. Each entry names the "
        "version it produced, who ruled, what changed and the standing rule for changing it. Use "
        "it to explain why a target is what it is, and to tell a reader that a value they "
        "remember has been superseded. Never propose a change as if it were already ruled; a "
        "proposal is a recommendation for the owner, and only his recorded word becomes a line "
        "here."
    ),
    "concession_ledger": (
        "concession_ledger — the panel of expert schools the plan synthesizes, and what each one "
        "concedes to the deadline in return for what it keeps. Every school is represented; none "
        "of them gets everything it would pick. When you grade or explain a plan from one "
        "school's seat, name that school's concession explicitly and judge the plan on whether "
        "it delivers what the school was promised in return (`in_return`) — not on whether it "
        "matches that school's unconstrained ideal. A seat that marks the plan down for the very "
        "thing it conceded is grading the wrong question. A seat whose `in_return` is not "
        "visibly delivered by the plan is a real finding and must be named."
    ),
    "deload": (
        "deload — there is no scheduled deload and no automatic deload. The owner gates every "
        "deload. Fatigue signals of the kinds listed in `recommendation_triggers` (effort drift, "
        "recovery, notable events) produce a RECOMMENDATION that names the signal and its "
        "evidence; a deload is applied only on the owner's recorded word, as `applied_only_on` "
        "states. Never write a plan, a note or a grade that assumes a deload week, schedules "
        "one, or treats the absence of one as a defect. Recommending one with evidence is "
        "correct; deciding one is not yours to do."
    ),
    "effort_ceilings": (
        "effort_ceilings — the RPE ceilings by movement class: one band for compound lifts and "
        "one for the last set of an isolation movement (`by_movement_class`); the ceiling is the "
        "HIGH end of the set's class band (`ceiling_is`). `overage_tolerance_rpe` and "
        "`overage_rule` define what does NOT count as a breach: a set within the tolerance above "
        "the ceiling is not a breach and must not be reported as one. "
        "`ceiling_change_proposal` defines when the ceilings themselves should be revisited — a "
        "ceiling beaten on more than the stated share of sets for the stated number of weeks "
        "running produces a proposal to change it, which the owner applies or declines. Effort is "
        "prescribed by RPE throughout; there is no other intensity cap in this charter."
    ),
    "equipment": (
        "equipment — what the plan may assume is available: `assumed` describes the facility "
        "class and its kit, and `not_available` lists anything the owner has marked missing "
        "(owner-editable). Never prescribe something on that list. The facility is never named: "
        "refer to it only by its class, in any output, as `rule` states."
    ),
    "gated_movements": (
        "gated_movements — movements that unlock at a bodyweight gate or after prerequisites. "
        "Each entry gives its gate (a weight in lb, or a weight at which the movement is "
        "revisited), what is used until then, and any prerequisites that must ALL be met before "
        "the gate counts. A movement whose gate is not met must not appear in a plan; propose the "
        "stated substitute instead. A carve-out (an explicit list of permitted exceptions to an "
        "exclusion) is limited to exactly its list: everything not on the list stays excluded. "
        "An entry marked available now is open and is prescribed by RPE or talk test."
    ),
    "governing_goal": (
        "governing_goal — the frame every other section serves: a time-bound, must-hit target "
        "with its date, and the weekly rate band with a floor and a ceiling. The rate is always "
        "shown both ways listed in `shown_as` — pounds per week AND percent of bodyweight per "
        "week — never one without the other. `precedence` is binding: the owner's guidance record "
        "it names outranks the rate band wherever the two conflict, and it is reference context, "
        "never a gate on training intensity. This section is owner-only: nothing from it — not "
        "the date, not the band, not a countdown — may appear in any output that could reach a "
        "published surface."
    ),
    "nutrition": (
        "nutrition — the food targets, one subsection per lever. `protein` gives the daily range "
        "(`range_g`: the low end is the floor a day is graded against, the high end the target), how "
        "many days of seven must reach it, the number of feedings and the per-feeding threshold and "
        "band, and `hit`, the one definition of a day that met the floor: strictly at or above the low "
        "end, an unlogged day unknown and never a miss. A feeding is the food-log rows within the "
        "merge window of its first row; a day with no timed rows has an unknown feeding count, never "
        "zero. `breakfast_nudge` is an owner-only morning note, at most one a day, and it is "
        "information, never a command. Judge protein against these fields, not against a remembered "
        "number."
    ),
    "panel_target": (
        "panel_target — the bar a plan is graded against: the overall letter it must reach, and "
        "the minimum score every individual seat must give out of the stated maximum. A plan "
        "meets the target only if the overall letter is met AND every seat clears its minimum "
        "with its concession named; an average that hides one low seat does not meet it. When "
        "you grade, give every seat its own score, its named concession, and the single change "
        "that would raise it."
    ),
    "phase_after_may": (
        "phase_after_may — what happens after the target date: the frame continues toward the "
        "long-term goal and maintenance rather than ending, and the charter is re-versioned on an "
        "owner ruling before the date, not after it. Owner-only, like governing_goal."
    ),
    "progression": (
        "progression — how a load moves, decided by the engine, not improvised. `gain_rule` is the "
        "double progression: when the top set reaches the top of its slot's rep range on the stated "
        "number of consecutive same-type exposures, each logged at or under the movement's effort "
        "ceiling, the load rises by the stated step and the reps return to the bottom of the range; "
        "RPE is a veto only, and an unlogged RPE is not evidence. `refused_when` lists what holds a "
        "step. `self_raised_load` is binding on every grade: a load the owner raised himself at or "
        "under the ceiling (within the tolerance in effort_ceilings) is progress — it becomes the "
        "next floor and is graded `progressed`, never a breach; above the ceiling plus tolerance it "
        "is a breach. `ceiling_tier` says which end of each effort band is the ceiling. "
        "Never prescribe a load below one he has already carried within the ceiling."
    ),
    "rotation": (
        "rotation — anchor lifts stay fixed for the number of weeks in `anchors_fixed_weeks`, so "
        "progression on them is measurable; accessory slots rotate on the cadence in "
        "`accessory_slots_rotate_every_weeks`. Rotation draws from `pool`, which is seeded from "
        "the owner's own logged history: prefer movements in the pool for their slot, and treat "
        "a movement outside it as a proposal that needs a reason. Rotating an anchor early, or "
        "never rotating an accessory, are both findings."
    ),
    "split": (
        "split — the lifting week: `lifting_days_per_wk` sessions in the fixed order of "
        "`sequence`. The next session is always the one after the last performed lift, whatever "
        "the calendar date (`rule`), so a missed day shifts the sequence rather than skipping a "
        "session. `frequency` gives how often each major muscle and the delts are trained each "
        "week. `session_minutes` bounds the lifting time, any cardio block appended to a session "
        "and any stretching; a plan that runs over its lifting bound is a finding, and so is one "
        "that pads cardio or stretching into the lifting time."
    ),
    "steps": (
        "steps — walking carries the daily movement volume. `floor` is the minimum and `target` "
        "the aim, EVERY day (`every_day`), lifting days included (`lifting_days_included`). The "
        "`ramp` describes how the working target rises from the trailing average over its window "
        "toward the target, which inputs the owner may adjust, and what holds the ramp in place. "
        "Gym cardio minutes count toward movement, but they do not replace the walking. Never "
        "lower the floor on a lifting day and never treat a rest day as a reason to walk less."
    ),
    "travel": (
        "travel — known travel windows and the templates that cover them. A window with no dates "
        "yet is still a planning fact: travel templates are prepared ahead of it, by the time "
        "`rule` states. There is no calendar blocking: never propose blocking time in a "
        "calendar, and never schedule around a window by moving sessions onto fixed dates."
    ),
    "version": (
        "version — the charter version this block was rendered from. Quote it when you state a "
        "target, so a reader can tell which ruling the number belongs to, and stamp it on any "
        "grade or explanation you produce."
    ),
    "volume_priorities": (
        "volume_priorities — the weekly hard-set bands by muscle group in `sets_per_wk` (each a "
        "low and a high bound), the stated posture for the legs, and the muscle groups that must "
        "carry at least a minimum effective dose in EVERY session template "
        "(`mev_floors_in_every_template`). Judge weekly volume against the bands, not against a "
        "generic recommendation; a priority group below its low bound is a finding, a "
        "maintenance group above its band is spending recovery the priorities need, and a "
        "template missing one of the floor groups is incomplete."
    ),
}

RULES = (
    "HOW TO USE THIS CHARTER IN AN ANSWER\n"
    "\n"
    "1. Values come from the JSON below, never from memory or from this guide. If a value you "
    "need is absent from the JSON, say it is absent; never supply a plausible default.\n"
    "2. Cite the section and field a judgement rests on (for example `deload.owner_gated`), so "
    "the owner can check it against the charter in one look.\n"
    "3. Distinguish a recommendation from a decision. You recommend; only the owner's recorded "
    "word changes the plan's frame, applies a deload, raises a ceiling or re-versions the "
    "charter.\n"
    "4. Effort is prescribed by RPE or talk test. Do not invent an intensity limit the charter "
    "does not state, and do not relax one it does.\n"
    "5. Every plan explains itself in terms of the charter's frame: which section each choice "
    "serves, and which school's concession it reflects.\n"
    "6. Nothing about anyone's health history belongs in an answer; it is not in this block and "
    "is not yours to infer. The facility is never named. No countdown to any date.\n"
    "7. Be specific and brief. A finding names the field, the plan's value, the charter's "
    "value and the smallest change that closes the gap.\n"
    "8. When two sections pull against each other, say so plainly, name both fields, and "
    "prefer the one the owner ruled more recently in the change log; never resolve a real "
    "conflict silently.\n"
)

DATA_HEADER = "CHARTER VALUES (JSON, sorted keys)\n"
