"""
bedrock_batch.py — batch-inference path at the single Claude chokepoint (#409, #4777).

Companion to `bedrock_client.invoke()` (the real-time path, ADR-062). AWS Bedrock
prices batch inference (`CreateModelInvocationJob`) at ~50% of on-demand for the
same Claude models — the right shape for deferrable bulk work.

**Who qualifies (ADR-132, amended 2026-10-11 for #4777).** Bedrock enforces a hard
floor of **100 records per batch job, per model**. Scheduled daily content never
reaches it (~62 calls/day across every producer and model, 2026-07), and batch
completes in "up to 24h", which no deadline-bound producer can wait on. The class
that does clear the floor is the episodic BULK job — a rebuild or a backfill of
100+ independent records in one run (the Hevy training-notes backfill, reading
enrichment re-runs, a Story Desk/season rebuild if it can be expressed as one job
of independent records). The trip-wire therefore counts records PER JOB as well as
calls per day.

**The adopter's contract** is `run_or_fallback(records, model, realtime_fn)`:

  * below the floor, at budget tier 3, or when the caller asks for real-time, every
    record runs through `realtime_fn` — identical to not adopting batch — and the
    returned `reason` says why, for the caller to print;
  * at/above the floor it stages the JSONL under the PRIVATE `bedrock-batch/` prefix
    (never `generated/`, which is anonymously readable at the S3 origin — #3559),
    submits the job with the `life-platform-bedrock-batch` service role
    (LifePlatformCore), polls to a deadline, and maps results back BY `recordId`
    (Bedrock returns them unordered). Any record the job did not answer, or answered
    with an error, and every record if the job fails or misses the deadline, falls
    back to `realtime_fn` — a batch problem never drops a record;
  * the cheaper path skips no gate: the tier-3 stop and the dev-session cap (on the
    job's projected upper-bound cost, before anything is sent) run first, each
    batch record is metered at the batch price through the same telemetry the
    real-time path emits, and the caller's deterministic gates run on the returned
    results exactly as they would on a real-time result.

Each record is the same Messages body the real-time path would send
(`_prepare_model_input` mirrors `invoke()`). Batch and prompt caching do not combine
on Bedrock, so a cached-prefix workload gains less than 50% here.

IAM: the service role is CDK-owned (`cdk/stacks/core_stack.py`). The CALLER needs
`bedrock:CreateModelInvocationJob`/`GetModelInvocationJob`/`StopModelInvocationJob`,
`iam:PassRole` on that role and S3 read/write/delete on the prefix — the operator's
own credentials for a laptop rebuild. No Lambda role is granted batch rights: no
Lambda calls this path yet.

Adopters: `scripts/season_rebuild.py --recheck` (the season's fact-read sweep, #4777).
"""

import json
import os
import time
import uuid

import boto3

from ai.bedrock_client import _ADAPTIVE_SURFACE_MARKERS, _PRICES, _price_for, estimate_cost_usd, resolve_model_id

# Bedrock hard floor — "Minimum number of records per batch inference job" is 100
# for every current Claude model (Haiku 4.5, Sonnet 4.6, Opus 4.x). Verified via
# `aws service-quotas list-service-quotas --service-code bedrock`. Not adjustable
# downward. Submitting fewer records fails the CreateModelInvocationJob call.
MIN_RECORDS_PER_JOB = 100

# Batch is discounted to ~50% of on-demand token pricing (AWS Bedrock pricing).
BATCH_DISCOUNT = 0.50

# Terminal + in-flight job states from GetModelInvocationJob.
_TERMINAL_STATES = {"Completed", "Failed", "Stopped", "Expired", "PartiallyCompleted"}
_SUCCESS_STATES = {"Completed", "PartiallyCompleted"}

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")

