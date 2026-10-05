"""#2649 — the literal-drift gate must fail on substance, not on the calendar.

`sync_doc_metadata.py` sets `facts["date"]` to *today's* UTC date on every run, so
under `--check` every doc's "Last updated:" stamp went stale at 00:00Z and stayed
stale until the next merge re-stamped it. Docs CI was 40/40 red.

The expensive part was not the red itself — `main` is not branch-protected, so
nothing was blocked. It is that a date-only diff and a genuine drift were reported
**identically**, with no severity split. A real drift (a wrong Lambda count, a wrong
tool count) was invisible inside daily noise that everyone had learned to ignore.

The contract, in four cases — the last two are the ones that matter:

  A  stale date only            -> PASS   (was FAIL: the bug)
  B  substantive drift only     -> FAIL   (must not be weakened by the fix)
  C  stale date AND drift       -> FAIL   (masking must not HIDE real drift)
  D  clean tree                 -> PASS

Case C is why the masking is per-change rather than per-file: `docs/ARCHITECTURE.md`
carries the date and the Lambda count on the SAME line, so a naive "ignore any line
containing a date" would have swallowed the count too.

`--check` ignores a date-only difference. `--apply` used to refresh the stamp
unconditionally; since #2986 it refreshes only what the run regenerated or verified
(`deploy/doc_restamp_guard.py`, guarded by `tests/test_doc_restamp_rule_2986.py`) — the
four cases above are unchanged, because a held stamp is a date-only difference too.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# ── #3025: this whole module is `serial` ─────────────────────────────────────
#
# It MUTATES THE REAL CHECKOUT — see tests/test_suite_parallel_safety_3025.py's
# IN_TREE_WRITERS for the reason it cannot be pointed at a temp dir. Under `pytest -n auto`
# that write is visible to every concurrent whole-tree sweep in the suite for as long as it
# exists, so this module is deselected from the parallel pass and runs afterwards in one
# process. Marked at MODULE level deliberately: `--dist loadfile` already groups a file onto
# one worker, so the file is the natural unit, and a per-test marker would miss a write done
# by a fixture.
pytestmark = pytest.mark.serial


_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "deploy"))

import doc_drift_verdict as _verdict  # noqa: E402 — #3646: the verdict codes, read not copied

_SCRIPT = _REPO / "deploy" / "sync_doc_metadata.py"
_DOC = _REPO / "docs" / "ARCHITECTURE.md"


def _gate_env(event_name="pull_request", strict=True):
    """A child env whose verdict is the GATE's, never CI's (#3646).

    `GITHUB_REF` is REMOVED, which is what disarms the push-to-main tolerance in
    `doc_drift_verdict.reconcile_bot_follows_this_run()` — the branch that turned
    a planted drift into exit 0 on main's own full-suite run (35465658218).

    `GITHUB_EVENT_NAME` is PINNED rather than removed, and the asymmetry is deliberate:
    `deploy/doc_platform_counts.py`'s #3384 exemption keys on `pull_request`, and it is
    the only thing that stops an unrelated `test_count` delta — which every branch that
    adds a test carries, and which the reconcile bot owns — from reaching a subprocess
    that is asserting about something else entirely. Removing it would red this file on
    every lane PR. Pinning it makes the child deterministic in BOTH directions instead
    of inheriting whatever the runner exported.
    """
    env = dict(os.environ)
    # #3984: `strict=True` pins the ref to main (the off-main tolerance is disarmed, the
    # push-to-main tolerance stays disarmed by the non-push event) — the planted drift below
    # must red. `strict=False` is the branch arm: the same drift is a notice and exit 0.
    env["GITHUB_REF"] = "refs/heads/main" if strict else "refs/heads/feature-3984"
    env["GITHUB_EVENT_NAME"] = event_name
    return env


def _check(strict=True) -> int:
    """Run the real gate exactly as CI does, and return its exit code.

    #3646 moved the non-zero code these tests assert from 1 to 3. The drift they plant
    is a `~` rewrite `--apply` regenerates — BOT-OWNED — so the gate now reports
    `pending-reconcile`. The property under test is unchanged and is still enforced:
    the gate is NOT green, and `EXIT_PENDING_RECONCILE` is read from the shipped module
    rather than hard-coded, so the two can never drift apart again. `_check()` runs the
    script in a subprocess with no `GITHUB_EVENT_NAME`, so the push-to-main tolerance
    (exit 0) cannot reach it — a test asserting "the guard is gone" must never be able
    to pass because of a CI-only exemption.
    """
    return _run(strict).returncode


def _run(strict=True):
    return subprocess.run(  # nosec B603 — fixed argv
        [sys.executable, str(_SCRIPT), "--check"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        env=_gate_env(strict=strict),
    )


def _drift_set(strict=True) -> frozenset:
    """The `~ …` lines the gate reports, as a SET.

    THE EXIT CODE IS NOT ENOUGH ON A BRANCH (#3760). Cases A and D below used to assert
    `_check() == 0` — "the tree is clean" — and that is unsatisfiable on any branch whose
    own diff moves a bot-owned counter. A PR that adds a Lambda or an alarm leaves
    `lambdas`/`alarms` stale by construction, and #3984 makes that state DELIBERATE: the
    pre-commit hook RESTORES `lambdas/web/platform_counts.py` off main and
    `deploy/agent_commit.sh` refuses the file outright, so a lane cannot hand-fix the
    number even if it wanted to. The reconcile bot owns it, on main, after the merge.

    So the property these tests are really about — a date-only difference ADDS NOTHING,
    a wrong count ADDS A LINE — is stated on the drift SET instead, which is both branch-
    independent and strictly stronger than the exit code it replaces (an exit code cannot
    tell "3 because of my Lambda" from "3 because of the planted defect"; a set can).
    """
    return frozenset(line.strip() for line in _run(strict).stdout.splitlines() if line.strip().startswith("~ "))


@pytest.fixture
def doc_text():
    """Restore ARCHITECTURE.md byte-for-byte however the test exits."""
    original = _DOC.read_text(encoding="utf-8")
    yield original
    _DOC.write_text(original, encoding="utf-8")


def _stale_the_date(text: str) -> str:
    """Roll the 'Last updated:' stamp back one day — the state every doc is in at
    00:00Z before the day's first merge."""
    import re

    def back_one_day(m):
        from datetime import date, timedelta

        y, mo, d = (int(x) for x in m.group(1).split("-"))
        return "Last updated: " + (date(y, mo, d) - timedelta(days=1)).isoformat()

    new, n = re.subn(r"Last updated: (\d{4}-\d{2}-\d{2})", back_one_day, text, count=1)
    assert n == 1, "could not find a 'Last updated: <date>' stamp to age"
    return new


def _live_lambda_phrase(doc_text: str) -> str:
    """The `<N> Lambdas` phrase as the doc CURRENTLY states it.

    #3741: this was the literal "104 Lambdas". The fleet grew to 105 and the mutation
    below became a no-op — `.replace()` found nothing, the doc was written back
    unchanged, the gate passed, and the test that exists to prove the gate can FAIL
    reported success. A hardcoded number inside a can-it-fail control is the same blind
    spot the control was written to catch, one level up.
    """
    import re as _re

    m = _re.search(r"\b(\d+) Lambdas\b", doc_text)
    assert m, "no '<N> Lambdas' phrase in the doc — this control cannot mutate what it cannot find"
    return m.group(0)


@pytest.mark.skipif(not _SCRIPT.exists(), reason="sync_doc_metadata.py not present")
def test_d_the_tree_carries_no_unownable_drift(doc_text):
    """Baseline. If this fails, every other case below is uninterpretable.

    "No drift a bot cannot regenerate" rather than "no drift at all" — see `_drift_set`.
    EXIT_FAILURE is still a red here: that is drift a human has to fix, and it must never
    be sitting in the tree while the cases below plant their own.
    """
    code = _check()
    assert code in (_verdict.EXIT_SUCCESS, _verdict.EXIT_PENDING_RECONCILE), (
        f"the gate reports substantive (non-regenerable) drift on this tree (exit {code}) — " "fix that before reading the rest"
    )


@pytest.mark.skipif(not _SCRIPT.exists(), reason="sync_doc_metadata.py not present")
def test_a_a_stale_date_stamp_alone_is_not_drift(doc_text):
    """The bug: this used to exit 1 once per UTC midnight.

    Asserted as "the drift set does not grow", which is the same claim without the
    branch-must-be-counter-clean assumption the exit-code form carried.
    """
    before = _drift_set()
    _DOC.write_text(_stale_the_date(doc_text), encoding="utf-8")
    after = _drift_set()
    assert after == before, f"ageing the date stamp added drift: {sorted(after - before)} (#2649)"


@pytest.mark.skipif(not _SCRIPT.exists(), reason="sync_doc_metadata.py not present")
def test_b_a_substantive_drift_still_fails(doc_text):
    """The fix must not buy green by weakening the gate."""
    phrase = _live_lambda_phrase(doc_text)
    before = _drift_set()
    _DOC.write_text(doc_text.replace(phrase, "999 Lambdas", 1), encoding="utf-8")
    assert _check() == _verdict.EXIT_PENDING_RECONCILE, "a wrong Lambda count no longer fails the gate — the guard is gone"
    # The exit code alone cannot distinguish "3 because of the plant" from "3 because this
    # branch moved a counter" — the set can, and must GROW.
    assert _drift_set() - before, "the planted wrong count added no drift line — the gate did not see it"


@pytest.mark.skipif(not _SCRIPT.exists(), reason="sync_doc_metadata.py not present")
def test_b2_off_main_the_same_substantive_drift_is_a_tolerated_notice(doc_text):
    """#3984: a branch never carries the regenerables — the bot rewrites them on main."""
    phrase = _live_lambda_phrase(doc_text)
    _DOC.write_text(doc_text.replace(phrase, "999 Lambdas", 1), encoding="utf-8")
    assert _check(strict=False) == 0, "off main, bot-owned drift must be pending-reconcile with exit 0 (#3984)"


def test_c_a_stale_date_does_not_hide_a_substantive_drift(doc_text):
    """The subtle one. Both literals live on the SAME line, so masking the date must
    not mask the count that shares it."""
    before = _drift_set()
    both = _stale_the_date(doc_text).replace(_live_lambda_phrase(doc_text), "999 Lambdas", 1)
    _DOC.write_text(both, encoding="utf-8")
    assert _check() == _verdict.EXIT_PENDING_RECONCILE, "a stale date stamp masked a real drift on the same line (#2649)"
    assert _drift_set() - before, "the stale date stamp swallowed the count that shares its line (#2649)"


def test_the_date_masker_is_not_a_blanket_line_ignore():
    """Unit-level statement of the same contract, so a refactor that reverts to
    line-level ignoring fails here even if the subprocess cases are skipped."""
    sys.path.insert(0, str(_REPO / "deploy"))
    os.environ.setdefault("AWS_REGION", "us-west-2")
    from sync_doc_metadata import _differs_only_by_date_stamp

    assert _differs_only_by_date_stamp("Last updated: 2026-08-14 (v8.6.0)", "Last updated: 2026-08-15 (v8.6.0)")
    assert not _differs_only_by_date_stamp(
        "Last updated: 2026-08-14 (v8.6.0 — 104 Lambdas)",
        "Last updated: 2026-08-15 (v8.6.0 — 999 Lambdas)",
    )
    assert not _differs_only_by_date_stamp("76 tools", "88 tools")
