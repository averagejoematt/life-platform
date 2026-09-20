"""
hevy_write_client.py — urllib client for Hevy's write surface.

Uses life-platform/hevy-write (separate from read; Yael bundling rule).
Defensive client-side throttle (Hevy doesn't publish rate limits per
PREREQS §A.9). GET-before-PUT conflict guard via updated_at compare.

Public methods:
  list_routines, get_routine, create_routine, update_routine_with_guard
  list_templates, get_template, create_template
  list_folders, create_folder
  get_workouts, get_workout_events  (Phase 2 adherence readback)

Exceptions:
  HevyAuthError      — 401/403   (do not retry; rotate the secret)
  HevyConflict       — updated_at mismatch on PUT (do not retry; resolve
                       conflict and re-author)
  HevyRetryable      — 429/5xx after retries exhausted (DLQ + alert)
  MovementUnmappable — re-exported from hevy_compiler
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import boto3
from common.http_retry import urlopen_with_retry
from common.secret_cache import get_secret_json

from training.hevy_compiler import MovementUnmappable  # noqa: F401  re-export

logger = logging.getLogger("hevy_write_client")

API_BASE = "https://api.hevyapp.com"
WRITE_SECRET_NAME = os.environ.get("HEVY_WRITE_SECRET", "life-platform/hevy-write")
MIN_INTERVAL_SECONDS = float(os.environ.get("HEVY_MIN_INTERVAL_SECONDS", "1.0"))

_sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_throttle_lock = threading.Lock()
_last_request_ts: list[float] = [0.0]


class HevyAuthError(Exception):
    pass


class HevyConflict(Exception):
    """Local IR's last-seen updated_at no longer matches Hevy. Refuses to clobber."""


class HevyRetryable(Exception):
    pass


class HevyOrphanCreated(Exception):
    """Hevy returned a 4xx on POST /v1/routines but ALSO created the routine
    (a quirk of Hevy's create-then-validate flow we observed on 2026-05-31:
    a body with unrecognized exercise_template_id values returned HTTP 400
    "Found invalid exercise template id" while still persisting the routine
    with title only).

    Carriers: hevy_routine_id + hevy_updated_at + the original status/body
    so the caller can link the orphan to the local IR and surface a warning
    instead of silently leaving an untracked routine behind.
    """

    def __init__(self, hevy_routine_id: str, hevy_updated_at: str | None, status: int, body: str):
        self.hevy_routine_id = hevy_routine_id
        self.hevy_updated_at = hevy_updated_at
        self.status = status
        self.body = body
        super().__init__(f"Hevy returned {status} but created routine {hevy_routine_id}")


def _api_key() -> str:
    s = get_secret_json(WRITE_SECRET_NAME, _sm)
    key = s.get("api_key") or s.get("apiKey")
    if not key:
        raise HevyAuthError(f"{WRITE_SECRET_NAME} missing api_key")
    return key


def _throttle() -> None:
    with _throttle_lock:
        elapsed = time.time() - _last_request_ts[0]
        wait = MIN_INTERVAL_SECONDS - elapsed
        if wait > 0:
            time.sleep(wait)
        _last_request_ts[0] = time.time()


def _request(
    method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, Any] | None = None, timeout: int = 30
) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})}"
    headers = {"api-key": _api_key(), "Content-Type": "application/json", "Accept": "application/json"}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    _throttle()
    # #501/X-11: only idempotent GETs get the full retry policy. A retried
    # POST/PUT after an ambiguous 5xx (Hevy applied the write, response just
    # never made it back) risks a duplicate-creation window — those mutations
    # get exactly one attempt, surfacing HevyRetryable immediately on 429/5xx
    # instead of silently re-sending the write.
    max_attempts = None if method == "GET" else 1
    try:
        with urlopen_with_retry(req, timeout=timeout, max_attempts=max_attempts) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise HevyAuthError(f"Hevy {method} {path} → {e.code}") from e
        if e.code in (429, 500, 502, 503, 504):
            suffix = "after retries" if max_attempts is None else "not retried — non-idempotent"
            raise HevyRetryable(f"Hevy {method} {path} → {e.code} ({suffix})") from e
        raise


