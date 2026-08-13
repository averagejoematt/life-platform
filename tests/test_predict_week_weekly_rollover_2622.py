"""tests/test_predict_week_weekly_rollover_2622.py — #2622: the weekly recurrence.

predict-the-week had no weekly owner. `site/config/current_challenge.json` was a
per-WEEK artifact that a human had to re-stamp every Monday, and nobody ever did:
cycle 11 stamped the WRONG week (#1952, six dark opening days), cycle 13 never
stamped at all (#2612 fixed only the reset path). The next Monday with nothing
behind it was 2026-08-17.

The fix is option (b) from the issue — **the reader derives the week**. The
artifact is read as a per-CYCLE one (its subjects are the frozen
pre-registration's own levers, valid every week of the cycle) and
`_predict_subject_state` stamps the CURRENT Pacific ISO week onto them — plus
option (c), a NAMED absence with reader-facing prose so a dark week is a
statement rather than a blank.

Why no EventBridge seeder (the acceptance's UTC-vs-Pacific question): a cron is
UTC-fixed while the ISO week boundary readers live on is Pacific, so one fixed
hour is right in PDT and an hour wrong in PST — the same wrong-week class that
already cost cycle 11 a week. Deriving at READ time removes the reconciliation
problem instead of solving it: the boundary is evaluated in
America/Los_Angeles at the moment of the request. `test_a_fixed_utc_cron_cannot
_hold_both_dst_states` mutation-proves that claim rather than arguing it.

Pins:
  1. The rollover itself — a week turns over with NO seeder run and the subject
     is there, stamped with the new week.
  2. The DST boundary, proven by mutation at the two instants a fixed-UTC cron
     gets wrong.
  3. The #1198 guard, unweakened: the served week_id is the current week BY
     CONSTRUCTION, and a previous cycle's artifact is refused, never rolled.
  4. The honest absence: every inactive response names its state and carries
     prose, and the cockpit renders it instead of hiding.
  5. One derivation, one week formula — the reader's `_iso_week_of` agrees with
     the seeder's `genesis_iso_week` (no second way to pick a week).
"""

import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from web import site_api_social as social, site_api_social_engage as engage

REPO_ROOT = Path(__file__).resolve().parent.parent
PT = ZoneInfo("America/Los_Angeles")

# The live cycle-13 anchor these pins are written against. Patched onto the module
# under test so the suite stays true after the next reset re-anchors the constant.
GENESIS = "2026-08-10"  # Monday, ISO 2026-W33
GENESIS_WEEK = "2026-W33"

# What the seeder derives from the frozen pre-registration (its own test_specs).
CHALLENGE = {
    "week_id": GENESIS_WEEK,
    "title": "The opening week — the board is on the record",
    "predict_metrics": [
        {"key": "calories", "label": "logged daily calories against the 1,500 kcal pre-registered line"},
        {"key": "steps", "label": "daily steps against the 6,000-step pre-registered floor"},
    ],
    "result": None,
    "prereg_sha256": "0" * 64,
}


def _load(module_name: str, rel_path: str):
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(REPO_ROOT / "deploy"))
bgpw = _load("build_genesis_predict_week", "deploy/build_genesis_predict_week.py")


# ── the clock + the artifact ─────────────────────────────────────────────────

_FROZEN = [datetime(2026, 8, 13, 19, 0, 0, tzinfo=timezone.utc)]


class _FrozenDatetime(datetime):
    """A `datetime` subclass with a pinned `now()` — the module calls `.date()`,
    `.isocalendar()` and `strftime` on the same name, so a Mock will not do."""

    @classmethod
    def now(cls, tz=None):
        return _FROZEN[0].replace(tzinfo=None) if tz is None else _FROZEN[0].astimezone(tz)


class _FakeS3:
    """S3 double serving one fixed current_challenge.json (or a hard 404)."""

    def __init__(self, payload):
        self.payload = payload
        self.reads = 0

    def get_object(self, Bucket=None, Key=None, **_kw):
        self.reads += 1
        if self.payload is None:
            raise RuntimeError("NoSuchKey")

        class _Body:
            def __init__(self, b):
                self._b = b

            def read(self):
                return self._b

        return {"Body": _Body(json.dumps(self.payload).encode())}


