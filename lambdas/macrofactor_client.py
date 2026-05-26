"""
macrofactor_client.py — Pure-Python MacroFactor unofficial-API client.

WS-2 Tier 1 (PRIMARY food-level nutrition path). Per
SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 §3.1 + ADR-061.

Reverse-engineered 2026-05-25 from the two community libraries:
  - @sjawhar/macrofactor-mcp (npm, TypeScript) — auth.ts + client.ts
  - macro-factor-api (crates.io, Rust)         — auth.rs + client.rs

Both confirm the same Firebase project + Firestore REST API. The Firebase
web API key is hardcoded in the Rust crate (public-facing key, designed
to be embedded; security comes from Firebase Auth rules + bundle ID
validation, not the key being secret).

Auth flow:
  1. POST identitytoolkit.googleapis.com/v1/accounts:signInWithPassword
     - key=<FIREBASE_WEB_API_KEY> query param
     - X-Ios-Bundle-Identifier: com.sbs.diet header
     - body: {email, password, returnSecureToken: true}
     - returns: {idToken, refreshToken, localId (=uid), expiresIn (sec)}
  2. Use idToken as `Authorization: Bearer <idToken>` for Firestore REST.
  3. Refresh via securetoken.googleapis.com/v1/token when within 5min of expiry.

Firestore paths (user data, all reads):
  users/{uid}                        — user profile
  users/{uid}/food/{YYYY-MM-DD}      — single doc per day, food entries as fields
  users/{uid}/scale/{YYYY}           — yearly weight log, keys are MMDD
  users/{uid}/nutrition/{YYYY}       — yearly nutrition summary
  users/{uid}/steps/{YYYY}           — yearly steps log

Food-entry field shortcodes (in the food document fields):
  t  = title/name        c = calories     p = protein
  b  = brand             e = carbs (sic)  f = fat
  g  = grams             s = serving description
  q  = quantity          h = hour         mi = minute
  ... (full list in MF Android source; we surface a sensible subset)

NB: This is an UNOFFICIAL UNDOCUMENTED API. The schema can change without
notice. The puller Lambda treats every call as best-effort and records
failures into a health status record so the operator can fall back to
the manual Dropbox export (Tier 2) on Matthew's terms.

NOT for production beyond Matthew's personal account.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
# Public Firebase web API key for the sbs-diet-app project. Extracted from
# https://crates.io/crates/macro-factor-api (auth.rs) 2026-05-25. Firebase web
# keys are public-by-design — actual security is in Auth rules + bundle ID.
FIREBASE_WEB_API_KEY = "AIzaSyA17Uwy37irVEQSwz6PIyX3wnkHrDBeleA"
BUNDLE_ID = "com.sbs.diet"
FIRESTORE_BASE = "https://firestore.googleapis.com/v1/projects/sbs-diet-app/databases/(default)/documents"

# Token refresh threshold — refresh if within 5 min of expiry.
_TOKEN_REFRESH_BUFFER_SEC = 300


class MacroFactorAuthError(RuntimeError):
    pass


class MacroFactorAPIError(RuntimeError):
    pass


class MacroFactorClient:
    """Thin Firebase-auth-+-Firestore-REST client for MacroFactor user data."""

    def __init__(self, email: str, password: str) -> None:
        if not email or not password:
            raise ValueError("MacroFactorClient requires email + password")
        self._email = email
        self._password = password
        self._id_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._uid: Optional[str] = None
        self._token_expires_at: float = 0  # epoch seconds

    # ── Auth ────────────────────────────────────────────────────────────────

    def sign_in(self) -> None:
        """Initial sign-in. Stores idToken/refreshToken/uid for later calls."""
        url = (
            "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
            f"?key={FIREBASE_WEB_API_KEY}"
        )
        body = json.dumps({
            "email": self._email,
            "password": self._password,
            "returnSecureToken": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Ios-Bundle-Identifier": BUNDLE_ID,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            raise MacroFactorAuthError(f"sign-in HTTP {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            raise MacroFactorAuthError(f"sign-in network error: {e}") from e

        self._id_token      = data.get("idToken")
        self._refresh_token = data.get("refreshToken")
        self._uid           = data.get("localId")
        try:
            expires_in = int(data.get("expiresIn", 3600))
        except Exception:
            expires_in = 3600
        self._token_expires_at = time.time() + expires_in
        if not (self._id_token and self._refresh_token and self._uid):
            raise MacroFactorAuthError(f"sign-in response missing fields: keys={sorted(data)}")

    def _ensure_fresh_token(self) -> str:
        """Refresh the idToken if within the buffer of expiry. Returns valid token."""
        if not self._id_token:
            self.sign_in()
        elif time.time() > self._token_expires_at - _TOKEN_REFRESH_BUFFER_SEC:
            self._refresh()
        assert self._id_token is not None
        return self._id_token

    def _refresh(self) -> None:
        if not self._refresh_token:
            raise MacroFactorAuthError("no refresh_token; call sign_in first")
        url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_WEB_API_KEY}"
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Ios-Bundle-Identifier": BUNDLE_ID,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            raise MacroFactorAuthError(f"token refresh HTTP {e.code}: {err_body}") from e

        self._id_token      = data.get("id_token") or data.get("access_token")
        self._refresh_token = data.get("refresh_token") or self._refresh_token
        try:
            expires_in = int(data.get("expires_in", 3600))
        except Exception:
            expires_in = 3600
        self._token_expires_at = time.time() + expires_in

    @property
    def uid(self) -> str:
        if not self._uid:
            raise MacroFactorAuthError("not signed in")
        return self._uid

    # ── Firestore REST ──────────────────────────────────────────────────────

    def _firestore_get(self, path: str) -> dict:
        """GET a Firestore document. Returns {} on 404 (no-data day). Raises on other errors."""
        token = self._ensure_fresh_token()
        req = urllib.request.Request(
            f"{FIRESTORE_BASE}/{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            err_body = e.read().decode("utf-8", errors="replace")[:300]
            raise MacroFactorAPIError(f"firestore GET {path} HTTP {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            raise MacroFactorAPIError(f"firestore GET {path} network error: {e}") from e

    def _firestore_list(self, collection_path: str, page_size: int = 100) -> list[dict]:
        """LIST documents in a Firestore collection. Auto-paginates via nextPageToken."""
        token = self._ensure_fresh_token()
        all_docs: list[dict] = []
        page_token: Optional[str] = None
        while True:
            qs = f"?pageSize={page_size}"
            if page_token:
                qs += f"&pageToken={urllib.parse.quote(page_token)}"
            req = urllib.request.Request(
                f"{FIRESTORE_BASE}/{collection_path}{qs}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                err_body = e.read().decode("utf-8", errors="replace")[:300]
                raise MacroFactorAPIError(f"firestore LIST {collection_path} HTTP {e.code}: {err_body}") from e
            except urllib.error.URLError as e:
                raise MacroFactorAPIError(f"firestore LIST {collection_path} network error: {e}") from e
            for doc in (data.get("documents") or []):
                all_docs.append(doc)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return all_docs

    # ── Firestore value decoding ────────────────────────────────────────────
    # Firestore returns values as typed wrappers: {stringValue}/{integerValue}/
    # {doubleValue}/{booleanValue}/{mapValue}/{arrayValue}/etc. MacroFactor's
    # Android app stores all food values as stringValue specifically, so the
    # decoder must coerce stringValue back to the right type for downstream
    # platform code that wants real numbers.
    @staticmethod
    def _decode_value(v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        if "stringValue" in v:    return v["stringValue"]
        if "integerValue" in v:   return int(v["integerValue"])
        if "doubleValue" in v:    return float(v["doubleValue"])
        if "booleanValue" in v:   return bool(v["booleanValue"])
        if "nullValue" in v:      return None
        if "timestampValue" in v: return v["timestampValue"]
        if "mapValue" in v:
            fields = v["mapValue"].get("fields") or {}
            return {k: MacroFactorClient._decode_value(val) for k, val in fields.items()}
        if "arrayValue" in v:
            vals = v["arrayValue"].get("values") or []
            return [MacroFactorClient._decode_value(val) for val in vals]
        return v

    @classmethod
    def _parse_document(cls, doc: dict) -> dict:
        """Convert a Firestore document → plain Python dict. Returns {} on empty doc."""
        if not doc:
            return {}
        fields = doc.get("fields") or {}
        return {k: cls._decode_value(v) for k, v in fields.items()}

    # ── Public read methods ────────────────────────────────────────────────

    def get_food_log(self, date_str: str) -> list[dict]:
        """Return the list of food entries logged on `date_str` (YYYY-MM-DD).

        Returns [] for days with no log (Firestore 404). Each entry is a
        normalized dict with food_name, calories/protein/carbs/fat,
        meal/serving/timestamp where available.
        """
        doc = self._firestore_get(f"users/{self.uid}/food/{date_str}")
        parsed = self._parse_document(doc)
        # MacroFactor stores food entries as a map keyed by entry id. Each
        # entry is itself a map of single-letter field codes.
        entries: list[dict] = []
        for entry_id, raw_entry in parsed.items():
            if not isinstance(raw_entry, dict):
                continue
            # Skip soft-deleted entries (MF marks them with a 'deleted' bool).
            if raw_entry.get("deleted") in (True, "true", "True", 1):
                continue
            entries.append(_normalize_food_entry(entry_id, raw_entry, date_str))
        # Sort by logged time when available.
        entries.sort(key=lambda e: (e.get("hour") or 0, e.get("minute") or 0))
        return entries

    def get_weight_year(self, year: int) -> list[dict]:
        """Return list of weight entries for a given year. Empty if no doc."""
        doc = self._firestore_get(f"users/{self.uid}/scale/{year}")
        parsed = self._parse_document(doc)
        out: list[dict] = []
        for k, v in parsed.items():
            if not isinstance(v, dict):
                continue
            if not (len(k) == 4 and k.isdigit()):
                continue
            mm, dd = k[:2], k[2:]
            date_str = f"{year:04d}-{mm}-{dd}"
            weight = v.get("w")
            try:
                weight_f = float(weight) if weight is not None else None
            except (TypeError, ValueError):
                weight_f = None
            out.append({
                "date":   date_str,
                "weight": weight_f,
                "body_fat_pct": _maybe_float(v.get("f")),
                "source": v.get("s"),
            })
        out.sort(key=lambda e: e["date"])
        return out

    def get_workouts(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list[dict]:
        """List all workouts in users/{uid}/workoutHistory, optionally filtered by date.

        Reverse-engineered shape (from @sjawhar/macrofactor-mcp client.ts):
          - Collection: users/{uid}/workoutHistory
          - Each doc has: name, startTime (ISO), duration (microseconds!),
            gymId, gymName, blocks[]
          - blocks[] → exercises[] (each: name + sets[])
          - sets[] → weight, reps, rpe, ...

        Returns a list of NORMALIZED workout dicts in the platform schema
        (compatible with the Hevy normalizer's output so MCP read tools see
        a uniform shape).
        """
        docs = self._firestore_list(f"users/{self.uid}/workoutHistory")
        out: list[dict] = []
        for doc in docs:
            parsed = self._parse_document(doc)
            doc_name = doc.get("name") or ""
            doc_id = doc_name.rsplit("/", 1)[-1] if doc_name else (parsed.get("id") or "")
            if not doc_id:
                continue
            workout = _normalize_mf_workout(doc_id, parsed)
            # Date-range filter applied after normalization (workout date may
            # not match Firestore-doc creation time exactly — e.g. user logs
            # yesterday's workout today).
            if start_date and workout["date"] < start_date:
                continue
            if end_date and workout["date"] > end_date:
                continue
            out.append(workout)
        out.sort(key=lambda w: w.get("start_time") or "", reverse=True)
        return out


# ── Module-level helpers ─────────────────────────────────────────────────────

def _maybe_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_food_entry(entry_id: str, raw: dict, date_str: str) -> dict:
    """Map MacroFactor's single-letter-field food entry → platform schema."""
    # Field codes (from npm logFood + Android source — confirmed during reverse-engineer):
    #   t = title/name      b = brand            c = calories
    #   p = protein         e = carbs            f = fat
    #   g = grams           s = serving desc     q = quantity
    #   h = hour            mi = minute          u = unit
    def _f(k: str) -> Any:
        return _maybe_float(raw.get(k))

    def _s(k: str) -> Optional[str]:
        v = raw.get(k)
        return str(v) if v is not None else None

    return {
        "entry_id":     entry_id,
        "date":         date_str,
        "food_name":    _s("t") or _s("b") or "(unnamed)",
        "brand":        _s("b"),
        "calories":     _f("c"),
        "protein_g":    _f("p"),
        "carbs_g":      _f("e"),
        "fat_g":        _f("f"),
        "grams":        _f("g"),
        "quantity":     _f("q"),
        "serving":      _s("s"),
        "unit":         _s("u"),
        "hour":         _maybe_int(raw.get("h")),
        "minute":       _maybe_int(raw.get("mi")),
        "raw_fields":   sorted(raw.keys()),  # bookkeeping: full field-code set observed
    }