# ── Routines ──────────────────────────────────────────────────────────────


def list_routines(page: int = 1, page_size: int = 10) -> dict[str, Any]:
    return _request("GET", "/v1/routines", query={"page": page, "pageSize": page_size})


def get_routine(routine_id: str) -> dict[str, Any]:
    return _request("GET", f"/v1/routines/{routine_id}")


_ORPHAN_PROBE_WINDOW_SECONDS = 180


def _maybe_recover_orphan(title: str | None, http_error: urllib.error.HTTPError) -> None:
    """Look for a routine matching `title` created in the last few minutes.

    Hevy can return HTTP 4xx on POST /v1/routines AND still persist the
    routine — observed 2026-05-31 with bad exercise_template_id values.
    If we find a match within the probe window, raise HevyOrphanCreated so
    the caller can link the id; otherwise return None (caller re-raises the
    original HTTPError).
    """
    if not title:
        return
    try:
        listing = list_routines(page=1, page_size=10)
    except Exception:
        return
    routines = listing.get("routines") or []
    now = time.time()
    for r in routines:
        if (r.get("title") or "") != title:
            continue
        created_at = r.get("created_at") or ""
        try:
            from datetime import datetime

            iso = created_at.replace("Z", "+00:00")
            age = now - datetime.fromisoformat(iso).timestamp()
        except Exception:
            age = 0
        if age <= _ORPHAN_PROBE_WINDOW_SECONDS:
            try:
                body_text = (http_error.read() or b"").decode("utf-8", errors="replace")
            except Exception:
                body_text = ""
            raise HevyOrphanCreated(
                hevy_routine_id=r.get("id"),
                hevy_updated_at=r.get("updated_at"),
                status=http_error.code,
                body=body_text,
            )


#: How far back a title lookup walks before giving up (pages × page_size routines).
#: Bounded on purpose: this runs before every first push, and an unbounded walk of a
#: growing routine list would turn one write into an open-ended read loop.
FIND_MAX_PAGES = 10
FIND_PAGE_SIZE = 10


def find_routine_by_title(title: str | None) -> dict[str, Any] | None:
    """The account's routine with this exact (case/whitespace-normalised) title, or None.

    Hevy publishes no idempotency key, so this read IS the idempotency mechanism for
    `create_routine` (#3115) — the same find-or-create shape `_ensure_folder` and the
    template resolver already use, which the routine create was the one write missing.

    Exact-title identity is sound here because the compiler renders titles through
    `routine_title.format_title` (`Phase - Type - N - Y`), so a genuinely new session
    gets a new counter and a re-push of the SAME session renders the same string. It is
    the same identity `_maybe_recover_orphan` has always used to recognise a 4xx-but-
    created routine. Fail-soft: any read error returns None and the POST proceeds —
    a duplicate routine is recoverable, a blocked push is a session Matthew can't train.
    """
    if not title:
        return None
    target = " ".join(str(title).split()).lower()
    for page in range(1, FIND_MAX_PAGES + 1):
        try:
            listing = list_routines(page=page, page_size=FIND_PAGE_SIZE)
        except Exception as e:  # noqa: BLE001 — never block a push on a lookup
            logger.warning(f"find_routine_by_title({title!r}) lookup failed on page {page}; POST proceeds: {e}")
            return None
        routines = listing.get("routines") or []
        if not routines:
            return None
        for r in routines:
            if " ".join(str(r.get("title") or "").split()).lower() == target:
                return r
        if len(routines) < FIND_PAGE_SIZE:
            return None
    return None


