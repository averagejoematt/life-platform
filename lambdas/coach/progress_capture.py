"""progress_capture.py — a progress photo from his phone, stored owner-only (#3758).

WHAT THIS IS

The capture half of #3743. He takes a front/side/back photo, sends it to the headcoach
Telegram bot with the caption `/progress front`, and it lands in the raw zone under his
own owner-only prefix with an index row beside it. Nothing about it is public, nothing
about it is inferred, and no model sees the image.

Telegram is a fourth capture channel, after webhook, API poll and MCP. It earns that on
one property the other three do not have: the camera and the chat are already in his hand
at the moment the photo exists. A capture path he has to remember to visit is a capture
path that stops producing in week three, which is what the `progress_photos` registry row
means by `behavioral: True`.

THE ORDER THIS LANDED IN, AND WHY IT MATTERS

`#3782` registered the source — tier, phase class, prefix, `catalog: False` — BEFORE this
module could store a single byte. That is ADR-154's ordered checklist: privacy tier before
the first write, not after the first week. This module is the second half, and it may
assume the tier exists because the tier already shipped.

WHAT IS DELIBERATELY NARROW

  * ONE bot. The headcoach bot only. Every coach bot shares this worker, and a photo
    arriving at the sleep coach is not a progress photo — it is a photo, in a chat, whose
    meaning nobody declared.
  * ONE chat. His own 1:1, resolved through `telegram_group.first_private_chat_id`, and
    never a group. A group id is negative and is filtered there for exactly this class of
    reason; a body photo broadcast to the board room is not a bug that can be undone.
  * ONE caption shape. `/progress <front|side|back> [YYYY-MM-DD]`. The optional past date
    is what lets a Day-1 set be back-dated after the fact (#3761) without a second command.
  * ONE content type. A JPEG, by magic bytes, under the size cap. Telegram says what it
    thinks it sent; the first three bytes are what it actually sent.

FAIL-SOFT, NOT FAIL-OPEN

Every refusal here returns a reason and stores nothing. The asymmetry is deliberate and
runs the opposite way from the publish gates: a publish gate that cannot judge must refuse
to publish, because the cost of a wrong PUBLISH is unbounded. This is a capture path into
an owner-only prefix, so the costly failure is the opposite one — a photo he took that
never landed, discovered weeks later when the set is impossible to retake. So a refusal
always TEXTS HIM BACK. Silence is the one outcome this module never produces.

IDEMPOTENT ON `file_unique_id`

Telegram redelivers on its own schedule and the worker's update dedupe is per-partition.
`file_unique_id` is stable for the same file across every redelivery and every bot, so it
is the key that answers "have I already stored this exact photo" — not the update id, not
the S3 key, and not a hash of the bytes we would have to download first to compute.

Pure and injectable: no boto3 client, no urllib opener and no clock is constructed here.
The worker passes them in, which is what makes the whole path testable with no network —
the `telegram_gateway` house style.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_TELEGRAM_FILE = "https://api.telegram.org/file/bot{token}/{file_path}"

#: The only bot that may capture a photo. `telegram_group.CHAIR_ROUTE` is the same
#: literal for a different reason (who chairs the room); this one is "who holds the
#: camera", and conflating them would make a change to either silently move the other.
CAPTURE_BOT_KEY = "headcoach"

#: `/progress front`, `/progress side 2026-09-06`. Anchored at both ends: a caption that
#: merely CONTAINS the word is a caption about a photo, not a command to store one.
CAPTION_RE = re.compile(r"^/progress\s+(front|side|back)(?:\s+(\d{4}-\d{2}-\d{2}))?\s*$", re.IGNORECASE)

POSES = ("front", "side", "back")

#: Telegram's own photo cap is 10 MB; 20 MB is headroom over it, not a policy. The real
#: purpose of a cap is that an unbounded read into Lambda memory is how a capture path
#: becomes an outage.
MAX_BYTES = 20 * 1024 * 1024
HTTP_TIMEOUT_S = 15

#: JPEG's SOI marker. Telegram's `photo` array is always re-encoded JPEG; a PNG or a
#: video thumbnail arriving here means something about the update was not what it claimed.
_JPEG_MAGIC = b"\xff\xd8\xff"

RAW_PREFIX = "raw/matthew/progress_photos"
INDEX_PK = "USER#matthew#SOURCE#progress_photos"

FORMAT_HINT = (
    "I can store that as a progress photo, but I need a caption to know which pose it is.\n\n"
    "Send the photo again with:  /progress front   (or side, or back)\n"
    "To back-date a set:  /progress front 2026-09-06"
)


class Refused(Exception):
    """A photo that will not be stored, with the reason he is told."""

    def __init__(self, reason: str, reply: str = ""):
        self.reason = reason
        self.reply = reply or reason
        super().__init__(reason)


# ── the caption ───────────────────────────────────────────────────────────────
def parse_caption(caption: str) -> Optional[tuple]:
    """`(pose, date_or_None)` for a valid `/progress` caption, else None.

    None means "this is not a capture command" and is NOT an error — most captioned
    photos in a coach chat are just captioned photos.
    """
    m = CAPTION_RE.match(" ".join(str(caption or "").split()))
    if not m:
        return None
    return m.group(1).lower(), m.group(2)


def is_capture_attempt(caption: str) -> bool:
    """True when he clearly MEANT to store a photo, whether or not he got it right.

    The distinction this draws is the whole difference between a helpful bot and a noisy
    one. A photo with no caption, or a caption about something else, is left alone. A
    caption that starts with `/progress` and then fails to parse is a typo, and a typo
    deserves the format hint rather than silence — he is standing in front of a mirror
    waiting for a reply.
    """
    return str(caption or "").strip().lower().startswith("/progress")


# ── the photo on the wire ─────────────────────────────────────────────────────
def largest_photo(sizes) -> dict:
    """The biggest rendition Telegram offers for one photo.

    Telegram sends an array of pre-scaled sizes and the largest is the closest thing to
    what his camera produced. Storing a thumbnail would be silently lossy in a way that
    only becomes visible months later, when the comparison this whole feature exists for
    is finally worth making.
    """
    best = None
    for s in sizes or []:
        if not isinstance(s, dict) or not s.get("file_id"):
            continue
        area = int(s.get("width") or 0) * int(s.get("height") or 0)
        rank = (int(s.get("file_size") or 0), area)
        if best is None or rank > best[0]:
            best = (rank, s)
    if best is None:
        raise Refused("no usable photo size in the update")
    return best[1]


def _api_get(url: str, opener=None) -> bytes:
    open_url = opener or urllib.request.urlopen
    with open_url(urllib.request.Request(url), timeout=HTTP_TIMEOUT_S) as r:
        return r.read()


def resolve_file_path(token: str, file_id: str, *, opener=None) -> str:
    """Telegram's `getFile` — the only way to turn a file_id into a download path.

    There is no other `getFile` in this repo; `telegram_group.bot_username` is the
    template for the shape (call a Bot API method, read `result`, fail soft), and this
    follows it except in one respect: it raises. A username lookup that fails degrades
    the room; a file lookup that fails means there is nothing to store, and pretending
    otherwise would write a zero-byte object under a real key.
    """
    url = _TELEGRAM_API.format(token=token, method="getFile") + f"?file_id={file_id}"
    try:
        result = (json.loads(_api_get(url, opener).decode("utf-8")) or {}).get("result") or {}
    except Exception as e:  # noqa: BLE001
        raise Refused(f"getFile failed ({type(e).__name__})", "Telegram would not hand me that file. Try sending it again.")
    path = result.get("file_path")
    if not path:
        raise Refused("getFile returned no file_path", "Telegram would not hand me that file. Try sending it again.")
    return str(path)


def download(token: str, file_path: str, *, opener=None, max_bytes: int = MAX_BYTES) -> bytes:
    """The bytes, checked for size and for actually being a JPEG."""
    url = _TELEGRAM_FILE.format(token=token, file_path=file_path)
    try:
        body = _api_get(url, opener)
    except Exception as e:  # noqa: BLE001
        raise Refused(f"file download failed ({type(e).__name__})", "I could not download that photo. Try sending it again.")
    if len(body) > max_bytes:
        raise Refused(f"photo is {len(body)} bytes, over the {max_bytes} cap", "That photo is too large for me to store.")
    if not body.startswith(_JPEG_MAGIC):
        raise Refused("payload is not a JPEG", "That did not arrive as a photo I can store. Send it as a photo, not a file.")
    return body


# ── storage ───────────────────────────────────────────────────────────────────
def s3_key(date: str, pose: str) -> str:
    """`raw/matthew/progress_photos/YYYY/MM/YYYY-MM-DD-<pose>.jpg`.

    The date-tree shape every other raw source uses, with the DATE in the leaf rather than
    only in the tree. The registry's first draft said `<pose>.jpg`, which reads fine until
    the second week of a month overwrites the first — three files per month, forever, with
    no error anywhere. The leaf carries the date because the thing being compared is two
    photos taken weeks apart.
    """
    return f"{RAW_PREFIX}/{date[:4]}/{date[5:7]}/{date}-{pose}.jpg"


def index_sk(date: str, pose: str) -> str:
    return f"DATE#{date}#{pose}"


def already_stored(table, file_unique_id: str, date: str, pose: str) -> Optional[dict]:
    """The existing row for this exact file, or None.

    Keyed on the row the photo WOULD occupy and then compared on `file_unique_id`, so a
    re-send of the same photo is a no-op while a genuinely different photo for the same
    pose and day REPLACES it — he retook it, and the second take is the one he wants.
    """
    try:
        resp = table.get_item(Key={"pk": INDEX_PK, "sk": index_sk(date, pose)})
    except Exception as e:  # noqa: BLE001
        logger.warning("[progress] index read failed (%s) — treating as absent", type(e).__name__)
        return None
    item = resp.get("Item") or None
    if item and str(item.get("telegram_file_unique_id") or "") == str(file_unique_id):
        return item
    return None


def store(
    body: bytes,
    *,
    s3,
    table,
    bucket: str,
    date: str,
    pose: str,
    file_unique_id: str,
    week_n=None,
    chat_id=None,
) -> dict:
    """Put the object, then write the index row. Returns the row.

    Object FIRST, row second, and never the reverse. A row pointing at a key that does not
    exist is a lie the viewer (#3760) would render as a broken image; an object with no row
    is invisible but intact, and the next send repairs it. Of the two half-states only one
    is recoverable.
    """
    key = s3_key(date, pose)
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="image/jpeg")

    row = {
        "pk": INDEX_PK,
        "sk": index_sk(date, pose),
        "date": date,
        "pose": pose,
        "s3_key": key,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "telegram_file_unique_id": str(file_unique_id),
        "source_channel": "telegram",
    }
    if week_n is not None:
        row["week_n"] = int(week_n)
    if chat_id is not None:
        row["chat_id"] = str(chat_id)
    table.put_item(Item=row)
    return row


# ── the one call the worker makes ─────────────────────────────────────────────
def handle(
    order: dict,
    token: str,
    *,
    s3,
    table,
    bucket: str,
    chat_ids,
    today: str,
    experiment_start: str = "",
    opener=None,
) -> dict:
    """Store one progress photo, or refuse with a reason he is told.

    Returns `{"ok": bool, "reason": str, "reply": str, ...}`. The worker sends `reply`
    and logs the rest; nothing here touches Telegram itself, so every branch below is
    reachable in a test with no network and no AWS.
    """
    from coach import telegram_group

    caption = order.get("caption") or order.get("text") or ""

    # 1. The bot. Every coach bot shares this worker; only one of them captures.
    if str(order.get("bot_key") or "") != CAPTURE_BOT_KEY:
        return {"ok": True, "reason": "not the capture bot", "reply": ""}

    # 2. The chat. His 1:1 and nothing else — a group id is negative and is refused by
    #    construction, not by a check that could be relaxed later.
    if order.get("is_group"):
        return {"ok": False, "reason": "group chat", "reply": ""}
    owner_chat = telegram_group.first_private_chat_id(chat_ids)
    if owner_chat is None or str(order.get("chat_id")) != str(owner_chat):
        return {"ok": False, "reason": "not the owner's chat", "reply": ""}

    # 3. The caption. A typo gets the hint; a photo about something else is left alone.
    parsed = parse_caption(caption)
    if parsed is None:
        if is_capture_attempt(caption) or not str(caption).strip():
            return {"ok": False, "reason": "caption did not parse", "reply": FORMAT_HINT}
        return {"ok": True, "reason": "not a capture command", "reply": ""}
    pose, explicit_date = parsed
    date = explicit_date or today

    try:
        size = largest_photo(order.get("photo"))
        file_unique_id = str(size.get("file_unique_id") or size.get("file_id") or "")

        # 4. Idempotence BEFORE the download. A redelivery must not re-fetch megabytes to
        #    discover it has nothing to do.
        prior = already_stored(table, file_unique_id, date, pose)
        if prior:
            return {
                "ok": True,
                "reason": "already stored",
                "reply": f"Already stored — {pose}, {date}. Nothing to do.",
                "s3_key": prior.get("s3_key"),
            }

        path = resolve_file_path(token, size["file_id"], opener=opener)
        body = download(token, path, opener=opener)
    except Refused as r:
        logger.warning("[progress] refused: %s", r.reason)
        return {"ok": False, "reason": r.reason, "reply": r.reply}

    week_n = _week_of(experiment_start, date)
    row = store(
        body,
        s3=s3,
        table=table,
        bucket=bucket,
        date=date,
        pose=pose,
        file_unique_id=file_unique_id,
        week_n=week_n,
        chat_id=order.get("chat_id"),
    )
    week_phrase = f"week {week_n}" if week_n else "off-cycle"
    protocol_phrase = _protocol_offset_phrase(date, experiment_start)
    detail = f"{week_phrase}, {protocol_phrase}" if protocol_phrase else week_phrase
    return {
        "ok": True,
        "reason": "stored",
        "reply": f"Stored — {pose}, {date} ({detail}).\n{row['s3_key']}",
        "s3_key": row["s3_key"],
        "week_n": week_n,
    }


def expected_capture_day(date: str, experiment_start: str = "") -> Optional[str]:
    """The protocol's target capture date (`YYYY-MM-DD`) for the week containing `date`.

    A thin wrapper over `pacific_time.week_close_day` (#3761) — the same derivation the
    weekly recap card uses to decide when a week closes — so the protocol's target day and
    the card's week boundary can never independently drift. Returns None off-cycle (no
    `experiment_start`, or `date` before genesis), matching `_week_of`'s contract below.
    """
    if not experiment_start:
        return None
    try:
        from common.pacific_time import week_close_day

        return week_close_day(date, experiment_start)
    except Exception:  # noqa: BLE001
        return None


def _protocol_offset_phrase(date: str, experiment_start: str) -> str:
    """`"on the protocol day"` or `"N days off the protocol day"`, or `""` off-cycle.

    Told to him on every stored capture so a back-dated or early/late set is visible at
    the moment it lands, not weeks later when the comparison is being made.
    """
    target = expected_capture_day(date, experiment_start)
    if not target:
        return ""
    from common.pacific_time import parse_day_key

    d, t = parse_day_key(date), parse_day_key(target)
    if d is None or t is None:
        return ""
    off = abs((d - t).days)
    return "on the protocol day" if off == 0 else f"{off} day{'s' if off != 1 else ''} off the protocol day"


def _week_of(experiment_start: str, date: str):
    """Which experiment week this photo belongs to, or None off-cycle.

    Derived from `pacific_day_n` rather than counted here, so a photo's week and a card's
    `Day N` can never disagree — they are the same arithmetic on the same genesis.
    """
    if not experiment_start:
        return None
    try:
        from common.pacific_time import pacific_day_n

        n = pacific_day_n(experiment_start, date)
    except Exception:  # noqa: BLE001
        return None
    if not n or n < 1:
        return None
    return ((int(n) - 1) // 7) + 1
