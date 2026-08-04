"""qa_check_podcast_parity.py — the read-aloud orphan regression guard (#1243).

read_aloud.js joins /journal/posts.json to /podcast/episodes.json on an EXACT
date match (#1121, reset-safe by design — see that module's docstring). That
join is honest-empty on a miss: a dangling key silently renders no player
instead of erroring. Silence at the join is correct behaviour for a genuinely
absent episode, but it is indistinguishable from an ORPHANED one — an episode
whose article was re-anchored (a genesis move, ADR-077) after the audio was
rendered, so the episode still carries the article's OLD publish date. #1243
found exactly this: the sole live episode ("The Plan, On the Record",
2026-07-11) named the same article as the live journal entry re-anchored to
2026-08-02 — same title, different date, orphaned read-aloud, and nothing
flagged it until a live fullreview walked the two feeds by hand.

This check automates that walk: for every /podcast/episodes.json entry whose
TITLE exactly matches a /journal/posts.json entry, the two dates must also
match. A title match with a date mismatch is exactly the orphan shape — flag
it at generation time (here, in the nightly QA sweep) instead of failing
silently at join time on the reader's browser.

Deliberately title-keyed, not date-keyed: an episode dated correctly needs no
scrutiny (the join already trivially finds it); this check exists for the
episodes the join silently DROPS. A title with no journal match at all is not
a defect here — chronicle installments cycle out of the current-cycle
manifest by phase-taxonomy design (ADR-077) and their audio is left in place
for the archive, not garbage-collected. This is intentionally the deterministic
counterpart to the read_aloud.js join: same identity rule (title text, not IDs
— neither feed carries a shared record id), opposite failure mode (a promise
here is a FAIL, not honest-empty).

Purely deterministic — no LLM/Bedrock call, so this check is NEVER
budget-paused. Own module (the module-size ceiling split idiom,
#1665/#1944/#1972/#1993) — `assess_podcast_parity` is the pure assessor
tests exercise directly with synthetic feeds; `check_podcast_parity` is the
live-fetching wrapper qa_smoke_lambda wires in.
"""

import json
import urllib.error
import urllib.request

from operational.qa_check import CONTENT_TRUTH, Check
from operational.qa_check_reader_truth import SITE_BASE_URL


def _title_key(title) -> str:
    return str(title or "").strip().lower()


def assess_podcast_parity(posts_payload, episodes_payload):
    """Pure assessor: (ok, message) for a (journal/posts.json, podcast/episodes.json)
    payload pair. Never raises — a malformed shape is itself a finding, not an
    exception.

    posts_payload: {"posts": [{"title": ..., "date": "YYYY-MM-DD", ...}, ...]}
    episodes_payload: {"episodes": [{"title": ..., "date": "YYYY-MM-DD", ...}, ...]}
    """
    if not isinstance(posts_payload, dict) or not isinstance(posts_payload.get("posts"), list):
        return False, "journal/posts.json: missing or malformed 'posts' list"
    if not isinstance(episodes_payload, dict) or not isinstance(episodes_payload.get("episodes"), list):
        return False, "podcast/episodes.json: missing or malformed 'episodes' list"

    posts_by_title = {}
    for p in posts_payload["posts"]:
        if isinstance(p, dict) and p.get("title") and p.get("date"):
            posts_by_title.setdefault(_title_key(p["title"]), []).append(p)

    orphans = []
    for e in episodes_payload["episodes"]:
        if not isinstance(e, dict) or not e.get("title") or not e.get("date"):
            continue
        candidates = posts_by_title.get(_title_key(e["title"]))
        if not candidates:
            continue  # no same-title article live — archived back-catalogue, not a defect
        if all(str(p["date"]) != str(e["date"]) for p in candidates):
            orphans.append(
                f"episode '{e['title']}' dated {e['date']} has a same-title journal article dated "
                f"{'/'.join(str(p['date']) for p in candidates)} — orphaned read-aloud (#1243 shape)"
            )

    if orphans:
        return False, "; ".join(orphans)
    return True, f"{len(episodes_payload['episodes'])} episode(s) checked, no same-title date mismatch"


def _fetch_site_json(path, timeout=15):
    req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-qa-smoke"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed trusted host
        return json.loads(r.read().decode("utf-8", "replace"))


def check_podcast_parity():
    """CHECK — #1243 read-aloud orphan regression guard. Fetches the live
    journal + podcast feeds and runs the deterministic assessor above.
    Fail-soft on fetch errors (a transient blip must never red the nightly);
    a real title/date mismatch is an ALARMED content-truth FAIL — a served
    episode silently orphaned from its article is exactly the regression this
    guard exists to catch."""
    check = Check("podcast_parity:read_aloud_orphan", "Reader Truth", CONTENT_TRUTH)
    try:
        posts = _fetch_site_json("/journal/posts.json")
        episodes = _fetch_site_json("/podcast/episodes.json")
    except urllib.error.HTTPError as e:
        return [check.warn(f"journal/podcast feed fetch failed (fail-soft): HTTP {e.code}")]
    except Exception as e:
        return [check.warn(f"journal/podcast feed fetch failed (fail-soft): {str(e)[:120]}")]

    ok, msg = assess_podcast_parity(posts, episodes)
    return [check.ok(msg) if ok else check.fail(msg)]
