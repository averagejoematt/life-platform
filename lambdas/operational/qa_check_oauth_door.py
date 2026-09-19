"""qa_check_oauth_door.py — #3620 (security ROW6): the nightly MCP OAuth-door observation.

The clause this serves ("the remote-MCP auth door is consent-gated, PKCE-bound and
never an open redirect") had, until now, exactly two kinds of evidence: unit
fixtures, which assert the code's shape rather than the door's behaviour, and one
manual probe run by the reviewer inside the review that graded it. The rate limit
standing beside it in the same clause has had a real nightly observation since
#2828 (`qa_check_edge_429.py`, in this directory) — so the pattern to copy was
already here, and what was missing was only that nobody had pointed it at this
door.

Four probes against the LIVE Function URL, each one a property that has a
plausible way to break silently:

  1. `/authorize` with an ALLOWED redirect returns the consent FORM (200 HTML),
     not a 302. A 302 here is #893's defect exactly: the door auto-approving
     anyone who knows the URL. The form is the gate; its absence is the failure.
  2. `/token` with a code this server never minted returns 4xx. A 200 would mean
     the door hands a bearer to an unbound request (#779's defect).
  3. A FOREIGN `redirect_uri` is refused at `/authorize` (4xx). `/register` is
     open dynamic client registration and accepts arbitrary `redirect_uris` — it
     is inert ONLY because `_redirect_uri_allowed` holds a static host allowlist
     that, before this check, nothing observed. A 302 to the foreign host is an
     open redirect that mints a real code.
  4. A POST to the MCP endpoint with no bearer returns 401. This is the bearer
     gate itself; a 200 means the tools are anonymous.

Outcome vocabulary — the #2828 contract, no vacuous green:
  * PASS   — the property was OBSERVED to hold.
  * FAIL   — the property was observed to NOT hold. A human must look; several of
             these are "the door is open right now".
  * YELLOW — could not observe (URL undiscoverable, network error, 5xx, timeout).
             Reported as absence of evidence, never as enforcement-fail and never
             as green.

Explicitly NO metric series of its own (#3620's rent block): qa-smoke's EMF line
carries aggregate Pass/Warn/Fail counts, which is the same information for
$0.00025/mo instead of $0.30/mo. The nightly run and the failure email are the
readout.

Partition: CONTENT_TRUTH — the causal test from qa_check.py. This runs on the
nightly clock, not the deploy path; an allowlist or a Function-URL auth-mode
change is not evidence about a deploy that landed minutes ago, and reverting the
fleet would not repair a door opened by configuration. Detection, not rollback,
is the contract (the same ruling `qa_check_edge_429` records for the same reason).

Lives outside qa_smoke_lambda because that module sits at its 1200-line hard
ceiling (#1665) — the qa_check_as_of / qa_check_edge_429 cohesive-split idiom.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from common.mcp_url import resolve_mcp_url

from operational.qa_check import CONTENT_TRUTH, Check

_TIMEOUT_S = 10

# An allowlisted callback (mcp/handler.py::_DEFAULT_REDIRECT_HOSTS — claude.ai is
# the first-party MCP client). Pinned to that tuple by
# tests/test_qa_check_oauth_door.py, which reads the source by AST rather than
# importing the handler (importing mcp/ here would run its AWS wiring inside
# qa-smoke — the same reason qa_check_edge_429 pins BOARD_RATE_LIMIT by AST).
_ALLOWED_REDIRECT = "https://claude.ai/api/mcp/auth_callback"

# Deliberately NOT an allowlisted host, and deliberately not a real domain that
# could ever receive a code. If `/authorize` ever 302s here, the door is an open
# redirect and the probe's own target is inert.
_FOREIGN_REDIRECT = "https://oauth-probe.invalid/cb"


def _request(url, *, method="GET", data=None, headers=None):
    """One probe. Returns (status:int, headers:dict, body:str).

    urllib raises on 4xx/5xx; both arms funnel into the same tuple so the caller
    reasons about statuses, not exception types. Redirects are NOT followed —
    a 302 is the answer here, not a step on the way to one. Network-level
    failures propagate; the caller maps them to YELLOW.
    """
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=_TIMEOUT_S) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def _yellow(c, why):
    c.passed = None
    c.message = f"could not observe ({why})"
    return c


def _authorize_url(base, redirect_uri):
    qs = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": "qa-smoke-oauth-probe",
            "redirect_uri": redirect_uri,
            "state": "qa-smoke-3620",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        }
    )
    return f"{base.rstrip('/')}/authorize?{qs}"


def _check_consent_form(base):
    """#893: /authorize must present the consent gate, never auto-approve."""
    c = Check("oauth:consent_form", "MCP OAuth door", CONTENT_TRUTH)
    try:
        status, headers, body = _request(_authorize_url(base, _ALLOWED_REDIRECT))
    except Exception as e:
        return _yellow(c, f"{type(e).__name__}: {e}")
    if status in (301, 302, 303, 307, 308):
        c.passed = False
        c.message = f"/authorize AUTO-APPROVED an allowed redirect ({status} → {headers.get('Location', '?')[:80]}) — the consent gate is not holding (#893)"
        return c
    if status >= 500:
        return _yellow(c, f"HTTP {status} from /authorize")
    if status == 200 and "<form" in body.lower():
        c.passed = True
        c.message = "/authorize returned the consent form (200, no redirect) on an allowed redirect_uri"
        return c
    c.passed = False
    c.message = f"/authorize answered {status} with no consent form on an ALLOWED redirect_uri — the door is not reachable by its own first-party client"
    return c


