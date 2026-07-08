"""
bedrock_batch.py — batch-inference seam at the single Claude chokepoint (#409).

Companion to `bedrock_client.invoke()` (the real-time path, ADR-062). AWS Bedrock
prices batch inference (`CreateModelInvocationJob`) at ~50% of on-demand for the
same Claude models — exactly the right shape for scheduled, non-latency-sensitive
content generation.

**Why this module is a *latent* capability, not a live path (ADR-132).**
Bedrock enforces a hard floor of **100 records per batch job, per model** (AWS
Service Quotas: "Minimum number of records per batch inference job" = 100 for
Claude Haiku 4.5 / Sonnet 4.6 — the two models our scheduled content uses).
Measured production volume (30d CloudWatch `LifePlatform/AI` SampleCount, 2026-07)
is ~62 model calls/day across ALL scheduled producers *combined and mixed across
models* — the single largest producer is ~19.5/day. No producer, and not even the
whole fleet's daily output for one model, reaches the 100-record floor; and batch
completion is "up to 24h" with no faster SLA, which conflicts with the
overnight→11 AM daily-brief deadline. So a batch job cannot honestly be submitted
at today's volume.

This module therefore ships the *mechanism* (submit / poll / retrieve + the
eligibility floor + the 50%-savings estimate), fully tested, but wires into no
producer. Its load-bearing part today is `batch_preflight()`: the gate that any
future adopter calls first and that, at current volume, returns "use real-time."
`run_or_fallback()` makes that fallback a first-class, tested behavior. When a
single-model scheduled volume crosses the floor (see `scripts/batch_feasibility.py`
for the live trip-wire check), a producer adopts `run_or_fallback()` and the batch
path lights up — respecting every budget tier and quality gate identically, because
each record is the same Messages body the real-time path would have sent.

No new IAM is granted by this change (nothing calls the submit path). Enabling
batch requires the grants documented in ADR-132 (a Bedrock batch service role with
`s3:GetObject`/`PutObject` on the batch prefix, plus `bedrock:CreateModelInvocationJob`
+ `iam:PassRole` on the caller) — added deliberately at enablement, not speculatively.
"""

import json
import os
import time
import uuid

import boto3
from bedrock_client import _ADAPTIVE_SURFACE_MARKERS, _PRICES, estimate_cost_usd, resolve_model_id

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
    (AI paused) — in both cases the caller uses the real-time path. This is the
    load-bearing decision today: at current production volume it always returns
    (False, "<n> records < 100-record Bedrock floor …").
    """
    if record_count < MIN_RECORDS_PER_JOB:
        return (
            False,
            f"{record_count} records < {MIN_RECORDS_PER_JOB}-record Bedrock batch floor " f"for a single model — use the real-time path",
        )
    # Tier-3 hard stop mirrors bedrock_client.invoke(): never spend when paused.
    try:
        from budget_guard import current_tier

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

    NB: nothing in the codebase calls this today (see module docstring / ADR-132).
    """
    eligible, reason = batch_preflight(len(records), model_name)
    if not eligible:
        raise ValueError(f"refusing to submit batch job: {reason}")

    bucket, _, key_prefix = input_s3_uri.replace("s3://", "").partition("/")
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


def run_or_fallback(
    records: list[dict],
    model_name: str,
    realtime_fn,
) -> dict:
    """Eligibility-gated dispatcher a producer adopts to get batch-when-worthwhile
    with an automatic real-time fallback.

    `records` are `build_jsonl_record` dicts; `realtime_fn(model_input) -> result`
    runs one record on the real-time path (bedrock_client.invoke / retry_utils).

    At today's volume `batch_preflight` returns not-eligible, so this loops
    `realtime_fn` over the records — identical behavior to not adopting batch at
    all, just centralized. When volume crosses the floor the batch branch (kept
    minimal here; submit/poll/retrieve above) takes over. Returns
    {mode, reason, results}.
    """
    eligible, reason = batch_preflight(len(records), model_name)
    if not eligible:
        results = [realtime_fn(r["modelInput"]) for r in records]
        return {"mode": "realtime", "reason": reason, "results": results}
    # Batch branch intentionally minimal — enablement wires submit_batch +
    # wait_for_batch + retrieve here behind real IAM (ADR-132). Guard so this is
    # never silently reached before that work lands.
    raise NotImplementedError("batch branch not enabled — cross the floor and wire submit_batch/wait_for_batch per ADR-132")


def retrieve_results(output_s3_uri: str, manifest_key: str) -> dict:
    """Parse a completed job's output JSONL (one {recordId, modelOutput} per line)
    into {recordId: modelOutput}. Bedrock returns records unordered — the caller
    reassembles by recordId. Kept thin; exercised only once batch is enabled.
    """
    bucket, _, key = output_s3_uri.replace("s3://", "").partition("/")
    obj = boto3.client("s3", region_name=BEDROCK_REGION).get_object(Bucket=bucket, Key=f"{key.rstrip('/')}/{manifest_key}")
    out = {}
    for line in obj["Body"].read().decode("utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[rec.get("recordId")] = rec.get("modelOutput")
    return out


# Re-export for callers/tests that want the price table without importing two modules.
PRICES = _PRICES
