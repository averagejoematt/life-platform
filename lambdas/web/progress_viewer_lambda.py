"""progress_viewer_lambda.py — the private progress-photo viewer (#3760, epic #3743).

WHAT A READER OF THE PUBLIC REPO SHOULD TAKE FROM THIS FILE

This route exists, it is named here, and none of that helps anyone get in. The gate is an
HMAC key in Secrets Manager (`privacy/progress_access`); the photos are never served from a
public object URL, only as presigned GETs minted per request with a ten-minute life. Knowing
the path buys a stranger exactly one 401.

WHY THIS IS ITS OWN LAMBDA AND NOT A SITE-API ROUTE

Because #3757 already ruled on it, and the ruling has a test:
`tests/test_progress_photos_registration_3757.py::test_no_public_serving_role_can_read_the_raw_tree`
asserts that **no `site_api*` role may name `raw/` at all**. Presigning requires `GetObject`
on `raw/matthew/progress_photos/*`, so putting the viewer in the site-api would have meant
granting the role that answers ~134 anonymous endpoints the ability to read the raw zone —
and the honest way to satisfy a gate that says no is to stop doing the thing, not to widen the
gate. `docs/DATA_GOVERNANCE.md` had already promised "a dedicated Lambda" for the same reason.

So the trust boundary here is the same one the Telegram pair draws (`telegram_webhook` is
near-powerless; `telegram_worker` holds the grants): the public read path cannot reach the
photos, and the function that can reach them answers exactly one path behind a signed cookie.

WHY THE PAGE IS RENDERED HERE AND NOT IN `site/`

Every byte under `site/` is world-readable at the S3 ORIGIN (the `PublicReadSite`
bucket-policy statement) and is swept into the sitemap, the RSS feed and the QA page registry.
A private page cannot live there — not "should not", cannot: the CloudFront behaviour is not
what makes a `site/**` object private, and #3741 is the incident where exactly that assumption
was made about `generated/recap/` and held for eight days at a live, anonymous 200.

WHAT IS SHOWN, AND WHAT IS REFUSED

Weeks as columns, poses (front / side / back) as rows, with the week's weight and tape figures
underneath — from the SAME partitions the public physical surface reads (`withings`,
`measurements`), never a second derivation of either. Two honesty rules carry over from
ADR-104:

  * A week with no weigh-in says "no weigh-in", never the last known number silently reused.
  * Tape is measured every 4-8 weeks, so the figure under a week is usually from an EARLIER
    session. It is labelled with that session's own date and how far back it is, because an
    unlabelled stale measurement under a photo is a comparison the data cannot support.

And the empty state is a real state: no photos exist yet at all (the capture path shipped in
#3758 and the first set is #3761), so the page's first job is to render that honestly with the
protocol day and the caption format, rather than an empty grid that reads as breakage.

NO PHASE FILTER, DELIBERATELY

Every public endpoint in this package runs `with_phase_filter` to hide prior-cycle rows. This
one does not. `progress_photos` is classed CROSS_PHASE in `experiment/phase_taxonomy` precisely
because a before/after spanning experiment restarts is the entire point of taking the
photographs; a filter that hid last cycle's set would delete the comparison the feature exists
for.

REGION

Defined in `LifePlatformWeb` (us-east-1) alongside `email-subscriber`, so its Function URL
domain resolves inside the same stack that builds the CloudFront behaviour — a us-west-2
function would have to travel through a `cdk.json` context value and a two-stack deploy dance.
Its DynamoDB, S3 and Secrets Manager clients are pinned to us-west-2, where the data is.
"""

from __future__ import annotations

import html
import logging
import os
import time
from urllib.parse import parse_qs

import boto3
from boto3.dynamodb.conditions import Key
from common.pacific_time import parse_day_key, shift_day_key, week_close_day
from privacy import progress_access as pa

from web.site_api_common import (
    EXPERIMENT_START,
    S3_REGION,
    USER_PREFIX,
    _cached_secret,
    _decimal_to_float,
    _latest_item_asof,
    _query_source,
    table,
)

try:  # OBS-1: structured logging, like every other handler on the fleet
    from common.platform_logger import get_logger

    logger = get_logger("progress-viewer")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("progress-viewer")
    logger.setLevel(logging.INFO)

S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
# The data's region, not the function's. This Lambda runs in us-east-1 (see the header); every
# client below is pinned to where the bucket, the table and the secret actually are.
DATA_REGION = os.environ.get("S3_REGION", S3_REGION)
SITE_API_ORIGIN_SECRET = os.environ.get("SITE_API_ORIGIN_SECRET", "")
INDEX_PK = f"{USER_PREFIX}progress_photos"
POSES = ("front", "side", "back")

