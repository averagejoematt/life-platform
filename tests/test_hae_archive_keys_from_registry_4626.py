"""tests/test_hae_archive_keys_from_registry_4626.py — #4626 epic row.

health_auto_export_archive.py built five raw-S3 keys from `raw/{user_id}/...` literals that
duplicated the apple_health `raw_layout` facet. The keys now come from the registry; this pins
that the written keys are exactly what the registry resolves (and are the keys already on disk).
"""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from ingestion import health_auto_export_archive as arch
from ingestion.source_registry import raw_date_key, raw_layout_for

DAY = "2026-10-17"


def _s3():
    s3 = MagicMock()
    s3.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
    s3.get_object.side_effect = s3.exceptions.NoSuchKey()
    return s3


def _put_key(s3):
    return s3.put_object.call_args.kwargs["Key"]


def test_day_files_land_on_the_registry_key():
    cases = [
        (arch.save_cgm_readings_to_s3, "cgm_readings", [{"time": "t1", "value": 1}]),
        (arch.save_bp_readings_to_s3, "blood_pressure", [{"time": "t1"}]),
        (arch.save_state_of_mind_to_s3, "state_of_mind", [{"time": "t1"}]),
        (arch.save_workouts_to_s3, "workouts", [{"id": "w1", "start": "t1"}]),
    ]
    for fn, sub, rows in cases:
        s3 = _s3()
        fn(s3, "b", "matthew", DAY, rows)
        assert _put_key(s3) == raw_date_key("apple_health", DAY, sub=sub)
        assert _put_key(s3) == f"raw/matthew/{sub}/2026/10/17.json"  # the key already on disk


def test_payload_archive_uses_the_registry_prefix():
    s3 = _s3()
    key = arch.save_raw_payload(s3, "b", "matthew", {"data": 1})
    assert key.startswith(raw_layout_for("apple_health")["prefix"] + "/")
    assert re.fullmatch(r".*/\d{4}/\d{2}/\d{2}_[0-9a-f]{16}\.json", key)
    assert json.loads(s3.put_object.call_args.kwargs["Body"]) == {"data": 1}


def test_no_hand_built_raw_key_literal_remains():
    src = Path(arch.__file__).read_text()
    assert not re.search(r'f"raw/\{', src), "build keys from the registry raw_layout facet, not a literal"
