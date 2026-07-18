"""tests/test_client_ip_extraction.py — #1221 regression guard.

Per-IP rate limiting (subscribe, votes, follows, nudges, checkins, board_ask) is
only sound if the client-IP it keys on cannot be forged by the caller. The `/api/*`
surface is CloudFront-fronted and WAF was removed 2026-06, so there is NO upstream
sanitization: CloudFront appends the edge-observed viewer IP as the LAST hop of
`X-Forwarded-For`, and every earlier hop is client-supplied. The prior helper took
the LEFTMOST hop, so an attacker could forge an arbitrary per-IP bucket per request.

These tests pin the corrected semantics (last hop + sourceIp-only fallback) and,
crucially, prove NON-VACUITY: the same header run through the pre-fix leftmost logic
returns the spoofed value, so this test genuinely fails against the old helper.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from client_ip import extract_client_ip  # noqa: E402


def _ev(headers=None, source_ip=None, identity_ip=None):
    event = {"headers": headers or {}}
    ctx = {}
    if source_ip is not None:
        ctx["http"] = {"sourceIp": source_ip}
    if identity_ip is not None:
        ctx["identity"] = {"sourceIp": identity_ip}
    if ctx:
        event["requestContext"] = ctx
    return event


# ── The core guard: the spoof from the issue ──────────────────────────────────


def test_takes_last_hop_not_client_supplied_leading_value():
    """'evil-spoof, 203.0.113.9' -> the edge-appended last hop, NOT the spoof."""
    ev = _ev(headers={"X-Forwarded-For": "evil-spoof, 203.0.113.9"}, source_ip="130.176.0.1")
    assert extract_client_ip(ev) == "203.0.113.9"


def test_non_vacuity_old_leftmost_logic_would_have_failed():
    """Prove the guard is non-vacuous: the pre-fix leftmost derivation returns the
    spoofed leading value for the exact same header, so this test distinguishes the
    fixed helper from the bug it replaces."""
    header = "evil-spoof, 203.0.113.9"
    # This is the *old* buggy derivation (leftmost hop). Reproduced here only to
    # assert it diverges from the fixed helper.
    old_leftmost = header.split(",")[0].strip()
    assert old_leftmost == "evil-spoof"  # what the old helper returned
    assert extract_client_ip(_ev(headers={"X-Forwarded-For": header})) == "203.0.113.9"
    assert extract_client_ip(_ev(headers={"X-Forwarded-For": header})) != old_leftmost


# ── Coverage the issue asks for ───────────────────────────────────────────────


def test_single_entry_xff():
    assert extract_client_ip(_ev(headers={"X-Forwarded-For": "203.0.113.9"})) == "203.0.113.9"


def test_no_xff_falls_back_to_source_ip():
    assert extract_client_ip(_ev(source_ip="198.51.100.7")) == "198.51.100.7"


def test_no_xff_falls_back_to_identity_source_ip():
    assert extract_client_ip(_ev(identity_ip="198.51.100.8")) == "198.51.100.8"


def test_no_xff_no_source_ip_returns_default():
    assert extract_client_ip(_ev()) == "unknown"


def test_extra_whitespace_is_stripped_on_each_hop():
    ev = _ev(headers={"X-Forwarded-For": "  evil-spoof ,   203.0.113.9   "})
    assert extract_client_ip(ev) == "203.0.113.9"


def test_multi_proxy_chain_still_takes_last_edge_hop():
    ev = _ev(headers={"X-Forwarded-For": "10.0.0.1, 70.70.70.70, 203.0.113.9"})
    assert extract_client_ip(ev) == "203.0.113.9"


def test_header_lookup_is_case_insensitive():
    assert extract_client_ip(_ev(headers={"x-forwarded-for": "evil, 203.0.113.9"})) == "203.0.113.9"


def test_empty_xff_header_falls_back_to_source_ip():
    ev = _ev(headers={"X-Forwarded-For": "   "}, source_ip="198.51.100.9")
    assert extract_client_ip(ev) == "198.51.100.9"
