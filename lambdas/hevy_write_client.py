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
from hevy_compiler import MovementUnmappable  # noqa: F401  re-export
from http_retry import urlopen_with_retry
from secret_cache import get_secret_json

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
    try:
        with urlopen_with_retry(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise HevyAuthError(f"Hevy {method} {path} → {e.code}") from e
        if e.code in (429, 500, 502, 503, 504):
            raise HevyRetryable(f"Hevy {method} {path} → {e.code} (after retries)") from e
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


def create_routine(body: dict[str, Any]) -> dict[str, Any]:
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


def list_templates(page: int = 1, page_size: int = 100) -> dict[str, Any]:
    return _request("GET", "/v1/exercise_templates", query={"page": page, "pageSize": page_size})


def get_template(template_id: str) -> dict[str, Any]:
    return _request("GET", f"/v1/exercise_templates/{template_id}")


def create_template(body: dict[str, Any]) -> dict[str, Any]:
    return _request("POST", "/v1/exercise_templates", body=body)


# ── Folders ───────────────────────────────────────────────────────────────


def list_folders(page: int = 1, page_size: int = 50) -> dict[str, Any]:
    return _request("GET", "/v1/routine_folders", query={"page": page, "pageSize": page_size})


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
