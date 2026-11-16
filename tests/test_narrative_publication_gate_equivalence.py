"""The #5645 publication gate made faster, never different (#5728 follow-up).

``tests/narrative_publication_equivalence.py`` walks a corpus — every route-walk fixture row plus synthetic
adversarial rows (private families in nested and malformed provenance records, rows that are their own record,
every graded-record prefix, odd envelopes, odd values) — through the live gate AND the pre-speed-up reference
(``tests/narrative_publication_reference.py``) and compares every output byte for byte. It runs in a fresh
interpreter (the fixture modules patch boto3 and the clock). The same walk ran over every live narrative row
(read-only, locally) when the speed-up landed; that corpus is never committed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

WALK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "narrative_publication_equivalence.py")


def _walk(*args) -> dict:
    out = subprocess.run([sys.executable, WALK, *args], capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def test_the_gate_decides_exactly_as_the_reference_does():
    res = _walk()
    # Non-vacuity: the corpus is the fixtures AND the adversarial set, and the wire half was exercised.
    assert res["fixture_rows"] >= 400 and res["synthetic_rows"] >= 900, res
    assert res["gate_calls"] >= 10 * res["rows"] and res["probes"] > 1000, res
    assert res["taint_exact"] > 0 and res["taint_shingles"] > 0, res
    assert res["diffs"] == 0, res["first_diffs"]


@pytest.mark.parametrize("mutation", ["wordy5", "stale_memo", "no_mask"])
def test_the_walk_catches_a_wrong_speed_up(mutation):
    """Negative controls: a stricter shingle threshold, a memo that outlives a cleared taint, an unnormalised mask."""
    assert _walk("--mutate", mutation)["diffs"] > 0
