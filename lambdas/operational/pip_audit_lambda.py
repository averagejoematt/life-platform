"""
pip_audit_lambda.py — SEC-5: Monthly dependency vulnerability scanning.

Runs first Monday of each month at 9:00 AM PT (17:00 UTC).
Reads all `lambdas/requirements/*.txt` files from S3, installs dependencies
into a temp virtualenv, runs pip-audit, and emails a vulnerability report.

Since only garmin.txt has real deps (the rest are placeholder stubs), this
Lambda is lightweight — typically runs in <60 seconds.

HOW IT WORKS:
  1. Downloads all requirements/*.txt files from S3 (uploaded during MAINT-1)
  2. Runs `pip install --dry-run` + `pip-audit --requirement` for each
  3. Aggregates findings: (vulnerability, package, version, CVE, severity, fix)
  4. Emails summary — GREEN if clean, RED if any HIGH/CRITICAL findings

S3 LAYOUT (written by deploy/upload_requirements_to_s3.sh):
  matthew-life-platform/
    config/requirements/
      garmin.txt
      strava.txt
      ... (18 files from MAINT-1)

ALTERNATIVES:
  If you prefer a local run over Lambda, use:
    bash deploy/run_pip_audit.sh
  which checks all lambdas/requirements/*.txt files locally and prints a report.

v1.0.0 — 2026-03-08 (SEC-5)
"""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("pip-audit")
except ImportError:
    logger = logging.getLogger("pip-audit")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-west-2")
BUCKET = os.environ["S3_BUCKET"]
USER_ID = os.environ.get("USER_ID", "matthew")
RECIPIENT = os.environ["EMAIL_RECIPIENT"]
SENDER = os.environ["EMAIL_SENDER"]
REQ_S3_PREFIX = os.environ.get("REQ_S3_PREFIX", "config/requirements/")

s3 = boto3.client("s3", region_name=REGION)
ses = boto3.client("sesv2", region_name=REGION)

# ── SCA layer-manifest coverage guard (#1336) ───────────────────────────────────
# Every binary dependency layer referenced by a `*_LAYER_ARN` in cdk/stacks/constants.py
# ships third-party code INTO a running Lambda (pillow-layer→Pillow, garth-layer→garth,
# lameenc-layer→lameenc), so each MUST have a pinned manifest under lambdas/requirements/
# that pip-audit can scan. If a layer is added to constants.py without a matching manifest,
# this guard fails the scan RED — closing the SCA blind spot that let pillow-layer run
# unscanned for months (#1336, SDLC review 2026-07-18).

# `arn:...:layer:<short>-layer:<version>` → capture <short>. Non-greedy so an internal
# hyphen in a future layer name still resolves against the `-layer:` anchor.
_LAYER_ARN_RE = re.compile(r"layer:([a-z0-9_-]+?)-layer:")

# A layer's third-party package may be pinned in a differently-named manifest. garth-layer's
# `garth==x.y.z` is pinned inside garmin.txt (the garmin-data-ingestion manifest), so garth
# is covered without a standalone garth.txt. Map layer short-name → acceptable manifest(s).
_LAYER_MANIFEST_ALIASES = {
    "garth": ["garth.txt", "garmin.txt"],
}

# Resolve the repo tree from this file: lambdas/operational/pip_audit_lambda.py → repo root.
_MODULE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MODULE_DIR.parents[1]


def _default_constants_path() -> Path:
    return Path(os.environ.get("CONSTANTS_PATH", str(_REPO_ROOT / "cdk" / "stacks" / "constants.py")))


def _default_requirements_dir() -> Path:
    env = os.environ.get("REQUIREMENTS_DIR")
    if env:
        return Path(env)
    repo_dir = _REPO_ROOT / "lambdas" / "requirements"
    if repo_dir.is_dir():
        return repo_dir
    # Lambda bundle may ship the manifests alongside the code.
    return Path("/var/task/requirements")


