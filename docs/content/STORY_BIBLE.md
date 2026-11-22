# Story Bible — The Measured Life

> **Status:** live · **Verified:** 2026-11-21 · **Issue:** #6155 · **Owner:** Matthew

The series' continuity guide, kept lightweight on purpose. It **points at the record** and copies none of it: each
section names the object that is authoritative, so the bible cannot drift from what the platform actually holds. It
carries public facts only — nothing here may say more than the live site already says. The repository is public.

**The threads below are investigative, never prewritten arcs.** No thread has an ending until the data gives it one.
A writer follows a thread by reporting what its evidence shows this week, including that it shows nothing yet.

`tests/test_elena_canon_6155.py` checks that every path and function this page names exists, and that the page
states no personal detail the owner has ruled out.

## 1. The central question

The season asks one standing question, carried by the season spine: `lambdas/content/story_craft.py::season_spine`.
The ledger carries it forward week to week (`lambdas/content/story_ledger.py`, rows `LEDGER#{date}` in the chronicle
partition). Read it there; do not restate it in a new place.

## 2. Approved public facts about Matthew

Only what the live site already states, in general terms:

- He is running a year-long, fully instrumented health experiment, one man, every number on the record.
- He has done this before: he lost a large amount of weight once and most of it came back. The year is his attempt to
  understand why the first time did not hold.
- A team of AI coach personas reads his data each morning, and their predictions are on the public record.
- The site states that each chapter is published after he approves it.

Everything else is governed by the prequel brief's rules: `docs/content/ELENA_PREQUEL_BRIEF.md` (what to abstract or
omit, always; what is safe to include). His own words appear only where he approved them, each for one page:
`www/src/lib/own_words.js`.

## 3. Elena's identity

One canonical specification, `lambdas/content/elena_canon.py` (`ELENA_CANON_VERSION`): identity and AI disclosure,
temperament, how she reasons about evidence, uncertainty, the registers she writes in, what she never does, length, and
voice anchors quoted only from published chapters. Every writer renders her from it — the Story Desk
(`lambdas/content/story_writers.py`), the legacy writer (`lambdas/emails/chronicle_prompt.py`), and the Panel's scripts
(`lambdas/emails/podcast_script_v2.py`, `lambdas/emails/panelcast_scripts.py`). Edit her there, nowhere else.

The owner's refinements of 2026-11-22 (canon 1.1.0, #6178):
- "compassionate without being soft" stays.
- She may be hopeful when the evidence warrants it; optimism is never a standing obligation.
- She has no invented career, employment history or first-hand interview. A staged encounter in a draft is a hard
  source finding (`lambdas/content/story_checks.py::staged_encounter_findings`).
- No journal text enters an editorial prompt without the owner's explicit authorisation.
- Voice anchors are eligible and verified only (`lambdas/content/elena_canon.py::verify_anchors`).
- A coach is quoted only in approved original wording.

On the site she is named the same way on every byline (`www/src/lib/narrator.js`).

## 4. The coaches' canonical roles

The coach registry: `config/personas.json`, read through `lambdas/coach/persona_registry.py`
(`OPERATIONAL_COACH_IDS` is the roster, `LEAD_PERSONA_ID` the head coach). Each coach's voice is
`config/coaches/{coach_id}.json`, rendered by `lambdas/coach/persona_core.py`. A name not on the roster does not appear
in a chapter.

## 5. Chronology and milestones

- The published chapters: the site's chapter list (`www/src/pages/story/`), built from the publication snapshot. A
  week without a chapter is held (a draft exists, not approved), skipped (no chapter was published), pending (in
  progress) or retired (the owner decided the draft will not be published); `lambdas/web/site_api_chapters.py`.
- The documented moments a stranger should see: `www/src/lib/moments.js` (selected by rule from published objects).
- Threads opened, advanced and resolved, bets and their results, titles used: the season ledger
  (`lambdas/content/story_ledger.py`). It advances only when a desk-written week publishes.
- Experiments and their pre-registrations: `config/experiment_library.json`.

To regenerate the chronology, rebuild the site from the current snapshot (`www/README.md`); a season rebuild is
`scripts/season_rebuild.py` (owner-promoted with `scripts/season_promote.py`). Never hand-edit a published chapter.

## 6. Open investigative threads

Each names where its evidence lives and what is **not yet known**. None is a plot.

| Thread | Where the evidence lives | Not yet known |
|---|---|---|
| Sustained weight loss | the scale series in the dossier (`lambdas/content/story_dossier.py`); the season spine | whether the loss holds past the point where it came back before; the season is not over |
| Strength preservation | training logs and adherence in the dossier; body-composition readings; the protein floor in the plan | how much lean mass has changed — the scale's bio-impedance reading is too noisy to settle it |
| Whether AI coaching improves his decisions | the graded predictions and each coach's record (`lambdas/coach/coach_prediction_evaluator.py`); corrections (`www/src/lib/corrections.js`) | graded calls measure forecasts, not decisions; there is no counterfactual week |
| Routine and life satisfaction | his approved own words (`www/src/lib/own_words.js`, `lambdas/content/owner_words.py`); public habit data | almost everything: the journal is private and nothing is inferred from it |
| How the system reacts to disappointing results | wrong calls and their grades; corrections; chapter revisions (`scripts/chronicle_revision_apply.py`); holds (`lambdas/content/autopublish_audit.py`) | whether the coaches change their models after being wrong, beyond the record of individual calls |
| Whether experiments yield findings | the experiment library (`config/experiment_library.json`); the hypothesis engine (`lambdas/compute/hypothesis_engine_lambda.py`) | a finding is only what the registry concludes; an open experiment is reported as open |
| Reader calls against the AI | reader calls (`lambdas/web/site_api_reader_call.py`, `lambdas/web/reader_call_rules.py`) and the coaches' graded calls | whether readers forecast him better than the coaches do; the sample is small |

## 7. Corrections

A correction is a platform act, recorded where it happened: prediction corrections in `www/src/lib/corrections.js`;
chapter revisions on the chronicle row (`scripts/chronicle_revision_apply.py`). Report a correction plainly; never
rewrite history to hide one.

## 8. Sensitive boundaries

The rules live in their own places and are not restated here:

- what is abstracted or omitted about Matthew: `docs/content/ELENA_PREQUEL_BRIEF.md`;
- journal privacy and the quote tiers: ADR-142 in `docs/DECISIONS.md`;
- the reader-surface door (no cycle, reset or attempt counts; no off-record specifics): `lambdas/content/story_checks.py`;
- spoken body numbers on the Panel: `lambdas/content/body_numbers.py`;
- real people and vice vocabulary: `lambdas/privacy/privacy_guard.py` (the vocabulary itself lives off-repo).