_s3 = None
_secrets = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=DATA_REGION)
    return _s3


def _signing_secret():
    """The HMAC key, or None when it cannot be read.

    None means the viewer answers 503 — never "let them in". The grant lives on this
    function's own role (`role_policies_serve.progress_viewer`); the secret itself is created
    once by hand (AWS writes are owner-gated) and is named in the PR that shipped this route.
    """
    global _secrets
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=DATA_REGION)
    name = os.environ.get(pa.SECRET_NAME_ENV, pa.DEFAULT_SECRET_NAME)
    try:
        return _cached_secret(_secrets, name)
    except Exception as e:  # noqa: BLE001
        logger.error("[progress] signing secret unreadable (%s) — viewer unavailable", type(e).__name__)
        return None


# ── responses ─────────────────────────────────────────────────────────────────
def _headers() -> dict:
    """Headers every response from this route carries.

    `Referrer-Policy: no-referrer` is not decoration. The page embeds presigned S3 URLs and is
    itself reached with a one-time token in the query string; a default referrer policy would
    hand both to any origin the browser talks to next.
    """
    return {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store, no-cache, must-revalidate, private",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def _deny(status: int = 401) -> dict:
    """One body for every refusal — expired, forged, replayed or absent look identical."""
    return {
        "statusCode": status,
        "headers": _headers(),
        "body": "<!doctype html><meta charset=utf-8><title>Not available</title>"
        '<p style="font:16px/1.5 system-ui;margin:3rem auto;max-width:28rem;padding:0 1rem">'
        "This page needs a current link. Ask the bot for one: <code>/progress view</code>.</p>",
    }


def _unavailable() -> dict:
    return {
        "statusCode": 503,
        "headers": _headers(),
        "body": "<!doctype html><meta charset=utf-8><title>Unavailable</title>"
        '<p style="font:16px/1.5 system-ui;margin:3rem auto;max-width:28rem;padding:0 1rem">'
        "The viewer cannot verify links right now. Try again in a minute.</p>",
    }


# ── the route ─────────────────────────────────────────────────────────────────
def handle(event: dict, path: str, method: str) -> dict:
    """`/progress-photos` (and `/progress-photos/`). GET only.

    Three outcomes and no fourth: a valid one-time token is exchanged for a cookie (302), a
    valid cookie renders the page (200), and everything else is the same 401.
    """
    if method != "GET":
        return _deny(405)

    secret = _signing_secret()
    if not secret:
        return _unavailable()

    now = time.time()
    qs = parse_qs(event.get("rawQueryString") or "") or {}
    token = (event.get("queryStringParameters") or {}).get("k") or (qs.get("k") or [None])[0]

    if token:
        ok, reason, nonce = pa.verify_link_token(secret, token, now=now)
        if not ok:
            logger.warning("[progress] link refused: %s", reason)
            return _deny()
        if not pa.consume_nonce(table, nonce, now=now):
            return _deny()
        logger.info("[progress] link redeemed — session issued")
        return {
            "statusCode": 302,
            "headers": {**_headers(), "Location": pa.VIEWER_PATH},
            "cookies": [pa.cookie_attributes(pa.sign_session(secret, now=now))],
            "body": "",
        }

    cookie = pa.cookie_from_header(_cookie_header(event))
    ok, reason = pa.verify_session(secret, cookie, now=now)
    if not ok:
        logger.warning("[progress] session refused: %s", reason)
        return _deny()

    return {"statusCode": 200, "headers": _headers(), "body": render_page(_weeks())}


def _cookie_header(event: dict) -> str:
    """The raw `Cookie:` header, however the invoker spelled it.

    A Lambda Function URL delivers cookies BOTH as a `cookies` list and (for a single header)
    in `headers`. Reading only one of the two is how a cookie check passes in a test and fails
    on the wire, so this reads both and joins them.
    """
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    parts = [str(headers.get("cookie") or "")]
    parts += [str(c) for c in (event.get("cookies") or [])]
    return "; ".join(p for p in parts if p)


# ── the data ──────────────────────────────────────────────────────────────────
def _photo_rows() -> list:
    """Every stored photo index row. No phase filter (see module docstring)."""
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(INDEX_PK) & Key("sk").begins_with("DATE#")}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return _decimal_to_float(items)