# Where batch input/output is staged (#4777). Private: the bucket policy grants
# anonymous GetObject on exactly these prefixes (`deploy/bucket_policy.json`'s
# PublicRead* statements — pinned by tests/test_bedrock_batch.py), and a prompt
# carries the owner's health data, so the batch prefix may never sit under one.
BATCH_BUCKET = os.environ.get("BEDROCK_BATCH_BUCKET", "matthew-life-platform")
BATCH_PREFIX = "bedrock-batch/"
PUBLIC_PREFIXES = ("site/", "blog/", "generated/")

# The Bedrock batch service role (CDK: LifePlatformCore, `BedrockBatchServiceRole`).
BATCH_ROLE_NAME = "life-platform-bedrock-batch"

# How long run_or_fallback waits on a job before falling back to real-time.
# Bedrock's own SLA is "up to 24h"; a bulk rebuild is deferrable by definition.
DEFAULT_WAIT_SECONDS = 24 * 3600

_BEDROCK_CTRL = None


def _ctrl():
    """Lazy-init the Bedrock *control-plane* client (batch jobs live here, not on
    bedrock-runtime where invoke_model lives)."""
    global _BEDROCK_CTRL
    if _BEDROCK_CTRL is None:
        _BEDROCK_CTRL = boto3.client("bedrock", region_name=BEDROCK_REGION)
    return _BEDROCK_CTRL


def _prepare_model_input(body: dict, model_id: str) -> dict:
    """Turn a real-time Messages `body` into a batch `modelInput` — byte-identical
    to what `bedrock_client.invoke()` would send to invoke_model.

    Strips the routing-only `model` key, scrubs sampling params the adaptive
    surfaces (Fable / Opus 4.7+) reject, and stamps the required anthropic_version.
    Keeping this in lockstep with invoke() is what guarantees a batched record and
    a real-time record produce the same generation (AC: the cheaper path skips
    nothing).
    """
    prepared = {k: v for k, v in body.items() if k != "model"}
    if any(marker in model_id.lower() for marker in _ADAPTIVE_SURFACE_MARKERS):
        for param in ("temperature", "top_p", "top_k"):
            prepared.pop(param, None)
        if "fable" in model_id.lower() and (prepared.get("thinking") or {}).get("type") == "disabled":
            prepared.pop("thinking", None)
    prepared["anthropic_version"] = "bedrock-2023-05-31"
    return prepared


def build_jsonl_record(record_id: str, body: dict, model_name: str | None = None) -> dict:
    """One line of a batch input JSONL: {"recordId", "modelInput"}.

    `record_id` must be unique within the job (Bedrock returns results unordered,
    keyed by recordId — the caller reassembles by it).
    """
    model_id = resolve_model_id(model_name or body.get("model"))
    return {"recordId": record_id, "modelInput": _prepare_model_input(body, model_id)}


def batch_preflight(record_count: int, model_name: str | None = None) -> tuple[bool, str]:
    """The gate every batch adopter calls first. Returns (eligible, reason).

    Not eligible below the 100-record floor, or when the budget is at tier-3
    (AI paused) — in both cases the caller uses the real-time path. Scheduled daily
    producers never clear the floor; a bulk rebuild/backfill job can (ADR-132 as
    amended for #4777).
    """
    if record_count < MIN_RECORDS_PER_JOB:
        return (
            False,
            f"{record_count} records < {MIN_RECORDS_PER_JOB}-record Bedrock batch floor " f"for a single model — use the real-time path",
        )
    # Tier-3 hard stop mirrors bedrock_client.invoke(): never spend when paused.
    try:
        from ai.budget_guard import current_tier

        if current_tier() >= 3:
            return (False, "budget tier 3 — AI paused; not submitting a batch job")
    except ImportError:
        pass
    _ = resolve_model_id(model_name)  # validate the model resolves
    return (True, f"{record_count} records ≥ floor — batch eligible")