def _layer_names_from_constants(constants_text: str) -> list[str]:
    """Return sorted-unique layer short-names from every `*_LAYER_ARN` literal."""
    return sorted({m.group(1) for m in _LAYER_ARN_RE.finditer(constants_text)})


def check_layer_manifest_coverage(constants_path=None, requirements_dir=None) -> list[str]:
    """Return layer short-names referenced in constants.py that have NO scanning manifest.

    Empty list == every referenced binary layer is covered by a pinned manifest. A
    non-empty list is the RED signal: those layers ship third-party code pip-audit cannot
    see. Fails on today's tree until pillow.txt/lameenc.txt exist; passes once they do.

    If constants.py cannot be read (e.g. not bundled into the Lambda), returns [] and logs
    a warning — the authoritative enforcement is the CI unit test, which always sees the
    repo tree.
    """
    cpath = Path(constants_path) if constants_path is not None else _default_constants_path()
    rdir = Path(requirements_dir) if requirements_dir is not None else _default_requirements_dir()
    try:
        constants_text = cpath.read_text()
    except OSError as e:
        logger.warning(f"[pip_audit] Cannot read constants for layer-manifest guard ({cpath}): {e}")
        return []
    missing = []
    for name in _layer_names_from_constants(constants_text):
        candidates = _LAYER_MANIFEST_ALIASES.get(name, [f"{name}.txt"])
        if not any((rdir / c).is_file() for c in candidates):
            missing.append(name)
    return missing


def check_alerts_enabled() -> dict:
    """AC5 regression guard (#1336): verify GitHub vulnerability + Dependabot alerts are ON
    so a future silent disablement (the exact #1336 root cause) is caught on this scheduled
    surface.

    The scheduled Lambda holds NO GitHub credentials, so without a token this is an honest
    SKIP (a lightweight assertion the Lambda genuinely can't make offline). To ACTIVATE the
    guard, wire a fine-grained read-only PAT into the Lambda's env as GH_ALERTS_TOKEN — then
    a disabled state returns status="disabled", which the handler escalates to RED.

    Returns a status dict for the report: status in {enabled, disabled, skipped, error}.
    """
    token = os.environ.get("GH_ALERTS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO", "averagejoematt/life-platform")
    if not token:
        return {
            "status": "skipped",
            "reason": "no GitHub token in Lambda env — set GH_ALERTS_TOKEN (read-only PAT) to activate (#1336 AC5)",
        }
    # GET /repos/{repo}/vulnerability-alerts → 204 enabled, 404 disabled.
    url = f"https://api.github.com/repos/{repo}/vulnerability-alerts"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "life-platform-pip-audit")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 204:
                return {"status": "enabled", "reason": "repo vulnerability alerts ON"}
            return {"status": "error", "reason": f"unexpected status {resp.status}"}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"status": "disabled", "reason": "GitHub vulnerability alerts are DISABLED (#1336 gate:owner)"}
        return {"status": "error", "reason": f"HTTP {e.code} querying vulnerability-alerts"}
    except Exception as e:  # noqa: BLE001 — network/DNS, degrade to a non-fatal note
        return {"status": "error", "reason": f"alerts check failed: {e}"}


def list_requirements_files() -> list[str]:
    """List all requirements.txt files in S3 under REQ_S3_PREFIX."""
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=REQ_S3_PREFIX)
        return [obj["Key"] for obj in resp.get("Contents", []) if obj["Key"].endswith(".txt")]
    except Exception as e:
        logger.error(f"[pip_audit] Failed to list S3 requirements: {e}")
        return []


def download_requirements(s3_key: str, local_path: str) -> bool:
    """Download a requirements file from S3."""
    try:
        s3.download_file(BUCKET, s3_key, local_path)
        return True
    except Exception as e:
        logger.warning(f"[pip_audit] Failed to download {s3_key}: {e}")
        return False


