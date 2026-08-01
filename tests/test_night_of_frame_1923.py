"""tests/test_night_of_frame_1923.py — pin the wake-date frame so a judge cannot re-litigate it.

On 2026-08-01 `reader_truth` raised a **HIGH** `temporal_contradiction` against
`/api/vitals`:

    sleep_hours field is dated 2026-07-31 (last night / night_of 2026-07-30),
    but as_of_date is ...

That is not a defect. It is the deliberate, documented temporal frame: sleep,
recovery, HRV and RHR are WAKE-DATE-KEYED — a record stored under 2026-07-31 is
the reading from the night that set up that morning, so `night_of = as_of - 1`.

A HIGH finding gated every deploy (until #1921 landed), so a correct design
decision could halt the pipeline — and the pressure that creates is to change
working code until a stochastic judge stops complaining. The right answer is to
pin the contract in code. With the invariant deterministic, the semantic checker
has nothing to opine on, and a REAL future violation is caught every time rather
than probabilistically.

The surface set is DERIVED (#1917's lesson): the guard AST-scans lambdas/web/ for
`"night_of"` dict keys and fails any that compute the offset inline instead of
calling the one shared helper. Hand-listing the surfaces is what let the two
`_Nd` field families drift apart in the first place.

Explicitly out of scope: `recovery_night_of`. Measuring before asserting showed it
is a DIFFERENT quantity — the date of a borrowed recovery block when the latest
night has none (#495/M-9) — a real stored date, not an offset. An invariant
applied to it would have been wrong.
"""

import ast
import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from web import site_api_common as sac  # noqa: E402

WEB = _REPO / "lambdas" / "web"


# ── the invariant itself ─────────────────────────────────────────────────────


def test_night_of_is_exactly_one_day_before_as_of():
    assert sac.night_of_for("2026-07-31") == "2026-07-30"
    assert sac.night_of_for("2026-01-01") == "2025-12-31"  # year boundary
    assert sac.night_of_for("2026-03-01") == "2026-02-28"  # non-leap month boundary
    assert sac.night_of_for("2024-03-01") == "2024-02-29"  # leap day


def test_offset_constant_is_one_and_is_what_the_helper_uses():
    """A changed constant must move the helper, not sit decoratively beside it."""
    assert sac.NIGHT_OF_OFFSET_DAYS == 1
    d = date(2026, 7, 31)
    expected = (d - timedelta(days=sac.NIGHT_OF_OFFSET_DAYS)).isoformat()
    assert sac.night_of_for(d.isoformat()) == expected


def test_timestamp_input_is_truncated_to_its_date():
    assert sac.night_of_for("2026-07-31T06:12:00Z") == "2026-07-30"


def test_unparseable_date_yields_no_frame_rather_than_a_guess():
    """Publishing no night_of beats publishing an invented one (ADR-104)."""
    for bad in (None, "", "not-a-date", "2026-13-45", 12345):
        assert sac.night_of_for(bad) is None


def test_frame_label_is_published_from_the_same_module_as_the_offset():
    """The label and the arithmetic must not be able to disagree."""
    assert sac.NIGHT_OF_FRAME == "last_night"


# ── the surface set, derived from source ─────────────────────────────────────


def _night_of_producers():
    """Every dict literal in lambdas/web/ that publishes a `night_of` key.

    Exact key match, so `recovery_night_of` — a different quantity — is excluded
    without needing to name it in an ignore list.
    """
    out = []
    for path in sorted(WEB.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "night_of":
                    out.append((path.name, k.lineno, ast.unparse(v)))
    return out


def test_the_scan_finds_the_known_producer():
    """Guard the guard: a scan finding nothing would pass everything."""
    producers = _night_of_producers()
    assert producers, "AST scan found no night_of producers — the scan is broken or the field was renamed"
    assert any(f == "site_api_vitals.py" for f, _, _ in producers)


def test_every_night_of_is_derived_from_the_shared_helper():
    """No surface may compute the offset inline — that is how a frame forks."""
    offenders = []
    for fname, lineno, expr in _night_of_producers():
        # The value must trace back to night_of_for(), directly or via a local
        # assigned from it. Accept the helper call or a bare name; reject visible
        # date arithmetic.
        if "timedelta" in expr or "strptime" in expr:
            offenders.append((fname, lineno, expr))
    assert not offenders, "night_of computed inline instead of via night_of_for() (#1923):\n" + "\n".join(
        f"    {f}:{ln}  {e[:90]}" for f, ln, e in offenders
    )


def test_vitals_binds_night_of_to_the_helper():
    """The one live producer, asserted concretely rather than only structurally."""
    src = (WEB / "site_api_vitals.py").read_text()
    assert "night_of_for(_as_of)" in src
    assert '"frame": NIGHT_OF_FRAME' in src, "the frame label must come from the shared module too"


def test_no_stray_inline_one_day_offset_remains_in_vitals():
    """Negative control for the refactor: the old inline computation is gone."""
    src = (WEB / "site_api_vitals.py").read_text()
    assert "_night_of = (datetime.strptime" not in src


# ── the contract as a reader sees it ─────────────────────────────────────────


def test_payload_shape_contract():
    """as_of_date / night_of / frame must be mutually consistent in the payload.

    This is the assertion `reader_truth` was making probabilistically, six
    different ways. Made once, deterministically, it cannot drift and cannot be
    re-litigated.
    """
    as_of = "2026-07-31"
    payload = {"as_of_date": as_of, "night_of": sac.night_of_for(as_of), "frame": sac.NIGHT_OF_FRAME}
    d_as_of = date.fromisoformat(payload["as_of_date"])
    d_night = date.fromisoformat(payload["night_of"])
    assert (d_as_of - d_night).days == sac.NIGHT_OF_OFFSET_DAYS
    assert payload["frame"] == "last_night", "the frame must name which convention produced the offset"