@pytest.fixture
def live(monkeypatch):
    """Wire the module to a frozen PT clock, the live genesis, and one artifact.

    Returns a `set_clock(utc_dt)` / `set_artifact(payload)` handle. Nothing else
    is stubbed: `_current_iso_week`, `_pt_today` and the S3 read all run for real
    against the frozen instant, so the boundary assertions below are measurements
    of the shipped code path, not of a test double.
    """
    state = {"s3": _FakeS3(CHALLENGE)}
    monkeypatch.setattr(social, "datetime", _FrozenDatetime)
    monkeypatch.setattr(social, "EXPERIMENT_START", GENESIS)
    monkeypatch.setattr(social.boto3, "client", lambda *a, **k: state["s3"])

    class _Handle:
        def set_clock(self, utc_dt):
            _FROZEN[0] = utc_dt

        def set_artifact(self, payload):
            state["s3"] = _FakeS3(payload)
            monkeypatch.setattr(social.boto3, "client", lambda *a, **k: state["s3"])

        @property
        def s3(self):
            return state["s3"]

    return _Handle()


def _at(y, m, d, hh, mm=0):
    """A wall-clock instant in Pacific Time, as the UTC instant the clock sees."""
    return datetime(y, m, d, hh, mm, tzinfo=PT).astimezone(timezone.utc)


# ── 1. the rollover: a Monday with no seeder run ─────────────────────────────


def test_the_week_rolls_over_with_no_seeder_run(live):
    """THE acceptance mutation. The artifact is stamped 2026-W33 and NOTHING
    writes it again. Cross the Pacific Monday into W34: pre-#2622 this returned
    None and the widget went blank (the third dark-week failure); now the same
    unchanged artifact serves W34."""
    live.set_clock(_at(2026, 8, 16, 23, 50))  # Sunday night, still W33
    subj, state = social._predict_subject_state()
    assert (subj["week_id"], state) == (GENESIS_WEEK, "live")

    live.set_clock(_at(2026, 8, 17, 0, 10))  # Monday 00:10 PT — nobody ran anything
    subj, state = social._predict_subject_state()
    assert subj is not None, "the widget went dark on the Monday — the #2622 regression"
    assert (subj["week_id"], state) == ("2026-W34", "rolled")
    # Same frozen levers, and the stored stamp is preserved as provenance.
    assert set(subj["metrics"]) == {"calories", "steps"}
    assert subj["derived_from"] == GENESIS_WEEK
    # Eight weeks on, still no seeder run.
    live.set_clock(_at(2026, 10, 12, 9, 0))
    subj, state = social._predict_subject_state()
    assert (subj["week_id"], state) == ("2026-W42", "rolled")


def test_a_measured_result_never_rides_along_into_a_new_week(live):
    """`result` is the outcome of the week it was measured in. Serving W33's
    reveal under W34's week_id would be a fabricated claim about a week that has
    not happened (ADR-104), so it is dropped on every rolled week."""
    live.set_artifact(dict(CHALLENGE, result={"metric": "steps", "direction": "up"}))
    live.set_clock(_at(2026, 8, 14, 9, 0))  # inside W33 — the reveal is honest
    assert social._predict_subject_state()[0]["result"] == {"metric": "steps", "direction": "up"}
    live.set_clock(_at(2026, 8, 17, 9, 0))  # W34 — the reveal belongs to last week
    subj, state = social._predict_subject_state()
    assert state == "rolled" and subj["result"] is None


def test_the_subject_is_re_read_every_request(live):
    """No module cache: a re-seed (or a reveal) lands without a cold start."""
    live.set_clock(_at(2026, 8, 17, 9, 0))
    social._predict_subject_state()
    social._predict_subject_state()
    assert live.s3.reads == 2


# ── 2. the boundary, and why there is no cron ────────────────────────────────


@pytest.mark.parametrize(
    "instant,expected",
    [
        (_at(2026, 8, 16, 23, 59), GENESIS_WEEK),  # Sunday 23:59 PDT  = Mon 06:59Z
        (_at(2026, 8, 17, 0, 0), "2026-W34"),  # Monday 00:00 PDT  = Mon 07:00Z
        (_at(2026, 11, 1, 23, 59), "2026-W44"),  # Sunday 23:59 PST  = Mon 07:59Z
        (_at(2026, 11, 2, 0, 0), "2026-W45"),  # Monday 00:00 PST  = Mon 08:00Z
    ],
)
def test_the_boundary_is_pacific_midnight_in_both_dst_states(live, instant, expected):
    live.set_clock(instant)
    assert social._predict_subject_state()[0]["week_id"] == expected


