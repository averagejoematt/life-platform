"""brief_recommendations.py — the Morning Brief trial's recommendation record SEAM (#6175, pending #6158).

#6158 is building the platform's authoritative recommendation record (stable id, coach, exact text,
evidence, decision window, explicitly reported response, follow-up, outcome). It was not on main when
this trial was built, so the brief trial keeps the two things it needs behind this one module, in its
own private partition, and nothing else reads them:

  * FIRST-SEEN (`shown_history`): which action classes each earlier brief showed, derived from what the
    platform already stored — the brief's own `computed_insights.guidance_given` rows (the TL;DR then
    each guidance item), the `computed_metrics` readiness colour (the READINESS SIGNAL every brief
    carries) and, from the first trial send on, the keys the trial itself recorded per send.
  * THE EXPLICITLY REPORTED RESPONSE: the one-use response token, and the answer recorded against it.

#6158 has landed; its pilot (`coach.brief_rec_intake`, dark behind CANONICAL_INTAKE_LIVE below) does NOT re-point
this partition: the trial stays the brief's delivery and interface telemetry, and the canonical record is written
from the daily-brief function — the offer after SES accepts a send, his spent answers on the next run. The public
answer door keeps writing only this partition (owner ruling 2026-11-22 §4: the trial record must not become a
competing authoritative lifecycle).

PARTITION `USER#matthew#SOURCE#brief_trial` (private; never read by a public route or a generator):
  SWITCH#format          {value: off | hybrid | measure}      — the trial switch (absent = off)
  SEND#<data day>        one row per brief send while the switch is not off: variant, word counts,
                         the recommendations shown (id, class, NEW/REPEAT, day n), food/grade flags,
                         and — once he answers — the response
  TOKEN#<sha256 hex>     one row per response link: rec id, send day, recipient hash, expiry, and once
                         used: used_at + response. The URL carries the opaque token; only its hash is
                         stored, so the table cannot mint a working link.

Never inferred: a response exists only when he pressed a button on the confirmation page. No sensor,
training or food data ever writes here.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets

#: THE #6158 PILOT SWITCH — the Morning Brief as the canonical recommendation record's first intake
#: (`coach.brief_rec_intake`). Committed False: the trial runs exactly as before (the intake module is never even
#: imported) and nothing reaches the canonical record. True = the brief records an OFFER after SES accepts a hybrid
#: send, carries his spent button answers into the record on its next run, and asks a due brief follow-up once.
#: Turning it on needs the owner's review of the IAM delta and a daily-brief deploy; rollback = False + deploy.
CANONICAL_INTAKE_LIVE = False

TRIAL_SOURCE = "brief_trial"
SWITCH_SK = "SWITCH#format"
TOKEN_TTL_SECONDS = 48 * 3600  # covers the day it is read and the next morning; tomorrow's brief mints a new one
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")  # secrets.token_urlsafe(32)
_TOKEN_DOMAIN = "brief-response:v1:"  # noqa: S105 — a hash domain label, not a secret
RESPONSE_PATH = "/api/brief_response"

# The button word -> the recorded status, in the owner ruling's vocabulary (2026-11-22 §1:
# accepted, declined, partially followed, deferred, still deciding, not recorded).
RESPONSES = {
    "done": "accepted",
    "not_doing": "declined",
    "still_deciding": "still_deciding",
}
RESPONSE_WORDS = {"done": "Done", "not_doing": "Not doing it", "still_deciding": "Still deciding"}
NOT_RECORDED = "not_recorded"


def trial_pk(user_prefix: str) -> str:
    return user_prefix + TRIAL_SOURCE


def token_hash(token: str) -> str:
    return hashlib.sha256((_TOKEN_DOMAIN + str(token)).encode()).hexdigest()


def recipient_hash(address: str) -> str:
    return hashlib.sha256(str(address or "").strip().lower().encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def response_url(site_url: str, token: str) -> str:
    """The link carries the opaque token and nothing else — no recommendation text, id, date or address."""
    return site_url.rstrip("/") + RESPONSE_PATH + "?t=" + token


def token_valid_shape(token) -> bool:
    return isinstance(token, str) and bool(TOKEN_RE.match(token))


# ── first-seen ───────────────────────────────────────────────────────────────────────────────────


def _guidance_keys(raw) -> set:
    from content.brief_hybrid import classify

    items = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(items, list):
        return set()
    return {classify(i) for i in items[1:] if str(i or "").strip()}  # [0] is the TL;DR: a summary, not an ask


def shown_history(fetch_range, sends: list, start_day: str, end_day: str) -> dict:
    """{data day: set(action keys its brief showed)} for start_day..end_day (both inclusive).

    SEAM (#6158): re-point here when the authoritative recommendation record exists."""
    from content.brief_hybrid import readiness_key

    hist: dict = {}
    for row in fetch_range("computed_insights", start_day, end_day) or []:
        day = str(row.get("sk", ""))[5:15] or row.get("date")
        keys = _guidance_keys(row.get("guidance_given"))
        if day and keys:
            hist.setdefault(day, set()).update(keys)
    for row in fetch_range("computed_metrics", start_day, end_day) or []:
        day = str(row.get("sk", ""))[5:15] or row.get("date")
        key = readiness_key(row.get("readiness_colour"))
        if day and key:
            hist.setdefault(day, set()).add(key)
    for row in sends or []:
        day = str(row.get("sk", ""))[5:15]
        for r in row.get("recs") or []:
            if day and r.get("key"):
                hist.setdefault(day, set()).add(str(r["key"]))
    return hist
