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

  AC1  When `CloudFront-Viewer-Address` is present, NO `X-Forwarded-For` in any
       position can move the derived identity. Asserted as an invariant over
       adversarial chains rather than as "index -1 vs index 0", so no future
       re-indexing can satisfy it — and so that attaching the origin request policy is
       provably sufficient to close the bypass with no further code change.
  AC2  `CloudFront-Viewer-Address` — set by CloudFront from the TCP peer and not
       client-influenceable — is preferred, with its port stripped (v4 and v6).
  AC3  When `CloudFront-Viewer-Address` is ABSENT, identity FAILS CLOSED: every such
       caller collapses into one shared bucket. `X-Forwarded-For` is not consulted at
       all, because it is caller-chosen and rotating it is the bypass. `sourceIp` is
       not used either — measured 2026-08-14 it is the CloudFront EDGE address, not
       stable per viewer (6 requests against a 3/hour limit gave
       `400 429 400 400 400 400`, i.e. almost no enforcement), so it fails OPEN in
       practice. Absence is loud, not silent: `client_ip_is_trusted()` returns False.
       Superseded the forgeable interim on 2026-08-21, once the origin request policy
       was deployed and the header verified arriving (six POSTs, six DIFFERENT forged
       `X-Forwarded-For` values, limited at exactly 3/hour).
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
def test_forwarded_for_cannot_override_the_trusted_header(chain):
    """THE load-bearing assertion, and the one the old guard could not make.

    Scoped deliberately to "the trusted header is present". Rotating X-Forwarded-For is
    the live exploit, and the only thing that actually closes it is deriving identity
    from a value CloudFront sets. What this pins is that once `CloudFront-Viewer-Address`
    arrives, NO X-Forwarded-For in any position can move the answer — so attaching the
    origin request policy is sufficient, with no further code change.
    """
    derived = extract_client_ip(_event(viewer=f"{VIEWER}:16225", xff=chain))
    assert derived == VIEWER, f"X-Forwarded-For {chain!r} overrode the trusted header"


def test_the_trusted_header_collapses_every_adversarial_chain_to_one_identity():
    """Stated set-wise too, so a partial fix cannot pass the parametrised form."""
    derived = {extract_client_ip(_event(viewer=f"{VIEWER}:16225", xff=c)) for c in ADVERSARIAL_CHAINS}
    assert derived == {VIEWER}, f"forged chains produced {len(derived)} distinct buckets: {derived}"


# ── The interim, stated out loud so it cannot be mistaken for a guarantee ──────


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


def test_absent_trusted_header_fails_closed_to_one_shared_bucket():
    """The point of the whole issue: without the trusted header, an attacker must not
    be able to mint a fresh bucket. Every shape collapses to the SAME identity."""
    derived = {
        extract_client_ip(_event()),
        extract_client_ip(_event(xff="1.1.1.1")),
        extract_client_ip(_event(xff="9.9.9.9, 2.2.2.2")),
        extract_client_ip({"headers": {}, "requestContext": {}}),
    }
    assert len(derived) == 1, f"fail-closed leaked {len(derived)} distinct buckets: {derived}"


def test_fail_closed_identity_is_not_caller_derived():
    """A constant, not anything read off the request — anything request-derived is
    attacker-chosen, which is the bypass itself."""
    for xff in ("evil", "1.1.1.1", "9.9.9.9, 2.2.2.2", "", "   "):
        got = extract_client_ip(_event(xff=xff))
        assert xff.strip() not in got or not xff.strip(), f"fail-closed identity echoed caller input: {got!r}"


def test_source_ip_is_not_used_as_a_middle_ground():
    """`sourceIp` is the CloudFront EDGE address — un-forgeable but not stable per
    viewer, so it fails OPEN in practice (measured 2026-08-14). Pinning its absence
    so a future 'safer fallback' refactor cannot quietly reintroduce it."""
    assert extract_client_ip(_event()) != EDGE


def test_the_default_argument_no_longer_silently_applies():
    """`default=` used to surface when nothing at all was present. Under fail-closed
    the trusted header is the ONLY thing that changes the answer, so a caller-supplied
    default must not become a second identity source."""
    assert extract_client_ip({}, default="sentinel") == extract_client_ip({})


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