def test_a_fixed_utc_cron_cannot_hold_both_dst_states(live):
    """The reconciliation, mutation-proved instead of argued.

    A seeder Lambda's schedule must be UTC-fixed (no DST drift, CLAUDE.md), but
    the reader's week boundary is Pacific midnight — which is 07:00Z under PDT
    and 08:00Z under PST. Pick either hour and the cron is wrong for half the
    year: at 07:30Z on a PST Monday it is still SUNDAY in Pacific, so a seeder
    firing then would stamp the incoming week onto a week readers are still
    living in — exactly cycle 11's wrong-week failure (#1952), which the #1198
    guard then converts into a dark week.

    Read-time derivation has no such hour to pick.
    """
    pdt_boundary = _at(2026, 8, 17, 0, 0)
    pst_boundary = _at(2026, 11, 2, 0, 0)
    assert (pdt_boundary.hour, pst_boundary.hour) == (7, 8), "the Pacific Monday moves an hour in UTC across DST"

    # 07:30Z — the hour a cron tuned to the PDT boundary would fire year-round.
    live.set_clock(datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc))
    assert datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc).astimezone(PT).weekday() == 6  # still Sunday in PT
    assert (
        social._predict_subject_state()[0]["week_id"] == "2026-W44"
    ), "the reader is still in last week — a cron here stamps the wrong one"

    # One hour later the Pacific week has actually turned, and so has the reader.
    live.set_clock(datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc))
    assert social._predict_subject_state()[0]["week_id"] == "2026-W45"


def test_the_reader_and_the_seeder_share_one_week_formula(live):
    """No second way to pick a week: `_iso_week_of` IS `genesis_iso_week`,
    including the ISO year boundary where %Y-W%V splits one week in two."""
    for d in ("2026-08-10", "2026-12-28", "2024-12-30", "2027-01-03", "2026-01-01"):
        assert social._iso_week_of(date.fromisoformat(d)) == bgpw.genesis_iso_week(d)
    assert social._iso_week_of(date(2024, 12, 30)) == "2025-W01"


# ── 3. the #1198 guard, unweakened ───────────────────────────────────────────


def test_a_previous_cycles_challenge_never_rolls_forward(live):
    """The reset leaves the OUTGOING cycle's challenge in S3 (that is #2612's
    whole story). Rolling it forward would solicit bets on levers the current
    freeze never pre-registered, so anything stamped before the live genesis week
    is refused — the roll-forward is scoped to the cycle it was derived for."""
    live.set_clock(_at(2026, 8, 17, 9, 0))
    for stale in ("2026-W32", "2026-W01", "2025-W52"):
        live.set_artifact(dict(CHALLENGE, week_id=stale))
        assert social._predict_subject_state() == (None, "no_subject"), stale


def test_the_served_week_is_the_current_week_by_construction(live):
    """The cycle-11 class (a WRONG week_id served) is now unreachable: the reader
    never echoes the stored stamp on a rolled week, it emits its own."""
    live.set_clock(_at(2026, 8, 20, 9, 0))  # W34
    for stamped in (GENESIS_WEEK, "2026-W34", "2026-W35", "2026-W99"):
        live.set_artifact(dict(CHALLENGE, week_id=stamped))
        subj, _ = social._predict_subject_state()
        assert subj["week_id"] == social._current_iso_week() == "2026-W34", stamped


def test_a_malformed_stamp_is_refused_not_rolled(live):
    """The cycle check is a STRING comparison, so a junk stamp must be rejected
    before it — 'garbage' sorts above every real week id and would otherwise read
    as this cycle's and roll forward."""
    live.set_clock(_at(2026, 8, 17, 9, 0))
    for junk in ("garbage", "2026-W3", "W33", "2026_W33", "2026-w33", "next week"):
        live.set_artifact(dict(CHALLENGE, week_id=junk))
        assert social._predict_subject_state() == (None, "no_subject"), junk


def test_a_future_stamp_is_pulled_back_to_the_current_week(live):
    """A subject stamped for a week that has not arrived must not solicit bets on
    that future window — it is served as THIS week's subject or not at all."""
    live.set_clock(_at(2026, 8, 20, 9, 0))
    live.set_artifact(dict(CHALLENGE, week_id="2026-W40"))
    subj, state = social._predict_subject_state()
    assert (subj["week_id"], state) == ("2026-W34", "rolled")


