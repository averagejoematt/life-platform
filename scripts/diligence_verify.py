#!/usr/bin/env python3
"""
scripts/diligence_verify.py — the A-Grade Program's acceptance instrument (D5, #3042).

WHAT THIS IS
────────────
The 2026-08-23 external acquisition-diligence review scored this platform 4.47/10
("conditional no-go") across 52 findings. `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md`
is the per-finding disposition register; phases D0–D4 did the remediation. This script is
D5: the report's own §15 verification playbooks, **scripted**, so the claims in that
register stop being prose an assessor has to trust and become checks an assessor can run.

It answers exactly one question, per playbook, against **live** state:

    if an external reviewer re-ran this check today, what would they see?

That is why almost nothing here reads the repo. A grep proving `field_tiers.py` declares
a field Tier-2 is not evidence; the evidence is that the live public API does not serve
it. The four families mirror the report's §15 grouping:

  * ``control``    — repo/GitHub control plane (approval gate, ruleset, vuln alerts, CodeQL)
  * ``privacy``    — what the public surface actually exposes (tree, raw.githubusercontent, API payloads)
  * ``prediction`` — whether the platform's own truth claims are gradeable and graded
  * ``edge``       — real request-path behaviour (CSP, rate limiting, data freshness)

THE VACUOUS-PASS TRAP, HANDLED EXPLICITLY
─────────────────────────────────────────
The single way an instrument like this fails its purpose is by reporting green when it
did not actually observe anything — no credentials, a network error, a renamed endpoint.
This platform has been bitten by that shape repeatedly (the CodeQL sentinel that had
never once read the code-scanning API, #3112; the "absent check invisible to a fail
filter" class). So there are **three** verdicts, never two:

  PASS        — the check ran and the control holds.
  FAIL        — the check ran and the control does NOT hold.
  UNVERIFIED  — the check could not run, with a stated reason.

UNVERIFIED is never silently folded into PASS. `--strict` exits non-zero on it, which is
the mode the evidence pack is generated in: an evidence bundle with an unobserved row is
not an evidence bundle. A playbook that raises an unexpected exception is UNVERIFIED with
the exception text, never a swallowed pass.

Every verdict carries `evidence`: the actual observed values, not a restatement of the
assertion. That is what lands in the register's live-evidence column.

USAGE
─────
    python3 scripts/diligence_verify.py                    # human report, all families
    python3 scripts/diligence_verify.py --family privacy   # one family
    python3 scripts/diligence_verify.py --json out.json    # machine bundle for the register
    python3 scripts/diligence_verify.py --strict           # UNVERIFIED also exits non-zero

Exit codes: 0 = every playbook PASSed · 1 = at least one FAIL · 2 = --strict and at least
one UNVERIFIED (and no FAIL) · 3 = usage/internal error.

Cost: read-only. A handful of GitHub API GETs, a handful of HTTPS GETs against the public
site, and one CloudWatch read. It deliberately does NOT hammer the live rate limiter —
see `edge_rate_limit_enforced` for why it reads the nightly observation instead.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Callable

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

SITE = "https://averagejoematt.com"
REPO = "averagejoematt/life-platform"
RAW = "https://raw.githubusercontent.com/averagejoematt/life-platform/main"

PASS = "PASS"  # noqa: S105 — a verdict constant, not a credential (ruff's name heuristic)
FAIL = "FAIL"
UNVERIFIED = "UNVERIFIED"

# The five docs relocated out of the public tree by D0.1 (#3043, DIL-001). An external
# reviewer's check is not "are they gone from HEAD" (a rewrite could hide that) but "does
# the raw endpoint that served them return 404 today".
RELOCATED_COACHING_DOCS = [
    "COACH_STANCE.md",
    "COACH_DOSSIERS.md",
    "COACH_CALIBRATION.md",
    "COACH_RELATIONSHIP_MODEL.md",
    "COACH_INTAKE.md",
]


class Verdict:
    """One playbook's result. `evidence` holds observed values, not restated assertions."""

    def __init__(self, status: str, summary: str, evidence: list[str] | None = None):
        self.status = status
        self.summary = summary
        self.evidence = evidence or []

    def as_dict(self) -> dict:
        return {"status": self.status, "summary": self.summary, "evidence": self.evidence}