def _row_date(row: dict) -> str:
    """The capture day of one index row: the stored `date`, else the sk's own day key.

    `progress_capture.index_sk` writes `DATE#<day>#<pose>`, so the day is the middle
    segment — read positionally rather than by a split that would return the pose if the
    row shape ever changes under us.
    """
    explicit = str(row.get("date") or "")
    if parse_day_key(explicit):
        return explicit
    parts = str(row.get("sk") or "").split("#")
    return parts[1] if len(parts) >= 2 and parse_day_key(parts[1]) else ""


def _row_week(row: dict):
    """The week this photo belongs to — the number `progress_capture` STAMPED at capture.

    Read, never re-derived, and that distinction is load-bearing on exactly this source.
    `progress_photos` is CROSS_PHASE (`experiment/phase_taxonomy`): the photos deliberately
    outlive experiment resets, because a before/after spanning attempts is the whole point.
    Re-deriving the week from the CURRENT `EXPERIMENT_START` would therefore relabel every
    pre-reset photo against a genesis it was never taken under — cycle 16's week 3 would
    render as a negative or an absurd week number the day the seventeenth reset landed, and
    nothing would have changed except the constant.

    So this module produces no week fact of its own. It renders the one the bot already acked
    to him (`progress_capture.handle` → `week_of` → `pacific_time.pacific_day_n`), and a row
    with no stamp — an off-cycle capture — says "off-cycle" rather than guessing.
    """
    try:
        n = int(row.get("week_n"))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _weight_for(as_of: str) -> dict:
    """The last weigh-in in the seven days ending at `as_of`, or an honest absence.

    Reads the `withings` partition through `_query_source` — the same helper
    `/api/weight_progress` uses — over the photo's own trailing week. A stretch with no
    weigh-in returns `{"lbs": None}`; it never borrows a neighbouring column's number
    (ADR-104). The window is anchored on the CAPTURE DATE rather than on a derived
    week-close day, for the cross-phase reason in `_row_week` above: the capture date is
    true in every cycle, and a close day derived from today's genesis is not.
    """
    if not as_of:
        return {"lbs": None}
    start = shift_day_key(as_of, -6)
    rows = [r for r in _query_source("withings", start, as_of) if r.get("weight_lbs")]
    if not rows:
        return {"lbs": None}
    last = sorted(rows, key=lambda r: str(r.get("sk", "")))[-1]
    return {"lbs": round(float(last["weight_lbs"]), 1), "date": str(last.get("sk", "")).replace("DATE#", "")}


