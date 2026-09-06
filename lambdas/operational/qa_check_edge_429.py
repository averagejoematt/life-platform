"""qa_check_edge_429.py — #2828: the nightly real-edge 429 observation.

Answers the standing question the 2026-08-14 P2 incident left open: **"is rate
limiting enforced at the edge right now?"** That incident had the in-Lambda
limiter silently unenforced for ~40 min while 18,421 tests and every CI gate
stayed green — the defect lived between the code and CloudFront, which every
fixture ASSERTS rather than OBSERVES. The only detector was a manual live-probe
habit. This check makes that habit a scheduled observation.

Mechanism (reuses `deploy/probe_rate_limiter.py`'s trip429 design — #1439):
POST `/api/board_ask` with a deliberately too-short question ("hi"). Reading
`_handle_board_ask` (site_api_ai_lambda.py): the entry rate charge
(`_board_rate_charge`) takes ONE token BEFORE the question-length rejection, so
every probe request increments the real counter and then 400s at the length
check — $0 model spend, no email, no reader quota touched (the counter is
per-IP and this Lambda's egress IP is not a reader's). #3560 moved the $0
hazard gate and the budget pause AHEAD of that charge; neither disturbs the
probe ("hi" is benign, and tier 3 is the ⏸ arm below), and the ordering this
probe depends on is pinned by tests/test_qa_check_edge_429.py. After BOARD_RATE_LIMIT charges, the next request must return a
real 429. The code cannot be imported here (importing the web handler would
run its import-time AWS wiring inside qa-smoke), so `MAX_PROBES` is a local
constant PINNED to the source by tests/test_qa_check_edge_429.py (AST read of
BOARD_RATE_LIMIT — the #2510-family lockstep idiom, no runtime import).

Outcome vocabulary (no vacuous green — #2828's acceptance):
  * PASS   — a real 429 observed within MAX_PROBES requests, carrying a
             `Retry-After` header and a JSON `error` body (the full shape).
  * FAIL   — every probe returned a definitive non-429 (the 2026-08-14
             signature: unmetered writes), OR a 429 arrived with the wrong
             shape, OR a <5-char question came back 200-unpaused (the probe's
             charge-before-validation premise broke — either way a human must
             look).
  * YELLOW — the probe could not run (network error / 5xx / timeout): reported
             as "could not observe", never as enforcement-fail and never as
             green.
  * PAUSED — budget tier 3: `_ai_paused_response` short-circuits board_ask
             BEFORE the rate check, so no 429 is observable. Shown ⏸ like
             every other deliberately-paused surface (#1927), not a fault.

Partition: CONTENT_TRUTH. The causal test (qa_check.py): a nightly
enforcement-drift finding is not evidence about a deploy that landed minutes
ago, and a fleet rollback would not repair a CloudFront/policy/DDB cause — the
08-14 instance happened to be deploy-caused, but this check runs on the
nightly clock, not the deploy path, and detection (not rollback) is #2828's
contract.

Lives outside qa_smoke_lambda because that module sits at the 1200-line hard
ceiling (#1665) — same cohesive-split idiom as qa_check_as_of (#2414).
"""

import json
import urllib.error
import urllib.request

from operational.qa_check import CONTENT_TRUTH, Check
from operational.qa_check_reader_truth import SITE_BASE_URL

# BOARD_RATE_LIMIT (7/hr since #3419) + 1 — enough to observe one real 429.
# Pinned to lambdas/web/site_api_ai_lambda.py's constant by the lockstep test;
# never imported at runtime (see module docstring).
MAX_PROBES = 8

_ENDPOINT = "/api/board_ask"
_TIMEOUT_S = 10


def _post_once(url):
    """One probe POST. Returns (status:int, headers:dict, body:str).

    urllib raises on 4xx/5xx; both arms funnel into the same tuple so the
    caller reasons about statuses, not exception types. Network-level failures
    (URLError, timeout) propagate — the caller maps them to YELLOW.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps({"question": "hi"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def _is_paused_body(body):
    """True when board_ask answered with the budget-guard 'paused' payload
    (HTTP 200, served before the rate check at tier 3)."""
    try:
        return "paused" in json.loads(body).get("status", "")
    except Exception:
        return False


def checks():
    c = Check("ratelimit:edge_429", "Rate-limit enforcement", CONTENT_TRUTH)
    url = f"{SITE_BASE_URL}{_ENDPOINT}"
    statuses = []
    for i in range(1, MAX_PROBES + 1):
        try:
            status, headers, body = _post_once(url)
        except Exception as e:
            # Probe could not run — visible yellow, never a vacuous green and
            # never an enforcement verdict (#2828: distinguish the two).
            c.passed = None
            c.message = f"could not observe (request {i}/{MAX_PROBES}: {type(e).__name__}: {e}) — statuses so far {statuses}"
            return [c]
        statuses.append(status)
        if status == 429:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            try:
                has_error_key = "error" in json.loads(body)
            except Exception:
                has_error_key = False
            if retry_after and has_error_key:
                c.passed = True
                c.message = f"real edge 429 observed after {i} request(s) (Retry-After={retry_after})"
            else:
                c.passed = False
                c.message = f"429 observed but shape wrong (Retry-After={retry_after!r}, json-error-key={has_error_key})"
            return [c]
        if status == 200:
            if _is_paused_body(body):
                # Budget tier 3 short-circuits board_ask before the rate
                # check — no 429 is observable tonight. Deliberate pause, ⏸.
                c.passed = None
                c.paused = True
                c.message = f"budget pause preempts the rate check (tier-3 'paused' payload on request {i}) — no observation possible"
                return [c]
            # A <5-char question processed?! The charge-before-validation
            # premise broke — the probe can no longer prove anything. Red.
            c.passed = False
            c.message = (
                f"probe premise broken: 200 (non-paused) on a too-short question at request {i} — re-read _handle_board_ask ordering"
            )
            return [c]
        if status >= 500:
            c.passed = None
            c.message = f"could not observe (HTTP {status} on request {i}/{MAX_PROBES}) — statuses so far {statuses}"
            return [c]
        # 400 (expected pre-limit) or another definitive 4xx: keep probing.
    # Every request got a definitive non-429 answer: the 2026-08-14 signature.
    c.passed = False
    c.message = f"NO 429 after {MAX_PROBES} requests (statuses {statuses}) — rate limiting is NOT observably enforced at the edge (the 2026-08-14 class)"
    return [c]
