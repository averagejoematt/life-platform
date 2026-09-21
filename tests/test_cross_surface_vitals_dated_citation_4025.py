"""tests/test_cross_surface_vitals_dated_citation_4025.py — #4025: a coach narrating
a PAST reading BY DATE is not a currency claim.

THE LIVE FAILURE, 2026-09-21. `qa-smoke-failures` lit on `cross_surface:vitals`:
"Dr. Nathan Reeves cites recovery 97% vs cockpit 90%". The card (`/api/coaching-
dashboard` coaches[2], `coach_id "mind"`, `published_vitals.recovery_pct 90.0`,
`recovery_as_of 2026-09-21`) reads:

    "...what did his body actually feel like on September 18th? That distinction —
     whether his felt sense preceded or followed the 97% recovery reading — matters
     more than either number alone."

Whoop `DATE#2026-09-20` recovery_score = 97; `DATE#2026-09-21` = 90. The coach's own
stamp AGREES with the cockpit (both 90%) — the 97% is a dated, historical citation of
yesterday's reading, not a claim about now. The existing `_HISTORICAL_ANCHOR` /
`_DATED_SENTENCE` exemptions only fire when the SAME sentence carries a recognizable
date word next to the figure; here the date ("September 18th") sits in the PRECEDING
sentence, so the figure's own sentence carries no date token at all and the exemption
never engages — exactly why the gate fired on correct, reader-honest prose.

THE FIX: `assess_cross_surface_vitals(..., history=...)` — a citation that disagrees
with the publication baseline but matches a REAL Whoop reading from some day in the
trailing `DATED_CITATION_WINDOW_DAYS` is a dated citation, not a contradiction, and the
pass message NAMES the day it matched. A citation matching no day in the window still
fails exactly as before (the #2113 shape is re-run here as the negative control).
`history=None` (the caller could not resolve it) keeps the strict pre-#4025 behaviour
and says so explicitly in the message.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from operational import weight_truth_qa as wq  # noqa: E402

# ── The 2026-09-21 specimen, as measured ────────────────────────────────────────

COCKPIT_09_21 = {
    "recovery_pct": 90.0,
    "hrv_ms": 60.0,
    "rhr_bpm": 55.0,
    "sleep_hours": 7.5,
    "recovery_as_of": "2026-09-21",
    "sleep_as_of": "2026-09-21",
}

_NATHAN_REEVES = {
    "name": "Dr. Nathan Reeves",
    "published_vitals": {"recovery_pct": 90.0, "recovery_as_of": "2026-09-21"},
    "position_summary": (
        "There's a question underneath all the metrics — what did his body actually feel like on September "
        "18th? That distinction — whether his felt sense preceded or followed the 97% recovery reading — "
        "matters more than either number alone."
    ),
}

# The trailing-14-day Whoop history a resolved `history=` argument would carry.
_HISTORY_09_21 = {
    "recovery": {
        "2026-09-08": 71.0,
        "2026-09-09": 68.0,
        "2026-09-14": 75.0,
        "2026-09-18": 80.0,
        "2026-09-19": 88.0,
        "2026-09-20": 97.0,
        "2026-09-21": 90.0,
    },
    "hrv": {"2026-09-20": 62.0, "2026-09-21": 60.0},
    "rhr": {"2026-09-20": 54.0, "2026-09-21": 55.0},
    "sleep": {"2026-09-20": 7.6, "2026-09-21": 7.5},
}


def test_the_09_21_specimen_fails_without_history_the_old_way():
    """Establish the regression against the pre-#4025 behaviour: this exact card,
    with no history to consult, is the FAIL that was actually live."""
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [_NATHAN_REEVES])
    assert not ok
    assert "recovery 97" in msg and "Dr. Nathan Reeves" in msg
    assert "no per-day history supplied" in msg, msg


def test_the_09_21_specimen_passes_with_history_and_names_the_day():
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [_NATHAN_REEVES], history=_HISTORY_09_21)
    assert ok, msg
    assert "2026-09-20" in msg, msg
    assert "dated citation" in msg, msg


def test_a_citation_matching_no_day_in_the_window_still_fails():
    """The #2113 shape, re-run as the negative control: the disagreeing figure is real
    (once lived in the partition) but sits well outside the trailing window, so the
    exemption must not reach it."""
    coach = {
        "name": "Dr. Sarah Chen",
        "position_summary": "Your Whoop recovery came in at 59%, HRV at 42 ms, resting HR at 59.",
    }
    # 59% never appears anywhere in the trailing-14-day history supplied.
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [coach], history=_HISTORY_09_21)
    assert not ok
    assert "recovery 59" in msg and "hrv 42" in msg
    assert "dated citation" not in msg, msg


def test_a_day_exactly_at_the_window_edge_still_matches():
    """DATED_CITATION_WINDOW_DAYS=7 counting the anchor day itself — 09-15 is the 7th
    day back from 09-21 inclusive."""
    history = {"recovery": {"2026-09-15": 71.0}, "hrv": {}, "rhr": {}, "sleep": {}}
    coach = {"name": "c", "position_summary": "his felt sense that morning lines up with the 71% recovery reading."}
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [coach], history=history)
    assert ok, msg
    assert "2026-09-15" in msg


def test_a_day_one_past_the_window_edge_does_not_match():
    """09-14 is 8 calendar days back from the 09-21 anchor — one day outside the window."""
    history = {"recovery": {"2026-09-14": 71.0}, "hrv": {}, "rhr": {}, "sleep": {}}
    coach = {"name": "c", "position_summary": "his felt sense that morning lines up with the 71% recovery reading."}
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [coach], history=history)
    assert not ok, msg


def test_history_none_is_the_default_and_never_a_silent_pass():
    """Backward-compatible default AND the acceptance requirement in one: omitting
    `history` reproduces today's strict behaviour byte-for-byte in outcome, and the
    message never lets a reader mistake the omission for "checked and forgiven"."""
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [_NATHAN_REEVES])
    assert not ok
    assert "no per-day history supplied" in msg


def test_history_none_says_so_even_on_a_clean_pass():
    """The note belongs on EVERY history=None outcome, not only the failures — an
    all-agreeing coach with no history resolved must not read as "dated citations
    were checked and none needed forgiving"."""
    coach = {"name": "c", "position_summary": "Your Whoop recovery came in at 90%, HRV at 60 ms, resting HR at 55 bpm."}
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [coach])
    assert ok, msg
    assert "no per-day history supplied" in msg


