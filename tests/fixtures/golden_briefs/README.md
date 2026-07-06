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

## Adding a fixture

Append a JSON object. For a canary, pick the `expect_checks` that matches the fault
class and make sure the injected number is **not** present in the fixture's own
facts/brief (else it's grounded and won't flag — see the `172` self-collision
noted in the PR). Run `python3 tests/golden_brief_eval.py` to validate.
