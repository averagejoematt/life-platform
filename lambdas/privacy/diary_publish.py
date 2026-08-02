"""
diary_publish.py — the cut→entry→engagement loop, and the Goodhart guardrail (#1845).

Story 5 of the diary-360 chain (#1841 claims, #1842 vocal metrics, #1843 diary-days,
#1844 the channel-divergence prereg). The diary now flows INTO the platform five ways.
This module closes the one loop that ran OUT of it and never came back: a cut is rendered
in the private studio, Matthew posts it, and — until now — nothing on the platform knew
that a published clip existed, which entry it came from, or what happened to it.

THE LOOP (three hops, each one deterministic)
─────────────────────────────────────────────
1. PUBLISH   The studio desk (Cowork, ``~/Documents/Claude/vlog``) appends one row to
             ``PUBLISH_LOG.md`` per post: date · session · cut · surface · link · entry.
             ``parse_publish_log()`` reads that markdown table by its HEADER (not by
             column position), so the studio may add columns without breaking this side,
             and ``format_publish_log_row()`` emits the same row back — the round-trip is
             pinned by test, which is what "the studio log and the platform record agree"
             (AC1) means operationally.
2. RECORD    ``scripts/sync_diary_publications.py`` turns each admitted row into ONE
             ``DIARY_PUBLISH#{channel}`` / ``POST#{post_id}`` row carrying the full
             provenance chain: session slug, cut id, surface, URL, and — when the session
             was routed to Notion — the exact ``source_sk`` of the diary entry the cut was
             taken from. Keyed by ``(channel, post_id)`` on purpose: that is the ONLY
             identity the inbound ingestion side already has in hand.
3. JOIN      ``lambdas/ingestion/youtube_lambda.py`` stamps ``diary_*`` provenance onto
             each inbound post it ingests whose ``(channel, post_id)`` matches a
             publication row. From then on the engagement the inbound feed carries is
             joinable back to the entry that produced it (AC2) — ``engagement_by_entry()``
             does the rollup, with n and the absence semantics stated.

The ledger deliberately mirrors ``social_provenance.BROADCAST_ORIGIN#`` (#1670) in shape
but is a SEPARATE partition, because the two answer different questions and conflating
them would break the membrane: ``BROADCAST_ORIGIN#`` means "the platform's own automated
syndication wrote this, do not re-display it as Matthew's voice", while a diary cut is
Matthew on camera, published by hand. A diary publication must NOT be classified
``origin: platform`` — it is the most human artifact the system has.

╔══════════════════════════════════════════════════════════════════════════════════════╗
║ THE GOODHART GUARDRAIL — the load-bearing part of this story (#1845 AC3)             ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
Engagement metrics MAY inform WHICH CUT gets published. They MUST NEVER reach the
interviewer's priming, question selection, format choice, or capture protocol.

The reason is not squeamishness about metrics; it is that this diary is an instrument.
The moment the questions are chosen for what performs, the answers stop being evidence
about Matthew's life and start being evidence about the audience — and every downstream
number the platform derives from the diary (enrichment themes, flourishing channels,
vocal biomarkers, the #1844 spoken-vs-typed divergence test, the on-tape claims ledger)
silently inherits that contamination with no way to detect it after the fact. Selection
pressure on the OUTPUT (which of the things he already said gets clipped) leaves the
instrument intact. Selection pressure on the INPUT destroys it. That asymmetry is the
whole rule.

So the boundary here is structural, not aspirational:

  * Every read of engagement data goes through ``engagement_by_entry()``, which REQUIRES
    a declared ``purpose=`` and refuses anything not on ``ENGAGEMENT_MAY_INFORM``
    (fail-closed — an unknown purpose is refused, not allowed).
  * ``ENGAGEMENT_MUST_NEVER_INFORM`` names the forbidden uses explicitly so the refusal
    message tells the caller WHY, rather than looking like a bug to route around.
  * ``tests/test_diary_publish_1845.py`` asserts that nothing under ``mcp/`` or
    ``lambdas/coach/`` imports this module at all — the interviewer's context comes from
    MCP tools, so "no MCP tool can reach engagement" is enforceable by import graph, and
    a future PR that wires one in fails CI instead of quietly winning an argument.
  * The prose rule lives in ``docs/content/DIARY_STUDIO_KIT.md`` and is referenced from
    the ``/vlog`` skill, so the human running the interview reads it too.

Pure — no boto3, no network, no clock of its own (``lookup_publication`` takes a table
handle the caller built). Scripts and Lambdas do the I/O.

v1.0.0 — 2026-07-27 (#1845, epic #1668)
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── The publication ledger ───────────────────────────────────────────────────────
# pk `DIARY_PUBLISH#{channel}`; sk `POST#{post_id}`.
#
# `(channel, post_id)` is the join key because it is the only identity the inbound
# ingestion path already holds (youtube_lambda stamps `channel` + `post_id` on every row).
# Classified SYSTEM_STATE in phase_taxonomy: a cut published in cycle 11 was still
# published in cycle 12 — publication is historical fact, not run intelligence.
PUBLISH_PK_PREFIX = "DIARY_PUBLISH#"
PUBLISH_SK_PREFIX = "POST#"

RECORD_TYPE = "diary_publication"
SCHEMA_VERSION = 1

# Surfaces the studio renders to (`STUDIO.md` §2b — the same vocabulary `cut.sh` takes,
# so a filename and a log row can never disagree about what was posted).
VALID_SURFACES = ("reel", "short", "story", "yt", "square")

# Entry channels a cut can come from (`notion_lambda.TEMPLATE_SK` suffixes).
VALID_ENTRY_CHANNELS = ("video_diary", "solo_recording")
DEFAULT_ENTRY_CHANNEL = "video_diary"

# The channels this loop can actually close today. A publication to a channel with no
# inbound ingestion path is still RECORDED (provenance is worth having either way) but its
# engagement side stays honestly absent — see `engagement_by_entry`.
CHANNEL_YOUTUBE = "youtube"
JOINABLE_CHANNELS = (CHANNEL_YOUTUBE,)

# What the keyless YouTube RSS feed actually carries. `views` is the ONLY engagement
# number available without the YouTube Data API (and even that field is frequently absent
# from the modern feed) — likes/comments/watch-time are a documented future upgrade, not a
# thing to pretend we have. ADR-104: absent stays absent, never zeroed.
ENGAGEMENT_FIELDS = ("views",)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# `2026-07-26_day00_cut01_reel_more-day-ones` / `2026-07-26_day00_retro_day-zero__full`
_CUT_CLIP_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_day(?P<day>\d{2,3})_cut(?P<rank>\d{2})_(?P<surface>[a-z]+)_(?P<slug>[a-z0-9-]+)$")
_CUT_FULL_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_day(?P<day>\d{2,3})_(?P<format>[a-z]+)_(?P<slug>[a-z0-9-]+)__full$")

# A Notion page id is 32 hex chars, hyphenated or not, anywhere in the page URL.
_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32})|([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")

# YouTube post-id extraction: watch?v=, youtu.be/, /shorts/, /live/, /embed/.
_YT_PATTERNS = (
    re.compile(r"[?&]v=([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,})"),
    re.compile(r"/shorts/([A-Za-z0-9_-]{6,})"),
    re.compile(r"/live/([A-Za-z0-9_-]{6,})"),
    re.compile(r"/embed/([A-Za-z0-9_-]{6,})"),
)

# ── The publish-log table contract (studio side) ─────────────────────────────────
# Column header -> canonical field. Parsing is header-driven so the studio can add
# columns (or reorder them) without breaking the platform side; only these are read.
LOG_COLUMNS = {
    "date": "published_date",
    "session": "session_slug",
    "cut": "cut_file",
    "surface": "surface",
    "link": "url",
    "entry": "entry_ref",
}
# The canonical row order the platform emits (and the studio's header should match).
LOG_COLUMN_ORDER = ("date", "session", "cut", "surface", "link", "entry")
LOG_HEADER = "| " + " | ".join(LOG_COLUMN_ORDER) + " |"
LOG_DIVIDER = "|" + "---|" * len(LOG_COLUMN_ORDER)

# Cells the studio writes when there is nothing to record (an unrouted session, a cut
# posted somewhere with no permalink yet). Treated as absent, never as a literal value.
_EMPTY_CELLS = {"", "-", "—", "--", "n/a", "na", "none", "not routed", "tbd"}


# ══ The Goodhart guardrail ═══════════════════════════════════════════════════════
# See the module docstring. This is the structural half of #1845 AC3; the prose half is
# docs/content/DIARY_STUDIO_KIT.md § "The Goodhart rule".

# Purposes engagement data MAY serve — selection pressure on the OUTPUT only.
ENGAGEMENT_MAY_INFORM = {
    "cut_selection": "which already-recorded moment gets clipped and published next",
    "surface_choice": "which surface (reel/short/yt) an already-chosen cut is rendered for",
    "publish_timing": "when an already-chosen cut goes out",
    "ops_report": "counting what was published and what happened to it, for Matthew's own review",
}

# Purposes it MUST NEVER serve — selection pressure on the INPUT, which is the instrument.
ENGAGEMENT_MUST_NEVER_INFORM = {
    "interview_priming": "the context the interviewer loads before a session (/vlog step 0)",
    "question_selection": "which questions get asked, or which follow-up is pursued",
    "format_choice": "which diary format is proposed (daily/weekly/debrief/retro/team/vent/micro)",
    "capture_protocol": "how, when, or how long a session is recorded",
    "coach_context": "anything a coach persona sees, since coaches feed the interview",
    "prompt_context": "any LLM prompt that shapes what Matthew is asked",
}


class GoodhartViolation(RuntimeError):
    """Raised when engagement data is requested for a purpose that would shape the tape.

    Deliberately an exception and not a filtered return: a caller that wants engagement
    for question selection has made a design error, and a silently-empty result would
    read as "no data yet" and be routed around.
    """


def assert_engagement_purpose(purpose) -> str:
    """The one door engagement data passes through. Fail-closed on anything unlisted.

    Returns the normalized purpose so call sites can log it; raises `GoodhartViolation`
    with the specific reason when the purpose is forbidden, and with the allowed set when
    it is simply unknown (a new use must be argued for and added, never assumed benign).
    """
    key = str(purpose or "").strip().lower()
    if key in ENGAGEMENT_MAY_INFORM:
        return key
    if key in ENGAGEMENT_MUST_NEVER_INFORM:
        raise GoodhartViolation(
            f"engagement data must never inform {key!r} ({ENGAGEMENT_MUST_NEVER_INFORM[key]}). "
            "Engagement may pick cuts; it may never pick questions — the diary's value as evidence "
            "depends on the interview being engagement-blind (#1845, docs/content/DIARY_STUDIO_KIT.md)."
        )
    raise GoodhartViolation(
        f"unknown engagement purpose {purpose!r} — refused fail-closed. Allowed: {sorted(ENGAGEMENT_MAY_INFORM)}. "
        "If a genuinely new OUTPUT-side use exists, add it to ENGAGEMENT_MAY_INFORM with its rationale."
    )


# ══ Keys and identifiers ═════════════════════════════════════════════════════════


def publish_key(channel: str, post_id: str) -> dict:
    """The DDB primary key for one publication row."""
    return {"pk": f"{PUBLISH_PK_PREFIX}{channel}", "sk": f"{PUBLISH_SK_PREFIX}{post_id}"}


def parse_post_ref(url):
    """`(channel, post_id)` for a published-post URL, or `(None, None)` if unrecognised.

    Only channels with a real inbound path are recognised — a link the platform cannot
    later see engagement for is recorded as a publication with no post id, which is the
    honest state (provenance yes, engagement no) rather than a fabricated key.
    """
    u = str(url or "").strip()
    if not u:
        return None, None
    # Hostname check, not substring — "evil.com/youtube.com/…" must not pass
    # (CodeQL py/incomplete-url-substring-sanitization, #1902).
    try:
        host = (urlparse(u if "://" in u else f"https://{u}").hostname or "").lower()
    except ValueError:
        return None, None
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        for pattern in _YT_PATTERNS:
            m = pattern.search(u)
            if m:
                return CHANNEL_YOUTUBE, m.group(1)
    return None, None


def parse_cut_filename(name):
    """Structure out of the studio's self-describing cut filename (`STUDIO.md` §2b).

    Returns a dict (`cut_id`, `kind`, `entry_date`, `day`, `surface`/`format`, `slug`) or
    None if the name does not follow the convention. `cut_id` is the basename without its
    extension — self-describing out of context, which is the property the naming rule
    exists for, and stable enough to be the publication's identity within a session.
    """
    base = str(name or "").strip().rsplit("/", 1)[-1]
    if base.lower().endswith((".mp4", ".mov", ".m4v")):
        base = base.rsplit(".", 1)[0]
    if not base:
        return None
    m = _CUT_CLIP_RE.match(base)
    if m:
        return {
            "cut_id": base,
            "kind": "clip",
            "entry_date": m.group("date"),
            "day": int(m.group("day")),
            "cut_rank": int(m.group("rank")),
            "surface": m.group("surface"),
            "clip_slug": m.group("slug"),
        }
    m = _CUT_FULL_RE.match(base)
    if m:
        return {
            "cut_id": base,
            "kind": "full",
            "entry_date": m.group("date"),
            "day": int(m.group("day")),
            "cut_rank": None,
            "surface": None,  # the long cut is surface-agnostic; the log row states it
            "clip_slug": m.group("slug"),
            "format": m.group("format"),
        }
    return None


def entry_sk_from_notion(page_ref, entry_date: str, entry_channel: str = DEFAULT_ENTRY_CHANNEL):
    """The exact diary-entry sk a Notion page URL/id points at, or None.

    Mirrors `notion_lambda.build_sk` bit for bit (stable suffix = last 12 hex of the
    de-hyphenated page id, #476/E-6). Derived rather than guessed: this is the pointer
    that makes engagement joinable to the ENTRY and not merely to a date, so an
    approximation would be worse than an absence.
    """
    if not DATE_RE.match(str(entry_date or "")) or entry_channel not in VALID_ENTRY_CHANNELS:
        return None
    m = _NOTION_ID_RE.search(str(page_ref or ""))
    if not m:
        return None
    stable = (m.group(0) or "").replace("-", "").lower()[-12:]
    return f"DATE#{entry_date}#journal#{entry_channel}#{stable}"


def _cell(value):
    """Normalize one markdown cell; the studio's placeholder dashes read as absent."""
    v = " ".join(str(value or "").split())
    v = v.strip("`")
    if v.lower() in _EMPTY_CELLS:
        return ""
    # `[text](url)` → url, so a linkified cell still yields a usable URL.
    m = re.match(r"^\[[^\]]*\]\((?P<u>[^)]+)\)$", v)
    return m.group("u").strip() if m else v


# ══ The studio log ═══════════════════════════════════════════════════════════════


def parse_publish_log(markdown):
    """Parse `PUBLISH_LOG.md` into rows, header-driven.

    Returns `(rows, problems)`. Every row is a dict of canonical field names; every line
    that looks like a table row but cannot be read is reported in `problems` rather than
    dropped — a silently-skipped publication is exactly the gap this story exists to close
    ("report the skips", `STUDIO.md` §4.5).

    Tolerates the pre-#1845 five-column log (no `entry` column) so the existing file keeps
    parsing: the entry pointer is then simply absent, not invented.
    """
    rows, problems = [], []
    header = None
    for lineno, raw_line in enumerate(str(markdown or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= {"-", ":"} and c for c in cells):
            continue  # the |---|---| divider
        lowered = [c.strip().lower() for c in cells]
        if header is None:
            if "date" in lowered and ("cut" in lowered or "session" in lowered):
                header = lowered
                continue
            problems.append(f"line {lineno}: table row before any header row — skipped")
            continue
        if len(cells) != len(header):
            problems.append(f"line {lineno}: {len(cells)} cells vs {len(header)} header columns — skipped")
            continue
        row = {"_lineno": lineno}
        for col, value in zip(header, cells):
            field = LOG_COLUMNS.get(col)
            if field:
                row[field] = _cell(value)
        rows.append(row)
    if header is None and str(markdown or "").strip():
        problems.append("no header row found — expected a markdown table starting with a `date` column")
    return rows, problems


def format_publish_log_row(record) -> str:
    """Emit the canonical `PUBLISH_LOG.md` row for a publication record.

    The studio writes this line; the platform stores the record; `parse_publish_log` reads
    the line back to the same fields. AC1 ("the studio log and the platform record agree")
    is that round-trip, and it is pinned by test rather than asserted in prose.
    """
    rec = record or {}
    cells = [
        rec.get("published_date", ""),
        rec.get("session_slug", ""),
        rec.get("cut_file") or rec.get("cut_id", ""),
        rec.get("surface", ""),
        rec.get("url", ""),
        rec.get("entry_ref") or "—",
    ]
    return "| " + " | ".join(str(c or "—") for c in cells) + " |"


# ══ Admission ════════════════════════════════════════════════════════════════════


def admit_publication(row):
    """Validate ONE publish-log row into a normalized publication, or refuse it.

    Returns `(ok, reason, normalized)`. Refusal reasons are written to be read by the
    person holding the log — they name the cell to fix. What is checked:

      * date, session slug, cut and surface present (the provenance quartet of AC1);
      * the surface is one the studio actually renders;
      * the cut filename follows `STUDIO.md` §2b, so `cut_id` is real and self-describing;
      * the cut filename's own surface token AGREES with the surface column (the exact
        disagreement the naming convention exists to make impossible);
      * the cut filename's date agrees with the session's date.

    A missing URL is NOT a refusal: "rendered and posted somewhere without a permalink" is
    a real state, and recording the provenance without engagement beats recording nothing.
    """
    if not isinstance(row, dict):
        return False, "row is not an object", None
    published_date = str(row.get("published_date") or "").strip()
    if not DATE_RE.match(published_date):
        return False, f"date {row.get('published_date')!r} is not YYYY-MM-DD", None
    session_slug = str(row.get("session_slug") or "").strip()
    if not session_slug:
        return False, "session is required — a publication with no session cannot point at an entry", None
    cut_file = str(row.get("cut_file") or "").strip()
    if not cut_file:
        return False, "cut is required — the cut file is the publication's identity", None
    surface = str(row.get("surface") or "").strip().lower()
    if surface not in VALID_SURFACES:
        return False, f"surface {row.get('surface')!r} not one of {VALID_SURFACES}", None

    cut = parse_cut_filename(cut_file)
    if not cut:
        return False, f"cut filename {cut_file!r} does not follow STUDIO.md §2b (YYYY-MM-DD_dayNN_cutNN_<surface>_<slug>)", None
    if cut["kind"] == "clip" and cut["surface"] != surface:
        return False, f"cut filename says surface {cut['surface']!r} but the row says {surface!r} — one of them is wrong", None

    entry_date = cut["entry_date"]
    session_date = session_slug[:10]
    if DATE_RE.match(session_date) and session_date != entry_date:
        return False, f"cut filename date {entry_date} does not match session {session_slug}", None

    url = str(row.get("url") or "").strip()
    channel, post_id = parse_post_ref(url)
    entry_ref = str(row.get("entry_ref") or "").strip()
    entry_channel = DEFAULT_ENTRY_CHANNEL
    entry_sk = entry_sk_from_notion(entry_ref, entry_date, entry_channel) if entry_ref else None

    return (
        True,
        "",
        {
            "published_date": published_date,
            "session_slug": session_slug,
            "cut_id": cut["cut_id"],
            "cut_file": cut_file,
            "cut_kind": cut["kind"],
            "cut_rank": cut["cut_rank"],
            "clip_slug": cut["clip_slug"],
            "day": cut["day"],
            "surface": surface,
            "url": url,
            "channel": channel,
            "post_id": post_id,
            "entry_date": entry_date,
            "entry_channel": entry_channel,
            "entry_ref": entry_ref,
            "entry_sk": entry_sk,
        },
    )


def build_publication_record(normalized, now_iso: str, user_id: str = "matthew"):
    """The DDB item for one admitted publication, or None when it has no joinable key.

    Only `(channel, post_id)`-keyed publications become rows: the ledger's whole job is to
    be looked up by the identity inbound ingestion holds, and a row with no such key could
    never be found. A publication to a channel with no inbound path is still reported by
    the sync script (and stays in the studio log) — it is simply not a ledger row yet.

    ADR-104: fields the row genuinely lacks (no entry pointer, no cut rank on a long cut)
    are OMITTED, never written as null or zero.
    """
    if not normalized or not normalized.get("channel") or not normalized.get("post_id"):
        return None
    record = {
        **publish_key(normalized["channel"], normalized["post_id"]),
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "channel": normalized["channel"],
        "post_id": normalized["post_id"],
        "url": normalized["url"],
        "published_date": normalized["published_date"],
        # ── the provenance chain (AC1) ──
        "session_slug": normalized["session_slug"],
        "cut_id": normalized["cut_id"],
        "cut_file": normalized["cut_file"],
        "cut_kind": normalized["cut_kind"],
        "surface": normalized["surface"],
        "entry_date": normalized["entry_date"],
        "entry_channel": normalized["entry_channel"],
        "entry_pk": f"USER#{user_id}#SOURCE#notion",
        "claimant": user_id,
        "recorded_at": now_iso,
    }
    if normalized.get("cut_rank") is not None:
        record["cut_rank"] = int(normalized["cut_rank"])
    if normalized.get("day") is not None:
        record["day"] = int(normalized["day"])
    if normalized.get("clip_slug"):
        record["clip_slug"] = normalized["clip_slug"]
    if normalized.get("entry_sk"):
        record["entry_sk"] = normalized["entry_sk"]
    if normalized.get("entry_ref"):
        record["entry_ref"] = normalized["entry_ref"]
    return record


# ══ The join (inbound side) ══════════════════════════════════════════════════════

# The `diary_*` attributes stamped onto an inbound social post that matches a
# publication. Named with a prefix so a query can project the provenance chain without
# knowing the rest of the post's shape.
STAMP_FIELDS = ("diary_session_slug", "diary_cut_id", "diary_surface", "diary_entry_date", "diary_entry_sk", "diary_cut_kind")


def publication_stamp(publication):
    """The `diary_*` provenance fields to write onto a matching inbound post (AC2).

    Absent values are omitted, so a publication with no Notion pointer stamps the session
    and cut (which are always known) and simply carries no `diary_entry_sk`.
    """
    pub = publication or {}
    if not pub.get("session_slug") or not pub.get("cut_id"):
        return {}
    stamp = {
        "diary_session_slug": pub["session_slug"],
        "diary_cut_id": pub["cut_id"],
    }
    for src, dst in (
        ("surface", "diary_surface"),
        ("entry_date", "diary_entry_date"),
        ("entry_sk", "diary_entry_sk"),
        ("cut_kind", "diary_cut_kind"),
    ):
        if pub.get(src):
            stamp[dst] = pub[src]
    return stamp


def lookup_publication(table, channel: str, post_id: str):
    """Read one publication row, or None. Fail-open on any error.

    Ingestion must never break because a provenance lookup failed — an unstamped post is
    a post whose diary origin is unknown, which is exactly what the absence means.
    """
    if table is None or not channel or not post_id:
        return None
    try:
        resp = table.get_item(Key=publish_key(channel, post_id))
    except Exception:  # noqa: BLE001 — provenance lookup must never break ingestion
        return None
    return resp.get("Item") or None


# ══ The read side (guarded) ══════════════════════════════════════════════════════


def engagement_by_entry(publications, posts, *, purpose):
    """Roll inbound engagement up to the diary entry that produced it (AC2).

    `purpose` is REQUIRED and checked by `assert_engagement_purpose` before a single
    number is read — see the module docstring. There is no unguarded variant of this
    function, and adding one is the change this story exists to prevent.

    Honest numbers (ADR-104/105): a cut whose inbound row carries no `views` contributes
    NOTHING (it is not counted as zero); `views_total` is None until at least one post
    actually reported a number; every entry carries `n_published` / `n_measured` and an
    explicit caveat that views are a reach signal, not a quality signal, and are not
    comparable across surfaces.
    """
    assert_engagement_purpose(purpose)

    by_key = {}
    for pub in publications or []:
        channel, post_id = pub.get("channel"), pub.get("post_id")
        if channel and post_id:
            by_key[(channel, post_id)] = pub

    entries: dict = {}
    for post in posts or []:
        pub = by_key.get((post.get("channel"), post.get("post_id")))
        if not pub:
            continue  # an inbound post with no publication row is not a diary cut
        key = pub.get("entry_sk") or f"DATE#{pub.get('entry_date')}"
        entry = entries.setdefault(
            key,
            {
                "entry_sk": pub.get("entry_sk"),
                "entry_date": pub.get("entry_date"),
                "session_slug": pub.get("session_slug"),
                "cuts": [],
                "n_published": 0,
                "n_measured": 0,
                "views_total": None,
            },
        )
        views = post.get("views")
        views_int = None
        try:
            if views is not None:
                views_int = int(views)
        except (TypeError, ValueError):
            views_int = None
        entry["n_published"] += 1
        if views_int is not None:
            entry["n_measured"] += 1
            entry["views_total"] = (entry["views_total"] or 0) + views_int
        entry["cuts"].append(
            {
                "cut_id": pub.get("cut_id"),
                "surface": pub.get("surface"),
                "channel": pub.get("channel"),
                "post_id": pub.get("post_id"),
                "url": pub.get("url") or post.get("url"),
                "published_date": pub.get("published_date"),
                "views": views_int,  # None = the feed did not report one, NOT zero
            }
        )

    for entry in entries.values():
        entry["cuts"].sort(key=lambda c: (c.get("published_date") or "", c.get("cut_id") or ""))
        entry["caveat"] = (
            f"n={entry['n_measured']} of {entry['n_published']} published cut(s) reported a view count "
            "(the keyless YouTube RSS often omits statistics entirely). Views are reach, not quality, "
            "and are not comparable across surfaces. Correlative only."
        )
    return {
        "entries": [entries[k] for k in sorted(entries)],
        "n_entries": len(entries),
        "purpose": str(purpose).strip().lower(),
        "guardrail": (
            "Engagement may inform WHICH CUT is published; it must never inform which questions "
            "are asked, which format is proposed, or how a session is captured (#1845)."
        ),
    }
