# calibration-core

**Grade a forecaster — human or LLM — against what actually happened.**

Every wearable now ships an AI coach. None of them publishes whether the advice
worked. This is the scorer that does: Brier score, reliability curve, skill
versus the base rate, and a verdict that refuses to flatter.

It is the exact grader behind the public calibration scoreboard at
[averagejoematt.com/method/calibration](https://averagejoematt.com/method/calibration/) —
extracted, not reimplemented, and held to that by a shared test-vector suite.

- **Zero dependencies.** One Python file, one JS file, standard library only.
- **Paste-and-see version:** <https://averagejoematt.com/method/grade-your-coach/>
  (computes entirely in your browser — nothing is uploaded).
- **Licence:** MIT.

---

## Quick start

### Python

```python
import calibration_core as cc

pairs = cc.pairs_from_prediction_records([
    {"confidence": 0.9,  "status": "confirmed"},
    {"confidence": 0.85, "status": "refuted"},
    {"confidence": 0.6,  "status": "confirmed"},
    {"confidence": 0.9,  "status": "pending"},     # not scorable yet — skipped
])
print(cc.score_pairs(pairs))
```

Or from a pasted CSV:

```python
parsed = cc.parse_ledger_text("""
confidence,outcome
0.9,confirmed
0.85,refuted
90%,yes
low,no
0.7,pending
""")
print(parsed["unresolved"])   # 1 — counted, never guessed at
print(cc.score_pairs(parsed["pairs"]))
```

### JavaScript (browser or Node, ES modules)

```js
import { parseLedgerText, scorePairs } from "./js/calibration-core.js";

const { pairs, unresolved, rejected } = parseLedgerText(pastedText);
const scorecard = scorePairs(pairs);
```

---

## The ledger schema

A ledger is a list of forecasts. The only two fields that matter for grading are
**the confidence stated at the time** and **the outcome that was later observed**.
Everything else (date, who said it, the claim text) is for your own reading.

| field | required | accepted values |
| --- | --- | --- |
| `confidence` | yes | a probability `0.0–1.0`; a percentage `"80%"`; a bare number `1 < n ≤ 100` (read as a percentage); or a word: `very low` (0.1), `low` (0.2), `medium`/`med`/`moderate` (0.5), `high` (0.85), `very high` (0.95) |
| `outcome` | yes | **true:** `confirmed`, `confirming`, `1`, `true`, `t`, `y`, `yes`, `hit`, `right`, `correct`, `happened` · **false:** `refuted`, `0`, `false`, `f`, `n`, `no`, `miss`, `wrong`, `incorrect` · **not yet gradable:** `pending`, `open`, `unresolved`, `unknown`, `inconclusive`, `expired`, `tbd`, `n/a`, `na`, `-`, empty |
| `date`, `claim`, `forecaster` | no | free text, carried through, never scored |

**The confidence must be the one stated *before* the outcome was known.** A
confidence assigned after the fact is not a forecast, and the whole exercise is
worthless. This is the one rule the code cannot enforce for you.

Pasted text is parsed as CSV or TSV, with or without a header. Blank lines and
lines starting with `#` are ignored. With no recognised header, field 0 is the
confidence and field 1 is the outcome. Recognised confidence headers:
`confidence`, `conf`, `probability`, `prob`, `p`, `stated_confidence`.
Recognised outcome headers: `outcome`, `result`, `actual`, `y`, `status`, `truth`.

Nothing is defaulted. A row whose confidence cannot be read is **rejected and
reported back** (`parsed["rejected"]`), never scored at 0.5 — a silently-defaulted
number would put a claim on the scorecard that nobody made. A row whose outcome is
not yet known is **counted as unresolved**, not treated as a miss.

---

## The grading rules

Given `n` resolved forecasts with stated probabilities `pᵢ` and outcomes `yᵢ ∈ {0,1}`:

### Brier score

```
brier = mean((pᵢ − yᵢ)²)
```

`0.0` is perfect. **`0.25` is the always-say-50% baseline.** `1.0` is
confidently wrong every single time. Lower is better. Reported rounded to 4dp;
`None`/`null` when nothing has resolved.

### Brier skill score

```
base_rate = mean(yᵢ)
bs_ref    = mean((base_rate − yᵢ)²)
skill     = 1 − brier / bs_ref
```

The honest question: **does the stated confidence beat just guessing the observed
average?** `1.0` perfect, `0.0` no better than the base rate, negative = *worse
than the base rate*. Undefined (`null`) when `n < 2` or when every outcome is
identical (`bs_ref == 0`) — undefined means *unknown*, and is never reported as
unskilled.

### Reliability curve

`[0,1]` is split into `n_bins` equal bands (default 10; the top edge is inclusive
on the last bin, so `p == 1.0` lands in the last bin, not off the end). Each
non-empty band reports `{lo, hi, n, mean_confidence, observed_rate}`. A
well-calibrated forecaster has `mean_confidence ≈ observed_rate` in every band.

### The verdict

Computed from the bin-count-weighted mean gap between stated confidence and
observed rate, and only once `n ≥ 5`:

```
gap = Σ(binₙ × (mean_confidence − observed_rate)) / Σ binₙ
```

| condition | verdict |
| --- | --- |
| `n < 5` or no bins | `insufficient_data` |
| `gap > 0.15` | `over-confident` |
| `gap < −0.15` | `under-confident` |
| otherwise, and `skill ≤ 0` | `not_yet_skillful` |
| otherwise | `well-calibrated` |

**`calibrated` and `skilled` are different claims, and the second one gates the
first.** A forecaster whose stated confidences track observed rates but whose
skill score is ≤ 0 did worse than always guessing the base rate — so no amount of
reliability is allowed to dress that up as "well-calibrated". It reads
`not_yet_skillful` instead, with its `n` and skill shown beside it.

### The credibility label

| condition (first match wins) | label | score |
| --- | --- | --- |
| `n < 3` | `nascent` | 30 |
| `skill ≤ 0` | `not_yet_skillful` | 45 |
| `brier ≤ 0.15` **and** `n ≥ 12` | `authoritative` | 90 |
| `brier ≤ 0.20` | `reliable` | 70 |
| otherwise | `developing` | 50 |

A skill ≤ 0 forecaster can never reach the flattering rungs, however low its
Brier score happens to be.

### Reproducing a scorecard by hand

Everything above is arithmetic on two columns. To check this library rather than
trust it: take the `worked_example.json` in `demo/`, compute `mean((p−y)²)`
yourself in a spreadsheet, and compare with the `expected_scorecard` block
committed alongside it. If they disagree, the library is wrong — open an issue.

---

## Output shape

`score_pairs()` / `scorePairs()` return exactly:

```jsonc
{
  "n": 31,                       // resolved forecasts scored
  "confirmed": 16,
  "refuted": 15,
  "accuracy_pct": 51.6,          // hit rate — the number that flatters; read it last
  "brier": 0.2801,               // null when nothing has resolved
  "brier_skill": -0.1215,        // null when undefined, never 0
  "skilled": false,              // true / false / null(unknown)
  "reliability_bins": [ { "lo": 0.3, "hi": 0.4, "n": 2,
                          "mean_confidence": 0.325, "observed_rate": 0.5 } ],
  "calibration": "over-confident",
  "label": "not_yet_skillful",
  "score": 45
}
```

(Those are the real numbers for `demo/worked_example.json`.)

---

## The demo datasets

`demo/` ships two files, and the difference between them is the point.

### `matthew_public_ledger.json` — real, and honestly empty

A verbatim snapshot of the **already-public** `/api/predictions` payload from
averagejoematt.com: 102 forward calls made by eight named AI coaches, each with
the confidence it stated. Provenance (endpoint URL, fetch timestamp, experiment
cycle) is in the file.

It was captured on **day 1 of experiment cycle 11**, so *every call in it is still
pending* — none has come due. Scoring it reports `n = 0` and
`insufficient_data`. That is the correct answer, not a broken one, and it is
shipped that way deliberately: an honest calibration tool has to be able to say
"nothing to grade yet".

The file also carries a `published_scorecard` block — what the site's own
calibration page was publishing at that moment, season and career — produced by
the same grader this package extracts. The career numbers cover forecasts from
earlier experiment cycles whose individual rows are not public, which is why they
cannot be recomputed from `rows` here.

### `worked_example.json` — synthetic, and explicitly labelled so

32 hand-written calls from a fictional wearable's LLM advisor. It exists purely so
a first-time reader sees a filled-in scorecard. `provenance.synthetic` is `true`
and its `why` field says so in plain English. It is not anyone's real coach and
not anyone's real data.

It also happens to be the failure mode worth understanding: **over-confident and
`not_yet_skillful`** — high stated confidence, and a skill score below zero, i.e.
worse than having just predicted the base rate every time. A hit rate of 51.6%
looks survivable until you notice the confidences attached to it.

---

## Parity — why you can trust that this is the same code

An extraction that is allowed to drift is worse than no extraction: you would be
grading your coach with a scorer that no longer matches the one the site
publishes, while the site still claims otherwise.

So `vectors/calibration_vectors.json` is a shared fixture that **three**
implementations must reproduce **exactly** — not within a tolerance:

1. the deployed platform grader (`lambdas/calibration_core.py` in the source
   repo) — the authority the fixture is generated *from*;
2. this package (`src/calibration_core.py`);
3. the browser port (`js/calibration-core.js`), which is vendored byte-for-byte
   into the site that hosts the paste tool.

`core_cases`, `confidence_cases`, `outcome_cases` and `record_cases` are the
three-way surface. `adapter_cases` (the paste-a-ledger parser and the rounding
helper) are two-way, Python ↔ JS, because the platform reads structured records
from a database and never parses free text.

**The rounding trap.** Python's `round(x, n)` is round-half-to-**even** on the
exact binary value of the double. JavaScript has no equivalent: `Math.round` is
half-up and `toFixed` rounds the shortest decimal representation, so both
disagree with Python on values like `2.675` (whose double is really
`2.67499999999999982`). The JS port therefore implements CPython's rounding
exactly, with BigInt rational arithmetic, rather than pretending the difference
does not exist. `pyRound` is the load-bearing 30 lines in that file, and
`adapter_cases.round_cases` pins it.

Run the parity suites:

```bash
python3 -m pytest tests/ -v        # Python vs. the fixture
node --test                       # JS vs. the same fixture (run from this directory)
```

---

## Layout

```
calibration-core/
├── README.md
├── LICENSE                              MIT (a carve-out; see the scope note)
├── pyproject.toml                       no runtime dependencies, by design
├── src/calibration_core.py              the package — one flat, vendorable file
├── js/calibration-core.js               the browser port — same numbers, ES module
├── vectors/calibration_vectors.json     the shared parity fixture
├── demo/matthew_public_ledger.json      real, public, provenance-stamped
├── demo/worked_example.json             synthetic, labelled, for the walkthrough
└── tests/
    ├── test_calibration_core.py         pytest — Python vs. the fixture
    └── calibration-core.test.mjs        node:test — JS vs. the same fixture
```

## API

| Python | JavaScript | what it does |
| --- | --- | --- |
| `score_pairs(pairs, n_bins=10)` | `scorePairs(pairs, nBins=10)` | the whole scorecard |
| `brier_score(pairs)` | `brierScore(pairs)` | mean squared error, unrounded |
| `brier_skill_score(pairs)` | `brierSkillScore(pairs)` | skill vs. the base rate, unrounded |
| `reliability_bins(pairs, n_bins=10)` | `reliabilityBins(pairs, nBins=10)` | the calibration curve, unrounded |
| `normalize_confidence(value)` | `normalizeConfidence(value)` | number / `"40%"` / word → `[0,1]` |
| `outcome_to_binary(status)` | `outcomeToBinary(status)` | `confirmed`→1, `refuted`→0, else `None` |
| `clean_pairs(pairs)` | `cleanPairs(pairs)` | drop malformed entries, never coerce them |
| `parse_ledger_text(text)` | `parseLedgerText(text)` | CSV/TSV paste → pairs + rejects + unresolved |
| `pairs_from_prediction_records(records)` | `pairsFromPredictionRecords(records)` | extract from `{confidence, status}` records |
| `pairs_from_calibration_rows(rows)` | `pairsFromCalibrationRows(rows)` | extract from `{stated_confidence, outcome}` rows |
| `pairs_from_forecast_resolution_rows(rows)` | `pairsFromForecastResolutionRows(rows)` | extract interval-coverage rows (`covered`) |
| — | `pyRound(x, nd)` | CPython-exact rounding (the parity primitive) |

## Design notes

- **No I/O.** Nothing here reads a file, opens a socket, or calls a model. You
  fetch your own records; this scores them.
- **Nothing is fabricated.** Unresolved forecasts are excluded from the Brier
  score rather than guessed at. Undefined skill is `null`, not `0`. An empty
  ledger reports `None` everywhere, not a flattering zero.
- **`accuracy_pct` is deliberately not the headline.** Hit rate rewards
  forecasting only the things you were already sure of. Brier and skill do not.
