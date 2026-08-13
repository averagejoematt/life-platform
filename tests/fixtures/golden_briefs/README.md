# Golden-brief fixtures (#742, ADR-127)

Frozen inputs for the falsifiable-honesty eval harness (`tests/golden_brief_eval.py`).
These are hand-maintained artifacts — the harness replays them through the same
deterministic honesty gate the live coach pipeline uses.

## `golden.json` — known-good outputs (expect ZERO findings)

A list of `~30` fixtures spanning all 8 coaches. Each:

```json
{
  "id": "training_01",
  "coach_id": "training_coach",
  "authoritative_facts": { "recovery_pct": 64 },
  "generation_brief": { "decision_class_ceiling": "observational", ... },
  "reference_output": "…the coach's grounded narrative…"
}
```

**Invariant:** every number in `reference_output` must appear in `authoritative_facts`
or `generation_brief` (or be a benign small count / year / round anchor per
`grounded_generation._BENIGN_NUMBERS`). If it doesn't, the gate flags it and the
harness fails — that's the point. Keep outputs voice-distinct across coaches
(content-word Jaccard < 0.55) so the distinctiveness check stays honest.

Fact keys the gate reads: `recovery_pct`, `hrv_ms`, `rhr_bpm`, `latest_weight`,
`weekly_rate_lbs`, `protein_g_avg`/`_target`/`_floor` (see
`grounded_generation.authoritative_facts_block` + `grounding_guard`).

## `canaries.json` — induced faults (expect CAUGHT)

Fifteen fixtures (5 at #742, grown to 15 by #2573 to clear the thin-denominator
floor) that each inject a fault the gate must catch. Each adds:

```json
{
  "mutation": "human description of the injected fault",
  "mutated_output": "…output containing the fault…",
  "expect_checks": ["evidence_ceiling"]
}
```

`expect_checks` ∈ `{evidence_ceiling, grounding_contradiction, anti_pattern}`. The
harness asserts every expected check fires; an uncaught canary fails the run. They
must together span all three dimensions (a self-test enforces this).

## Second use: calibrating the LLM JUDGE (#1374)

The same 45 fixtures are the labeled set for `tests/judge_calibration.py`, reachable as
`python3 tests/golden_brief_eval.py --judge-calibration`. The deterministic harness above
asks *"does the honesty gate work?"*; the calibration mode asks *"how good is the LLM
quality-gate judge that BLOCKS coach drafts (ADR-108/#390)?"* and answers with a confusion
matrix carrying its n and a 95% Wilson interval on every rate.

**Ground truth is the label already here:** the 30 goldens are the positives (genuinely
publishable), the 5 canaries the negatives (induced defect). That is why the story did not
need the "~30 days of verdict history" its deferral asked for — see the module header for
why that wait could never have ended.

**The denominators are asymmetric and the report says so.** 30 positives is workable, and
since #2573 the 15 negatives clear the 10-case thin floor — so a specificity FIGURE is now
publishable where 5 negatives only ever supported a bound. Anything published still carries
its interval; `judge_calibration.publication_record` drops any rate whose denominator falls
back under the floor rather than softening it (`tests/test_judge_calibration_1374.py`
pins that door shut).

**Known corpus/rubric mismatch — largely closed by #2573.** These canaries were authored
for the *deterministic* gate. Before #2573 only the anti-pattern canaries sat inside the LLM
judge's four-criterion rubric; the fabrication and contradiction ones tested faults that
rubric never asked about. #2573 added criterion 5 (which *consumes* the deterministic
verdict rather than re-deciding it), so every canary class is now in scope. The harness
keeps BOTH mappings (`RUBRIC_SCOPE_PRE_2573` / `RUBRIC_SCOPE_POST_2573`) and reports the
split under each, so the published number shows what moved rather than only where it landed.

**The corpus is polar by construction, and that bounds what it can answer.** The goldens
were authored to be obviously publishable and the canaries to carry an obvious fault. In the
2026-08-13 run every golden scored 82–92 (one outlier at 42) and every canary 15–25 (one
outlier at 92) — **nothing at all between 42 and 82**, straddling a threshold of 60. So this
corpus can measure the gate's rates but *cannot* estimate a per-decision error margin
(#1374 acceptance item 3): there is no labeled data at the boundary to fit one to.
`judge_calibration.margin_analysis` computes that refusal from the scores rather than
asserting it, and flips to `ESTIMABLE` the moment the boundary region is populated. What
would populate it: labeled **borderline** drafts. Real HELD drafts are the natural source —
borderline by definition — but `coach_quality_gate` performs no `put_item`, so that needs a
retention change first, not another run.

### Re-evaluation cadence (drift)

| When | What | Why |
|---|---|---|
| On any change to `QUALITY_GATE_SYSTEM_PROMPT`, `PASS_SCORE_THRESHOLD`, or the judge model/tier | Re-run `--judge-calibration` and record the matrix in the PR | Those three ARE the instrument; changing one invalidates the prior calibration |
| Quarterly, unprompted | Re-run and compare cells to the last recorded matrix | Vendor model updates move a judge with no repo change to trigger a re-run |
| Whenever a canary or golden is added | Re-run **and re-publish** (`--publish`) | The denominators change, so every interval changes — and the published artifact is stale until it is rewritten |
| Whenever the corpus gains BORDERLINE cases | Re-run and re-read `margin_analysis` | It is the only thing that can flip acceptance item 3 from NOT_ESTIMABLE; a populated boundary region is the trigger to revisit margin-aware gating |

### Publication (#1374 acceptance item 2)

`--publish` writes `site/data/judge_calibration.json`, which
`scripts/v4_build_evidence.py` inlines into the `/method/` shells and
`evidence_intelligence.js::_judgeBlock` renders on **/method/calibration/** — the
"Calibrating the grader" panel. Nothing on that page is hand-typed; regenerate the artifact
and rebuild rather than editing the HTML. Two invariants the code enforces so a figure
cannot outrun its instrument: a run that did not measure publishes **nothing** (and never
truncates the previously published artifact), and `must_ship_with` travels with the figures
— including the one that matters most, that these are the **combined** gate's rates
(deterministic prepass + judge), not the LLM judge's own discrimination.

Deliberately **not** on a CI schedule: at ~45 Haiku calls a run this is cheap but not free,
and a number nobody reads is worse than no number. It is an instrument you pick up, not a
gate. It pauses only at budget tier 3 (the #1927 lesson — an AI check that pauses at tier 1
is dark most of the month while still reporting green) and reports `NOT_RUN` rather than
emitting a matrix it did not measure.

## Adding a fixture

Append a JSON object. For a canary, pick the `expect_checks` that matches the fault
class and make sure the injected number is **not** present in the fixture's own
facts/brief (else it's grounded and won't flag — see the `172` self-collision
noted in the PR). Run `python3 tests/golden_brief_eval.py` to validate.