def test_nothing_is_served_before_day_one(live):
    """#931: the pre-start countdown. Dark is the correct state before genesis —
    but now it is a NAMED dark, not a blank."""
    live.set_clock(_at(2026, 8, 3, 9, 0))
    assert social._predict_subject_state() == (None, "pre_start")


def test_an_unusable_or_missing_artifact_fails_closed(live):
    live.set_clock(_at(2026, 8, 17, 9, 0))
    for payload in (
        None,
        {},
        {"week_id": GENESIS_WEEK},
        {"week_id": GENESIS_WEEK, "predict_metrics": []},
        {"predict_metrics": [{"key": "steps"}]},
    ):
        live.set_artifact(payload)
        assert social._predict_subject_state() == (None, "no_subject"), payload


def test_a_broken_genesis_constant_refuses_to_roll(monkeypatch, live):
    """Fail closed, never guess: with no usable anchor the cycle scope cannot be
    checked, so nothing rolls forward."""
    live.set_clock(_at(2026, 8, 17, 9, 0))
    for bad in ("", None, "not-a-date"):
        monkeypatch.setattr(social, "EXPERIMENT_START", bad)
        assert social._predict_subject_state() == (None, "no_subject"), bad


# ── 4. the honest absence (acceptance item (c)) ──────────────────────────────


def _get(qs=None):
    return {"queryStringParameters": qs or {}, "headers": {"x-forwarded-for": "203.0.113.7"}}


@pytest.mark.parametrize("state", sorted(engage.PREDICT_ABSENCE_NOTES))
def test_every_absence_state_carries_reader_facing_prose(monkeypatch, state):
    """A surface that renders nothing is indistinguishable from a broken one —
    which is exactly why a whole dark cycle went unnoticed. Every inactive
    response names its state and says something a reader can read."""
    monkeypatch.setattr(social, "_predict_subject_state", lambda: (None, state))
    body = json.loads(social.handle_predict_week_tally(_get())["body"])
    assert body["active"] is False
    assert body["state"] == state
    assert len(body["note"].split()) >= 5 and body["note"].endswith(".")


def test_an_unknown_absence_state_still_says_something(monkeypatch):
    monkeypatch.setattr(social, "_predict_subject_state", lambda: (None, "something_new"))
    body = json.loads(social.handle_predict_week_tally(_get())["body"])
    assert body["active"] is False and body["note"].strip()


def test_the_tally_endpoint_serves_the_rolled_week(live, monkeypatch):
    live.set_clock(_at(2026, 8, 17, 9, 0))
    monkeypatch.setattr(engage, "_predict_tallies", lambda *a, **k: {"up": 0, "down": 0, "flat": 0})
    body = json.loads(social.handle_predict_week_tally(_get())["body"])
    assert body["active"] is True and body["week_id"] == "2026-W34"
    assert set(body["metrics"]) == {"calories", "steps"}


def test_the_cockpit_states_the_absence_instead_of_hiding(live):
    """The front-end half of (c): an inactive-but-reachable response renders the
    API's own prose. Only a failed fetch still hides the section — a 500 is not a
    statement the page can honestly make."""
    js = (REPO_ROOT / "site" / "assets" / "js" / "cockpit.js").read_text()
    block = js[js.index("async function renderPredict()") : js.index("function _predictTallyLine")]
    assert "predict-none" in block and "d.note" in block
    # the inactive branch UNHIDES; the only remaining `hidden = true` is the fetch failure
    assert re.search(r"if \(!d\) \{ sec\.hidden = true; return; \}", block)
    assert block.count("sec.hidden = true") == 1
    assert block.count("sec.hidden = false") == 2
    assert ".predict-none" in (REPO_ROOT / "site" / "assets" / "css" / "cockpit.css").read_text()


# ── 5. the write leg still keys on the week actually being served ────────────


def test_a_prediction_posts_against_the_rolled_week(live):
    """The POST leg validates against `_predict_subject`, so a reader betting on
    the rolled week is accepted and last week's id is rejected (409) — votes can
    never land in a bucket that has already closed."""
    live.set_clock(_at(2026, 8, 17, 9, 0))
    assert social._predict_subject()["week_id"] == "2026-W34"
    ev = {"body": json.dumps({"week_id": GENESIS_WEEK, "metric": "steps", "choice": "up"}), "headers": {"x-forwarded-for": "203.0.113.7"}}
    assert social._handle_predict_week(ev)["statusCode"] == 409
