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

Five fixtures that each inject a fault the gate must catch. Each adds:

```json
{
  "mutation": "human description of the injected fault",
  "mutated_output": "…output containing the fault…",
  "expect_checks": ["evidence_ceiling"]
}
```

`expect_checks` ∈ `{evidence_ceiling, grounding_contradiction, anti_pattern}`. The
harness asserts every expected check fires; an uncaught canary fails the run. The
five together must span all three dimensions (a self-test enforces this).

## Second use: calibrating the LLM JUDGE (#1374)

The same 35 fixtures are the labeled set for `tests/judge_calibration.py`, reachable as
`python3 tests/golden_brief_eval.py --judge-calibration`. The deterministic harness above
asks *"does the honesty gate work?"*; the calibration mode asks *"how good is the LLM
quality-gate judge that BLOCKS coach drafts (ADR-108/#390)?"* and answers with a confusion
matrix carrying its n and a 95% Wilson interval on every rate.

**Ground truth is the label already here:** the 30 goldens are the positives (genuinely
publishable), the 5 canaries the negatives (induced defect). That is why the story did not
need the "~30 days of verdict history" its deferral asked for — see the module header for
why that wait could never have ended.

**The denominators are asymmetric and the report says so.** 30 positives is workable; **5
negatives is thin** — a perfect 5/5 still has a 95% lower bound near 0.57, so no
specificity figure from this corpus is a measurement. Anything published from it must
carry the interval, never the point estimate.

**Known corpus/rubric mismatch.** These canaries were authored for the *deterministic*
gate. Only `canary_anti_pattern` is squarely inside the LLM judge's four-criterion rubric
(anti-patterns, decision class, voice distinctiveness, cross-coach similarity) — the
fabrication and contradiction canaries test faults that rubric never asks about. The
harness classifies each canary (`RUBRIC_SCOPE`) and reports specificity split by scope, so
a low number is not silently read as "the judge is bad" when it may be "the rubric has no
rule for this."

### Re-evaluation cadence (drift)

| When | What | Why |
|---|---|---|
| On any change to `QUALITY_GATE_SYSTEM_PROMPT`, `PASS_SCORE_THRESHOLD`, or the judge model/tier | Re-run `--judge-calibration` and record the matrix in the PR | Those three ARE the instrument; changing one invalidates the prior calibration |
| Quarterly, unprompted | Re-run and compare cells to the last recorded matrix | Vendor model updates move a judge with no repo change to trigger a re-run |
| Whenever a canary or golden is added | Re-run | The denominators change, so every interval changes |

Deliberately **not** on a CI schedule: at ~35 Haiku calls a run this is cheap but not free,
and a number nobody reads is worse than no number. It is an instrument you pick up, not a
gate. It pauses only at budget tier 3 (the #1927 lesson — an AI check that pauses at tier 1
is dark most of the month while still reporting green) and reports `NOT_RUN` rather than
emitting a matrix it did not measure.

## Adding a fixture

Append a JSON object. For a canary, pick the `expect_checks` that matches the fault
class and make sure the injected number is **not** present in the fixture's own
facts/brief (else it's grounded and won't flag — see the `172` self-collision
noted in the PR). Run `python3 tests/golden_brief_eval.py` to validate.