def create_routine(body: dict[str, Any]) -> dict[str, Any]:
    """POST a new routine — find-or-create, never blind-create (#3115).

    A replayed commit (client timeout, cron re-run, retried MCP call) used to POST a
    second routine, because Hevy mints a fresh id per call and offers no idempotency
    header. The pre-flight title lookup makes the call converge instead: if the routine
    is already there, its id is returned and NOTHING is written remotely.

    Deliberately a link, not a PUT: an update here would have no `expected_updated_at`
    to check against, so it could clobber an edit Matthew made in the Hevy app — the
    exact thing `update_routine_with_guard` exists to refuse. The linked id means the
    NEXT commit takes the guarded update branch, which is where a content change belongs.
    """
    title = (body.get("routine") or {}).get("title") if isinstance(body, dict) else None
    existing = find_routine_by_title(title)
    if existing:
        logger.warning(f"routine {title!r} already exists in Hevy (id={existing.get('id')}) — linking, not creating a second one (#3115)")
        return {"routine": existing, "linked_existing": True}
    try:
        return _request("POST", "/v1/routines", body=body)
    except urllib.error.HTTPError as e:
        # Auth + retryable are already wrapped by _request; anything else that
        # surfaces here is a non-retryable 4xx (typically 400/422). Probe for
        # an orphan-created routine matching the title.
        title = (body.get("routine") or {}).get("title") if isinstance(body, dict) else None
        _maybe_recover_orphan(title, e)
        raise


def update_routine_with_guard(routine_id: str, body: dict[str, Any], expected_updated_at: str | None) -> dict[str, Any]:
    """GET-before-PUT conflict guard. Refuses to clobber if remote updated_at moved."""
    if expected_updated_at:
        current = get_routine(routine_id)
        remote_routine = current.get("routine", current)
        if isinstance(remote_routine, list):
            remote_routine = remote_routine[0] if remote_routine else {}
        remote_updated = remote_routine.get("updated_at")
        if remote_updated and remote_updated != expected_updated_at:
            raise HevyConflict(
                f"routine {routine_id}: expected updated_at={expected_updated_at} " f"but remote is {remote_updated} (in-app edit?)"
            )
    return _request("PUT", f"/v1/routines/{routine_id}", body=body)


# ── Exercise templates ────────────────────────────────────────────────────


# #3718 — wire-contract facts, stated once, beside the client that knows them.
UPDATE_BRANCH_NOTE = (
    "update — this commit targeted an EXISTING routine. folder_id is create-only in "
    "Hevy, so the routine cannot move folders no matter what this result says."
)
UNVERIFIED_NOTE = (
    "NOT VERIFIED: {reason}. The write was acknowledged by Hevy but a readback does not "
    "show it. Do NOT tell the athlete this session is ready — check the routine in the "
    "app before relying on it."
)


def _norm_note(text) -> str:
    return " ".join(str(text or "").split())


def _exercise_field_mismatches(sent_exercises: list, live_exercises: list) -> list[str]:
    """#3938: per-exercise, for the fields the readback carries: notes (whitespace-normalised),
    rest_seconds, and the set count. Only fields PRESENT in both sides are compared — a field the
    readback lacks is `unverifiable`, not a mismatch."""
    out: list[str] = []
    for i, (s_ex, l_ex) in enumerate(zip(sent_exercises, live_exercises)):
        if "notes" in s_ex and "notes" in l_ex and _norm_note(s_ex.get("notes")) != _norm_note(l_ex.get("notes")):
            out.append(
                f"exercises[{i}].notes differ (sent {len(str(s_ex.get('notes') or ''))} chars, Hevy holds {len(str(l_ex.get('notes') or ''))})"
            )
        if (
            "rest_seconds" in s_ex
            and "rest_seconds" in l_ex
            and s_ex.get("rest_seconds") is not None
            and s_ex.get("rest_seconds") != l_ex.get("rest_seconds")
        ):
            out.append(f"exercises[{i}].rest_seconds differ (sent {s_ex.get('rest_seconds')}, Hevy holds {l_ex.get('rest_seconds')})")
        if "sets" in s_ex and "sets" in l_ex and len(s_ex.get("sets") or []) != len(l_ex.get("sets") or []):
            out.append(f"exercises[{i}].sets count differs (sent {len(s_ex.get('sets') or [])}, Hevy holds {len(l_ex.get('sets') or [])})")
    return out


