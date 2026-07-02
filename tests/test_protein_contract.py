"""tests/test_protein_contract.py — one protein story on every door.

Replays the 2026-07-01 cross-door contradiction: /data/nutrition hardcoded 190 and
the front-end called it the "floor" while the coaches (grounded on canonical_facts)
graded against the real 170 floor — a reader crossing doors saw two truths with the
same word. The contract: the serving layer reads the SAME profile keys with the
SAME defaults as daily_metrics_compute (the canonical_facts producer), and serves
the floor as its own field.
"""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PRODUCER = os.path.join(ROOT, "lambdas", "compute", "daily_metrics_compute_lambda.py")
_SERVER = os.path.join(ROOT, "lambdas", "web", "site_api_observatory.py")

_PAIR_RE = re.compile(r'\.get\(\s*"(protein_(?:target|floor)_g)"\s*,\s*(\d+)')


def _profile_pairs(path):
    with open(path, encoding="utf-8") as f:
        return set(_PAIR_RE.findall(f.read()))


def test_producer_defines_both_protein_lines():
    pairs = _profile_pairs(_PRODUCER)
    assert ("protein_target_g", "190") in pairs
    assert ("protein_floor_g", "170") in pairs


def test_serving_layer_reads_the_same_keys_and_defaults():
    producer = _profile_pairs(_PRODUCER)
    server = _profile_pairs(_SERVER)
    assert server == producer, (
        f"site_api_observatory profile keys/defaults {server} have drifted from "
        f"daily_metrics_compute {producer} — the doors will tell two protein truths again"
    )


def test_no_hardcoded_protein_target_in_serving_layer():
    with open(_SERVER, encoding="utf-8") as f:
        src = f.read()
    assert not re.search(r"protein_target\s*=\s*190\b", src), "protein_target must come from the profile, not a literal"


def test_floor_served_as_its_own_field():
    with open(_SERVER, encoding="utf-8") as f:
        src = f.read()
    for field in ('"protein_floor_g"', '"protein_floor_hit_pct"'):
        assert field in src, f"nutrition_overview must serve {field}"