def _maybe_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_mf_workout(doc_id: str, parsed: dict) -> dict:
    """Map a MF workoutHistory doc → platform-canonical workout shape.

    Output shape mirrors lambdas/hevy_common.normalize_workout so MCP read
    tools (tool_get_workouts etc.) see a uniform schema across sources.
    Differences from Hevy:
      - duration is microseconds in MF, seconds in Hevy → normalize to seconds
      - MF uses blocks[] → exercises[]; Hevy uses exercises[] directly. Flatten.
      - workout_uid = 'mf:<doc_id>' — for cross-tier dedupe with the future
        macrofactor_export per-workout records, BOTH paths must produce the
        same uid. The Firestore doc id is the natural stable key.
    """
    start_iso = parsed.get("startTime") or ""
    try:
        from datetime import datetime as _dt
        start_dt = _dt.fromisoformat(str(start_iso).replace("Z", "+00:00"))
        date_str = start_dt.strftime("%Y-%m-%d")
    except Exception:
        date_str = ""

    # duration is in microseconds per the npm client (`d.duration as number / 1_000_000`)
    duration_us = parsed.get("duration")
    try:
        duration_sec = int(float(duration_us) / 1_000_000) if duration_us is not None else None
    except (TypeError, ValueError):
        duration_sec = None

    # Flatten blocks → exercises so the platform schema matches Hevy's shape.
    exercises: list[dict] = []
    total_volume_kg = 0.0
    set_count = 0
    for block in (parsed.get("blocks") or []):
        if not isinstance(block, dict):
            continue
        for ex in (block.get("exercises") or []):
            if not isinstance(ex, dict):
                continue
            sets = []
            for s in (ex.get("sets") or []):
                if not isinstance(s, dict):
                    continue
                weight_kg = _maybe_float(s.get("weight") or s.get("weightKg"))
                reps = _maybe_int(s.get("reps"))
                sets.append({
                    "set_index":    _maybe_int(s.get("index")) or len(sets),
                    "weight_kg":    weight_kg,
                    "reps":         reps,
                    "rpe":          _maybe_float(s.get("rpe")),
                    "type":         s.get("type") or "normal",
                    "duration_sec": _maybe_int(s.get("durationSeconds") or s.get("duration_seconds")),
                    "distance_m":   _maybe_float(s.get("distanceMeters") or s.get("distance_meters")),
                })
                set_count += 1
                if weight_kg is not None and reps is not None:
                    total_volume_kg += weight_kg * reps
            exercises.append({
                "name":         ex.get("name") or ex.get("title") or "",
                "template_id":  ex.get("exerciseId") or ex.get("templateId") or ex.get("exercise_template_id"),
                "sets":         sets,
                "notes":        ex.get("notes") or "",
            })

    return {
        "source":            "macrofactor_api",
        "source_workout_id": doc_id,
        "workout_uid":       f"mf:{doc_id}",
        "date":              date_str,
        "title":             parsed.get("name") or "",
        "description":       parsed.get("notes") or "",
        "start_time":        str(start_iso) if start_iso else "",
        "end_time":          "",
        "duration_sec":      duration_sec,
        "total_volume_kg":   round(total_volume_kg, 2),
        "exercises":         exercises,
        "exercise_count":    len(exercises),
        "set_count":         set_count,
        "original_unit":     "kg",  # MF stores in kg per its Firestore schema
        "gym_id":            parsed.get("gymId"),
        "gym_name":          parsed.get("gymName"),
    }