def _check_token_without_code(base):
    """#779: /token may only exchange a code this server actually issued."""
    c = Check("oauth:token_unbound", "MCP OAuth door", CONTENT_TRUTH)
    payload = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": "qa-smoke-code-that-was-never-minted-3620",
            "code_verifier": "qa-smoke-verifier-3620-qa-smoke-verifier-3620-x",
            "redirect_uri": _ALLOWED_REDIRECT,
        }
    ).encode()
    try:
        status, _h, body = _request(
            f"{base.rstrip('/')}/token",
            method="POST",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except Exception as e:
        return _yellow(c, f"{type(e).__name__}: {e}")
    if status >= 500:
        return _yellow(c, f"HTTP {status} from /token")
    if status == 200:
        c.passed = False
        c.message = "/token returned 200 for a code this server NEVER minted — it is handing out bearers to unbound requests (#779)"
        return c
    if 400 <= status < 500:
        c.passed = True
        c.message = f"/token refused an unminted code ({status})"
        return c
    c.passed = False
    c.message = f"/token answered an unexpected {status} for an unminted code (body {body[:80]!r})"
    return c


def _check_foreign_redirect_refused(base):
    """The open-redirect property. /register mints arbitrary redirect_uris; only
    /authorize's static allowlist stops one being honoured."""
    c = Check("oauth:foreign_redirect", "MCP OAuth door", CONTENT_TRUTH)
    registered = "not attempted"
    try:
        reg_status, _h, _b = _request(
            f"{base.rstrip('/')}/register",
            method="POST",
            data=json.dumps({"redirect_uris": [_FOREIGN_REDIRECT], "client_name": "qa-smoke-oauth-probe"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        registered = f"/register → {reg_status}"
    except Exception as e:
        # A /register failure does not invalidate the probe: the property under
        # test is what /authorize does with a foreign redirect_uri, registered
        # or not. Recorded in the message so the two are never conflated.
        registered = f"/register unreachable ({type(e).__name__})"
    try:
        status, headers, _body = _request(_authorize_url(base, _FOREIGN_REDIRECT))
    except Exception as e:
        return _yellow(c, f"{type(e).__name__}: {e} [{registered}]")
    if status >= 500:
        return _yellow(c, f"HTTP {status} from /authorize [{registered}]")
    if status in (301, 302, 303, 307, 308):
        c.passed = False
        c.message = f"OPEN REDIRECT: /authorize 302'd a foreign redirect_uri to {headers.get('Location', '?')[:80]} [{registered}]"
        return c
    if 400 <= status < 500:
        c.passed = True
        c.message = f"/authorize refused a foreign redirect_uri ({status}) [{registered}]"
        return c
    c.passed = False
    c.message = f"/authorize answered {status} (not a refusal) for a foreign redirect_uri [{registered}]"
    return c


def _check_mcp_requires_bearer(base):
    """The bearer gate itself: an unauthenticated MCP POST must 401."""
    c = Check("oauth:bearer_required", "MCP OAuth door", CONTENT_TRUTH)
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    try:
        status, _h, _body = _request(
            base,
            method="POST",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
    except Exception as e:
        return _yellow(c, f"{type(e).__name__}: {e}")
    if status >= 500:
        return _yellow(c, f"HTTP {status} from the MCP endpoint")
    if status == 401:
        c.passed = True
        c.message = "MCP POST without a bearer returned 401"
        return c
    if status == 200:
        c.passed = False
        c.message = "MCP POST without a bearer returned 200 — the tool surface is ANONYMOUS"
        return c
    c.passed = False
    c.message = f"MCP POST without a bearer returned {status}, not 401 — the gate's answer is not the documented one"
    return c


def checks():
    """The four probes. Yellow-all when the Function URL cannot be discovered —
    absence of evidence is reported as absence, never as a pass."""
    base = resolve_mcp_url()
    probes = (
        ("oauth:consent_form", _check_consent_form),
        ("oauth:token_unbound", _check_token_without_code),
        ("oauth:foreign_redirect", _check_foreign_redirect_refused),
        ("oauth:bearer_required", _check_mcp_requires_bearer),
    )
    if not base:
        out = []
        for name, _fn in probes:
            c = Check(name, "MCP OAuth door", CONTENT_TRUTH)
            out.append(_yellow(c, "MCP Function URL could not be discovered (lambda:GetFunctionUrlConfig)"))
        return out
    return [fn(base) for _name, fn in probes]