def readback_fields(check: dict, took_update_branch: bool) -> dict:
    """The commit-result keys that describe what Hevy ACTUALLY holds (#3718).

    Assembled here so the wire facts and the words describing them live together,
    and so a caller cannot report a verified commit while omitting the readback.
    `branch` appears only on the update path, where the folder provably cannot move.
    """
    out = {
        "verified": bool(check.get("verified")),
        "hevy_folder_id": check.get("folder_id"),
        "hevy_updated_at": check.get("updated_at"),
    }
    if took_update_branch:
        out["branch"] = UPDATE_BRANCH_NOTE
    # #3938: sent-but-unreturned fields ride in the result by name; a quiet commit stays quiet.
    if check.get("unverifiable"):
        out["unverifiable"] = list(check["unverifiable"])
    if check.get("mismatches"):
        out["mismatches"] = list(check["mismatches"])
    return out


def verify_commit_landed(routine_id: str, body: dict, before_updated_at: str | None) -> dict:
    """Read the routine back from Hevy and say whether the write actually landed (#3718).

    Lives HERE, not in the MCP tool layer: `exercise_template_id` is Hevy wire
    schema, and tests/test_hevy_compiler_isolation.py holds that such knowledge
    stays in hevy_compiler.py / this client. The guard was right — the client
    owning "did this write land" is the correct shape anyway.

    THE INCIDENT. On 2026-09-08 a commit reported "Pushed. Foundation - Legs -
    1 - 3, filed in your Legs folder." The IR recorded hevy_routine_id, an
    hevy_folder_id of 3087819 (Legs) and hevy_pushed_at 23:00:03Z. Read live 29
    minutes later, that routine was in folder 3087806 (Archive), its updated_at
    was still 2026-09-07T04:05:50Z, and its contents were June's. Nothing
    reached Hevy, the owner was told it had, and he would have discovered it at
    the gym.

    The response to a write is the API agreeing it received a request. It is
    not evidence of state. This asks Hevy what it now holds and compares it to
    what we sent — template ids and set counts, plus whether updated_at moved.
    """
    out: dict[str, Any] = {"verified": False, "reason": None, "folder_id": None, "updated_at": None, "unverifiable": []}
    if not routine_id:
        out["reason"] = "no routine id returned"
        return out
    try:
        got = get_routine(routine_id)
    except Exception as e:  # noqa: BLE001 - an unreadable routine is an unverified one
        out["reason"] = f"readback failed ({type(e).__name__}: {e})"
        return out
    rt = got.get("routine") if isinstance(got.get("routine"), dict) else got
    if isinstance(rt, list):
        rt = rt[0] if rt else {}
    if not rt:
        out["reason"] = "readback returned no routine"
        return out

    out["folder_id"] = rt.get("folder_id")
    out["updated_at"] = rt.get("updated_at")

    sent_routine: dict[str, Any] = body["routine"] if isinstance(body.get("routine"), dict) else body
    sent_exercises = sent_routine.get("exercises", []) or []
    live_exercises = rt.get("exercises") or []
    # #3938: a field we SENT that the readback does not carry cannot be verified — say so by
    # name instead of passing over it in silence. Routine-level `notes` was exactly this for
    # the life of the feature (Hevy's routine object has no such field; the write is dropped).
    out["unverifiable"] = sorted(k for k in sent_routine if k not in rt)
    sent = [str(e.get("exercise_template_id")) for e in sent_exercises]
    live = [str(e.get("exercise_template_id")) for e in live_exercises]
    if sent and live != sent:
        out["reason"] = f"content mismatch — sent {len(sent)} exercise(s), Hevy holds {len(live)}"
        return out
    # #3938: compare every per-exercise field the readback DOES carry against what was sent —
    # notes and rest_seconds are where the gym-readable text now lives, so a note that did not
    # land (truncated, dropped) is a write that did not apply, not a detail.
    mismatches = _exercise_field_mismatches(sent_exercises, live_exercises)
    if mismatches:
        out["mismatches"] = mismatches
        out["reason"] = "content mismatch — " + "; ".join(mismatches[:3])
        return out
    if before_updated_at and str(rt.get("updated_at") or "") == str(before_updated_at):
        # The decisive check for the #3718 case: a PUT that changed nothing.
        out["reason"] = f"updated_at did not move (still {before_updated_at}) — the write did not apply"
        return out

    out["verified"] = True
    return out


