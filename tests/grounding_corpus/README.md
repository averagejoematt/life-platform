# The adversarial grounding corpus (#3614)

One JSON fixture per sentence the platform was caught fabricating on a live surface.
`tests/test_grounding_corpus_3614.py` replays every fixture against the gate class that
must fail it and asserts its matched control passes the same gate with the same inputs;
`corpus.sha256.json` is the content-address seal (`python3 scripts/grounding_corpus_stamp.py
verify | stamp [--amend <id>]`). The corpus is grow-only.

## Fixture schema

| key | meaning |
|---|---|
| `id` | the file name without `.json` — `<captured date>-<surface>-<what it said>` |
| `issue` / `review` | the story that owns the specimen and the review finding that captured it |
| `captured_at` / `surface` | when and where it was served |
| `verbatim` | `true` if `specimen` is the served text byte for byte; `false` needs `verbatim_note` saying what was and was not captured |
| `status` | `caught` (a class fails it today) or `open` (no class yet — needs `closes_with` + `why_open`) |
| `gate` | `composite` (`grounded_generation.grounding_findings`), `plan` (`plan_facts_gate.plan_figure_findings`), or `null` for a non-prose specimen |
| `expect_type` | the finding `type` the gate must return for a `caught` specimen |
| `specimen` / `control` | the fabricated sentence and its matched grounded twin |
| `inputs` | FROZEN gate inputs as of the capture day (allow-list, dates, genesis, the plan block) — never today's constants |

## Adding a specimen

1. Write the fixture with the sentence verbatim and the inputs frozen to the capture day.
2. `python3 scripts/grounding_corpus_stamp.py stamp` (adds are always accepted).
3. Bump `MIN_SPECIMENS` (and `MIN_CAUGHT` if it is caught) in the test, in the same PR.

## Closing an open specimen

The PR that lands the class flips `status` to `caught`, sets `expect_type`, re-seals with
`stamp --amend <id>`, and bumps `MIN_CAUGHT`. A specimen that stops failing is fixed by
fixing the gate — never by rewording the sentence.
