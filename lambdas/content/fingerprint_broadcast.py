"""fingerprint_broadcast.py — #1402: the broadcast payload for the Daily Fingerprint.

The card already exists. `og_image_lambda.build_fingerprint` has drawn the day's mark
since #1379, and `web.fingerprint.build_mark` makes it a *pure* function of the day's
real readings — same numbers in, byte-identical mark out. What did not exist was
anything postable: the PNG was overwritten daily at one URL (so yesterday's post would
point at today's picture), and there was no caption, so every share was hand-written.

This module supplies the missing half, and only that half:

  • a DATED, immutable artifact pair — `/moments/fingerprint/{date}/` and
    `/moments/assets/fingerprint-{date}.png` — written by `og_moments._sweep_fingerprint`
    through the same `_put_moment` path every other moment class uses.
  • a deterministic PROVENANCE caption: day N, attempt M, as of <date>, how many of the
    tracked signals actually reported, and the link. No adjectives, no call to action.

Three properties are load-bearing, each enforced in code below and pinned by
tests/test_fingerprint_broadcast.py:

1. **Projection only, never generation** (ADR-140 rule 1). Every value in the payload is
   read through `project_public()`, which can reach exactly the fields in
   `PUBLIC_SOURCE_FIELDS` — all of them already published on averagejoematt.com's
   `public_stats.json`. `build_broadcast` never touches the raw stats dict. There is no
   `bedrock_client` import and no code path that could acquire one: the caption is a
   format string, which is the whole point (ADR-108 measured a 10.2% quality-gate failure
   rate — a managed risk on a correctable email, a certainty-with-a-schedule on an
   irreversible public post).

2. **No body claim, ever.** The mark is drawn from recovery/sleep/HRV/streak and the
   caption carries none of those numbers — but "carries none today" is a property of the
   current template, not of the artifact. `assert_no_body_claims()` makes it structural:
   the caption is scanned for weight/body-composition vocabulary and digits-adjacent
   units before the payload is returned, so a future edit that reintroduces one fails
   the build rather than the review.

3. **Human-selected posting only.** `AUTOMATED_SYNDICATION_ALLOWED` is False and the
   payload says so in-band. ADR-140 rule 5 permanently excludes milestones, achievements,
   weigh-ins and anything body-composition-related from AUTOMATED posting, and #1629's
   owner-recorded non-negotiable is broader still — no automated surface may post a claim
   about Matthew's body. The fingerprint is a pure function of his vitals. So the ONLY
   sanctioned consumer of this payload is `scripts/post_social.py`, where a human reads
   the caption and chooses. Reversing that needs a new three-board convening, not an edit
   here. `syndicatable` in the payload answers "may a human be offered this?" — never
   "may a robot post this?", which is answered No, above, structurally.

Stdlib + `common.utm` only. Pure and re-runnable: identical inputs give an identical
payload apart from `generated_at`.
"""

import re

from common.utm import with_utm

SITE_BASE = "https://averagejoematt.com"

# The one prefix a broadcast URL may live under. Everything below /moments/ is written by
# the daily og sweep into the `generated/` S3 prefix (ADR-046) and served publicly via
# CloudFront's generated origin — so "is it on the allowlist" and "is it already public"
# are the same question, answered by string prefix rather than by reviewer memory.
PUBLIC_URL_PREFIXES = ("/moments/",)

# Every field the payload may read, as (block, key) pairs into public_stats.json. All five
# are already rendered to readers on the cockpit and /data/wall/. Adding a row here is the
# deliberate act of widening what may be broadcast; nothing else in this module can reach
# a field that is not listed.
PUBLIC_SOURCE_FIELDS = (
    ("platform", "days_in"),
    ("platform", "tier0_streak"),
    ("vitals", "recovery_pct"),
    ("vitals", "sleep_hours"),
    ("vitals", "hrv_ms"),
)