def estimate_batch_savings(usage_by_record: list[dict], model_name: str | None = None) -> dict:
    """Projected on-demand vs batch cost for a set of records, from their usage
    dicts (same shape bedrock_client meters). Pure — unit-testable without AWS.

    Returns {on_demand_usd, batch_usd, saved_usd, discount}. batch_usd is
    on-demand × (1 - BATCH_DISCOUNT); the token counts are identical, only the
    per-token price halves.
    """
    model_id = resolve_model_id(model_name)
    on_demand = sum(estimate_cost_usd(u or {}, model_id) for u in usage_by_record)
    batch = on_demand * (1.0 - BATCH_DISCOUNT)
    return {
        "on_demand_usd": round(on_demand, 6),
        "batch_usd": round(batch, 6),
        "saved_usd": round(on_demand - batch, 6),
        "discount": BATCH_DISCOUNT,
    }


def submit_batch(
    records: list[dict],
    model_name: str,
    input_s3_uri: str,
    output_s3_uri: str,
    role_arn: str,
    job_name: str | None = None,
) -> str:
    """Write the JSONL, create the model-invocation job, return its jobArn.

    `records` are `build_jsonl_record` dicts. Raises ValueError below the floor so
    a mis-wired caller can never submit an under-minimum job (Bedrock would reject
    it anyway; failing here is clearer and free). Callers should gate on
    `batch_preflight()` first — this is belt-and-suspenders.

    The input key must sit under the private `bedrock-batch/` prefix.
    """
    eligible, reason = batch_preflight(len(records), model_name)
    if not eligible:
        raise ValueError(f"refusing to submit batch job: {reason}")

    bucket, _, key_prefix = input_s3_uri.replace("s3://", "").partition("/")
    assert_private_prefix(key_prefix)
    assert_private_prefix(output_s3_uri.replace("s3://", "").partition("/")[2])
    jsonl = "\n".join(json.dumps(r) for r in records)
    boto3.client("s3", region_name=BEDROCK_REGION).put_object(Bucket=bucket, Key=key_prefix, Body=jsonl.encode("utf-8"))

    resp = _ctrl().create_model_invocation_job(
        jobName=job_name or f"content-batch-{uuid.uuid4().hex[:12]}",
        roleArn=role_arn,
        modelId=resolve_model_id(model_name),
        inputDataConfig={"s3InputDataConfig": {"s3Uri": input_s3_uri}},
        outputDataConfig={"s3OutputDataConfig": {"s3Uri": output_s3_uri}},
    )
    return resp["jobArn"]


def poll_batch(job_arn: str) -> dict:
    """One GetModelInvocationJob snapshot → {status, done, succeeded, message}."""
    job = _ctrl().get_model_invocation_job(jobIdentifier=job_arn)
    status = job.get("status", "Unknown")
    return {
        "status": status,
        "done": status in _TERMINAL_STATES,
        "succeeded": status in _SUCCESS_STATES,
        "message": job.get("message", ""),
    }


def wait_for_batch(job_arn: str, deadline_epoch: float, poll_interval: float = 60.0) -> dict:
    """Poll until the job is terminal or `deadline_epoch` passes.

    Returns the final `poll_batch` dict; `done=False` means the deadline hit first
    (the caller must then run the real-time fallback — an overnight batch that
    misses the 11 AM brief cannot block the brief). `deadline_epoch` is a
    time.time() value so callers keep the deadline in one place.
    """
    while time.time() < deadline_epoch:
        snap = poll_batch(job_arn)
        if snap["done"]:
            return snap
        remaining = deadline_epoch - time.time()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))
    snap = poll_batch(job_arn)
    if snap["done"]:
        return snap
    return {"status": snap["status"], "done": False, "succeeded": False, "message": "deadline exceeded before batch completed"}


