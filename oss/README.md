# `oss/` — pieces of this platform published as standalone open-source artifacts

Each subdirectory is a **self-contained, MIT-licensed package** that is developed
here and published outward. They exist because a claim the platform makes in
public ("every forecast is graded, and here is the score") is only checkable if
the thing doing the grading is checkable too.

The rules that make that real:

- **No platform imports.** A subdirectory here must run after being copied out on
  its own — no `stats_core`, no `boto3`, no relative imports into this repo.
  Enforced by test.
- **No private data.** Demo datasets are the already-public API surface only,
  each with a provenance block stating its source and whether it is real or
  synthetic. Enforced by test.
- **Parity, not resemblance.** Where a package is an *extraction* of code that
  still runs in the platform, a shared test-vector suite pins both copies to
  identical numbers, and a drift gate reds CI if either moves.
- **Its own LICENSE.** The repository root is proprietary; each package here
  carries an MIT carve-out that travels with the copied directory and nothing
  else.

| package | what it is | gates |
| --- | --- | --- |
| [`calibration-core/`](calibration-core/) | The forecast grader behind [/method/calibration](https://averagejoematt.com/method/calibration/) — Brier, reliability curve, skill vs. base rate — plus the browser port that powers [/method/grade-your-coach](https://averagejoematt.com/method/grade-your-coach/). (#1396) | `tests/test_calibration_core_parity.py`, `tests/js/calibration_core.test.mjs` |
| [`starter-slice/`](starter-slice/) | The fork-me starter template: one public source → S3 → DynamoDB → one chart, runnable offline with no AWS account, with the cost note **generated** from the published [stack manifest](https://averagejoematt.com/data/stack.json) rather than retyped. (#2541) | `tests/test_starter_slice.py` (forbidden-literal sweep, standalone-import scan, cost drift, and the template's own suite in a subprocess) |

Publishing a package outward is an owner step (`gh repo create` + a push of the
subdirectory's contents); nothing in CI does it automatically.
