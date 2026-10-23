"""tests/test_partner_email_checkins_5125.py — the support-contact rulings of 2026-10-23 (#5125 R1 / R3 / R5).

Holds:
  * R5 — the partner email's emotional read is `health.checkin_partner_view`: an answered-evenings count and a
    low / moderate / high band per rating with a week-over-week direction; "too few check-ins to say" below
    MIN_EVENINGS; the read PROJECTS only the check-in keys (never intake, mood valence or his word); a failed read is
    an honest absence, never zero; it is the ONLY door from `lambdas/emails/` to either check-in partition, and its
    output never reaches the model's prompt.
  * R3 — the 7-day all-channel silence counts an answered evening check-in as platform use, so a week of check-ins
    is never mailed to the contact as a silence; a check-in row with no rating present is not a check-in.
  * R1 — the contact is read only from the private config object; no identity is logged or stored.

No clock is read: every date is fixed (#4848).
"""

# premerge-gate: #5125: rglob sweep of lambdas/web/ and lambdas/emails/ — the check-in projection is the only door to the owner-only check-in partitions

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))
sys.path.insert(0, str(ROOT / "tests"))

from coach import named_human_contact as nhc  # noqa: E402
from health import checkin_partner_view as cpv  # noqa: E402


def day(d, **kw):
    return {"sk": f"DATE#{d}", "has_checkin": bool(kw), **kw}


WEEK = [
    day("2026-10-12", stress=2, hunger=1, cravings=0),
    day("2026-10-13", stress=2, hunger=0, cravings=1),
    day("2026-10-14", stress=1, hunger=1, cravings=0),
    day("2026-10-15", stress=3, hunger=1, cravings=1),
    day("2026-10-16"),  # a no-check-in marker row (#5211) is not an answered evening
]
PRIOR = [day(f"2026-10-0{i}", stress=4, hunger=1, cravings=0) for i in range(5, 9)]


# ── R5: the projection ───────────────────────────────────────────────────────────────────────
def test_bands_and_direction_in_words():
    v = cpv.summarize(WEEK, PRIOR)
    assert v["evenings"] == 4
    assert v["ratings"]["stress"] == {"band": "moderate", "direction": "lower than last week"}  # mean 2.0 vs 4.0
    assert v["ratings"]["hunger"] == {"band": "low", "direction": "about the same as last week"}
    assert v["ratings"]["cravings"]["band"] == "low"
    assert v["sentence"].startswith("He answered 4 of 7 evening check-ins. Stress mostly moderate (lower than last week)")


def test_band_edges():
    assert [cpv.band(x) for x in (0, 1.49, 1.5, 2.49, 2.5, 4)] == ["low", "low", "moderate", "moderate", "high", "high"]
    assert cpv.band(None) is None


def test_too_few_evenings_reads_as_too_few_never_a_pattern():
    v = cpv.summarize(WEEK[:2], PRIOR)
    assert v["evenings"] == 2 and all(c == {"band": None, "direction": None} for c in v["ratings"].values())
    assert cpv.TOO_FEW in v["sentence"]
    assert cpv.summarize([], PRIOR)["sentence"] == "He did not answer the evening check-in this week."
    assert cpv.summarize(WEEK, PRIOR[:2])["ratings"]["stress"]["direction"] is None  # no direction off a thin prior week


def test_the_sentence_carries_one_count_and_no_score_day_or_word():
    v = cpv.summarize(WEEK + [day("2026-10-17", stress=1, word="exhausted")], PRIOR)
    digits = re.findall(r"\d+", v["sentence"])
    assert digits == ["5", "7"], digits  # the answered count and the week length — nothing else
    assert "exhausted" not in json.dumps(v) and "2026" not in json.dumps(v)