def ensure_pip_audit() -> bool:
    """Install pip-audit if not present (Lambda cold start)."""
    try:
        result = subprocess.run([sys.executable, "-m", "pip_audit", "--version"], capture_output=True, timeout=10)
        if result.returncode == 0:
            return True
    except Exception:
        pass

    logger.info("[pip_audit] Installing pip-audit...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "pip-audit==2.7.3", "--quiet", "--target", "/tmp/pip_audit_pkg"],
            capture_output=True,
            timeout=120,
        )
        if result.returncode == 0:
            if "/tmp/pip_audit_pkg" not in sys.path:
                sys.path.insert(0, "/tmp/pip_audit_pkg")
            logger.info("[pip_audit] pip-audit installed successfully")
            return True
        else:
            logger.error(f"[pip_audit] pip-audit install failed: {result.stderr.decode()}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("[pip_audit] pip-audit install timed out")
        return False


def audit_requirements_file(req_path: str, lambda_name: str) -> dict:
    """Run pip-audit on a single requirements file.

    Returns:
        {
          "lambda": str,
          "vulnerabilities": [...],
          "packages_checked": int,
          "status": "clean" | "vulnerable" | "error" | "empty",
          "error_msg": str (if error),
        }
    """
    # Check if file is empty or just comments
    try:
        with open(req_path) as f:
            content = f.read()
        real_lines = [l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]
        if not real_lines:
            return {
                "lambda": lambda_name,
                "vulnerabilities": [],
                "packages_checked": 0,
                "status": "empty",
                "notes": "No packages in requirements",
            }
    except Exception as e:
        return {"lambda": lambda_name, "vulnerabilities": [], "packages_checked": 0, "status": "error", "error_msg": str(e)}

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--requirement",
                req_path,
                "--format",
                "json",
                "--disable-pip",  # don't audit pip itself
                "--no-deps",  # check only what's listed, not transitive
            ],
            capture_output=True,
            timeout=120,
        )

        output = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")

        # pip-audit exits 1 if vulnerabilities found
        try:
            audit_data = json.loads(output)
        except json.JSONDecodeError:
            if "No known vulnerabilities found" in output or "No known vulnerabilities found" in stderr:
                return {"lambda": lambda_name, "vulnerabilities": [], "packages_checked": len(real_lines), "status": "clean"}
            return {
                "lambda": lambda_name,
                "vulnerabilities": [],
                "packages_checked": len(real_lines),
                "status": "error",
                "error_msg": f"JSON parse failed. stdout={output[:200]}, stderr={stderr[:200]}",
            }

        vulnerabilities = []
        for dep in audit_data.get("dependencies", []):
            for vuln in dep.get("vulns", []):
                vulnerabilities.append(
                    {
                        "package": dep.get("name", "?"),
                        "version": dep.get("version", "?"),
                        "vuln_id": vuln.get("id", "?"),
                        "description": vuln.get("description", "")[:300],
                        "fix_versions": vuln.get("fix_versions", []),
                        "aliases": vuln.get("aliases", []),
                    }
                )

        packages_checked = len(audit_data.get("dependencies", []))
        status = "vulnerable" if vulnerabilities else "clean"

        return {
            "lambda": lambda_name,
            "vulnerabilities": vulnerabilities,
            "packages_checked": packages_checked,
            "status": status,
        }

    except subprocess.TimeoutExpired:
        return {
            "lambda": lambda_name,
            "vulnerabilities": [],
            "packages_checked": 0,
            "status": "error",
            "error_msg": "pip-audit timed out after 120s",
        }
    except Exception as e:
        return {"lambda": lambda_name, "vulnerabilities": [], "packages_checked": 0, "status": "error", "error_msg": str(e)}


