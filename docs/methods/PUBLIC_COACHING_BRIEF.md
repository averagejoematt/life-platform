# The public-safe coaching brief

**Status: BUILT DARK 2026-11-09** (owner ruling 2026-11-09, third, section E). Nothing is publicly visible until
`lambdas/common/public_brief_policy.py::PUBLICATION_LIVE` is turned on, which is the owner's act, with the Coaching
Room switches.
**Code:** `lambdas/common/public_brief_policy.py` (the input whitelist, the dark switch, cycles),
`lambdas/coach/public_brief.py` (the producer), `lambdas/web/site_api_coach_brief.py` (`GET /api/coach_brief?coach=<id>`).
**Tests:** `tests/test_public_brief.py`. **Fields:** `docs/SCHEMA.md` (the `PUBLIC_BRIEF#` row of the coach tier).

## The ruling

> "Standardized public-safe brief for future cycles; only explicitly publication-eligible inputs; clearly distinguish:
> observations/interpretations; specific falsifiable prospective predictions; frozen evaluation criteria + windows;
> recommendations/proposed actions; what the owner actually did (recorded evidence); later corrections/changes in
> position. Preserve private process separately. Don't fabricate historical advice or reconstruct older private
> conversations."

## Why a second product

The coaches' daily and weekly words are written from a context that includes private families (almost every read
carries the journal's presence), so the narrative-provenance gate (`common/narrative_provenance.py`, owner ruling
2026-11-03) withholds them, and the Coaching Room's coach-record and docket pages are nearly empty. The brief does not
loosen that gate. It is a separate weekly product whose inputs are fixed before the model is called and can only be
public. The private coaching process does not change and does not feed it.

## What a brief may be made from

- **Measured metrics only**, and only those in `experiment/measurable_metrics.py::METRIC_SOURCES`, the one registry the
  prediction grader reads.
- **Every source the metric is read from must be classified public** by `common/activity_publication.py::source_class`,
  the source classification every public surface uses. It derives every owner-only partition of
  `privacy/field_tiers.py::SOURCE_TIERS` as private. A metric with an unclassified, private or unresolvable source is
  not an input (fail closed). `public_brief_policy.eligible_metrics()` recomputes this on every call, so it is never a
  stored list.
- Per coach, the inputs are the `public_brief_metrics` listed for it in `config/personas.json`, kept only where they
  are eligible. A coach with none gets no brief. Today the Mind, Labs and Explorer seats have none.
- The coach's name and title (the `persona` family), and the coach's own previous brief when that brief is itself
  publishable (with its calls' ledger statuses, the `prediction_ledger` family).

Never inputs, not even by inference: the journal and anything derived from it (entries, themes, quotes, presence,
analysis), mood and State of Mind, the video diary, check-in answers, the coach's private state (stance, threads,
compressed history, conversations), any other coach's words, and any person other than Matthew. The provenance stamp
on every row is computed from this same input set. `narrative_provenance` therefore decides publication from what the
brief was actually made from. A brief whose input set named a private or unknown family would be withheld at the
public chokepoint and left out of the API; the producer also refuses to make the call at all.

## The six sections

1. **Observations and interpretations.** Each eligible metric's mean over the 7 days before the cycle, the 7 days
   before that, and the 28 days before the cycle, each with its n and the latest reading. Code computes these numbers.
   The coach's interpretations each cite the observation ids they rest on.
2. **Predictions.** Each one names a metric, a direction or a level, and a window of 7 to 28 days. The platform writes
   the claim from those fields, so the words say exactly what is graded. It passes the filing rules
   (`coach/filing_rules.py`) and is filed in the existing prediction ledger (`PREDICTION#`, `source: public_brief`). The
   existing evaluator grades it. There is no second ledger.
3. **Evaluation criteria and windows.** A copy of each call's filed `evaluation`: the test, the window start and end,
   the tolerance and the rule that set it, and one engine sentence describing how it is graded. The copy is frozen at
   filing, so the test is on the brief before the window opens.
4. **Recommendations.** Proposed actions for the cycle. Each may carry an action check on a behaviour metric (calories,
   protein, steps): a comparison and a threshold.
5. **What he did.** Evidence rows written once the recommendation's window has closed, starting the day after at the
   earliest. They come from the recorded readings only: days in the window, days with a reading, days meeting the
   check, the readings and their source. A recommendation without a check is served as `not_measured`. One with no
   readings is `no_record`. Nothing is inferred from timing or correlation.
6. **Corrections and changes in position.** Append-only revision rows. Each names the item of the earlier brief it
   revises. The next cycle's coach is shown its previous brief and may change position. Grade corrections stay on the
   ledger's own trail (`CORRECTION#`, `corrections[]`).

## Checks before anything is written (fail closed)

- Budget first: `budget_guard.allow("coach_narrative")` (band 2), before any read or model call.
- No backfill: only the cycle that contains today, and never one before `FIRST_CYCLE` (2026-11-16). No historical
  advice is written, and no older conversation is reconstructed.
- One Haiku call through `bedrock_client.invoke`, plus one regeneration only if the reply is not usable JSON.
- Item checks. Every number in the coach's words must appear in the facts or in the item's own structure. No
  private-activity words (`prediction_publication.words_name_private_activity`). No words about a partner, family or
  any other person. Nothing the deterministic sensitivity spine flags (`privacy/broadcast_sensitivity_gate.py`). Cites
  must be real observation ids. A call must be on one of the coach's inputs and must file as gradeable. A failing item
  is dropped and only its count is kept. A brief with no surviving item is held, and nothing is written.
- A brief is never rewritten. Evidence and revisions are new rows, never edits.

## When it runs

Mondays at 09:00 platform time, on the `coach-history-summarizer` function with the event `{"mode": "public_brief"}`.
The schedule is `coach-history-summarizer#PublicBrief` in `config/schedules.json`. The function and its role are
unchanged, and its Sunday compression run is untouched. The schedule exists once `LifePlatformCompute` is deployed.
A missed or paused week shows as a gap in the dated cycles the API serves. The run never fills a gap later.

## Serving (dark)

`GET /api/coach_brief?coach=<persona_id>` returns 404 while the switch is off. When it is on, the route returns the
coach's briefs, newest first (at most 12). Each has the six sections above, and each call carries its current ledger
status. Every read goes through the public chokepoint (`web/narrative_publication.py`), so the route omits a withheld
brief, evidence row or revision, and a call the call policy does not publish together with its criteria. It never
marks or counts what it left out. While the switch is off, the calls are graded but classified private
(`prediction_publication.PUBLIC_BRIEF_DARK`), so no public list or number moves.