class Table:
    def __init__(self, items=None, fail=False):
        self.items, self.fail, self.calls = items or [], fail, []

    def query(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("ddb")
        lo, hi = kw["ExpressionAttributeValues"][":lo"], kw["ExpressionAttributeValues"][":hi"]
        return {"Items": [i for i in self.items if lo <= i["sk"] <= hi]}


def test_the_read_projects_only_the_checkin_keys():
    t = Table(WEEK + PRIOR)
    v = cpv.week_view(t, "2026-10-12", "2026-10-18", "2026-10-05", "2026-10-11")
    assert v["evenings"] == 4 and v["ratings"]["stress"]["direction"] == "lower than last week"
    for call in t.calls:
        assert call["ExpressionAttributeValues"][":pk"] == "USER#matthew#SOURCE#checkin_intake_pairs"
        assert call["ProjectionExpression"] == cpv.PROJECTION
    projected = {f.strip() for f in cpv.PROJECTION.split(",")}
    assert projected == {"sk", "has_checkin", "hunger", "stress", "cravings"}
    assert not projected & {"kcal", "kcal_over_target", "target_kcal", "protein_hit", "last_meal_min", "mood_valence", "word"}


def test_a_failed_read_is_an_honest_absence():
    v = cpv.week_view(Table(fail=True), "2026-10-12", "2026-10-18", "2026-10-05", "2026-10-11")
    assert v["evenings"] is None and "could not be read" in v["sentence"]


def test_the_projection_is_the_only_door_from_emails_and_web_and_never_reaches_the_prompt():
    importers = []
    for top in ("web", "emails"):
        for path in (ROOT / "lambdas" / top).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "checkin_partner_view" in text:
                importers.append(path.name)
            assert not re.search(
                r"\bfrom health(\.checkin_intake_pairs| import checkin_intake_pairs)|coach\.evening_checkin|from coach import evening_checkin",
                text,
            ), path
    assert importers == ["partner_email_lambda.py"]

    import partner_email_lambda as partner

    placeholders = set(re.findall(r"\{(\w+)\}", partner.BOARD_PROMPT))
    assert not {p for p in placeholders if "checkin" in p or "stress" in p or "mood" in p or "craving" in p}, placeholders
    for gone in ("journal entries", "Journal themes", "Avoidance", "REEVES", "🧠"):
        assert gone not in partner.BOARD_PROMPT, gone


# ── R3: the check-in is a channel of the all-channel silence ─────────────────────────────────
class ContactTable:
    """Engagement channels quiet since 09-05; the evening check-in answered last night (or not at all)."""

    def __init__(self, checkin_items):
        self.checkin_items, self.puts = checkin_items, []

    def query(self, **kw):
        pk = kw["ExpressionAttributeValues"][":pk"]
        if pk.endswith("#SOURCE#evening_checkin"):
            assert "ProjectionExpression" in kw and "word" not in kw["ProjectionExpression"]
            return {"Items": self.checkin_items}
        if pk.endswith("#SOURCE#travel"):
            return {"Items": []}
        return {"Items": [{"sk": "DATE#2026-09-05", "total_completed": 1}]}

    def get_item(self, Key):  # noqa: N803
        return {}

    def put_item(self, Item):  # noqa: N803
        self.puts.append(Item)


class S3:
    def __init__(self):
        self.reads = 0

    def get_object(self, Bucket, Key):  # noqa: N803
        self.reads += 1
        body = json.dumps({"status": "DESIGNATED", "name": "Test Person", "contact": {"email": "contact@example.invalid"}, "armed": True})

        class B:
            def read(self):
                return body.encode()

        return {"Body": B()}


class Ses:
    def __init__(self):
        self.sent = []

    def send_email(self, **kw):
        self.sent.append(kw)


def _leg(table):
    ses, logs, s3 = Ses(), [], S3()
    out = nhc.run_leg(
        table=table,
        ses_client=ses,
        today="2026-09-20",
        user_id="matthew",
        owner_recipient="owner@example.invalid",
        event_dry_run=False,
        log=logs.append,
        s3_client_factory=lambda: s3,
        bucket="b",
    )
    return out, ses, logs, s3


def test_an_answered_checkin_keeps_him_off_the_silence_alert():
    out, ses, logs, s3 = _leg(ContactTable([{"sk": "DATE#2026-09-19", "stress": 2}]))
    assert out["reason"] == "not_quiet" and ses.sent == [] and s3.reads == 0  # the identity is never even read


def test_a_ratingless_checkin_row_is_not_platform_use_and_the_armed_alert_fires():
    out, ses, logs, s3 = _leg(ContactTable([{"sk": "DATE#2026-09-19"}]))
    assert out["sent"] and out["rung"] == nhc.RUNG_QUIET and out["armed"] is True
    assert ses.sent[0]["Destination"]["ToAddresses"] == ["contact@example.invalid"]
    blob = "\n".join(logs) + json.dumps(out)
    assert "Test Person" not in blob and "@" not in blob  # R1: no identity in a log line or the result


def test_the_checkin_channel_is_named_and_presence_only():
    assert nhc.CHECKIN_CHANNEL == "evening_checkin" and nhc.CHECKIN_PRESENCE_FIELDS == ("hunger", "stress", "cravings")
