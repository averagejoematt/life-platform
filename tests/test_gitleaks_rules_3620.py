"""#3620 — the custom gitleaks rules fire on the platform's own bearer shapes.

GitHub's validity checks and non-provider patterns are not offered on this
user-owned repo (#3606 item 3), so gitleaks' default ruleset was the entire
detector — and it knows AWS keys and GitHub PATs, not `lp_…`. Five
platform-minted credential shapes were invisible to every scanner in the
pipeline.

A custom regex's failure mode is being SILENTLY WRONG: it compiles, the scan
runs, the gate is green, and it has never matched anything. So each rule ships
with a positive control (a planted token of the real shape) and the negative
controls that keep it scoped. This test re-runs every rule's own regex against
both fixture files using Python's `re`, which means the controls hold on a
machine with no gitleaks binary installed — which is every machine in this
repo's CI lane except the secret-scan job's container.

This is NOT a substitute for running gitleaks (the binary owns keyword
pre-filtering, entropy and allowlist semantics). It is the half that can run
everywhere, and it is the half that catches a typo'd regex.
"""

import os
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover — py<3.11
    import tomli as tomllib

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG = os.path.join(_REPO, ".gitleaks.toml")
_FIXTURES = os.path.join(_REPO, "tests", "fixtures", "gitleaks")

# The planted tokens are NOT restated here — they are read from the fixture by the
# label above each one. Two reasons, and the second is the one that bit: a second copy
# of a token is a twin that drifts, and this file's own copy tripped gitleaks'
# `generic-api-key` plus two of the new rules on the PR that introduced it (run
# 35456614255, four findings on lines 36-40). The fixture directory is allowlisted by
# path; this file deliberately is not, so it must contain no token literals at all.
_FIXTURE_LABEL = re.compile(r"^#\s*(life-platform-[a-z0-9-]+)\s*$")
_FIXTURE_VALUE = re.compile(r"""=\s*["']([^"']+)["']""")

# The rule ids this test knows about. The VALUES come from the fixture; this tuple is
# only the SET, so a rule added to .gitleaks.toml with no planted control still reds.
_RULE_IDS = (
    "life-platform-mcp-bearer",
    "life-platform-mcp-session-bearer",
    "life-platform-hae-ingest-bearer",
    "life-platform-telegram-webhook-secret",
    "life-platform-site-api-origin-secret",
)


def _planted():
    """rule id -> the token planted under its label in the positive-control fixture."""
    out = {}
    pending = None
    for line in open(os.path.join(_FIXTURES, "planted_tokens.txt")):
        label = _FIXTURE_LABEL.match(line.strip())
        if label:
            pending = label.group(1)
            continue
        if pending:
            value = _FIXTURE_VALUE.search(line)
            if value:
                out[pending] = value.group(1)
                pending = None
    return out


def _rules():
    with open(_CONFIG, "rb") as f:
        cfg = tomllib.load(f)
    return {r["id"]: r for r in cfg.get("rules", [])}


def _positive():
    return open(os.path.join(_FIXTURES, "planted_tokens.txt")).read()


def _negative():
    return open(os.path.join(_FIXTURES, "negative_controls.txt")).read()


def test_all_five_rules_are_present():
    got = set(_rules())
    missing = set(_RULE_IDS) - got
    assert not missing, f"rules declared in this test but absent from .gitleaks.toml: {sorted(missing)}"


def test_every_rule_matches_its_planted_token():
    """The positive control. A rule that matches nothing is the silent failure."""
    rules = _rules()
    text = _positive()
    planted = _planted()
    missing_controls = set(_RULE_IDS) - set(planted)
    assert not missing_controls, f"rule(s) with no planted control in the fixture: {sorted(missing_controls)}"
    unfired = []
    for rid, expected in planted.items():
        pattern = re.compile(rules[rid]["regex"])
        m = pattern.search(text)
        if not m:
            unfired.append(rid)
            continue
        group = rules[rid].get("secretGroup", 0)
        assert m.group(group) == expected, f"{rid} matched but recovered {m.group(group)!r}, not the planted token"
    assert not unfired, f"rule(s) did not fire on their own planted token: {unfired}"


def test_no_rule_fires_on_the_negative_controls():
    """The scoping control. A rule that fires on a secret NAME or a short prefix
    interrupts every PR, gets allowlisted away, and then the real token walks through."""
    rules = _rules()
    text = _negative()
    noisy = []
    for rid in _RULE_IDS:
        m = re.compile(rules[rid]["regex"]).search(text)
        if m:
            noisy.append(f"{rid} -> {m.group(0)!r}")
    assert not noisy, f"rule(s) fired on a negative control: {noisy}"


def test_the_fixtures_are_allowlisted_by_path():
    """Without this the controls red the secret-scan gate on every PR touching them."""
    with open(_CONFIG, "rb") as f:
        cfg = tomllib.load(f)
    paths = [p for al in cfg.get("allowlists", []) for p in al.get("paths", [])]
    assert any("fixtures/gitleaks" in p for p in paths), "the positive-control fixtures are not allowlisted"


def test_every_regex_compiles():
    for rid, rule in _rules().items():
        try:
            re.compile(rule["regex"])
        except re.error as e:
            raise AssertionError(f"{rid} has an uncompilable regex: {e}") from e


def test_the_real_mcp_prefix_is_still_lp():
    """The rule is only right while the code still mints this shape. Read by text,
    not by import — importing mcp/handler runs its module-level wiring."""
    src = open(os.path.join(_REPO, "mcp", "handler.py")).read()
    assert 'f"lp_{sig}"' in src, "mcp/handler.py no longer mints `lp_<sig>` — re-point life-platform-mcp-bearer"