def _tape_for(as_of: str) -> dict:
    """The tape session in force on the day of the photo, with its OWN date.

    Tape is measured every 4-8 weeks (`source_registry`'s 60-day staleness), so the session
    under a column is usually older than the photo. `days_back` travels with the numbers so
    the page can say so instead of implying the measurement was taken alongside the shot.
    """
    if not as_of:
        return {}
    rec = _latest_item_asof("measurements", as_of)
    if not rec:
        return {}
    session = str(rec.get("date") or str(rec.get("sk", "")).replace("DATE#", ""))
    d, c = parse_day_key(session), parse_day_key(as_of)
    out = {
        "session_date": session,
        "days_back": (c - d).days if (d and c) else None,
        "waist_navel_in": rec.get("waist_navel_in"),
        "chest_in": rec.get("chest_in"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _weeks() -> list:
    """One column per stored set, oldest first.

    Grouped by the stamped week where there is one, and by the capture DATE where there is
    not — so an off-cycle set gets its own column with its own date rather than being folded
    into a week it does not belong to.

    Weeks with no photo are simply absent rather than rendered empty: this is a record of what
    he actually took, and a column of three grey boxes for a week he skipped would be a
    fabricated absence in a surface whose whole job is honest comparison.
    """
    by_col: dict = {}
    for row in _photo_rows():
        date = _row_date(row)
        pose = str(row.get("pose") or "")
        key = str(row.get("s3_key") or "")
        if not date or pose not in POSES or not key:
            continue
        week = _row_week(row)
        slot = by_col.setdefault(
            f"w{week}" if week else f"d{date}",
            {"week": week, "first_date": date, "last_date": date, "poses": {}},
        )
        slot["first_date"] = min(slot["first_date"], date)
        slot["last_date"] = max(slot["last_date"], date)
        # A retake on a later day within the same column wins — `store()` already overwrote
        # the object for a same-day retake, and across days the newer capture is the current
        # one.
        prior = slot["poses"].get(pose)
        if not prior or date >= prior["date"]:
            slot["poses"][pose] = {"date": date, "key": key}

    columns = []
    for slot in sorted(by_col.values(), key=lambda s: s["first_date"]):
        as_of = slot["last_date"]
        columns.append(
            {
                "week": slot["week"],
                "as_of": as_of,
                "poses": {p: _presign(slot["poses"][p]["key"]) if p in slot["poses"] else None for p in POSES},
                "pose_dates": {p: slot["poses"][p]["date"] for p in slot["poses"]},
                "weight": _weight_for(as_of),
                "tape": _tape_for(as_of),
            }
        )
    return columns


def _presign(key: str):
    """A 10-minute GET for one object under `raw/matthew/progress_photos/`.

    Per request, never stored, never a public object URL. A failure returns None and the cell
    renders as missing — a broken <img> would be indistinguishable from a photo he never took.
    """
    try:
        return _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=pa.PRESIGN_TTL_S,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[progress] presign failed for %s (%s)", key, type(e).__name__)
        return None


# ── the page ──────────────────────────────────────────────────────────────────
_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0b0d10;color:#e8eaed;font:16px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:1.25rem 1rem .5rem;max-width:64rem;margin:0 auto}
h1{font-size:1.15rem;margin:0 0 .2rem;letter-spacing:.01em}
.sub{color:#9aa3ad;font-size:.82rem;margin:0}
main{padding:1rem;overflow-x:auto;-webkit-overflow-scrolling:touch}
.grid{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(72vw,16rem);gap:.75rem;align-items:start;min-width:min-content}
/* Capped rather than 1fr: stretching two columns across a desktop makes each photo
   enormous and the WEEK-OVER-WEEK comparison worse, which is the only thing this page
   is for. Fixed-width columns keep as many weeks in view as the screen allows. */
@media (min-width:52rem){.grid{grid-auto-columns:15rem;justify-content:start}}
.col{background:#14181d;border:1px solid #232a32;border-radius:.6rem;padding:.6rem}
.colhead{font-size:.86rem;font-weight:600;margin:0 0 .5rem}
.colhead span{display:block;font-weight:400;color:#9aa3ad;font-size:.74rem}
figure{margin:0 0 .5rem}
figcaption{font-size:.7rem;color:#8b949e;letter-spacing:.06em;text-transform:uppercase;margin:.15rem 0 0}
/* Every cell is the SAME box (3:4, `contain`) so the pose rows line up across columns —
   comparing week 1 front with week 3 front is the entire feature, and a short cell for a
   pose he skipped would shift every row below it out of alignment. `contain`, never
   `cover`: cropping a body photo to fit a box changes what the photo says. */
img,.miss{aspect-ratio:3/4;width:100%;border-radius:.35rem;background:#0b0d10}
img{display:block;object-fit:contain}
.miss{border:1px dashed #2c343d;color:#6d757e;font-size:.74rem;display:flex;align-items:center;justify-content:center;text-align:center;padding:.5rem}
dl{margin:.6rem 0 0;padding:.55rem 0 0;border-top:1px solid #232a32;font-size:.8rem}
dt{color:#8b949e;font-size:.7rem;letter-spacing:.05em;text-transform:uppercase;margin:.35rem 0 .1rem}
dd{margin:0}
.note{color:#8b949e;font-size:.74rem}
.empty{max-width:34rem;margin:2rem auto;padding:0 1rem;color:#c4ccd4}
code{background:#14181d;border:1px solid #232a32;border-radius:.25rem;padding:.08rem .3rem;font-size:.86em}
footer{max-width:64rem;margin:0 auto;padding:.5rem 1rem 2rem;color:#6d757e;font-size:.72rem}
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _shell(body: str) -> str:
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        '<meta name=robots content="noindex,nofollow,noarchive">'
        "<meta name=referrer content=no-referrer>"
        "<title>Progress — private</title>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def _weight_block(weight: dict) -> str:
    if not weight.get("lbs"):
        return "<dt>Weight</dt><dd class=note>no weigh-in this week</dd>"
    return f"<dt>Weight</dt><dd>{_e(weight['lbs'])} lb <span class=note>({_e(weight.get('date'))})</span></dd>"


def _tape_block(tape: dict) -> str:
    if not tape:
        return "<dt>Tape</dt><dd class=note>no session yet</dd>"
    bits = []
    if tape.get("waist_navel_in") is not None:
        bits.append(f"waist {_e(round(float(tape['waist_navel_in']), 1))}″")
    if tape.get("chest_in") is not None:
        bits.append(f"chest {_e(round(float(tape['chest_in']), 1))}″")
    if not bits:
        bits.append("session recorded, no waist/chest figure")
    back = tape.get("days_back")
    # The provenance is part of the number, not a footnote: a tape session six weeks old under
    # this week's photo is a different claim from one taken the same day.
    when = "measured this week" if back in (0, None) or int(back) <= 6 else f"measured {int(back)} days earlier"
    return f"<dt>Tape</dt><dd>{' · '.join(bits)}<br><span class=note>{_e(tape.get('session_date'))} — {when}</span></dd>"


def _column(week: dict) -> str:
    n = week.get("week")
    head = f"Week {_e(n)}" if n else "Off-cycle"
    cells = []
    for pose in POSES:
        url = (week.get("poses") or {}).get(pose)
        taken = (week.get("pose_dates") or {}).get(pose)
        if url:
            inner = f'<img src="{_e(url)}" alt="{_e(pose)}, {_e(taken)}" loading=lazy>'
        else:
            inner = f"<div class=miss>no {_e(pose)} photo</div>"
        cells.append(f"<figure>{inner}<figcaption>{_e(pose)}</figcaption></figure>")
    return (
        f"<section class=col><h2 class=colhead>{head}<span>shot {_e(week.get('as_of'))}</span></h2>"
        + "".join(cells)
        + f"<dl>{_weight_block(week.get('weight') or {})}{_tape_block(week.get('tape') or {})}</dl></section>"
    )


def _empty_state() -> str:
    """No photos stored yet — the true state until #3761's Day-1 set lands.

    Says what the protocol is and how to send one, because the reader of this page is the one
    person who can change the state it is reporting.
    """
    from common.pacific_time import pacific_today

    today = pacific_today()
    close = week_close_day(today, EXPERIMENT_START)
    when = f"This week's protocol day is <strong>{_e(close)}</strong>." if close else "The cycle has not started yet."
    return (
        "<div class=empty><h1>No progress photos stored yet.</h1>"
        f"<p>{when} Send the photo to the head coach bot with the caption "
        "<code>/progress front</code> (or <code>side</code>, or <code>back</code>). "
        "To back-date a set: <code>/progress front 2026-09-06</code>.</p>"
        "<p class=note>This page shows only what is actually stored. It will not render a "
        "placeholder for a week you did not photograph.</p></div>"
    )


def render_page(weeks: list) -> str:
    """The whole document. Pure — `weeks` in, HTML out, so the render is testable offline."""
    if not weeks:
        return _shell(_empty_state())
    first, last = weeks[0].get("as_of"), weeks[-1].get("as_of")
    body = (
        "<header><h1>Progress — front, side, back by week</h1>"
        f"<p class=sub>{len(weeks)} week{'s' if len(weeks) != 1 else ''} stored · {_e(first)} → {_e(last)} "
        "· private: not linked from anywhere, image links expire in 10 minutes</p></header>"
        "<main><div class=grid>" + "".join(_column(w) for w in weeks) + "</div></main>"
        "<footer>Owner-only (Tier 2). Photos are served as short-lived presigned links and are "
        "never published, aggregated or counted on any public surface.</footer>"
    )
    return _shell(body)


# ── the Lambda entrypoint ─────────────────────────────────────────────────────
def lambda_handler(event: dict, context: object) -> dict:  # noqa: ARG001 — Lambda signature
    """One function, one path, three outcomes.

    The SEC-04 origin guard runs FIRST and above everything that touches data (#3561's rule,
    learned when `/api/healthz` answered a DynamoDB read to any caller of the committed
    Function URL). A Function URL is `auth_type=NONE`, so the invocation itself cannot be
    prevented in-handler; what can be prevented is every byte of work behind it. A direct hit
    that did not come through CloudFront costs a 403 and nothing else.

    Any path other than the viewer's is a 404 — this function has exactly one route, and a
    Function URL that answered anything else would be a second surface nobody registered.
    """
    import hmac as _hmac

    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    if SITE_API_ORIGIN_SECRET:
        if not _hmac.compare_digest(str(headers.get("x-amj-origin") or ""), SITE_API_ORIGIN_SECRET):
            return {"statusCode": 403, "headers": _headers(), "body": ""}

    path = event.get("rawPath") or event.get("path") or "/"
    method = (event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")).upper()
    if path.rstrip("/") != pa.VIEWER_PATH.rstrip("/"):
        return {"statusCode": 404, "headers": _headers(), "body": ""}

    try:
        return handle(event, path, method)
    except Exception as e:  # noqa: BLE001 — a 500 here must not leak a stack trace to the viewer
        logger.error("[progress] viewer failed: %s", e)
        return {"statusCode": 500, "headers": _headers(), "body": "<!doctype html><meta charset=utf-8><title>Error</title>"}


# Alias for callers/tests that prefer the short name.
handler = lambda_handler