def assert_private_prefix(key_or_prefix: str) -> None:
    """Refuse any staging key that would land under an anonymously readable prefix."""
    k = (key_or_prefix or "").lstrip("/")
    for pub in PUBLIC_PREFIXES:
        if k.startswith(pub):
            raise ValueError(f"refusing to stage batch data under the public prefix {pub!r} ({k!r}) — use {BATCH_PREFIX!r}")
    if not k.startswith(BATCH_PREFIX):
        raise ValueError(f"batch staging key {k!r} is outside the private {BATCH_PREFIX!r} prefix")


def batch_role_arn() -> str:
    """The service role's ARN: `BEDROCK_BATCH_ROLE_ARN`, else built from the caller's account."""
    explicit = (os.environ.get("BEDROCK_BATCH_ROLE_ARN") or "").strip()
    if explicit:
        return explicit
    acct = boto3.client("sts", region_name=BEDROCK_REGION).get_caller_identity()["Account"]
    return f"arn:aws:iam::{acct}:role/{BATCH_ROLE_NAME}"


def job_uris(job_tag: str, bucket: str | None = None) -> tuple[str, str]:
    """(input_s3_uri, output_s3_uri) for one job, both under the private prefix."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in job_tag)[:63] or uuid.uuid4().hex[:12]
    in_key = f"{BATCH_PREFIX}{safe}/input.jsonl"
    out_key = f"{BATCH_PREFIX}{safe}/output/"
    assert_private_prefix(in_key)
    assert_private_prefix(out_key)
    b = bucket or BATCH_BUCKET
    return f"s3://{b}/{in_key}", f"s3://{b}/{out_key}"


def projected_batch_usd(records: list[dict], model_name: str | None = None) -> float:
    """An UPPER-BOUND batch cost for a set of records, before anything is sent.

    Input tokens are over-estimated at one per three characters of the serialized
    modelInput; output at the full `max_tokens`. Priced at the batch rate. Used by the
    dev-session cap, which must refuse a job before it can bill, not after.
    """
    model_id = resolve_model_id(model_name)
    p = _price_for(model_id)
    total = 0.0
    for r in records:
        mi = r.get("modelInput") or {}
        in_tok = len(json.dumps(mi, default=str)) / 3.0
        out_tok = float(mi.get("max_tokens") or 0)
        total += (in_tok * p["in"] + out_tok * p["out"]) / 1_000_000.0
    return total * (1.0 - BATCH_DISCOUNT)


def _job_id(job_arn: str) -> str:
    return job_arn.rsplit("/", 1)[-1]


def parse_output_jsonl(text: str) -> tuple[dict, dict]:
    """A job's output JSONL → ({recordId: modelOutput}, {recordId: error}).

    Bedrock writes one line per record, unordered: `{recordId, modelInput, modelOutput}`
    on success, `{recordId, modelInput, error: {errorCode, errorMessage}}` on a
    per-record failure. A line with neither is treated as an error, never a result.
    """
    outputs: dict = {}
    errors: dict = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        rid = rec.get("recordId")
        if rid is None:
            continue
        if rec.get("error") or not isinstance(rec.get("modelOutput"), dict):
            errors[rid] = rec.get("error") or {"errorMessage": "no modelOutput in the batch output line"}
        else:
            outputs[rid] = rec["modelOutput"]
    return outputs, errors


def retrieve_job_output(output_s3_uri: str, job_arn: str, input_filename: str = "input.jsonl") -> tuple[dict, dict]:
    """Read a finished job's output. Bedrock writes it to
    `<output_uri>/<job id>/<input file name>.out`."""
    return _read_output(output_s3_uri, f"{_job_id(job_arn)}/{input_filename}.out")


def _read_output(output_s3_uri: str, manifest_key: str) -> tuple[dict, dict]:
    bucket, _, key = output_s3_uri.replace("s3://", "").partition("/")
    full = f"{key.rstrip('/')}/{manifest_key}"
    assert_private_prefix(full)
    obj = boto3.client("s3", region_name=BEDROCK_REGION).get_object(Bucket=bucket, Key=full)
    return parse_output_jsonl(obj["Body"].read().decode("utf-8"))


def _cleanup(input_s3_uri: str, output_s3_uri: str, log) -> None:
    """Best-effort: delete this job's staged prompts and outputs (they carry health data)."""
    try:
        s3 = boto3.client("s3", region_name=BEDROCK_REGION)
        bucket, _, in_key = input_s3_uri.replace("s3://", "").partition("/")
        _, _, out_prefix = output_s3_uri.replace("s3://", "").partition("/")
        keys = [in_key]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=out_prefix):
            keys += [o["Key"] for o in page.get("Contents") or []]
        for k in keys:
            assert_private_prefix(k)
            s3.delete_object(Bucket=bucket, Key=k)
    except Exception as e:  # noqa: BLE001 — cleanup never fails a run whose results are in hand
        log(f"[batch] cleanup of {input_s3_uri} failed ({type(e).__name__}: {e}); delete the job's {BATCH_PREFIX} objects by hand")


