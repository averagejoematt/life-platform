"""garmin_client.py — garminconnect generation seam for the Garmin lambda (#2101).

Split out of garmin_lambda.py, which had reached the 1200-line ceiling (#1665).
This module owns exactly one concern: producing an authenticated
`garminconnect.Garmin` regardless of which generation of the library the binary
layer happens to carry. Token loading, refresh and the 429 breaker stay in
garmin_lambda.py — they are garth-lifecycle concerns, not client-construction.

── Why this exists ───────────────────────────────────────────────────────────

The layer ships garminconnect 0.2.40 today, which is inside PYSEC-2026-3467's
affected range (`< 0.3.5`, measured from OSV 2026-08-06). The fix lands in
0.3.5, which dropped garth for its own curl_cffi client. Two independent seams
change between the generations:

  1. THE INJECTION ATTRIBUTE. 0.2.x holds its transport on `Garmin.garth`;
     0.3.x renamed it to `Garmin.client`. Measured (0.2.40 vs 0.3.5/0.3.8):
     each generation has exactly one of the two attributes, so `hasattr` is a
     sound, version-string-free discriminator. Every one of the lambda's 13
     reads funnels through a single `<transport>.connectapi(path, **kwargs)`
     call in BOTH generations — verified by walking 0.3.5's getter sources —
     and garth 0.6.3's `Client.connectapi(path, method="GET", **kwargs)`
     satisfies that contract. So garth-backed auth keeps working on 0.3.x; what
     breaks is only the attribute name. (#1780 measured the AttributeError and
     concluded "code-incompatible"; the measurement was right, the conclusion
     was broader than the evidence.)

  2. THE TOKEN FAMILY. 0.3.x's own auth is NOT reachable from the tokens we
     hold. Measured: feeding the stored browser-auth bundle (oauth1/oauth2) to
     garminconnect 0.3.5's `Client.loads()` raises "Missing tokens from dict
     load" — 0.3.x wants `di_token`/`di_refresh_token`/`di_client_id` minted by
     a CAS service-ticket exchange against diauth.garmin.com, a different
     issuer from garth's connectapi OAuth2 exchange. Migrating auth therefore
     needs a NEW interactive re-auth against a vendor mid anti-automation
     crackdown (ADR-074) — it cannot be a code-only change.

So the CVE is cleared by the LAYER moving to garminconnect >= 0.3.5, and this
module makes that rebuild a no-drama swap. `native_garmin_client` is the ramp to
retiring garth entirely: wired and unit-tested, but inert until a DI bundle
exists in the secret.

Note the CVE's mechanism is doubly inapplicable here: it is a 0o644 write in
`Client.dump(path)`, and neither generation reaches that code unless a tokenstore
PATH is set. This lambda never sets one. Upgrading is hygiene (the advisory
leaves pip-audit), not incident response.

Nothing here imports garth or garminconnect at module scope — they reach the
runtime only via the binary layer, so the import must stay inside the call.
"""

import json
import logging

try:
    from common.platform_logger import get_logger

    logger = get_logger("garmin")
except ImportError:  # pragma: no cover - local/test fallback
    logger = logging.getLogger("garmin")
    logger.setLevel(logging.INFO)

# Secret key carrying a garminconnect >= 0.3.5 native DI token bundle. Absent
# today; written only by a future 0.3.x-native re-auth.
NATIVE_TOKEN_KEY = "garmin_di_tokens"  # noqa: S105 - a secret KEY NAME, not a credential

# The profile endpoints display_name can be read from, in preference order. The
# first 404s on some account tiers, which is why there are two.
_PROFILE_PATHS = (
    "/userprofile-service/socialProfile",
    "/userprofile-service/userdisplayname",
)