def test_an_empty_history_dict_behaves_like_no_match_not_like_none():
    """A resolved-but-empty history (a real DDB read that found zero rows) must not
    carry the `history=None` strict-mode note — the caller DID resolve it; there was
    simply nothing in the window. Distinguishing this from `history=None` matters:
    a caller silently swallowing an error into `{}` must not be indistinguishable
    from an honest omission."""
    empty = {"recovery": {}, "hrv": {}, "rhr": {}, "sleep": {}}
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [_NATHAN_REEVES], history=empty)
    assert not ok
    assert "no per-day history supplied" not in msg, msg


def test_a_dated_match_only_applies_to_a_value_that_already_disagrees():
    """The exemption narrows a FAIL into a PASS on a real matching day — it must never
    be consulted for a value that already agrees with the live baseline, so it cannot
    accidentally rename an ordinary pass's provenance."""
    coach = {"name": "c", "position_summary": "Your Whoop recovery came in at 90%, HRV at 60 ms, resting HR at 55 bpm."}
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [coach], history=_HISTORY_09_21)
    assert ok, msg
    assert "dated citation" not in msg, "an already-agreeing figure must not be reported as a dated match"


# ── resolve_vitals_history: the DDB read, bounded and fail-soft ────────────────


class _FakeTable:
    def __init__(self, items=None, raises=False):
        self._items = items or []
        self._raises = raises
        self.last_kwargs = None

    def query(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raises:
            raise RuntimeError("simulated DDB outage")
        return {"Items": self._items}


def test_resolve_vitals_history_returns_none_with_no_table():
    assert wq.resolve_vitals_history(None) is None


def test_resolve_vitals_history_is_fail_soft_on_a_ddb_error():
    assert wq.resolve_vitals_history(_FakeTable(raises=True)) is None


def test_resolve_vitals_history_parses_the_real_whoop_field_names():
    items = [
        {"sk": "DATE#2026-09-20", "recovery_score": 97, "hrv": 62.0, "resting_heart_rate": 54, "sleep_duration_hours": 7.6},
        {"sk": "DATE#2026-09-21", "recovery_score": 90, "hrv": 60.0, "resting_heart_rate": 55, "sleep_duration_hours": 7.5},
        # A workout sub-item under the same partition must never be mistaken for a
        # daily reading — it carries none of the daily fields and a real ID key.
        {"sk": "DATE#2026-09-21#WORKOUT#abc123", "sport_name": "Running"},
    ]
    history = wq.resolve_vitals_history(_FakeTable(items))
    assert history["recovery"] == {"2026-09-20": 97.0, "2026-09-21": 90.0}
    assert history["hrv"] == {"2026-09-20": 62.0, "2026-09-21": 60.0}
    assert history["rhr"] == {"2026-09-20": 54.0, "2026-09-21": 55.0}
    assert history["sleep"] == {"2026-09-20": 7.6, "2026-09-21": 7.5}


def _leaf_literals(condition):
    """Every literal string reachable inside a boto3 Key condition tree."""
    out = []
    for v in getattr(condition, "_values", ()):
        if isinstance(v, str):
            out.append(v)
        else:
            out.extend(_leaf_literals(v))
    return out


def test_resolve_vitals_history_queries_the_whoop_partition_key_bounded():
    table = _FakeTable([])
    wq.resolve_vitals_history(table, days=14)
    kce = table.last_kwargs["KeyConditionExpression"]
    # Key-bounded against the whoop partition specifically — never a scan.
    literals = _leaf_literals(kce)
    assert any("USER#matthew#SOURCE#whoop" in v for v in literals), literals
    assert any(v.startswith("DATE#") for v in literals), literals


def test_a_missing_metric_field_on_one_day_does_not_drop_the_others():
    items = [{"sk": "DATE#2026-09-20", "recovery_score": 97}]  # no hrv/rhr/sleep that day
    history = wq.resolve_vitals_history(_FakeTable(items))
    assert history["recovery"] == {"2026-09-20": 97.0}
    assert history["hrv"] == {}


# ── checks() wiring: the caller reuses its own table, read-only ───────────────


class _FakeCheck:
    def __init__(self, name, category, partition):
        self.name, self.category, self.partition = name, category, partition
        self.passed = None
        self.message = ""

    def ok(self, msg=""):
        self.passed, self.message = True, msg
        return self

    def fail(self, msg=""):
        self.passed, self.message = False, msg
        return self

    def warn(self, msg="", chronic=False):
        self.passed, self.message = None, msg
        return self


def _fake_urlopen_factory(payloads_by_path):
    import io
    import json as _json

    def _fake_urlopen(req, timeout=15):
        path = "/" + req.full_url.split("://", 1)[1].split("/", 1)[1]
        body = _json.dumps(payloads_by_path.get(path, {})).encode("utf-8")

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp(body)

    return _fake_urlopen


def test_checks_resolves_history_from_the_injected_table_and_forgives_a_dated_citation(monkeypatch):
    payloads = {
        "/api/vitals": {"vitals": COCKPIT_09_21},
        "/api/coaching-dashboard": {"coaches": [_NATHAN_REEVES]},
        "/api/sleep_detail": {"sleep_detail": {}},
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen_factory(payloads))
    items = [
        {"sk": "DATE#2026-09-20", "recovery_score": 97},
        {"sk": "DATE#2026-09-21", "recovery_score": 90},
    ]
    results = wq.checks(_FakeCheck, "http://example.test", "content_truth", table=_FakeTable(items))
    by_name = {c.name: c for c in results}
    assert by_name["cross_surface:vitals"].passed is True, by_name["cross_surface:vitals"].message
    assert "2026-09-20" in by_name["cross_surface:vitals"].message


def test_checks_without_a_table_keeps_the_strict_pre_4025_behaviour(monkeypatch):
    """The un-wired call shape every existing test in test_sleep_disclosure_pair_3451.py
    uses — `table` defaults to None, so a live gap must still FAIL exactly as before."""
    payloads = {
        "/api/vitals": {"vitals": COCKPIT_09_21},
        "/api/coaching-dashboard": {"coaches": [_NATHAN_REEVES]},
        "/api/sleep_detail": {"sleep_detail": {}},
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen_factory(payloads))
    results = wq.checks(_FakeCheck, "http://example.test", "content_truth")
    by_name = {c.name: c for c in results}
    assert by_name["cross_surface:vitals"].passed is False
    assert "no per-day history supplied" in by_name["cross_surface:vitals"].message


# ── mutation control (documented in the PR, not just here): disabling the dated-
# citation lookup must turn the passing specimen test red again. This monkeypatch
# reproduces that mutation in-process so the guard travels with the suite, in
# addition to the manual sabotage run recorded in the PR body.


def test_mutation_disabling_the_history_match_reds_the_specimen(monkeypatch):
    monkeypatch.setattr(wq, "_match_dated_history", lambda *a, **k: None)
    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_09_21, [_NATHAN_REEVES], history=_HISTORY_09_21)
    assert not ok, "disabling the history lookup must fail the 09-21 specimen again: " + msg