def _meter_batch_record(usage: dict, model_id: str) -> None:
    """Meter one batch record exactly as invoke() meters a real-time one, at the batch price."""
    from ai import bedrock_client as _bc

    _bc._emit_usage_metrics(usage or {}, model_id, cost_scale=1.0 - BATCH_DISCOUNT)
    try:
        from ai import dev_session_cap

        dev_session_cap.record(_bc.caller_class(), estimate_cost_usd(usage or {}, model_id) * (1.0 - BATCH_DISCOUNT))
    except Exception:  # noqa: BLE001 — metering never breaks a result already in hand
        pass


def _dev_cap_projected(records: list[dict], model_name: str) -> None:
    """The dev-session cap on the whole job's upper-bound cost. Raises a BudgetExceeded."""
    try:
        from ai import bedrock_client as _bc, dev_session_cap
    except ImportError:
        return
    dev_session_cap.check_projected(_bc.caller_class(), projected_batch_usd(records, model_name), _bc._cw)


def run_or_fallback(
    records: list[dict],
    model_name: str,
    realtime_fn,
    *,
    batch_result_fn=None,
    force_realtime: bool = False,
    deadline_epoch: float | None = None,
    poll_interval: float = 60.0,
    bucket: str | None = None,
    role_arn: str | None = None,
    job_name: str | None = None,
    cleanup: bool = True,
    log=print,
) -> dict:
    """Batch when the job clears the floor, real-time otherwise — the one adopter API.

    `records` are `build_jsonl_record` dicts with unique recordIds.
    `realtime_fn(model_input) -> result` runs one record on the real-time path.
    `batch_result_fn(model_output) -> result` turns a batch record's raw Messages
    response into the SAME shape `realtime_fn` returns (default: the raw response,
    which is what `bedrock_client.invoke` returns — so `realtime_fn=invoke`-style
    callers need no adapter).

    Returns {mode, reason, results, job_arn, batch_records, realtime_records,
    realtime_record_ids, savings}. `results` is in `records` order. `mode` is
    "realtime" (never submitted), "batch" (every record answered by the job) or
    "batch+realtime" (the job ran but some or all records fell back). `reason` is a
    sentence the caller should print — the operator is told which path ran and why.
    """
    batch_result_fn = batch_result_fn or (lambda out: out)
    ids = [r.get("recordId") for r in records]
    if len(set(ids)) != len(ids) or any(i is None for i in ids):
        raise ValueError("run_or_fallback needs a unique recordId on every record (results are mapped back by it)")

    def _realtime_all(reason: str) -> dict:
        results = [realtime_fn(r["modelInput"]) for r in records]
        return {
            "mode": "realtime",
            "reason": reason,
            "results": results,
            "job_arn": None,
            "batch_records": 0,
            "realtime_records": len(records),
            "realtime_record_ids": list(ids),
            "savings": None,
        }

    if force_realtime:
        return _realtime_all(f"{len(records)} records — real-time requested by the caller")
    eligible, reason = batch_preflight(len(records), model_name)
    if not eligible:
        return _realtime_all(f"{reason} (ran on-demand)")

    _dev_cap_projected(records, model_name)  # refuses before anything is staged or billed

    model_id = resolve_model_id(model_name)
    tag = job_name or f"batch-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:6]}"
    in_uri, out_uri = job_uris(tag, bucket)
    job_arn = submit_batch(records, model_name, in_uri, out_uri, role_arn or batch_role_arn(), job_name=_job_name(tag))
    log(f"[batch] submitted {job_arn} — {len(records)} records on {model_id}, staged at {in_uri}")

    deadline = deadline_epoch if deadline_epoch is not None else time.time() + DEFAULT_WAIT_SECONDS
    outputs: dict = {}
    errors: dict = {}
    try:
        snap = wait_for_batch(job_arn, deadline, poll_interval=poll_interval)
    except Exception as e:  # noqa: BLE001 — a throttled/failed poll must not strand a billing job or drop records (#4797)
        log(f"[batch] waiting on {job_arn} raised {type(e).__name__}: {e}; stopping it and running on-demand")
        snap = {"status": f"WaitError:{type(e).__name__}", "done": False, "succeeded": False, "message": str(e), "wait_error": True}
    if not snap["done"]:
        try:
            _ctrl().stop_model_invocation_job(jobIdentifier=job_arn)
        except Exception as e:  # noqa: BLE001 — a failed stop leaves a job that bills at most once
            log(f"[batch] could not stop {job_arn} after the deadline ({type(e).__name__}); it may still complete and bill")
        if snap.get("wait_error"):
            why = f"batch job {job_arn} wait failed ({snap['status']}); every record re-ran on-demand"
        else:
            why = f"batch job {job_arn} missed its deadline ({snap['status']}); every record re-ran on-demand"
    elif not snap["succeeded"]:
        why = f"batch job {job_arn} ended {snap['status']} ({snap.get('message') or 'no message'}); every record re-ran on-demand"
    else:
        try:
            outputs, errors = retrieve_job_output(out_uri, job_arn)
        except Exception as e:  # noqa: BLE001 — an unreadable output falls back, never drops records
            log(f"[batch] could not read the output of {job_arn} ({type(e).__name__}: {e})")
        why = f"batch job {job_arn} {snap['status']}"

    results: list = []
    fallback_ids: list = []
    batch_usage: list = []
    for r in records:
        rid = r["recordId"]
        out = outputs.get(rid)
        if out is not None:
            _meter_batch_record(out.get("usage") or {}, model_id)
            batch_usage.append(out.get("usage") or {})
            results.append(batch_result_fn(out))
        else:
            fallback_ids.append(rid)
            results.append(realtime_fn(r["modelInput"]))
    if errors:
        log(f"[batch] {len(errors)} record(s) errored in {job_arn}; they re-ran on-demand")
    if cleanup:
        _cleanup(in_uri, out_uri, log)
    n_batch = len(records) - len(fallback_ids)
    reason = f"{why}: {n_batch} of {len(records)} records answered by batch, {len(fallback_ids)} on-demand"
    return {
        "mode": "batch" if not fallback_ids else "batch+realtime",
        "reason": reason,
        "results": results,
        "job_arn": job_arn,
        "batch_records": n_batch,
        "realtime_records": len(fallback_ids),
        "realtime_record_ids": fallback_ids,
        "savings": estimate_batch_savings(batch_usage, model_name) if batch_usage else None,
    }


def _job_name(tag: str) -> str:
    """Bedrock job names allow [a-zA-Z0-9-+] up to 63 chars; keep the staging tag recognisable."""
    return ("".join(c if (c.isalnum() or c in "-+") else "-" for c in tag) or "content-batch")[:63]


# Re-export for callers/tests that want the price table without importing two modules.
PRICES = _PRICES
