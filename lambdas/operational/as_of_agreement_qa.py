"""as_of_agreement_qa.py — #2414 (completing #2392): reader payload document
stamps must never run AHEAD of the Pacific day.

The live failure (#2392): `observatory_week.as_of_date` was anchored in UTC on a
Pacific site, so every night 17:00–24:00 PT it stamped TOMORROW's date while
/api/vitals (PT-anchored) stamped today — two doors disagreeing what day it is,
measured in the same minute. #2414 swept the whole naive-UTC-"today" class and
added the premerge AST guard (tests/test_pacific_today_guard_2414.py); this
module is the RUNTIME sensor for the same invariant, because a premerge guard
cannot see a regression that arrives via data or a new deploy path.

The invariant, stated once: a reader-facing document day-stamp is at most the
PT-expected day (`stamp <= pacific_today()`). "Behind" is legal — a page built
from yesterday's data honestly says so; "ahead" is impossible except through a
wrong clock frame.

Pure module — no AWS, no network, no clock — same split as `weight_truth_qa`:
qa_smoke_lambda owns the fetching, the PT "today", and the Check() wrapping.
"""

import re

# Day-stamp keys that name the document's day on reader payloads. Deliberately
# the stamp keys only — data fields (record dates, sk-derived dates) may honestly
# be in the past or keyed differently per source.
AS_OF_KEYS = ("as_of_date", "as_of")

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def day_stamps(payload, _path="$") -> list:
    """Every (json_path, value) in `payload` whose key is an AS_OF key holding a
    plain YYYY-MM-DD day. Instant-valued stamps (ISO datetimes) are skipped —
    an instant is frame-free; only day-valued stamps carry the PT-day contract."""
    out = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            here = f"{_path}.{k}"
            if k in AS_OF_KEYS and isinstance(v, str) and _DAY_RE.match(v):
                out.append((here, v))
            else:
                out.extend(day_stamps(v, here))
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            out.extend(day_stamps(v, f"{_path}[{i}]"))
    return out


def assess_as_of(payload, pt_today: str) -> dict:
    """Judge one reader payload against the PT-expected day.

    Returns {"stamps": <count checked>, "violations": [ "path=value (ahead of
    pt_today)" ... ]}. A payload with no day-stamps is a zero-stamp OK, not a
    failure — plenty of endpoints legitimately carry none.
    """
    stamps = day_stamps(payload)
    violations = [f"{path}={value} is AHEAD of the PT day {pt_today}" for path, value in stamps if value > pt_today]
    return {"stamps": len(stamps), "violations": violations}