# Vocabulary that would turn a provenance line into a claim about a body. Matched
# case-insensitively as whole words against the assembled caption. This is deliberately
# blunt: a false positive costs one word choice, a false negative costs an irreversible
# public post that the 2026-07-21 board denied on the merits.
BODY_CLAIM_TOKENS = (
    "lbs",
    "lb",
    "kg",
    "kgs",
    "pound",
    "pounds",
    "weight",
    "weighed",
    "weigh",
    "weigh-in",
    "bmi",
    "bodyfat",
    "body fat",
    "waist",
    "down from",
    "lost",
)

# Engagement-bait vocabulary. The no-gloss rule (DESIGN_SYSTEM_V5 §"earned glow / no
# gloss") is a design standard for pixels; a syndicated caption is the same standard in
# prose. The template is checked against this list by a test, not just by taste.
ENGAGEMENT_BAIT_TOKENS = (
    "you won't believe",
    "you wont believe",
    "link in bio",
    "smash",
    "like and",
    "follow for",
    "drop a",
    "who else",
    "tag someone",
    "let me know",
    "guess how",
    "insane",
    "crazy",
    "shocking",
    "must-see",
    "game changer",
    "game-changer",
    "transformation",
    "secret",
    "hack",
)

# A day whose mark is "warming up" (fewer than web.fingerprint.THIN_N signals reported)
# still gets its card and its permalink — the sparse mark IS the honest render, and the
# archive should not have holes. It is simply not offered for posting: #1629's
# non-negotiable 11 was written from cycle 8's three present-None firings, where a reset
# week produced confident output about a hollow artifact.
UTM_MEDIUM = "social"
UTM_CAMPAIGN = "fingerprint"
DEFAULT_CHANNEL = "bluesky"

# See the module docstring, property 3. Read by scripts/post_social.py and pinned by test.
AUTOMATED_SYNDICATION_ALLOWED = False
AUTOMATED_SYNDICATION_REASON = "denied — ADR-140 rule 5 / #1629: no automated surface posts a vitals-derived mark. Human selection only."


class BroadcastContentError(ValueError):
    """A payload tried to carry something it is structurally not allowed to carry."""


def project_public(stats):
    """Reduce `public_stats.json` to exactly the fields on PUBLIC_SOURCE_FIELDS.

    The projection — not the raw stats dict — is what `build_broadcast` reads, so an
    unlisted field is not "filtered out later", it is never in scope. Missing blocks and
    missing keys both yield None rather than raising: a gap is a legitimate day.
    """
    stats = stats or {}
    out = {}
    for block, key in PUBLIC_SOURCE_FIELDS:
        value = (stats.get(block) or {}).get(key)
        out[f"{block}.{key}"] = value
    return out


def card_path(date_str):
    """The dated card. Matches `_put_moment(s3, 'fingerprint', date, ...)` exactly."""
    return f"/moments/assets/fingerprint-{date_str}.png"


def permalink_path(date_str):
    """The dated permalink shell. Immutable once written — that is the point: a post
    made today must still point at today's mark a year from now."""
    return f"/moments/fingerprint/{date_str}/"


def assert_public_artifact(path):
    """Every URL a broadcast emits must be a generated, already-public /moments/ path."""
    if not isinstance(path, str) or not path.startswith(PUBLIC_URL_PREFIXES):
        raise BroadcastContentError(f"broadcast URL is not an allowlisted public artifact: {path!r}")
    return path


def assert_no_body_claims(text):
    """Raise if the caption contains body-composition vocabulary (ADR-140 rule 5)."""
    lowered = str(text or "").lower()
    for token in BODY_CLAIM_TOKENS:
        if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", lowered):
            raise BroadcastContentError(f"broadcast caption carries a body claim ({token!r}); ADR-140 rule 5 forbids it")
    return text


def assert_no_engagement_bait(text):
    """Raise if the caption reads as engagement bait rather than provenance."""
    lowered = str(text or "").lower()
    for token in ENGAGEMENT_BAIT_TOKENS:
        if token in lowered:
            raise BroadcastContentError(f"broadcast caption carries engagement bait ({token!r}); provenance only")
    return text


