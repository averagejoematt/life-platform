"""#1221 — the rate-limit identity was derived from a value the caller chooses.

WHAT THE OLD GUARD GOT WRONG (docs/CONVENTIONS.md §9a)
------------------------------------------------------

`tests/test_client_ip_extraction.py` was green, non-vacuous, and mutation-provable —
its author wrote `test_non_vacuity_old_leftmost_logic_would_have_failed` specifically
to prove the previous logic failed it. It still guarded nothing, because its fixture
hand-built `X-Forwarded-For: "evil-spoof, 203.0.113.9"`, encoding the assumption that
CloudFront appends a trustworthy last hop. #1221 was filed, "fixed" by flipping
first-hop→last-hop, closed, and guarded by a test that verified the function did what
its author intended in a universe the wire does not share.

So this file does NOT assert a hop index. It asserts the contract that was MEASURED
against the deployed edge on 2026-08-14, using `/api/submit_finding` (limit 3/hour,
rate check before the body parse, so a malformed body probes the limiter without
writing anything):

    X-Forwarded-For: 203.0.113.77   x5  ->  400 400 400 429 429   (bucket armed)
    X-Forwarded-For: 198.51.100.42  x2  ->  400 400               (FRESH bucket)
    no header at all                x5  ->  400 400 400 429 429   (a third bucket)

Had CloudFront appended a trailing hop, run 2 would have shared run 1's bucket and
returned 429. It did not. The only model fitting all three runs: CloudFront forwards
the client's `X-Forwarded-For` unchanged and adds its own only when absent — so the
last hop IS the caller's value, in every position.

The contract that follows, and that this file pins:

  AC1  `X-Forwarded-For` is never consulted, in any position. This is asserted as an
       invariant over adversarial chains rather than as "index -1 vs index 0", so no
       future re-indexing can satisfy it.
  AC2  `CloudFront-Viewer-Address` — set by CloudFront from the TCP peer and not
       client-influenceable — is preferred, with its port stripped (v4 and v6).
  AC3  The un-forgeable `sourceIp` is the only fallback, and the degraded state is
       reportable via `client_ip_is_trusted()` rather than silent.
  AC4  GUARD THE SET: no handler anywhere may derive an identity from a raw
       `sourceIp` or `X-Forwarded-For` read. Derived by AST, so a NEW handler that
       keys on either fails this suite the day it lands.

NOTE the remaining half of #1221 is infrastructure and owner-run: `/api/*` carries
`OriginRequestPolicyId: null` (verified live 2026-08-14), so `CloudFront-Viewer-Address`
does not reach the origin yet. Until the policy is attached the fallback is in force —
un-forgeable but coarser. These tests pin the code contract; they cannot pin the edge.
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, _REPO)

from common.client_ip import client_ip_is_trusted, extract_client_ip  # noqa: E402

VIEWER = "198.51.100.11"
EDGE = "203.0.113.9"


def _event(*, xff=None, viewer=None, source_ip=EDGE):
    headers = {}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    if viewer is not None:
        headers["CloudFront-Viewer-Address"] = viewer
    return {
        "headers": headers,
        "requestContext": {"http": {"method": "POST", "sourceIp": source_ip}},
    }


# ── AC1: X-Forwarded-For is never an identity, in any position ────────────────

# Every one of these is a chain an attacker can send verbatim. The derived identity
# must be identical for all of them, because none of it is trustworthy input.
ADVERSARIAL_CHAINS = [
    "1.1.1.1",
    "1.1.1.1, 2.2.2.2",
    "2.2.2.2, 1.1.1.1",
    "1.1.1.1, 2.2.2.2, 3.3.3.3",
    f"{VIEWER}, 9.9.9.9",
    f"9.9.9.9, {VIEWER}",
    "   4.4.4.4   ,   5.5.5.5   ",
    "not-an-ip-at-all",
    "",
]


@pytest.mark.parametrize("chain", ADVERSARIAL_CHAINS)
def test_forwarded_for_never_changes_the_identity(chain):
    """The load-bearing assertion, and the one the old guard could not make.

    Rotating X-Forwarded-For is the actual live exploit — a new forged value bought a
    fresh rate-limit bucket. So the property is not "read a different hop", it is
    "this header cannot move the answer at all".
    """
    assert extract_client_ip(_event(xff=chain)) == EDGE, f"X-Forwarded-For {chain!r} influenced the derived identity"


def test_every_adversarial_chain_yields_one_single_identity():
    """Stated set-wise as well, so a partial fix cannot pass the parametrised form."""
    derived = {extract_client_ip(_event(xff=c)) for c in ADVERSARIAL_CHAINS}
    assert derived == {EDGE}, f"forgeable chains produced {len(derived)} distinct buckets: {derived}"


def test_non_vacuity_the_old_last_hop_logic_would_have_failed_this():
    """Proves the suite can fail — against the implementation that actually shipped.

    The previous helper returned the last X-Forwarded-For hop. Under the measured edge
    behaviour that is the caller's own value, so these two requests landed in DIFFERENT
    buckets and the limiter was evadable. The current helper must put them in the same
    one.
    """

    def _old_last_hop(event):
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        hops = [h.strip() for h in (headers.get("x-forwarded-for") or "").split(",") if h.strip()]
        return hops[-1] if hops else event["requestContext"]["http"]["sourceIp"]

    a, b = _event(xff="203.0.113.77"), _event(xff="198.51.100.42")
    assert _old_last_hop(a) != _old_last_hop(b), "fixture no longer reproduces the old behaviour"
    assert extract_client_ip(a) == extract_client_ip(b), "the forged values still buy separate buckets"


# ── AC2: the trustworthy header wins, port stripped ───────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("198.51.100.11:16225", "198.51.100.11"),
        ("198.51.100.11", "198.51.100.11"),
        ("  198.51.100.11:443  ", "198.51.100.11"),
        ("2001:db8::1:5000", "2001:db8::1"),  # v6: port split off the RIGHT
        ("[2001:db8::1]:443", "2001:db8::1"),  # bracketed v6
        ("2001:db8::1", "2001:db8::1"),
    ],
)
def test_viewer_address_is_used_and_its_port_stripped(raw, expected):
    assert extract_client_ip(_event(viewer=raw)) == expected


def test_the_port_is_stripped_so_one_viewer_is_one_bucket():
    """Why stripping wins the IPv6 ambiguity — a design decision, pinned.

    `2001:db8::1:5000` is simultaneously a valid address AND that address plus port
    5000. The port changes per connection, so keeping it would mint a fresh bucket for
    every request and defeat the limiter exactly as thoroughly as the forgeable header
    this replaces. One viewer across many ephemeral ports must be ONE identity.
    """
    for family in (["198.51.100.11:%d" % p for p in (1, 1024, 51000, 65535)], ["2001:db8::1:%d" % p for p in (1, 1024, 51000)]):
        derived = {extract_client_ip(_event(viewer=v)) for v in family}
        assert len(derived) == 1, f"ephemeral ports split one viewer into {len(derived)} buckets: {derived}"


def test_a_bare_address_survives_stripping():
    """The other side of that trade: stripping must not corrupt a portless value.

    `2001:db8::1` → naive right-split gives the garbage `2001:db8:`. CloudFront always
    sends a port so this is not an observed input, but a mangled identity would be
    silently wrong rather than loudly broken, which is the worst failure mode here.
    """
    assert extract_client_ip(_event(viewer="2001:db8::1")) == "2001:db8::1"
    assert extract_client_ip(_event(viewer="198.51.100.11")) == "198.51.100.11"


def test_viewer_address_beats_a_forged_forwarded_for():
    """A caller supplying both must not be able to override the trustworthy value."""
    assert extract_client_ip(_event(viewer=f"{VIEWER}:16225", xff="1.1.1.1, 2.2.2.2")) == VIEWER


# ── AC3: the fallback, and its observability ──────────────────────────────────


def test_falls_back_to_source_ip_when_the_policy_is_not_attached():
    """Today's live state: OriginRequestPolicyId is null, so the header never arrives."""
    assert extract_client_ip(_event()) == EDGE


