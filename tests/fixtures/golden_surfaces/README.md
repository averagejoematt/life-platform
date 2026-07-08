# Golden-surface fixtures (#812, R22 FABLE-02, epic #720)

Frozen inputs for the generalized falsifiable-honesty harness
(`tests/golden_surface_eval.py`) — one pack per AI surface the runtime ADR-104
grounding gate protects. `tests/fixtures/golden_briefs/` (#742) covers the coach
briefs; these packs cover the other five reader-facing surfaces, each replayed
through the surface's ACTUAL gate function (never a re-implementation):

| surface | gate function replayed | check dimensions |
| --- | --- | --- |
| `board_ask` | `web.site_api_ai_lambda.board_grounding_findings` | `evidence_ceiling` |
| `chronicle` | `wednesday_chronicle_lambda.installment_grounding_findings` | `evidence_ceiling` |
| `memoir` | `compute.coach_memoir_lambda.gate_check` | `evidence_ceiling`, `miss_dodged`, `empty_output` |
| `state_of_matthew` | `compute.state_of_matthew_lambda.narration_gate` | `evidence_ceiling`, `causal_language` |
| `field_notes` | `intelligence.field_notes_lambda.note_contradiction_hits` | `grounding_contradiction` |

## Layout

Each `<surface>/` dir holds:

- **`golden.json`** — known-good outputs (expect ZERO findings). Every fixture
  carries a `provenance` string: REAL recorded outputs name the DDB record they
  were taken from (verbatim), and any reconstructed input says so explicitly.
  AUTHORED goldens (used where no real record exists yet, e.g. memoirs) say
  AUTHORED. Never silently synthesize a "real" fixture.
- **`canaries.json`** — seeded faults (expect CAUGHT). ALWAYS synthetic; the
  `mutation` field starts with "SEEDED FAULT (synthetic)" and describes the
  fault class. `expect_checks` lists the check(s) that must fire — an uncaught
  canary fails the whole run. Per surface, canaries must span every check
  dimension in the table above (a self-test enforces it).

## Fixture shape

```json
{
  "id": "som_real_2026_07_05",
  "surface": "state_of_matthew",
  "provenance": "REAL recorded pair: DDB pk=... sk=...",
  "inputs": { ...surface-specific gate inputs... },
  "reference_output": "…"            // golden;  canaries use "mutated_output"
}
```

`inputs` per surface: `board_ask` `{system_context, question[, prior_answers]}` ·
`chronicle` `{elena_prompt, user_message}` · `memoir` `{facts}` (the
`_render_facts_for_prompt` dict incl. `learnings_raw`) · `state_of_matthew`
`{state}` (the narration state sections) · `field_notes` `{metrics_record}`
(a `computed_metrics`-shaped record; the output here is the note's
`{ai_present, ai_cautionary, ai_affirming}` dict, not a string).

Harvested fixtures (from `scripts/harvest_eval_fixtures.py`, consuming the
`EVALRET#` retention stream — #744) use `"mode": "generic"` and carry
`inputs.allowed` (the recorded numeric allow-list) + optional `inputs.facts`;
they replay through `grounded_generation.grounding_findings` plus the surface's
extra deterministic checks.

## Adding a fixture

Append to the surface's file, label provenance honestly, and run
`python3 tests/golden_surface_eval.py` — a golden must draw zero findings, a
canary's injected value must NOT exist in its own inputs (else it's grounded and
won't flag). The monthly harvest workflow proposes candidates automatically;
promote them with `scripts/harvest_eval_fixtures.py --promote` after a human
privacy/quality review.