def _provenance_line(date_str, day, attempt):
    """ "The daily fingerprint — day 4, attempt 12, as of 2026-08-05."

    day / attempt are omitted rather than guessed when unavailable — an absent number is
    honest, an invented one is the failure mode this platform exists to avoid.
    """
    bits = []
    if isinstance(day, int) and day > 0:
        bits.append(f"day {day}")
    if isinstance(attempt, int) and attempt > 0:
        bits.append(f"attempt {attempt}")
    bits.append(f"as of {date_str}")
    return "The daily fingerprint — " + ", ".join(bits) + "."


def _method_line(n_signals, total_signals, warming_up):
    """What the mark is and what it was drawn from. No adjectives about the day."""
    reported = f"{n_signals} of {total_signals} signals reported"
    if warming_up:
        return f"Only {reported} today — too thin to earn the glow, so the mark stays sparse."
    return f"Same numbers in, same mark out. {reported}; the glow is earned, never added."


def build_caption(*, date_str, day, attempt, n_signals, total_signals, warming_up, channel=DEFAULT_CHANNEL):
    """The full provenance caption: what it is · what it was drawn from · where to look.

    Deterministic — no clock, no randomness, no model. The link is UTM-tagged through the
    one canonical tagger (#1621) so a click from a syndicated card is attributable to the
    channel that carried it, which is the epic's actual leading measure.
    """
    link = with_utm(SITE_BASE + permalink_path(date_str), source=channel, medium=UTM_MEDIUM, campaign=UTM_CAMPAIGN)
    caption = "\n\n".join(
        [
            _provenance_line(date_str, day, attempt),
            _method_line(n_signals, total_signals, warming_up),
            link,
        ]
    )
    assert_no_body_claims(caption)
    assert_no_engagement_bait(caption)
    return caption


def build_broadcast(*, date_str, mark, stats, total_signals, attempt=None, channel=DEFAULT_CHANNEL, generated_at=None):
    """Assemble the day's broadcast payload from already-public values only.

    `mark` is the spec `web.fingerprint.build_mark` already produced for the card — passed
    in rather than recomputed so the caption's signal count can never disagree with the
    picture it captions.

    Returns a dict carrying the dated card + permalink, the provenance caption, the
    signal count, and the two governance flags (`syndicatable`, `automated_syndication`).
    """
    public = project_public(stats)
    day = public["platform.days_in"]
    day = int(day) if isinstance(day, (int, float)) else None

    mark = mark or {}
    n_signals = int(mark.get("n") or 0)
    warming_up = bool(mark.get("warming_up", True))

    caption = build_caption(
        date_str=date_str,
        day=day,
        attempt=attempt,
        n_signals=n_signals,
        total_signals=int(total_signals),
        warming_up=warming_up,
        channel=channel,
    )

    payload = {
        "date": date_str,
        "day": day,
        "attempt": attempt,
        "channel": channel,
        "card_url": assert_public_artifact(card_path(date_str)),
        "permalink": assert_public_artifact(permalink_path(date_str)),
        "caption": caption,
        "signals_reported": n_signals,
        "signals_tracked": int(total_signals),
        "warming_up": warming_up,
        # May a HUMAN be offered this for posting? A warming-up mark is published but not
        # offered — see the comment above UTM_MEDIUM.
        "syndicatable": not warming_up,
        # May any AUTOMATED surface post it? No, structurally. See docstring property 3.
        "automated_syndication": AUTOMATED_SYNDICATION_REASON,
        "generated_at": generated_at,
    }
    return payload


def shell_body_html(payload):
    """The permalink shell's body — the caption's own provenance, nothing more.

    Escaping is the caller's job (`og_moments._shell_html` escapes its own fields); the
    only interpolated values here are a date and two integers.
    """
    return (
        f"<p>The mark for {payload['date']} — a pure function of that day's readings, "
        f"drawn from {payload['signals_reported']} of {payload['signals_tracked']} tracked signals.</p>"
        "<p>The same numbers always draw the same mark, and the glow can only be earned by "
        "real readings, so it cannot be faked. A sparse, unlit mark is a day that reported "
        "little — an honest render, not a broken page.</p>"
    )