class GarthTransportAdapter:
    """Delegating proxy that lets a garth client stand in for garminconnect
    0.3.x's own transport.

    Only one behaviour needs bridging. 0.2.40's `Garmin.connectapi` catches
    `GarthHTTPError` explicitly and translates 401/429/4xx into the
    `GarminConnect*Error` family; 0.3.x's `_handle_api_errors` decorator catches
    only `(requests.HTTPError, GarminConnectConnectionError)`, and garth's
    `GarthHTTPError` subclasses neither (measured MRO: GarthHTTPError ->
    GarthException -> Exception). Unadapted, a 401 or 429 on a data read would
    escape 0.3.x untranslated and unretried. This re-raises it as the exception
    0.3.x expects, carrying the status so its 401/429/5xx branches still fire.

    Everything else is delegated untouched, so the proxy cannot silently drop a
    transport attribute 0.3.x reaches for.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @staticmethod
    def _is_garth_http_error(e) -> bool:
        try:
            from garth.exc import GarthHTTPError

            return isinstance(e, GarthHTTPError)
        except ImportError:
            # garth absent (a future garth-free layer) — nothing to translate.
            return False

    def connectapi(self, path, **kwargs):
        try:
            return self._inner.connectapi(path, **kwargs)
        except Exception as e:
            if not self._is_garth_http_error(e):
                raise
            try:
                # Lazy + guarded like _is_garth_http_error: on the layer this
                # import always succeeds (the adapter exists to serve
                # garminconnect); in CI the wheel is layer-shipped and absent,
                # and with nothing to translate INTO we re-raise untranslated.
                from garminconnect import GarminConnectConnectionError
            except ImportError:
                raise e
            # garth wraps the underlying requests exception on `.error`; the
            # status lives on its response. 0.3.x reads `.status_code` first.
            status = getattr(getattr(getattr(e, "error", None), "response", None), "status_code", None)
            translated = GarminConnectConnectionError(f"garth transport error: {e}")
            translated.status_code = status
            raise translated from e


def attach_transport(api, garth_client) -> str:
    """Wire an authenticated garth client into whichever garminconnect is on the
    layer. Returns the seam name used, for logging. Raises if neither seam
    exists (a third generation we have not measured — fail loud, do not guess).
    """
    if hasattr(api, "garth"):
        # 0.2.x — inject the bare client. This is byte-for-byte today's
        # behaviour: 0.2.40 does its own GarthHTTPError translation and reaches
        # for other garth attributes, so it must not see a proxy.
        api.garth = garth_client
        return "garth"
    if hasattr(api, "client"):
        api.client = GarthTransportAdapter(garth_client)
        return "client"
    raise RuntimeError("garminconnect exposes neither `.garth` nor `.client` — unrecognised generation, refusing to guess a seam.")


def resolve_display_name(api, connectapi, secret: dict) -> None:
    """Populate api.display_name from the secret, else from the profile API.

    Shared by both auth paths — the endpoints and the field names are identical
    across generations; only the callable differs. Left unset on total failure
    so the caller can raise with its own re-auth instructions.
    """
    if secret.get("display_name"):
        api.display_name = secret["display_name"]
        logger.info("display_name resolved from stored secret")
        return
    for profile_path in _PROFILE_PATHS:
        try:
            profile = connectapi(profile_path)
            name = None
            if isinstance(profile, dict):
                name = profile.get("displayName") or profile.get("userName") or profile.get("fullName")
            elif isinstance(profile, str):
                name = profile.strip()
            if name:
                api.display_name = name
                logger.info(f"Resolved display_name: {name} (from {profile_path})")
                return
        except Exception as e:
            logger.info(f"Profile path {profile_path} failed: {e}")


def native_garmin_client(secret: dict, save_secret):
    """garminconnect >= 0.3.5's OWN auth — the path that finally retires garth.

    Returns a logged-in `Garmin`, or None when this path is not available, in
    which case the caller falls back to the garth path. Two preconditions, both
    checked rather than assumed:

      * the secret carries a DI token bundle under NATIVE_TOKEN_KEY, and
      * the installed garminconnect exposes `.client` with `loads()` (i.e. is
        0.3.x, not the 0.2.40 currently on the layer).

    Either can be false independently, so the secret and the layer can migrate
    in either order without a broken window.

    No credential login is attempted: Lambda has no stdin for MFA, and hammering
    Garmin SSO from a datacentre IP is what earned the ADR-074 pause. Token
    refresh needs no machinery on this path either — 0.3.x's `_run_request`
    refreshes proactively on a near-expiry DI token and retries once on a 401.
    `save_secret` is injected rather than imported to keep this module free of a
    cycle back into the handler.
    """
    blob = secret.get(NATIVE_TOKEN_KEY)
    if not blob:
        return None

    from garminconnect import Garmin

    api = Garmin()
    client = getattr(api, "client", None)
    if client is None or not hasattr(client, "loads"):
        logger.warning(f"{NATIVE_TOKEN_KEY} is present but the installed garminconnect has no native token store — using garth.")
        return None

    client.loads(blob if isinstance(blob, str) else json.dumps(blob))
    logger.info("Loaded native garminconnect DI tokens (0.3.x auth path).")

    resolve_display_name(api, client.connectapi, secret)
    if not api.display_name:
        raise RuntimeError("Could not resolve Garmin display_name on the native auth path — DI tokens may be expired.")

    # Rotation durability (#2076): a refreshed bundle must reach Secrets Manager
    # eagerly, or the next cold start resumes a token that has already rotated.
    try:
        new_tokens = client.dumps()
        if new_tokens and new_tokens != secret.get(NATIVE_TOKEN_KEY):
            secret[NATIVE_TOKEN_KEY] = new_tokens
            save_secret(secret)
            logger.info("Refreshed native DI tokens saved to Secrets Manager.")
    except Exception as e:
        logger.info(f"Warning: could not save refreshed DI tokens ({e})")

    return api