def test_default_only_when_there_is_nothing_at_all():
    assert extract_client_ip({"headers": {}, "requestContext": {}}) == "unknown"
    assert extract_client_ip({}, default="sentinel") == "sentinel"


def test_trust_is_reported_not_silent():
    """The degraded window must be observable — "green while guarding nothing" is
    the exact failure #1221 was for a month."""
    assert client_ip_is_trusted(_event(viewer=f"{VIEWER}:16225")) is True
    assert client_ip_is_trusted(_event()) is False
    assert client_ip_is_trusted(_event(xff="1.1.1.1")) is False, "a forged header must never read as trusted"


def test_header_lookup_is_case_insensitive():
    """API Gateway and Function URLs differ in header casing; both must work."""
    for key in ("cloudfront-viewer-address", "CloudFront-Viewer-Address", "CLOUDFRONT-VIEWER-ADDRESS"):
        assert extract_client_ip({"headers": {key: f"{VIEWER}:1"}, "requestContext": {}}) == VIEWER


# ── AC4: guard the SET — no handler may derive identity itself ────────────────

_ALLOWED = {"client_ip.py"}  # the one helper that is *allowed* to read the raw envelope


def _raw_identity_reads() -> list:
    """Every place outside the helper that reads sourceIp or X-Forwarded-For.

    Derived by AST over the whole lambdas/ tree, so a newly added handler keying on
    either one fails this test the day it lands — the instance-by-instance version of
    this fix is what let site_api_ai_lambda stay the lone holdout for a month.
    """
    hits = []
    for p in pathlib.Path(_REPO, "lambdas").rglob("*.py"):
        if p.name in _ALLOWED:
            continue
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        # A dict LITERAL key is construction, not derivation — the AI-quality canary
        # builds a synthetic FunctionURL event (`{"sourceIp": CANARY_IP}`) to invoke
        # site-api-ai. That is a producer of an envelope, not a consumer deriving an
        # identity from one, and flagging it would be a false positive.
        constructed = {id(k) for node in ast.walk(tree) if isinstance(node, ast.Dict) for k in node.keys if k is not None}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in constructed:
                if node.value in ("sourceIp", "x-forwarded-for", "X-Forwarded-For"):
                    hits.append(f"{p.relative_to(_REPO)}:{node.lineno} → {node.value!r}")
    return sorted(hits)


def test_no_handler_derives_its_own_client_identity():
    offenders = _raw_identity_reads()
    assert not offenders, "these must call common.client_ip.extract_client_ip instead:\n  " + "\n  ".join(offenders)


def test_the_set_guard_can_actually_fail():
    """A mutation must actually mutate — proves the AST walk sees these literals."""
    import tempfile

    with tempfile.TemporaryDirectory(dir=os.path.join(_REPO, "lambdas")) as d:
        probe = pathlib.Path(d, "probe_handler.py")
        probe.write_text('def h(e):\n    return e["requestContext"]["http"]["sourceIp"]\n')
        assert any("probe_handler.py" in h for h in _raw_identity_reads()), "the AST walk does not detect a raw sourceIp read"