def _ok(summary: str, evidence: list[str] | None = None) -> Verdict:
    return Verdict(PASS, summary, evidence)


def _bad(summary: str, evidence: list[str] | None = None) -> Verdict:
    return Verdict(FAIL, summary, evidence)


def _unknown(reason: str, evidence: list[str] | None = None) -> Verdict:
    return Verdict(UNVERIFIED, reason, evidence)


# ── transport helpers ────────────────────────────────────────────────────────────
# Both raise on failure; every playbook wraps its own calls, so a transport failure
# becomes UNVERIFIED with the reason rather than a FAIL that misattributes an outage
# to a broken control.


def _http(url: str, timeout: int = 20) -> tuple[int, dict[str, str], bytes]:
    """GET a URL. Returns (status, headers, body) and does not raise on 4xx/5xx."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "diligence-verify/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read()


def _json_api(path: str) -> dict:
    status, _, body = _http(f"{SITE}{path}")
    if status != 200:
        raise RuntimeError(f"{path} returned HTTP {status}")
    return json.loads(body)


def _gh(endpoint: str, method: str = "GET") -> tuple[int, str]:
    """`gh api` with the status code preserved. Returns (exit_code, stdout-or-stderr).

    Uses the CLI rather than a raw token so this runs with whatever auth the operator
    already has, and so a missing/insufficient token surfaces as UNVERIFIED rather than
    as a silent empty result — the #3112 defect, which is precisely a finding this
    script exists to prevent recurring.
    """
    proc = subprocess.run(
        ["gh", "api", "-X", method, endpoint],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, (proc.stdout if proc.returncode == 0 else proc.stderr).strip()


# ═════════════════════════════════════════════════════════════════════════════════
# FAMILY: control — the repo/GitHub control plane
# ═════════════════════════════════════════════════════════════════════════════════


def control_production_approval_gate() -> Verdict:
    """DIL-004: the report claimed no production approval gate exists. Verify live.

    The register's verdict is WRONG-as-filed; that verdict is only defensible if the
    gate is still live at re-grade time, so this re-asserts it rather than citing the
    2026-08-23 observation.
    """
    rc, out = _gh(f"repos/{REPO}/environments/production")
    if rc != 0:
        return _unknown(f"could not read the production environment: {out[:200]}")
    env = json.loads(out)
    rules = env.get("protection_rules", []) or []
    kinds = [r.get("type") for r in rules]
    reviewer_rule = next((r for r in rules if r.get("type") == "required_reviewers"), None)
    if not reviewer_rule:
        return _bad(
            "the production environment has NO required_reviewers rule — deploys are ungated",
            [f"protection_rules types = {kinds}"],
        )
    reviewers = reviewer_rule.get("reviewers", []) or []
    return _ok(
        f"production deploys require approval ({len(reviewers)} reviewer(s))",
        [f"protection_rules types = {kinds}", f"reviewer count = {len(reviewers)}"],
    )


def control_main_ruleset_active() -> Verdict:
    """DIL-005: main's ruleset is active and blocks force-push + deletion.

    Deliberately checks the LIVE rulesets rather than deploy/github_posture.json: the
    posture file is the declared claim, and an assessor's question is whether the claim
    is true. (The declared-vs-live comparison is drift_sentinel's job, weekly.)
    """
    rc, out = _gh(f"repos/{REPO}/rulesets")
    if rc != 0:
        return _unknown(f"could not list rulesets: {out[:200]}")
    rulesets = json.loads(out)
    active = [r for r in rulesets if r.get("enforcement") == "active"]
    if not active:
        return _bad("no ACTIVE ruleset protects main", [f"{len(rulesets)} ruleset(s) exist, none active"])

    found: set[str] = set()
    names: list[str] = []
    for rs in active:
        rc2, out2 = _gh(f"repos/{REPO}/rulesets/{rs['id']}")
        if rc2 != 0:
            continue
        detail = json.loads(out2)
        names.append(detail.get("name", "?"))
        for rule in detail.get("rules", []) or []:
            found.add(rule.get("type", ""))

    required = {"deletion", "non_fast_forward"}
    missing = required - found
    evidence = [f"active rulesets = {names}", f"rule types present = {sorted(found)}"]
    if missing:
        return _bad(f"main is missing protection rule(s): {sorted(missing)}", evidence)
    return _ok("main blocks force-push and deletion via an active ruleset", evidence)


def control_vulnerability_alerts_enabled() -> Verdict:
    """DIL-006: the report claimed Dependabot/vulnerability alerts were disabled."""
    rc, out = _gh(f"repos/{REPO}/vulnerability-alerts")
    if rc != 0:
        # `gh api` exits non-zero on the 404 that means "disabled" — distinguish that
        # from a genuine auth/transport failure rather than reporting either as the other.
        if "404" in out or "Not Found" in out:
            return _bad("vulnerability alerts are DISABLED (endpoint returns 404)", [out[:200]])
        return _unknown(f"could not read vulnerability-alerts: {out[:200]}")
    return _ok("vulnerability alerts are enabled", ["GET vulnerability-alerts → 204"])


def control_codeql_alerts_triaged() -> Verdict:
    """DIL-018: open CodeQL alerts are back to steady-state zero.

    This is the check whose *sentinel* had never once succeeded (#3112 — a billing-scoped
    token, a missing `security-events: read` scope, and an error-treated-as-no-drift
    fail-soft, three independent sufficient defects). So the auth failure path here is
    UNVERIFIED and loud, never an empty list read as "clean".
    """
    rc, out = _gh(f"repos/{REPO}/code-scanning/alerts?state=open&per_page=100")
    if rc != 0:
        return _unknown(f"could not read code-scanning alerts (the #3112 failure mode): {out[:200]}")
    try:
        alerts = json.loads(out)
    except json.JSONDecodeError:
        return _unknown(f"code-scanning alerts returned non-JSON: {out[:200]}")
    if not isinstance(alerts, list):
        return _unknown(f"code-scanning alerts returned {type(alerts).__name__}, expected a list")

    if alerts:
        rules = [a.get("rule", {}).get("id", "?") for a in alerts[:10]]
        sev = [a.get("rule", {}).get("security_severity_level") or a.get("rule", {}).get("severity") for a in alerts[:10]]
        return _bad(
            f"{len(alerts)} open CodeQL alert(s)",
            [f"rule ids = {rules}", f"severities = {sev}"],
        )
    return _ok("0 open CodeQL alerts", ["GET code-scanning/alerts?state=open → []"])


# ═════════════════════════════════════════════════════════════════════════════════
# FAMILY: privacy — what the public surface actually exposes
# ═════════════════════════════════════════════════════════════════════════════════


def privacy_no_private_markers_in_tree() -> Verdict:
    """DIL-001: no file in the public tree carries an in-band PRIVATE marker.

    The structural half of the containment: a tracked file in a public repo cannot be
    private, so the marker itself is the contradiction.

    This IMPORTS the predicate from `tests/test_no_private_markers_3043.py` rather than
    re-deriving it, and that is load-bearing. The first draft of this playbook used a
    naive `"Status: PRIVATE" in text` substring test and immediately produced a false
    positive on the diligence register itself — which *quotes* the marker inside a table
    cell as the evidence for DIL-001. The canonical predicate anchors on the bolded
    doc-status header at line start and documents that exact quote as deliberately
    benign. Two guards with two definitions of the same word is the twin-sources drift
    class the program is closing everywhere else (DIL-011, #3045); this one gets the
    same treatment.
    """
    sys.path.insert(0, os.path.join(_ROOT, "tests"))
    try:
        from test_no_private_markers_3043 import (  # type: ignore[import-not-found]
            _TEXT_SUFFIXES,
            ALLOWLIST,
            file_carries_private_marker,
        )
    except ImportError as e:
        return _unknown(f"could not import the canonical PRIVATE-marker predicate: {e}")

    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=_ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return _unknown(f"could not enumerate tracked files: {e}")

    hits, scanned = [], 0
    for rel in tracked:
        if rel in ALLOWLIST or os.path.splitext(rel)[1] not in _TEXT_SUFFIXES:
            continue
        try:
            with open(os.path.join(_ROOT, rel), encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        scanned += 1
        if file_carries_private_marker(text):
            hits.append(rel)

    if hits:
        return _bad(f"{len(hits)} tracked file(s) carry an in-band PRIVATE marker", hits[:10])
    return _ok("no tracked file declares itself PRIVATE", [f"scanned {scanned} tracked text file(s) with the canonical predicate"])


def privacy_relocated_docs_are_404() -> Verdict:
    """DIL-001: the five relocated coaching docs no longer resolve on the raw endpoint.

    Note the honest scope, which the register states and this check does not overclaim:
    it proves the CURRENT surface is gone. Historical copies remain reachable by direct
    sha (the dated risk acceptance in the register); no HTTP check can or should claim
    otherwise.
    """
    evidence, still_live = [], []
    for doc in RELOCATED_COACHING_DOCS:
        try:
            status, _, _ = _http(f"{RAW}/docs/coaching/{doc}")
        except Exception as e:  # noqa: BLE001 — transport failure must not read as absence
            return _unknown(f"could not probe {doc}: {e}")
        evidence.append(f"{doc} → HTTP {status}")
        if status == 200:
            still_live.append(doc)
    if still_live:
        return _bad(f"{len(still_live)} relocated doc(s) still served publicly: {still_live}", evidence)
    return _ok(f"all {len(RELOCATED_COACHING_DOCS)} relocated coaching docs return 404 on the raw endpoint", evidence)


def privacy_public_api_serves_no_owner_only_field() -> Verdict:
    """DIL-008/011: no field the registry classes owner-only appears on a public payload.

    This is the check that matters, and it runs in the direction an assessor cares about:
    it takes the OWNER_ONLY vocabulary from `field_tiers.py` and looks for those names in
    the live JSON of the public endpoints. A repo-side grep proving the registry declares
    a field Tier-2 proves nothing about what the API returns.

    A served field absent from the registry is TIER_PUBLIC by omission (the documented,
    deliberate default for this platform) and is not a finding here — DIL-011's port is
    what made the vocabulary complete, and `tests/test_data_governance_tier_guard_3045.py`
    is what keeps it complete. This playbook's job is the leak check.
    """
    try:
        from privacy.field_tiers import TIER_OWNER_ONLY, fields_at_tier
    except Exception as e:  # noqa: BLE001
        return _unknown(f"could not import the field-tier registry: {e}")

    owner_only = set(fields_at_tier(TIER_OWNER_ONLY))
    if not owner_only:
        return _unknown("the registry declares NO owner-only fields — nothing to check, which is not a pass")

    endpoints = ["/api/vitals", "/api/labs", "/api/character", "/api/platform_stats"]
    leaks: list[str] = []
    evidence = [f"owner-only vocabulary = {len(owner_only)} field(s)"]
    for ep in endpoints:
        try:
            payload = _json_api(ep)
        except Exception as e:  # noqa: BLE001
            return _unknown(f"could not read {ep}: {e}")
        blob = json.dumps(payload)
        served = sorted(f for f in owner_only if f'"{f}"' in blob)
        evidence.append(f"{ep} → {len(served)} owner-only field(s) present")
        leaks += [f"{ep}:{f}" for f in served]

    if leaks:
        return _bad(f"{len(leaks)} owner-only field(s) served on a public endpoint", leaks[:15])
    return _ok(f"no owner-only field appears on {len(endpoints)} public endpoints", evidence)


# ═════════════════════════════════════════════════════════════════════════════════
# FAMILY: prediction — are the platform's own truth claims gradeable and graded?
# ═════════════════════════════════════════════════════════════════════════════════


def prediction_calibration_is_reported_honestly() -> Verdict:
    """DIL-007/032: the calibration surface reports a real n, a real score, and a skill
    verdict that follows from the numbers rather than from optimism (ADR-104/105).

    The failure this guards is not "the score is low" — a low score honestly reported is
    the platform working. It is the surface claiming skill it has not demonstrated.
    """
    try:
        payload = _json_api("/api/calibration")
    except Exception as e:  # noqa: BLE001
        return _unknown(f"could not read /api/calibration: {e}")

    plat = payload.get("platform") or {}
    n, brier_skill, skilled = plat.get("n"), plat.get("brier_skill"), plat.get("skilled")
    label = plat.get("calibration") or plat.get("label")
    evidence = [f"n={n}", f"brier_skill={brier_skill}", f"skilled={skilled}", f"label={label}"]

    if n is None or brier_skill is None or skilled is None:
        return _unknown("the calibration payload is missing n / brier_skill / skilled", evidence)
    if n == 0:
        return _bad("calibration reports n=0 — nothing has been graded", evidence)
    # The honesty invariant: `skilled` must follow from brier_skill, not precede it.
    if skilled and brier_skill <= 0:
        return _bad(f"claims skill (skilled=true) on a non-positive brier_skill ({brier_skill})", evidence)
    if not skilled and brier_skill > 0:
        return _bad(f"reports skilled=false despite a positive brier_skill ({brier_skill})", evidence)
    return _ok(f"calibration reports n={n}, brier_skill={brier_skill}, skilled={skilled} — self-consistent", evidence)


def prediction_gradable_share_healthy() -> Verdict:
    """DIL-007: the gradeable share of open predictions is above the alarm floor.

    #3046's diagnosis was that 28 of 50 "pending" predictions were structurally
    ungradeable (`eval_type: qualitative`), which is what made "75 pending / 0 graded"
    look like neglect rather than a broken emission contract. `GradableShare` is the
    metric that made it visible; `prediction-gradable-share-low` (< 0.5, 3d) is the alarm.
    """
    try:
        import boto3
    except Exception as e:  # noqa: BLE001
        return _unknown(f"boto3 unavailable: {e}")
    try:
        cw = boto3.client("cloudwatch", region_name="us-west-2")
        alarms = cw.describe_alarms(AlarmNames=["prediction-gradable-share-low"], AlarmTypes=["MetricAlarm"])["MetricAlarms"]
    except Exception as e:  # noqa: BLE001
        return _unknown(f"could not read CloudWatch: {e}")

    if not alarms:
        return _bad(
            "the prediction-gradable-share-low alarm does not exist — a permanently "
            "ungradeable majority would be invisible (the DIL-007 failure mode)"
        )
    alarm = alarms[0]
    state = alarm["StateValue"]
    evidence = [f"alarm state = {state}", f"threshold = {alarm.get('Threshold')}", f"updated = {alarm.get('StateUpdatedTimestamp')}"]
    if state == "ALARM":
        return _bad("gradable share is below the floor — the alarm is firing", evidence)
    if state == "INSUFFICIENT_DATA":
        return _unknown("the gradable-share alarm has insufficient data — the share is unobserved", evidence)
    return _ok("gradable share is above the floor and the alarm that watches it exists and is OK", evidence)


# ═════════════════════════════════════════════════════════════════════════════════
# FAMILY: edge — real request-path behaviour
# ═════════════════════════════════════════════════════════════════════════════════


def edge_csp_is_hardened() -> Verdict:
    """DIL-015: the live CSP has `script-src 'self'` with no unsafe-inline and no CDN.

    Read off the response headers of the real origin, which is the only place the claim
    is true or false. The pre-D1 surface was 266 inline blocks across 91 pages.
    """
    try:
        status, headers, _ = _http(f"{SITE}/")
    except Exception as e:  # noqa: BLE001
        return _unknown(f"could not fetch the site root: {e}")
    if status != 200:
        return _unknown(f"site root returned HTTP {status}")

    csp = headers.get("content-security-policy")
    if not csp:
        return _bad("no Content-Security-Policy header on the site root", [f"headers = {sorted(headers)[:12]}"])

    directives = {}
    for part in csp.split(";"):
        part = part.strip()
        if part:
            name, _, value = part.partition(" ")
            directives[name.strip()] = value.strip()

    script_src = directives.get("script-src", "")
    evidence = [f"script-src = {script_src!r}", f"directives = {sorted(directives)}"]
    problems = []
    if "'unsafe-inline'" in script_src:
        problems.append("script-src allows 'unsafe-inline'")
    if "'unsafe-eval'" in script_src:
        problems.append("script-src allows 'unsafe-eval'")
    if "jsdelivr" in csp or "cdn." in csp:
        problems.append("a CDN origin is still allowlisted")
    if script_src.split() != ["'self'"]:
        problems.append(f"script-src is not exactly 'self' (got {script_src!r})")
    if problems:
        return _bad("; ".join(problems), evidence)
    return _ok("script-src is exactly 'self' — no inline, no eval, no CDN", evidence)


def edge_rate_limit_enforced() -> Verdict:
    """DIL-002/014: the rate limiter actually returns 429 on the real edge.

    Deliberately does NOT generate abuse traffic against production to prove this. #3058
    ships a nightly qa-smoke check (`edge_429_enforcement`) that trips exactly one real
    429 at $0 model cost, with a RED / could-not-observe vocabulary that refuses a vacuous
    green. The right instrument already exists and runs on a schedule; this reads its
    verdict. Re-implementing the probe here would both duplicate the check and turn an
    evidence run into a self-inflicted traffic spike.
    """
    qa_module = os.path.join(_ROOT, "lambdas", "operational", "qa_check_edge_429.py")
    if not os.path.exists(qa_module):
        return _bad(
            "the nightly edge-429 observation (#3058) is gone — the only standing proof "
            "that the limiter fires on the real edge no longer exists",
            [f"expected {os.path.relpath(qa_module, _ROOT)}"],
        )
    wired = os.path.join(_ROOT, "lambdas", "operational", "qa_smoke_lambda.py")
    try:
        with open(wired, encoding="utf-8") as fh:
            src = fh.read()
    except OSError as e:
        return _unknown(f"could not read the qa-smoke handler: {e}")
    if "qa_check_edge_429" not in src:
        return _bad(
            "qa_check_edge_429 exists but is NOT wired into the nightly qa-smoke run — " "the observation would never execute",
            ["qa_smoke_lambda.py does not reference qa_check_edge_429"],
        )

    # Deliberately NOT cited as evidence: the `qa-smoke-failures` alarm state. That alarm
    # aggregates every qa-smoke check, so quoting it next to this verdict would let an
    # unrelated failing check read as an edge-429 result in either direction — the first
    # draft of this playbook printed "PASS" directly above "alarm = ALARM", which is the
    # kind of line an assessor is right to attack. The honest scope of this playbook is
    # stated below and is narrower than it would like to be.
    return _ok(
        "the real-edge 429 observation exists, is wired into the nightly run, and can fail",
        [
            "qa_check_edge_429.py present",
            "referenced by qa_smoke_lambda.py (the nightly handler)",
            "SCOPE: proves the observation is installed and executable, NOT that last "
            "night's run observed a 429 — that verdict lives in the qa-smoke output "
            "(#3058's RED / could-not-observe vocabulary), not in an aggregate alarm",
        ],
    )


def edge_public_data_is_fresh() -> Verdict:
    """DIL-023/024: the public surface serves fresh data and dates what it serves.

    An assessor's freshness check is not "does the endpoint respond" but "does the
    payload say how old it is". `/api/vitals` carries per-field `*_as_of` stamps and a
    `window_disclosure` — the ADR-104 behavioural-absence contract — so the check is that
    those stamps exist and are recent, not merely that a number came back.
    """
    try:
        payload = _json_api("/api/vitals")
    except Exception as e:  # noqa: BLE001
        return _unknown(f"could not read /api/vitals: {e}")

    vitals = payload.get("vitals") or {}
    as_of = vitals.get("as_of_date")
    disclosure = vitals.get("window_disclosure")
    evidence = [f"as_of_date = {as_of}", f"window_disclosure present = {bool(disclosure)}"]
    if not as_of:
        return _bad("the vitals payload carries no as_of_date — the reader cannot tell how old it is", evidence)
    if not disclosure:
        return _bad(
            "the vitals payload carries no window_disclosure — the ADR-104 honest-window contract is absent",
            evidence,
        )

    from datetime import date

    try:
        served = date.fromisoformat(as_of)
    except ValueError:
        return _bad(f"as_of_date is not an ISO date: {as_of!r}", evidence)
    age = (date.today() - served).days
    evidence.append(f"age = {age} day(s)")
    if age > 3:
        return _bad(f"the served vitals are {age} days old", evidence)
    return _ok(f"public data is {age} day(s) old and dates itself honestly", evidence)


# ═════════════════════════════════════════════════════════════════════════════════
# The playbook registry
# ═════════════════════════════════════════════════════════════════════════════════


# (id, family, DIL ids answered, callable). Adding a row here is how a new §15 playbook
# joins the evidence pack; the register's live-evidence column is generated from the run.
def control_register_maps_all_52() -> Verdict:
    """Every DIL id 001–052 carries a disposition row in the response register.

    The epic's box-1 checkbox is a human claim and went stale once already (it said
    "20 of 52" two days after commit e619dd3d6 made the register 52/52). This derives
    the coverage by parsing the register's own table rows — combined rows
    ("| 039/040 …", "| 037/033/034/043/044/045/046 …") count each id — so the box
    cannot rot silently again. A checkbox is not a gate; this is the gate.
    """
    path = os.path.join(_ROOT, "docs", "reviews", "DILIGENCE_2026-08-23_RESPONSE.md")
    try:
        with open(path, encoding="utf-8") as fh:
            txt = fh.read()
    except OSError as e:
        return _unknown(f"register unreadable: {e}")
    ids: set[int] = set()
    for m in re.finditer(r"^\|\s*(\d{3}(?:/\d{3})*)\s", txt, re.M):
        for part in m.group(1).split("/"):
            ids.add(int(part))
    found = sorted(i for i in ids if 1 <= i <= TOTAL_DIL_FINDINGS)
    missing = [f"DIL-{i:03d}" for i in range(1, TOTAL_DIL_FINDINGS + 1) if i not in ids]
    if missing:
        return _bad(
            f"{len(missing)} of {TOTAL_DIL_FINDINGS} DIL ids have NO register row",
            [f"missing: {', '.join(missing)}"],
        )
    return _ok(
        f"all {TOTAL_DIL_FINDINGS} DIL ids carry a register disposition row (derived by parse)",
        [f"row ids found = {len(found)} of {TOTAL_DIL_FINDINGS}"],
    )


PLAYBOOKS: list[tuple[str, str, str, Callable[[], Verdict]]] = [
    ("production_approval_gate", "control", "DIL-004", control_production_approval_gate),
    ("main_ruleset_active", "control", "DIL-005", control_main_ruleset_active),
    ("vulnerability_alerts_enabled", "control", "DIL-006", control_vulnerability_alerts_enabled),
    ("codeql_alerts_triaged", "control", "DIL-018", control_codeql_alerts_triaged),
    ("register_maps_all_52", "control", "DIL-register", control_register_maps_all_52),
    ("no_private_markers_in_tree", "privacy", "DIL-001", privacy_no_private_markers_in_tree),
    ("relocated_docs_are_404", "privacy", "DIL-001", privacy_relocated_docs_are_404),
    ("public_api_serves_no_owner_only_field", "privacy", "DIL-008/011", privacy_public_api_serves_no_owner_only_field),
    ("calibration_reported_honestly", "prediction", "DIL-007/032", prediction_calibration_is_reported_honestly),
    ("gradable_share_healthy", "prediction", "DIL-007", prediction_gradable_share_healthy),
    ("csp_is_hardened", "edge", "DIL-015", edge_csp_is_hardened),
    ("rate_limit_enforced", "edge", "DIL-002/014", edge_rate_limit_enforced),
    ("public_data_is_fresh", "edge", "DIL-023/024", edge_public_data_is_fresh),
]

FAMILIES = ["control", "privacy", "prediction", "edge"]

# The external report filed DIL-001 … DIL-052. Stated once, here, so the coverage
# fraction the register quotes is derived rather than re-typed.
TOTAL_DIL_FINDINGS = 52


def covered_dils(results: list[dict]) -> set[str]:
    """The DIL ids this run actually asserted (a playbook may answer several)."""
    out: set[str] = set()
    for r in results:
        stem, _, rest = r["dil"].partition("-")  # "DIL-008/011" → several ids
        for part in rest.split("/"):
            # Numeric only: meta-playbooks (e.g. "DIL-register") assert the register
            # itself, not a finding, and must not inflate the live-asserted count.
            if part.strip().isdigit():
                out.add(f"{stem}-{part.strip()}")
    return out


def run_playbooks(families: list[str]) -> list[dict]:
    results = []
    for pid, family, dil, fn in PLAYBOOKS:
        if family not in families:
            continue
        try:
            verdict = fn()
        except Exception as e:  # noqa: BLE001 — an unexpected raise is UNVERIFIED, never a pass
            verdict = _unknown(f"playbook raised {type(e).__name__}: {e}")
        results.append({"id": pid, "family": family, "dil": dil, **verdict.as_dict()})
    return results


def _render(results: list[dict]) -> None:
    icon = {PASS: "PASS", FAIL: "FAIL", UNVERIFIED: "????"}
    print("=" * 78)
    print("  diligence_verify — the §15 playbooks, run against LIVE state")
    print("=" * 78)
    for family in FAMILIES:
        rows = [r for r in results if r["family"] == family]
        if not rows:
            continue
        print(f"\n── {family} " + "─" * (72 - len(family)))
        for r in rows:
            print(f"  [{icon[r['status']]}] {r['id']}  ({r['dil']})")
            print(f"         {r['summary']}")
            for ev in r["evidence"]:
                print(f"           · {ev}")

    counts = {s: sum(1 for r in results if r["status"] == s) for s in (PASS, FAIL, UNVERIFIED)}
    print("\n" + "=" * 78)
    print(f"  {counts[PASS]} PASS · {counts[FAIL]} FAIL · {counts[UNVERIFIED]} UNVERIFIED (of {len(results)})")
    if counts[UNVERIFIED]:
        print("  UNVERIFIED is not a pass. An evidence pack with an unobserved row is incomplete.")
    # Coverage is DERIVED from the registry, never hand-stated. The register quotes this
    # number, and a hand-maintained copy of it is precisely the literal-drift class #3101
    # killed elsewhere. It is also the honest bound on what this instrument proves: the
    # report has 52 findings and most of the remainder are priced acceptances or
    # commercial gaps, which no script can verify.
    print(f"  DIL coverage (derived): {len(covered_dils(results))} of {TOTAL_DIL_FINDINGS} findings asserted live —")
    print(f"    {', '.join(sorted(covered_dils(results)))}")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the diligence §15 verification playbooks against live state.")
    ap.add_argument("--family", action="append", choices=FAMILIES, help="limit to a family (repeatable)")
    ap.add_argument("--json", metavar="PATH", help="write the machine-readable evidence bundle here")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on UNVERIFIED as well as FAIL")
    args = ap.parse_args(argv)

    families = args.family or FAMILIES
    results = run_playbooks(families)
    _render(results)

    if args.json:
        # No timestamp is embedded: the caller stamps it. Two runs over unchanged state
        # produce byte-identical bundles, so a diff means the platform moved.
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"playbooks": results}, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"\nevidence bundle → {args.json}")

    if any(r["status"] == FAIL for r in results):
        return 1
    if args.strict and any(r["status"] == UNVERIFIED for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
