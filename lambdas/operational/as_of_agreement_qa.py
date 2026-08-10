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

#2379 adds the COMPLEMENT direction below (`assess_as_of_data_correspondence`):
a stamp that does not run ahead of the clock can still disagree with the data
the same document actually carries. Read the threshold comment there before
touching it — this runs nightly and a false positive emails the owner.
"""

import re
from datetime import date

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


# ---------------------------------------------------------------------------
# #2379 — served-date correspondence (the complement of the check above)
# ---------------------------------------------------------------------------
# `assess_as_of` enforces ONE direction: a stamp may never run ahead of the
# Pacific clock, and "behind is legal" by design. The uncovered complement is a
# document stamped TODAY while every dated field it actually serves is a week
# old — the stamp does not disagree with the clock, it disagrees with the DATA.
# The LLM reader-truth judge found that class; this is the deterministic owner
# of it, so it keeps working at budget tier 3 where the AI half pauses.
#
# THRESHOLD — AS_OF_DATA_LAG_MAX_DAYS = 7, and why that number:
#   * 1-2 days of lag is CORRECT, not a defect. A daily document is built the
#     morning after the day it covers (last night's sleep, yesterday's completed
#     nutrition), and the slowest sanctioned ingest lag on the platform is ~24h.
#     A stamp of day D over newest data D-1, or D-2 when a source lands a full
#     day late, is the healthy steady state.
#   * Between that and a week, the gap is a BEHAVIOURAL one — a quiet source, an
#     unworn strap, a travel week. That is honest content and it is owned by the
#     freshness tiers, not by a stamp-agreement assert. Firing there would email
#     the owner about his own week off.
#   * 7 days is the platform's own quiet-vs-dead width (raw_archive_qa's
#     RAW_LIVENESS_* windows use the same 7 to separate "writer quiet" from
#     "archive dead") and it is the width #2379 states the class in: "a payload
#     stamped today while serving last week's rows". Past it, EVERY dated field
#     in the document is stale while the stamp claims today, which no sanctioned
#     cadence explains.
# Deliberately ONE-SIDED: data NEWER than the stamp is not a violation here. A
# document stamped for a completed day may honestly carry a partial row for the
# day in progress, and the ahead-of-clock direction is already `assess_as_of`'s.
AS_OF_DATA_LAG_MAX_DAYS = 7


def newest_data_day(payload):
    """The newest plain YYYY-MM-DD day the document actually SERVES, or None.

    "Serves" = any day-valued string under a key that is not itself a document
    stamp (AS_OF_KEYS). Deliberately a max over a GENEROUS superset of data
    keys: widening what counts as data can only raise the max, which can only
    shrink the measured lag — i.e. every widening makes the assert below more
    lenient, never more trigger-happy. That one-way property is what keeps this
    safe to run nightly against payload shapes it has never seen.
    """
    newest = None
    for value in _data_days(payload):
        if newest is None or value > newest:
            newest = value
    return newest


def _data_days(payload, _key=None):
    """Every day-valued string in `payload` that is not a document stamp.

    List elements inherit their parent key, so a list under an AS_OF key stays
    excluded and a list of record dates under `days` stays included.
    """
    out = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            out.extend(_data_days(v, k))
    elif isinstance(payload, list):
        for v in payload:
            out.extend(_data_days(v, _key))
    elif isinstance(payload, str) and _key not in AS_OF_KEYS and _DAY_RE.match(payload):
        out.append(payload)
    return out


def assess_as_of_data_correspondence(payload) -> dict:
    """Judge one reader payload's day-stamps against the newest day it serves.

    Clock-free by construction — this compares the document against ITSELF, so
    it needs no "today" and cannot become a midnight time-bomb. Returns
    {"stamps": <count checked>, "newest_data_day": <str|None>, "violations":
    [...]}. A payload with no stamps, or one carrying no dated data at all
    (an honest empty state), is a zero-violation OK — absence of data is not
    evidence of a lying stamp.
    """
    stamps = day_stamps(payload)
    newest = newest_data_day(payload)
    violations = []
    if newest is not None:
        newest_d = date.fromisoformat(newest)
        for path, value in stamps:
            lag = (date.fromisoformat(value) - newest_d).days
            if lag > AS_OF_DATA_LAG_MAX_DAYS:
                violations.append(f"{path}={value} is {lag}d AHEAD of the newest day this document serves ({newest})")
    return {"stamps": len(stamps), "newest_data_day": newest, "violations": violations}