def list_templates(page: int = 1, page_size: int = 100) -> dict[str, Any]:
    return _request("GET", "/v1/exercise_templates", query={"page": page, "pageSize": page_size})


def get_template(template_id: str) -> dict[str, Any]:
    return _request("GET", f"/v1/exercise_templates/{template_id}")


def create_template(body: dict[str, Any]) -> dict[str, Any]:
    return _request("POST", "/v1/exercise_templates", body=body)


# ── Folders ───────────────────────────────────────────────────────────────


# Hevy caps pageSize at 10 on every collection endpoint EXCEPT /v1/exercise_templates
# (verified live at 100). This default was 50 and 400'd every call for months (#3670):
#   pageSize=10 -> 200 · pageSize=11 -> 400 {"error":"pageSize must be less than or equal to 10"}
# _ensure_folder swallowed the 400, so every routine was created in the account root.
# Do not raise this above 10 — see scripts/diag_hevy_folders.py for the live sweep.
HEVY_MAX_PAGE_SIZE = 10


def list_folders(page: int = 1, page_size: int = HEVY_MAX_PAGE_SIZE) -> dict[str, Any]:
    return _request("GET", "/v1/routine_folders", query={"page": page, "pageSize": page_size})


#: Page ceiling for `list_all_folders` — 20 pages x 10 = 200 folders. A bound so a
#: mis-reported `page_count` cannot spin the client, NOT an expectation about the
#: account. A truncated sweep is reported by `folders_truncated`, never silently.
FOLDER_PAGE_LIMIT = 20


def list_all_folders(max_pages: int = FOLDER_PAGE_LIMIT) -> tuple[list[dict[str, Any]], bool]:
    """Every routine folder, walked across pages. Returns ``(folders, truncated)``.

    Why this exists (#3670, the half the page_size fix does NOT cover): capping
    `pageSize` at 10 makes the call 200 instead of 400, but it also makes ONE page
    a strictly smaller window than the broken `pageSize=50` ever asked for. A
    caller that reads page 1 only is correct exactly while the account holds <= 10
    folders; at 11 the target folder can sit on page 2, the find-or-create scan
    misses it, and the "fix" quietly creates a DUPLICATE folder instead of filing
    into the existing one. That is a worse failure than the 400, because it looks
    like success in Hevy too.

    Raises whatever `list_folders` raises — the fail-soft decision belongs to the
    caller (`hevy_routine_commit_report.ensure_folder`), which must name the miss
    in its own result rather than swallow it.
    """
    folders: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = list_folders(page=page)
        batch = payload.get("routine_folders") or payload.get("folders") or []
        folders.extend(batch)
        try:
            page_count = int(payload.get("page_count") or 1)
        except (TypeError, ValueError):
            page_count = 1
        if not batch or page >= page_count:
            return folders, False
        if page >= max_pages:
            logger.warning(f"list_all_folders stopped at the {max_pages}-page bound (page_count={page_count})")
            return folders, True
        page += 1


def create_folder(title: str) -> dict[str, Any]:
    return _request("POST", "/v1/routine_folders", body={"routine_folder": {"title": title}})


# ── Workouts + events (Phase 2 readback) ──────────────────────────────────


def get_workouts(page: int = 1, page_size: int = 10) -> dict[str, Any]:
    return _request("GET", "/v1/workouts", query={"page": page, "pageSize": page_size})


def get_workout_events(since: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
    """ISO-8601 since cursor; returns events with type=updated|deleted."""
    return _request("GET", "/v1/workouts/events", query={"page": page, "pageSize": page_size, "since": since})


# ── Test seam ─────────────────────────────────────────────────────────────


def _reset_throttle_for_tests() -> None:
    with _throttle_lock:
        _last_request_ts[0] = 0.0
