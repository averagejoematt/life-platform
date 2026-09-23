"""closure_probe_qa.py — close-on-first-live-output: the nightly leg that reads every open
`closure:live-proof` issue's `## Proof probe` and closes it on the first true reading (#4022).

WHY
  An instrument issue closes on its first non-degraded LIVE output, never on the merge
  (#3595, `scripts/closure_contract.py`). Until this leg, the read that proves it was done
  by hand: a session re-read each "stays open on the next nightly" note, ran the read and
  wrote the `**Live proof:**` line. Eight of 54 open issues waited that way on 2026-09-21.

WHAT IT DOES (one leg inside the existing 18:30Z qa-smoke invoke — no new schedule)
  1. Lists open issues labelled `closure:live-proof` (GitHub REST, read-only).
  2. Parses each body's `## Proof probe` block (`operational.proof_probe` — the ONE grammar).
  3. Evaluates every probe READ-ONLY against its live address (site `/api/*`, the platform
     table, the platform bucket, a CI job's latest completed run on main, a CloudWatch
     metric, or a qa-smoke check from THIS run).
  4. When EVERY probe in a block reads true, on the SCHEDULED invoke only, with the write
     credential present: writes the audit line to `s3://…/remediation-log/closure-probe/`,
     posts the closing comment (the closure-contract shape, built by
     `proof_probe.closing_comment`) and closes the issue. The audit write comes FIRST — no
     audit line, no close.

  It merges nothing, deploys nothing, and writes to GitHub only `POST …/comments` and
  `PATCH …/issues/N {"state": "closed"}`. There is no merge call anywhere in this module
  (`tests/test_closure_proof_probe_4022.py` asserts it by AST).

WHAT IT NEVER DOES
  * close on `false`, `absent` or `degraded` — only an observed, non-degraded, true reading;
  * close past a probe's `expires` date — an expired probe is a needs-human WARN;
  * run at all on a CI smoke invoke (no GitHub read, no Check) — only the scheduled nightly,
    or an explicit `{"closure_probe": "report"}` invoke that evaluates and REPORTS only;
  * close on a dry run — it evaluates and reports;
  * close without the write credential — a probe that fires with none is a WARN naming it.

THE CREDENTIAL (degrades to report-only until it is granted)
  The write path is the remediation dispatcher's scoped GitHub identity
  (`life-platform/github-dispatch-token`, ADR-064), named by the env var
  `CLOSURE_PROBE_TOKEN_SECRET`. When the env var is unset the leg does NOT attempt the
  secret read at all — an attempted read the role is not granted would log a denial nightly
  and light the #3563 swallowed-denial alarm for a gap that is already declared. The CDK
  change that arms it (env var + `secretsmanager:GetSecretValue` on that secret +
  `s3:PutObject` on `remediation-log/closure-probe/*` for the qa-smoke role, and the PAT
  gaining Issues: read & write) is the residual carried on #4022.

Partition: CONTENT_TRUTH — nothing here is evidence about the deploy in flight, so it can
never gate ci-cd's rollback. The leg never raises (every failure is a reported WARN).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from operational import proof_probe as pp

try:
    from common.platform_logger import get_logger

    logger = get_logger("qa-smoke")
except ImportError:
    logger = logging.getLogger("qa-smoke")

REPO = os.environ.get("CLOSURE_PROBE_REPO", "averagejoematt/life-platform")
TOKEN_SECRET_ENV = "CLOSURE_PROBE_TOKEN_SECRET"  # noqa: S105 — an env-var NAME, not a secret
AUDIT_PREFIX = "remediation-log/closure-probe/"
MAX_ISSUES = 25
HTTP_TIMEOUT_S = 10
CHECK_NAME = "closure:proof_probes"
CHECK_CATEGORY = "Closure Proof Probes"
_UA = "life-platform-qa-smoke-closure-probe"


def is_scheduled(event: Any) -> bool:
    """True for the EventBridge nightly (qa-smoke's rule sends EventBridge's own event)."""
    return isinstance(event, dict) and event.get("source") == "aws.events"


# ── GitHub (REST, urllib) ─────────────────────────────────────────────────────────────
class GitHub:
    """The narrow GitHub surface this leg uses. Reads work unauthenticated (public repo);
    the two writes require `token`."""

    def __init__(self, token: Optional[str] = None, repo: str = REPO, opener: Callable[..., Any] = urllib.request.urlopen):
        self.token = token
        self.repo = repo
        self._open = opener

    def _req(self, method: str, path: str, payload: Optional[dict] = None) -> Tuple[int, Any]:
        url = path if path.startswith("https://") else f"https://api.github.com{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": _UA}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._open(req, timeout=HTTP_TIMEOUT_S) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, None

    def open_labelled_issues(self) -> List[dict]:
        label = urllib.parse.quote(pp.INSTRUMENT_LABEL)
        status, body = self._req("GET", f"/repos/{self.repo}/issues?labels={label}&state=open&per_page={MAX_ISSUES}")
        if status != 200 or not isinstance(body, list):
            raise RuntimeError(f"GitHub issue list returned HTTP {status}")
        return [i for i in body if isinstance(i, dict) and "pull_request" not in i]

    def latest_job_conclusion(self, workflow: str, job: str) -> pp.Reading:
        wf = urllib.parse.quote(workflow)
        status, runs = self._req("GET", f"/repos/{self.repo}/actions/workflows/{wf}/runs?branch=main&status=completed&per_page=1")
        if status == 404:
            return pp.Reading(found=False)
        if status != 200 or not isinstance(runs, dict):
            return pp.Reading(error=f"workflow runs HTTP {status}")
        items = runs.get("workflow_runs") or []
        if not items:
            return pp.Reading(found=False)
        run_id = items[0].get("id")
        status, jobs = self._req("GET", f"/repos/{self.repo}/actions/runs/{run_id}/jobs?per_page=100")
        if status != 200 or not isinstance(jobs, dict):
            return pp.Reading(error=f"run jobs HTTP {status}")
        for j in jobs.get("jobs") or []:
            if (j.get("name") or "").strip() == job:
                return pp.Reading(doc=j.get("conclusion"), found=j.get("conclusion") is not None, note=f"run {run_id}")
        return pp.Reading(found=False, note=f"run {run_id}")

    def comment(self, number: int, body: str) -> int:
        status, _ = self._req("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": body})
        return status

    def close(self, number: int) -> int:
        status, _ = self._req("PATCH", f"/repos/{self.repo}/issues/{number}", {"state": "closed", "state_reason": "completed"})
        return status


def load_token(secrets_client_factory: Callable[[], Any]) -> Optional[str]:
    """The write credential, or None. Unset env var ⇒ None WITHOUT a secret read (see docstring)."""
    secret_id = os.environ.get(TOKEN_SECRET_ENV, "").strip()
    if not secret_id:
        return None
    try:
        from common.secret_cache import get_secret

        return get_secret(secret_id, secrets_client_factory()).strip() or None
    except Exception as e:  # noqa: BLE001 — a missing credential degrades to report-only, it never raises
        logger.warning(f"[QA] closure-probe: write credential unreadable ({type(e).__name__}) — report-only this run")
        return None


# ── readers: one live read per probe kind ─────────────────────────────────────────────
def _qa_check_status(checks: List[Any], name: str) -> pp.Reading:
    mine = [c for c in checks or [] if getattr(c, "name", None) == name]
    if not mine:
        return pp.Reading(found=False)
    if any(c.passed is False for c in mine):
        status = "fail"
    elif any(c.passed is None for c in mine):
        status = "warn"
    elif all(getattr(c, "paused", False) for c in mine):
        status = "paused"
    else:
        status = "ok"
    return pp.Reading(doc=status, found=True, note="this run")


def _read_api(site_base_url: str, path: str, opener: Callable[..., Any]) -> pp.Reading:
    req = urllib.request.Request(site_base_url.rstrip("/") + path, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with opener(req, timeout=HTTP_TIMEOUT_S) as resp:
            return pp.Reading(doc=json.loads(resp.read()), found=True)
    except urllib.error.HTTPError as e:
        return pp.Reading(found=False) if e.code == 404 else pp.Reading(error=f"HTTP {e.code}")
    except (ValueError, OSError) as e:
        return pp.Reading(error=type(e).__name__)


def _read_ddb(table: Any, address: str) -> pp.Reading:
    pk, sk = (p.strip() for p in address.split("|", 1))
    try:
        item = table.get_item(Key={"pk": pk, "sk": sk}).get("Item")
    except Exception as e:  # noqa: BLE001
        return pp.Reading(error=type(e).__name__)
    return pp.Reading(doc=item, found=item is not None)


def _read_s3(s3: Any, bucket: str, key: str) -> pp.Reading:
    try:
        raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as e:  # noqa: BLE001
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", "")) if hasattr(e, "response") else ""
        return pp.Reading(found=False) if code in ("NoSuchKey", "404") else pp.Reading(error=code or type(e).__name__)
    try:
        return pp.Reading(doc=json.loads(raw), found=True)
    except ValueError:
        return pp.Reading(doc=raw.decode("utf-8", "replace"), found=True)


def _read_metric(cloudwatch: Any, address: str, now: datetime) -> pp.Reading:
    parts = [p.strip() for p in address.split("::")]
    dims = []
    if len(parts) == 3:
        for pair in parts[2].split(","):
            k, _, v = pair.partition("=")
            dims.append({"Name": k.strip(), "Value": v.strip()})
    try:
        resp = cloudwatch.get_metric_statistics(
            Namespace=parts[0],
            MetricName=parts[1],
            Dimensions=dims,
            StartTime=now - timedelta(hours=24),
            EndTime=now,
            Period=86400,
            Statistics=["Maximum"],
        )
    except Exception as e:  # noqa: BLE001
        return pp.Reading(error=type(e).__name__)
    points = [d.get("Maximum") for d in resp.get("Datapoints") or [] if d.get("Maximum") is not None]
    return pp.Reading(doc=max(points), found=True, note="24h Maximum") if points else pp.Reading(found=False)


def read_probe(probe: pp.Probe, ctx: Dict[str, Any]) -> pp.Reading:
    """ONE live read for one probe. Never raises: a failure is a `degraded` reading."""
    try:
        if probe.kind == "qa_check":
            return _qa_check_status(ctx.get("checks") or [], probe.address)
        if probe.kind == "api_field":
            return _read_api(ctx["site_base_url"], probe.address, ctx.get("http_opener") or urllib.request.urlopen)
        if probe.kind == "ddb_key":
            return _read_ddb(ctx["table"], probe.address)
        if probe.kind == "s3_key":
            return _read_s3(ctx["s3"], ctx["bucket"], probe.address)
        if probe.kind == "cloudwatch_metric":
            return _read_metric(ctx["cloudwatch"](), probe.address, ctx["now"])
        if probe.kind == "ci_job":
            wf, job = (p.strip() for p in probe.address.split("::", 1))
            return ctx["github"].latest_job_conclusion(wf, job)
    except Exception as e:  # noqa: BLE001 — "could not look" is a degraded reading, never a raise
        return pp.Reading(error=type(e).__name__)
    return pp.Reading(error=f"no reader for kind {probe.kind!r}")


# ── the close (audit FIRST) ────────────────────────────────────────────────────────────
def _audit(s3: Any, bucket: str, number: int, now: datetime, record: dict) -> str:
    key = f"{AUDIT_PREFIX}{now:%Y/%m/%d/%H%M%S}-issue-{number}.json"
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(record, default=str).encode(), ContentType="application/json")
    return key


def close_issue(gh: GitHub, s3: Any, bucket: str, number: int, comment: str, now: datetime) -> Tuple[bool, str]:
    """audit → comment → close. (ok, detail). The audit line is written before any GitHub
    write, so a close with no audit trail cannot happen; a failed audit aborts the close."""
    record = {"issue": number, "repo": gh.repo, "at": now.isoformat(), "action": "close", "comment": comment, "leg": pp.LEG_NAME}
    try:
        key = _audit(s3, bucket, number, now, record)
    except Exception as e:  # noqa: BLE001
        return False, f"audit write failed ({type(e).__name__}) — not closed"
    status = gh.comment(number, comment)
    if status != 201:
        return False, f"comment HTTP {status} — not closed (audit {key})"
    status = gh.close(number)
    if status != 200:
        return False, f"comment posted but close HTTP {status} (audit {key})"
    return True, f"closed (audit {key})"


# ── the leg ────────────────────────────────────────────────────────────────────────────
def evaluate_issue(issue: dict, ctx: Dict[str, Any], today) -> Dict[str, Any]:
    """Pure over its readers. → {number, state, detail, evals, block} where state is one of
    no_probe | invalid | expired | pending | fired."""
    number = int(issue.get("number") or 0)
    block = pp.parse_block(issue.get("body") or "")
    if block is None:
        return {"number": number, "state": "no_probe", "detail": "no `## Proof probe` section"}
    if not block.valid:
        return {"number": number, "state": "invalid", "detail": "; ".join(block.errors)}
    if pp.is_expired(block, today):
        return {"number": number, "state": "expired", "detail": f"probe expired {block.expires} — needs a human", "block": block}
    readings = [read_probe(p, ctx) for p in block.probes]
    evals = [pp.evaluate(p, r) for p, r in zip(block.probes, readings)]
    verdict = pp.block_verdict(evals)
    if verdict == pp.VERDICT_TRUE:
        return {"number": number, "state": "fired", "evals": evals, "notes": [r.note for r in readings], "block": block}
    reasons = ", ".join(f"{e.probe.kind} {e.verdict}: {e.reason}" for e in evals if e.verdict != pp.VERDICT_TRUE)
    return {"number": number, "state": "pending", "detail": f"{verdict} ({reasons})"}


def check_closure_proof_probes(
    checks: List[Any],
    table: Any,
    s3: Any,
    bucket: str,
    Check: Any,
    partition: str,
    *,
    site_base_url: str,
    event: Any = None,
    dry_run: bool = False,
    github: Optional[GitHub] = None,
    cloudwatch_factory: Optional[Callable[[], Any]] = None,
    secrets_factory: Optional[Callable[[], Any]] = None,
    now: Optional[datetime] = None,
    http_opener: Optional[Callable[..., Any]] = None,
) -> List[Any]:
    """The qa-smoke leg. Returns ONE Check — or NONE on an invoke that is neither the
    scheduled nightly nor an explicit `{"closure_probe": "report"}` (CI's post-deploy smoke
    invokes and the offline handler tests must not reach GitHub). Never raises."""
    if not (is_scheduled(event) or (isinstance(event, dict) and event.get("closure_probe") == "report")):
        return []
    c = Check(CHECK_NAME, CHECK_CATEGORY, partition)
    try:
        return [
            _run(c, checks, table, s3, bucket, site_base_url, event, dry_run, github, cloudwatch_factory, secrets_factory, now, http_opener)
        ]
    except Exception as e:  # noqa: BLE001 — the leg reports, it never takes the sweep down
        return [c.warn(f"closure-probe leg errored ({type(e).__name__}: {str(e)[:160]}) — no probe was evaluated, nothing closed")]


def _boto(service: str) -> Callable[[], Any]:
    def make() -> Any:
        import boto3

        return boto3.client(service, region_name=os.environ.get("AWS_REGION", "us-west-2"))

    return make


def _run(c, checks, table, s3, bucket, site_base_url, event, dry_run, github, cloudwatch_factory, secrets_factory, now, http_opener):
    now = now or datetime.now(timezone.utc)
    write_enabled = is_scheduled(event) and not dry_run
    token = load_token(secrets_factory or _boto("secretsmanager")) if write_enabled else None
    gh = github or GitHub(token=token)
    try:
        issues = gh.open_labelled_issues()
    except Exception as e:  # noqa: BLE001
        return c.warn(f"could not list open `{pp.INSTRUMENT_LABEL}` issues ({str(e)[:120]}) — no probe evaluated (could not look ≠ pass)")
    ctx = {
        "checks": checks,
        "table": table,
        "s3": s3,
        "bucket": bucket,
        "site_base_url": site_base_url,
        "github": gh,
        "cloudwatch": cloudwatch_factory or _boto("cloudwatch"),
        "now": now,
        "http_opener": http_opener,
    }
    buckets: Dict[str, List[str]] = {
        k: [] for k in ("closed", "fired_blocked", "close_failed", "expired", "pending", "invalid", "no_probe")
    }
    for issue in issues[:MAX_ISSUES]:
        # utc-exempt(#4022): a probe's `expires` is declared as a UTC calendar date in the grammar (proof_probe.py)
        r = evaluate_issue(issue, ctx, now.date())
        n = r["number"]
        if r["state"] != "fired":
            key = r["state"]
            buckets[key].append(f"#{n}" + (f" ({r['detail']})" if key in ("expired", "pending", "invalid") else ""))
            continue
        comment = pp.closing_comment(r["evals"], now, residual=r["block"].residual, notes=r["notes"])
        if not write_enabled:
            buckets["fired_blocked"].append(f"#{n} (report-only: {'dry run' if dry_run else 'not the scheduled nightly'})")
            continue
        if not gh.token:
            buckets["fired_blocked"].append(
                f"#{n} (probe TRUE — no write credential; `{TOKEN_SECRET_ENV}` unset/unreadable, CDK residual on #4022)"
            )
            continue
        ok, detail = close_issue(gh, s3, bucket, n, comment, now)
        buckets["closed" if ok else "close_failed"].append(f"#{n} {detail}")
        logger.info(f"[QA] closure-probe #{n}: {detail}")
    summary = (
        f"{len(issues)} open `{pp.INSTRUMENT_LABEL}` issue(s): closed {len(buckets['closed'])}"
        + (f" ({', '.join(s.split(' ', 1)[0] for s in buckets['closed'])})" if buckets["closed"] else "")
        + f", pending {len(buckets['pending'])}, "
        f"fired-not-closed {len(buckets['fired_blocked'])}, expired {len(buckets['expired'])}, "
        f"invalid {len(buckets['invalid'])}, no probe {len(buckets['no_probe'])}"
    )
    details = [f"{k}: {v}" for k, vals in buckets.items() for v in vals]
    blocked_scheduled = write_enabled and any("no write credential" in s for s in buckets["fired_blocked"])
    if buckets["expired"] or buckets["close_failed"] or blocked_scheduled:
        needs = buckets["expired"] + buckets["close_failed"] + [s for s in buckets["fired_blocked"] if "no write credential" in s]
        return c.warn(f"{summary} — needs a human: {'; '.join(needs)[:400]}").with_details(details)
    return c.ok(summary).with_details(details)
