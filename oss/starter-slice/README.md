# starter-slice

**One source, one bucket, one table, one chart.** The smallest honest version of
the pipeline behind [averagejoematt.com](https://averagejoematt.com) — a public
weather API into object storage, normalized into a key-value table, read back out
and rendered as a chart you can open in a browser.

Fork the architecture, not the data. The full manifest of what that architecture
reads, runs and costs is published at
[`/data/stack.json`](https://averagejoematt.com/data/stack.json)
([field reference](https://averagejoematt.com/data/stack.schema.json)).

- **Runs with no AWS account and no money:** `--local` is the same pipeline with
  the network storage swapped for a directory.
- **No dependencies.** Standard library only. `boto3` is imported lazily and only
  the AWS backend needs it.
- **No personal data.** The source is a public weather archive with no key, no
  account and nothing to consent to.
- **Licence:** MIT.

---

## Quick start (free, offline after the first fetch)

```bash
python3 run.py ingest --local     # fetch 14 settled days, write raw + normalized
python3 run.py chart  --local     # read the table back, write out/chart.html
open out/chart.html               # or xdg-open / start
```

That is the whole loop. Look at what it left behind:

```
.slice-data/
  raw/demo/weather/2026/08/2026-08-01.json    the API response, unmodified
  table/USER_demo_SOURCE_weather.json         one normalized row per day
out/chart.html                                 self-contained, no JS, light + dark
```

The keys under `.slice-data/raw/` are **character-for-character the S3 keys** the
AWS backend writes. Local mode is not a toy mode; it is the same pipeline with the
bill removed.

## The same thing on real AWS

This part costs money and needs credentials. Read the cost section first.

```bash
aws cloudformation deploy --stack-name starter-slice --template-file infrastructure.yaml
aws cloudformation describe-stacks --stack-name starter-slice \
  --query 'Stacks[0].Outputs' --output table

export SLICE_BUCKET=<BucketName from the outputs>
export SLICE_TABLE=<TableName from the outputs>

python3 run.py ingest              # note: no --local
python3 run.py chart
```

Tear it down when you are done — **empty the bucket first**, CloudFormation will
not delete a bucket with objects in it:

```bash
aws s3 rm "s3://$SLICE_BUCKET" --recursive
aws cloudformation delete-stack --stack-name starter-slice
```

## Configuration

| variable | default | what it does |
| --- | --- | --- |
| `SLICE_USER_ID` | `demo` | the owner segment in every key — `USER#demo#SOURCE#weather` |
| `SLICE_LAT` / `SLICE_LON` | `51.4779` / `-0.0015` | where to read the weather (the default is the Greenwich meridian, deliberately not anybody's house) |
| `SLICE_BUCKET` | *none* | raw-object bucket. No default on purpose: a pipeline that invents a bucket name writes somewhere you did not intend |
| `SLICE_TABLE` | *none* | DynamoDB table |
| `SLICE_LOCAL_ROOT` | `.slice-data` | where `--local` keeps everything |

## How it is put together

```
run.py                     the CLI: ingest / chart / cost
starter_slice/config.py    key construction — the ONE place a key shape is decided
starter_slice/source.py    the API call and the normalizer (two separable jobs)
starter_slice/store.py     LocalStore and AwsStore behind one interface
starter_slice/pipeline.py  the loop: fetch -> raw -> normalize -> table -> chart
starter_slice/chart.py     inline SVG, no chart library, no JavaScript
infrastructure.yaml        the bucket and the table, as CloudFormation
tests/test_slice.py        run `python3 -m pytest tests/` — no network, no AWS
```

Four habits are baked in because they are the ones that hurt to learn later:

1. **Raw is written before normalization and never edited.** When you later want a
   field you did not think to keep, the raw object is the only thing that can give
   it to you. A normalizer is re-runnable; a lost API response is not.
2. **A missing reading is dropped, never zero-filled.** Once an invented zero is in
   the table it is indistinguishable from a measured one.
3. **Floats never reach DynamoDB.** They go through `Decimal(str(value))` — and via
   the *string* form, because `Decimal(0.1)` carries binary float noise.
4. **Keys are constructed in exactly one place.** `config.py` owns the shape of
   every S3 key and every table key. When the shape has three owners it grows three
   variants, and then nothing can read the whole history.

## What this is NOT

An honest teaching slice has to say what it left out. This is roughly 300 lines
against a platform of about a hundred Lambdas, and it deliberately omits:

- **Scheduling.** You run it by hand. The real thing runs on EventBridge crons
  pinned to UTC so daylight saving cannot move them.
- **Credentialed sources.** Every interesting health source needs OAuth, token
  refresh, and a re-authorization path for when a provider quietly kills your
  token. That machinery is most of the real ingestion code.
- **Gap-aware backfill.** This fetches a fixed window every time. The real
  ingesters detect which days are missing and fetch only those.
- **Retries and rate limits.** One request, one attempt, no backoff.
- **Any AI.** No inference, no budget governor, no quality gate.
- **Deployment, monitoring, alarms, tests-as-gates, cost governance** — the parts
  that turn a script into something you can leave running.

If you want to see what the full shape looks like before you build toward it, the
manifest above enumerates every source, protocol and cost figure.

## What it costs

<!-- BEGIN GENERATED: cost (scripts/build_starter_slice_cost.py) -->

**What this slice costs you.** Not asserted. This template has never been billed in a third party's account, and the answer depends on region, request volume and how long you leave it running -- any figure printed here would be a guess wearing a decimal point. What IS knowable is the billed set below: storage measured in kilobytes and roughly thirty on-demand writes a day, with no compute, no schedule and no AI inference. Read your own AWS bill after a week; that is the only number that will be true for you.

| billed by this template | free |
| --- | --- |
| S3 (PutObject + a few KB stored)<br>DynamoDB on-demand (a handful of writes and one query per run) | Open-Meteo (no key, no account, no bill)<br>the local backend (--local touches no AWS service at all) |

**What the full platform costs**, for scale — these figures are read from its published manifest,
[`cost_of_ownership`](https://averagejoematt.com/data/stack.json), not restated here:

| | |
| --- | --- |
| typical run-rate | ~$80 / month |
| self-imposed ceiling | $85 / month (floats to $100 under reader-traffic surge) |
| non-AI floor | $36-$43 / month |
| AI, variable | $24-$44 / month |
| billed actuals | Mar 2026 $20.04, Apr 2026 $35.01, May 2026 $48.19, Jun 2026 $79.80 |

_One budget covers the WHOLE platform, not just the AI. CI minutes are billed by the code host on a separate plan and are not inside this figure._

_ADR-104/105. Every figure carries a `basis` saying how it was derived and a `confidence` saying how much weight it holds. Where no source exists the value is null with a basis explaining why, never a plausible-looking guess._

<!-- END GENERATED: cost -->

`python3 run.py cost` prints the same figures from `cost_note.json`.

## Provenance

Extracted from the `life-platform` repository, where it lives at
`oss/starter-slice/` and is held to its claims by `tests/test_starter_slice.py`
(no personal data, no imports back into the platform, and the cost figures above
in sync with the published manifest).
