"""#4624 backlog row: one fallback maximum heart rate, not four.

Readers carried their own `profile.get("max_heart_rate", <n>)` default (186 / 184 / 190, and a
pinned 183 in the load model). Behaviour is identical while the profile loads; on a profile miss
each reader put a different set of activities in Zone 2. `common.max_hr` is the one address.
"""

import ast
import pathlib

import pytest
from common.max_hr import DEFAULT_MAX_HR, max_hr_from_profile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_profile_value_wins_and_misses_fall_to_the_one_default():
    assert max_hr_from_profile({"max_heart_rate": 190}) == 190.0
    assert max_hr_from_profile({"max_heart_rate": "181"}) == 181.0
    for miss in (None, {}, {"max_heart_rate": None}, {"max_heart_rate": 0}):
        assert max_hr_from_profile(miss) == float(DEFAULT_MAX_HR)


def test_a_malformed_value_raises_rather_than_being_guessed():
    with pytest.raises(ValueError):
        max_hr_from_profile({"max_heart_rate": "one eighty"})


def test_load_model_pins_the_same_value():
    from training import training_load

    assert training_load.MAX_HR == float(DEFAULT_MAX_HR) == 183.0


# The seven readers that carried their own default. A fixed list, not a tree sweep: a sweep would
# enter the gate census (a concurrent-lane pin), and this row's residual is stated on the PR — a NEW
# reader's own default is not caught here, only a regression in these.
READERS = (
    "lambdas/emails/partner_email_lambda.py",
    "lambdas/emails/weekly_digest_extractors.py",
    "lambdas/content/output_writers.py",
    "lambdas/compute/dashboard_refresh_lambda.py",
    "mcp/tools_training.py",
)


def _numeric_defaults(source):
    out = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "max_heart_rate"
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, (int, float))
        ):
            out.append(node.lineno)
    return out


def test_the_known_readers_use_the_one_default():
    for rel in READERS:
        src = (ROOT / rel).read_text()
        assert not _numeric_defaults(src), f"{rel}: numeric max_heart_rate default — use common.max_hr.max_hr_from_profile"
        assert "max_hr_from_profile(" in src, f"{rel}: no longer reads the one resolver"


def test_detector_fires_on_the_old_pattern():
    """Control: the detector finds the pattern it exists for."""
    assert _numeric_defaults('max_hr = profile.get("max_heart_rate", 186)\n') == [1]
    assert _numeric_defaults("max_hr = max_hr_from_profile(profile)\n") == []
