"""tests/test_sync_census_fact_3156.py — #3156: an underivable census must never pass
for a measurement.

THE DEFECT: `deploy/sync_census_fact.py`'s `discover_gate_census_count()` swallowed
EVERY exception to a bare `None`, discarding the reason. `apply()` then substituted
`_FALLBACK_COUNT = 531` (frozen 2026-08-24) into `facts["gate_census_count"]` as if it
were a measurement. Docs CI installs no packages, so `scripts/gate_census.py`'s
`discover_ci_gates()` — which needs `import yaml` to parse `.github/workflows/**` — threw
`ModuleNotFoundError` on EVERY Docs CI run, and `--check` compared
docs/PROPORTIONALITY.md against the frozen 531 forever, while any branch whose local
pre-commit hook has PyYAML installed keeps deriving the true live count (538) and
re-stamping it. Verbatim the #1957 "a credentialed --apply and a credential-free --check
would stamp different numbers and fight each other forever" class.

Root cause confirmed live (not guessed) via a bare venv with zero packages installed:

    ModuleNotFoundError: No module named 'yaml'
      File ".../scripts/gate_census.py", line 518, in discover_ci_gates
        import yaml  # local: keeps the module importable where PyYAML is absent

THE FIX (two halves — both proven here):
  1. `discover_gate_census_count()` now returns `(count, error)` instead of throwing the
     reason away — `test_discover_gate_census_count_*` below.
  2. `apply()` never substitutes a frozen number for an underivable count: under
     `--check` it fails LOUDLY (`sys.exit(1)`, message names the reason); otherwise the
     rule is explicitly SKIPPED with a printed reason and the doc is left untouched —
     `test_apply_*` below, plus one true end-to-end test that goes through the REAL
     `sync_doc_metadata.main()` (not a bypassed `_apply_auto_discovered`) to prove the
     full wiring, the way the acceptance criteria asked: "a planted ImportError makes
     --check fail loudly rather than pass-with-fallback."

`_FALLBACK_COUNT` is gone entirely — `test_fallback_count_constant_is_gone` pins that.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import sync_census_fact  # noqa: E402
import sync_doc_metadata as sync  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# discover_gate_census_count() — the reason must survive, not just the None.
# ══════════════════════════════════════════════════════════════════════════════


def test_discover_gate_census_count_succeeds_on_repo_head():
    """Sanity: against the real repo, with real deps, this must actually derive a
    number — the whole point of #3156 is that a REAL measurement must never be
    indistinguishable from a swallowed failure."""
    count, error = sync_census_fact.discover_gate_census_count(Path(_REPO))
    assert error is None
    assert isinstance(count, int) and count > 0


def test_discover_gate_census_count_reports_the_planted_importerror():
    """THE mutation proof for discovery itself: plant a fake ImportError at the actual
    call site inside the census (gate_census.build_census, exactly where the real
    PyYAML import lives, #518) and confirm the reason is captured, not thrown away."""
    import gate_census

    def _boom(root):
        raise ModuleNotFoundError("No module named 'yaml'")

    orig = gate_census.build_census
    gate_census.build_census = _boom
    try:
        count, error = sync_census_fact.discover_gate_census_count(Path(_REPO))
    finally:
        gate_census.build_census = orig

    assert count is None
    assert error is not None
    assert "yaml" in error and "ModuleNotFoundError" in error


def test_discover_gate_census_count_reports_missing_scripts_dir(tmp_path):
    """The other failure mode (no scripts/ at all) is reported too, not silently None."""
    count, error = sync_census_fact.discover_gate_census_count(tmp_path)
    assert count is None
    assert error is not None and "scripts" in error


# ══════════════════════════════════════════════════════════════════════════════
# apply() — never a silent fallback comparison, in either direction.
# ══════════════════════════════════════════════════════════════════════════════


def _fail_discovery(root=None):
    return None, "ModuleNotFoundError: No module named 'yaml' (planted, #3156)"


def test_apply_fails_loudly_under_check_when_census_underivable(monkeypatch, capsys):
    """THE headline acceptance box: --check on an underivable census must fail LOUD —
    nonzero exit, a message naming 'census underivable' and the reason — never pass
    quietly with a frozen number substituted in."""
    monkeypatch.setattr(sync_census_fact, "discover_gate_census_count", _fail_discovery)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])
    facts: dict = {}
    rules: list = []

    with pytest.raises(SystemExit) as exc:
        sync_census_fact.apply(facts, rules, root=Path(_REPO))

    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert "census underivable" in out
    assert "yaml" in out
    # And it must not have smuggled a number in on the way to exiting.
    assert "gate_census_count" not in facts


def test_apply_skips_with_reason_outside_check_when_census_underivable(monkeypatch, capsys):
    """Outside --check (plain dry run / --apply run somewhere without the census's
    deps), an underivable count is explicitly SKIPPED — printed reason, doc/rule left
    untouched — never silently compared against a frozen number."""
    monkeypatch.setattr(sync_census_fact, "discover_gate_census_count", _fail_discovery)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py"])  # no --check, no --apply
    facts: dict = {}
    rules: list = []

    sync_census_fact.apply(facts, rules, root=Path(_REPO))  # must not raise

    out = capsys.readouterr().out
    assert "skip" in out.lower()
    assert "yaml" in out
    assert "gate_census_count" not in facts, "an underivable count must never be substituted"
    assert sync_census_fact._RULE not in rules, "the rule must not be registered against an unmeasured fact"


def test_apply_sets_fact_and_registers_rule_on_success(monkeypatch):
    """The happy path still works: a real count sets the fact and registers the rule
    exactly once, idempotently."""
    monkeypatch.setattr(sync_census_fact, "discover_gate_census_count", lambda root=None: (999, None))
    facts: dict = {}
    rules: list = []

    sync_census_fact.apply(facts, rules, root=Path(_REPO))
    sync_census_fact.apply(facts, rules, root=Path(_REPO))  # second call: no duplicate

    assert facts["gate_census_count"] == 999
    assert rules.count(sync_census_fact._RULE) == 1


def test_fallback_count_constant_is_gone():
    """#3156 acceptance box 4: _FALLBACK_COUNT is removed outright, not merely demoted —
    there is nothing left in the module a --check could silently compare against."""
    assert not hasattr(sync_census_fact, "_FALLBACK_COUNT")


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end: the REAL sync_doc_metadata.main() (not a bypassed
# _apply_auto_discovered) with a planted ImportError, proving the full wiring —
# main() -> _apply_auto_discovered() -> sync_census_fact.apply() -> sys.exit(1).
# ══════════════════════════════════════════════════════════════════════════════


def test_main_check_fails_loudly_end_to_end_on_planted_importerror(monkeypatch, capsys):
    monkeypatch.setattr(sync_census_fact, "discover_gate_census_count", _fail_discovery)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert "census underivable" in out