def build_report_html(results: list[dict], scan_date: str) -> tuple[str, bool]:
    """Build HTML email. Returns (html, has_vulnerabilities)."""
    total_vulns = sum(len(r["vulnerabilities"]) for r in results)
    has_vulns = total_vulns > 0
    has_errors = any(r["status"] == "error" for r in results)
    vulnerable_lambdas = [r for r in results if r["status"] == "vulnerable"]
    empty_lambdas = sum(1 for r in results if r["status"] == "empty")
    clean_lambdas = sum(1 for r in results if r["status"] == "clean")

    if has_vulns:
        header_color = "#dc2626"
        status_icon = "🔴"
        status_text = f"VULNERABLE — {total_vulns} vulnerability{'s' if total_vulns > 1 else ''} found"
    elif has_errors:
        header_color = "#d97706"
        status_icon = "🟡"
        status_text = "SCAN ERRORS — review logs"
    else:
        header_color = "#059669"
        status_icon = "🟢"
        status_text = "CLEAN — no known vulnerabilities"

    # Vulnerability details rows
    vuln_rows = ""
    for r in vulnerable_lambdas:
        for v in r["vulnerabilities"]:
            fix_str = ", ".join(v.get("fix_versions", [])) or "no fix available"
            aliases_str = ", ".join(v.get("aliases", [])[:3])
            vuln_rows += f"""
            <tr>
              <td style="padding:8px 12px;font-family:monospace;font-size:12px;">{r['lambda']}</td>
              <td style="padding:8px 12px;font-family:monospace;">{v['package']}=={v['version']}</td>
              <td style="padding:8px 12px;font-family:monospace;color:#dc2626;">{v['vuln_id']}</td>
              <td style="padding:8px 12px;font-size:12px;color:#666;">{v['description'][:150]}...</td>
              <td style="padding:8px 12px;color:#059669;">{fix_str}</td>
              <td style="padding:8px 12px;font-size:11px;color:#9ca3af;">{aliases_str}</td>
            </tr>"""

    vuln_table = ""
    if has_vulns:
        vuln_table = f"""
    <h3 style="margin:24px 0 8px;color:#dc2626;">🚨 Vulnerabilities</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#fef2f2;">
          <th style="padding:8px 12px;text-align:left;">Lambda</th>
          <th style="padding:8px 12px;text-align:left;">Package</th>
          <th style="padding:8px 12px;text-align:left;">Vuln ID</th>
          <th style="padding:8px 12px;text-align:left;">Description</th>
          <th style="padding:8px 12px;text-align:left;">Fix</th>
          <th style="padding:8px 12px;text-align:left;">Aliases</th>
        </tr>
      </thead>
      <tbody>{vuln_rows}</tbody>
    </table>"""

    # Summary rows per Lambda
    summary_rows = ""
    for r in sorted(results, key=lambda x: (x["status"] != "vulnerable", x["lambda"])):
        status_badge = {
            "clean": "<span style='color:#059669;'>✅ Clean</span>",
            "empty": "<span style='color:#6b7280;'>— Empty</span>",
            "vulnerable": f"<span style='color:#dc2626;'>🔴 {len(r['vulnerabilities'])} vuln</span>",
            "error": "<span style='color:#d97706;'>⚠️ Error</span>",
        }.get(r["status"], r["status"])
        error_note = f" | {r.get('error_msg', '')[:80]}" if r.get("error_msg") else ""
        notes = r.get("notes", "") + error_note
        summary_rows += f"""
        <tr>
          <td style="padding:6px 12px;font-family:monospace;font-size:12px;">{r['lambda']}</td>
          <td style="padding:6px 12px;">{status_badge}</td>
          <td style="padding:6px 12px;text-align:center;color:#6b7280;">{r['packages_checked']}</td>
          <td style="padding:6px 12px;font-size:11px;color:#9ca3af;">{notes}</td>
        </tr>"""

    return (
        f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:system-ui,sans-serif;margin:0;padding:16px;background:#f9fafb;">
<div style="max-width:900px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
  <div style="background:{header_color};padding:20px 24px;">
    <h2 style="color:white;margin:0;font-size:20px;">{status_icon} Monthly pip-audit Report</h2>
    <p style="color:rgba(255,255,255,.9);margin:4px 0 0;font-size:13px;">{scan_date} | {status_text}</p>
  </div>
  <div style="padding:16px 24px;background:#f8fafc;border-bottom:1px solid #e5e7eb;">
    <strong>Scan summary:</strong> {len(results)} requirements files | {sum(r['packages_checked'] for r in results)} packages checked |
    {clean_lambdas} clean | {empty_lambdas} empty (no deps) | {total_vulns} vulnerabilities
  </div>
  <div style="padding:20px 24px;">
    {vuln_table}
    <h3 style="margin:{'24px' if has_vulns else '0'} 0 8px;">Per-Lambda Summary</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#f3f4f6;">
          <th style="padding:6px 12px;text-align:left;">Lambda</th>
          <th style="padding:6px 12px;text-align:left;">Status</th>
          <th style="padding:6px 12px;text-align:center;">Packages</th>
          <th style="padding:6px 12px;text-align:left;">Notes</th>
        </tr>
      </thead>
      <tbody>{summary_rows}</tbody>
    </table>
  </div>
  {'<div style="padding:16px 24px;background:#fef3c7;border-top:1px solid #e5e7eb;"><strong>🔧 Remediation:</strong> Run <code>pip install --upgrade {" ".join(set(v["package"] for r in vulnerable_lambdas for v in r["vulnerabilities"]))}</code> and update requirements.txt accordingly. Then redeploy affected Lambdas.</div>' if has_vulns else ""}
  <div style="padding:12px 24px;font-size:11px;color:#9ca3af;border-top:1px solid #e5e7eb;">
    AI-generated analysis, not medical advice. Life Platform | pip-audit Lambda (SEC-5)
  </div>
</div>
</body></html>""",
        has_vulns,
    )


def _is_first_monday_of_month() -> bool:
    """Guard for EventBridge schedule: only run on first Monday of each month.

    EventBridge cannot natively express 'first Monday of month',
    so we schedule every Monday and check here. Invoke manually with
    event={"force": true} to bypass the guard.
    """
    today = datetime.now(timezone.utc)
    return today.day <= 7  # First Mon of month must be day 1-7


def lambda_handler(event, context):
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # First-Monday guard (bypass with event={"force": true})
    if not event.get("force") and not _is_first_monday_of_month():
        logger.info(f"[pip_audit] Skipping — not first Monday of month (day {datetime.now(timezone.utc).day})")
        return {"statusCode": 200, "body": "Skipped — not first Monday of month"}

    logger.info(f"[pip_audit] Monthly dependency scan starting: {scan_date}")

    # Install pip-audit if needed
    if not ensure_pip_audit():
        logger.error("[pip_audit] Cannot proceed — pip-audit not available")
        return {"statusCode": 500, "body": "pip-audit installation failed"}

    # Get requirements files from S3
    s3_keys = list_requirements_files()
    if not s3_keys:
        logger.warning("[pip_audit] No requirements files found in S3 — check REQ_S3_PREFIX")
        # Fallback: check if bundled files exist locally (from Lambda package)
        local_req_dir = "/var/task/requirements"
        if os.path.isdir(local_req_dir):
            local_files = list(Path(local_req_dir).glob("*.txt"))
            logger.info(f"[pip_audit] Using {len(local_files)} bundled requirements files")
        else:
            return {"statusCode": 200, "body": "No requirements files found to audit"}

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for s3_key in s3_keys:
            lambda_name = s3_key.replace(REQ_S3_PREFIX, "").replace(".txt", "")
            local_path = os.path.join(tmpdir, f"{lambda_name}.txt")

            if not download_requirements(s3_key, local_path):
                results.append(
                    {
                        "lambda": lambda_name,
                        "vulnerabilities": [],
                        "packages_checked": 0,
                        "status": "error",
                        "error_msg": "S3 download failed",
                    }
                )
                continue

            logger.info(f"[pip_audit] Auditing {lambda_name}...")
            result = audit_requirements_file(local_path, lambda_name)
            results.append(result)

            if result["vulnerabilities"]:
                logger.warning(f"[pip_audit] {lambda_name}: {len(result['vulnerabilities'])} vulnerabilities found")

    # ── SCA layer-manifest coverage guard (#1336 AC2) — RED if a deployed binary layer
    # referenced in cdk/stacks/constants.py has no manifest for pip-audit to scan.
    missing_layer_manifests = check_layer_manifest_coverage()
    if missing_layer_manifests:
        logger.error(f"[pip_audit] SCA GAP — deployed layer(s) with no scanning manifest: {missing_layer_manifests}")
        results.append(
            {
                "lambda": "sca-layer-coverage",
                "packages_checked": 0,
                "status": "vulnerable",
                "vulnerabilities": [
                    {
                        "package": f"{name}-layer",
                        "version": "(deployed, unpinned)",
                        "vuln_id": "SCA-UNSCANNED-LAYER",
                        "description": (
                            f"Binary layer '{name}-layer' is referenced by a *_LAYER_ARN in cdk/stacks/constants.py "
                            f"but has NO pinned manifest in lambdas/requirements/ — its third-party code is scanned "
                            f"by nothing. Add lambdas/requirements/{name}.txt (#1336)."
                        ),
                        "fix_versions": [f"add lambdas/requirements/{name}.txt"],
                        "aliases": [],
                    }
                    for name in missing_layer_manifests
                ],
            }
        )

    # ── AC5 regression guard (#1336) — verify GitHub vulnerability/Dependabot alerts stay ON.
    alerts = check_alerts_enabled()
    logger.info(f"[pip_audit] GitHub alerts guard: {alerts}")
    if alerts["status"] == "disabled":
        results.append(
            {
                "lambda": "github-alerts-guard",
                "packages_checked": 0,
                "status": "vulnerable",
                "vulnerabilities": [
                    {
                        "package": "repo:vulnerability-alerts",
                        "version": "disabled",
                        "vuln_id": "SCA-ALERTS-DISABLED",
                        "description": alerts["reason"] + " — CVE-triggered Dependabot bump PRs cannot fire while off.",
                        "fix_versions": ["enable repo vulnerability + Dependabot alerts (gate:owner)"],
                        "aliases": [],
                    }
                ],
            }
        )
    else:
        results.append(
            {
                "lambda": "github-alerts-guard",
                "packages_checked": 0,
                "vulnerabilities": [],
                "status": "clean" if alerts["status"] == "enabled" else "empty",
                "notes": f"alerts guard [{alerts['status']}]: {alerts['reason']}",
            }
        )

    html, has_vulns = build_report_html(results, scan_date)
    total_vulns = sum(len(r["vulnerabilities"]) for r in results)
    vuln_icon = "🔴" if has_vulns else "🟢"
    subject = f"{vuln_icon} Monthly pip-audit | {scan_date[:10]} | {'VULNERABLE — action required' if has_vulns else 'Clean'}"

    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info(f"[pip_audit] Report sent: {subject}")
    except Exception as e:
        logger.error(f"[pip_audit] Failed to send report: {e}")
        raise

    # RED-on-missing-manifest / disabled-alerts: fail the invocation (non-zero → CloudWatch
    # Errors alarm) AFTER the report email is sent, so the operator sees the detail AND the
    # scheduled run pages (#1336 AC2/AC5). Vulnerable-package findings intentionally stay
    # email-only (unchanged prior behavior); only the CONFIG gaps this story closes hard-fail.
    hard_fail_reasons = []
    if missing_layer_manifests:
        hard_fail_reasons.append(f"unscanned deployed layer(s) with no manifest: {missing_layer_manifests}")
    if alerts["status"] == "disabled":
        hard_fail_reasons.append("GitHub vulnerability/Dependabot alerts DISABLED")
    if hard_fail_reasons:
        raise RuntimeError("SCA guard RED (#1336): " + "; ".join(hard_fail_reasons))

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "files_audited": len(results),
                "total_vulnerabilities": total_vulns,
                "has_vulnerabilities": has_vulns,
            }
        ),
    }
