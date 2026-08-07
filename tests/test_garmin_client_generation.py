"""tests/test_garmin_client_generation.py — #2101.

garminconnect 0.2.40 (the version on garth-layer:2 today) is inside
PYSEC-2026-3467's affected range, `< 0.3.5`. The fix line renamed the transport
seam `Garmin.garth` -> `Garmin.client` and dropped garth as a dependency, which
is why #1780 recorded the upgrade as "code-incompatible".

`lambdas/ingestion/garmin_lambda.py` is now generation-agnostic, so the layer can
move without a flag day. These tests pin that behaviour.

OFFLINE AND STUB-ONLY, deliberately, for two independent reasons:

  * garth and garminconnect reach the Lambda ONLY via the binary layer — neither
    is in requirements-dev.txt, so a CI runner cannot import either. A test that
    imported them would red the whole suite at collection, not just itself.
  * Garmin's anti-automation posture is what put this source on the ADR-074
    pause. No test here may touch the network.

Where a stub encodes a fact about the real packages, the fact is stated with how
it was measured, so a future reader can re-measure rather than trust the stub.
"""

import os
import pathlib
import re
import sys
import types

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import garmin_client as gc, garmin_lambda as gl  # noqa: E402

GARMIN_SRC = _REPO / "lambdas" / "ingestion" / "garmin_lambda.py"


# ── Stand-ins for the two garminconnect generations ──────────────────────────
# Shape measured 2026-08-06 from the real wheels in a throwaway venv:
#   0.2.40 -> Garmin() has `.garth` (a garth.http.Client), no `.client`
#   0.3.5/0.3.8 -> Garmin() has `.client` (its own Client), no `.garth`
# Each generation has exactly ONE of the two, which is what makes hasattr a
# sound discriminator rather than a version-string parse.


class _Garmin02x:
    def __init__(self):
        self.garth = None
        self.display_name = None


class _Garmin03x:
    def __init__(self):
        self.client = None
        self.display_name = None


class GarthHTTPError(Exception):
    """garth.exc.GarthHTTPError stand-in.

    Measured MRO of the real class: GarthHTTPError -> GarthException ->
    Exception. It is NOT a requests.HTTPError, which is the whole reason the
    adapter exists — 0.3.x's error decorator catches only
    (requests.HTTPError, GarminConnectConnectionError). The real class also
    carries the underlying requests exception on `.error`.
    """

    def __init__(self, msg, status=None):
        super().__init__(msg)
        resp = types.SimpleNamespace(status_code=status)
        self.error = types.SimpleNamespace(response=resp)


class _GarthClient:
    """Minimal garth.http.Client stand-in.

    The real signature is `connectapi(self, path, method="GET", **kwargs)`,
    returning parsed JSON (or None on 204) — measured against garth 0.6.3, the
    version pinned in the layer.
    """

    def __init__(self, responses=None, raises=None):
        self.responses = responses or {}
        self.raises = raises
        self.calls = []
        self.oauth2_token = None

    def connectapi(self, path, **kwargs):
        self.calls.append((path, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.responses.get(path)

    def dumps(self):
        return '{"oauth1": {}, "oauth2": {}}'


@pytest.fixture
def fake_layer(monkeypatch):
    """Install stub `garminconnect` and `garth.exc` modules.

    Necessary even on a dev box that happens to have the real packages
    installed: the tests must assert the same way on a bare CI runner, where
    neither import resolves at all.
    """

    class GarminConnectConnectionError(Exception):
        pass

    fake_gc = types.ModuleType("garminconnect")
    fake_gc.GarminConnectConnectionError = GarminConnectConnectionError
    monkeypatch.setitem(sys.modules, "garminconnect", fake_gc)

    garth = types.ModuleType("garth")
    exc = types.ModuleType("garth.exc")
    exc.GarthHTTPError = GarthHTTPError
    garth.exc = exc
    monkeypatch.setitem(sys.modules, "garth", garth)
    monkeypatch.setitem(sys.modules, "garth.exc", exc)
    return fake_gc


# ── The seam ─────────────────────────────────────────────────────────────────


def test_attaches_bare_client_on_the_02x_seam():
    """0.2.x must keep seeing the raw garth client, byte-for-byte today's
    behaviour: 0.2.40 does its own GarthHTTPError translation and reaches for
    other garth attributes, so a proxy there would be an unforced risk."""
    api, garth = _Garmin02x(), _GarthClient()
    assert gc.attach_transport(api, garth) == "garth"
    assert api.garth is garth


def test_attaches_adapter_on_the_03x_seam():
    api, garth = _Garmin03x(), _GarthClient()
    assert gc.attach_transport(api, garth) == "client"
    assert isinstance(api.client, gc.GarthTransportAdapter)
    assert api.client._inner is garth


def test_unrecognised_generation_fails_loud():
    """A third generation renaming the seam again must raise, not silently
    produce a Garmin object whose every read AttributeErrors one call later."""
    with pytest.raises(RuntimeError, match="neither"):
        gc.attach_transport(types.SimpleNamespace(), _GarthClient())


# ── The adapter ──────────────────────────────────────────────────────────────


def test_adapter_passes_results_and_kwargs_through():
    garth = _GarthClient(responses={"/p": {"ok": 1}})
    adapter = gc.GarthTransportAdapter(garth)
    assert adapter.connectapi("/p", params={"calendarDate": "2026-08-06"}) == {"ok": 1}
    assert garth.calls == [("/p", {"params": {"calendarDate": "2026-08-06"}})]


def test_adapter_delegates_unknown_attributes():
    """__getattr__ delegation means the proxy cannot silently drop a transport
    attribute 0.3.x reaches for."""
    garth = _GarthClient()
    garth.oauth2_token = "sentinel"
    assert gc.GarthTransportAdapter(garth).oauth2_token == "sentinel"
    assert gc.GarthTransportAdapter(garth).dumps() == '{"oauth1": {}, "oauth2": {}}'


@pytest.mark.parametrize("status", [401, 429, 503])
def test_adapter_translates_garth_errors_with_the_status_preserved(fake_layer, status):
    """0.3.x's decorator branches on the status it can extract, so the status
    must survive translation or a 401 stops being an auth error and a 5xx stops
    being retryable."""
    garth = _GarthClient(raises=GarthHTTPError("boom", status=status))
    adapter = gc.GarthTransportAdapter(garth)
    with pytest.raises(fake_layer.GarminConnectConnectionError) as excinfo:
        adapter.connectapi("/p")
    assert excinfo.value.status_code == status


def test_adapter_does_not_swallow_unrelated_exceptions(fake_layer):
    garth = _GarthClient(raises=ValueError("not a transport error"))
    with pytest.raises(ValueError):
        gc.GarthTransportAdapter(garth).connectapi("/p")


def test_adapter_passes_garth_errors_through_when_garth_is_absent(monkeypatch, fake_layer):
    """On a future garth-free layer there is nothing to translate; the error
    must propagate rather than be misclassified."""
    monkeypatch.setitem(sys.modules, "garth.exc", None)
    garth = _GarthClient(raises=GarthHTTPError("boom", status=401))
    with pytest.raises(GarthHTTPError):
        gc.GarthTransportAdapter(garth).connectapi("/p")


# ── Guard the SET, not the instance ──────────────────────────────────────────

# Every public method name on garminconnect 0.3.8's Garmin that this lambda
# calls. Recorded 2026-08-06 by `dir(Garmin)` against the real 0.3.8 wheel
# (`pip install --no-deps garminconnect==0.3.8`); re-measure the same way if a
# new call site is added. Listing it here rather than importing the package is
# what keeps this test runnable on a CI box with no layer.
GARMIN_03X_SURFACE = frozenset(
    {
        "get_activities_by_date",
        "get_body_battery",
        "get_heart_rates",
        "get_hrv_data",
        "get_intensity_minutes_data",
        "get_max_metrics",
        "get_respiration_data",
        "get_sleep_data",
        "get_spo2_data",
        "get_stats",
        "get_stress_data",
        "get_training_readiness",
        "get_training_status",
        "get_user_summary",
        "login",
    }
)


def test_every_api_call_site_exists_on_the_03x_surface():
    """Derive the call sites from the source rather than restating them, so
    adding `api.get_something_new(...)` fails here until someone has actually
    checked it against the version the layer is about to carry."""
    used = set(re.findall(r"\bapi\.([a-z_][a-z0-9_]*)\(", GARMIN_SRC.read_text()))
    missing = sorted(used - GARMIN_03X_SURFACE)
    assert missing == [], f"call sites not verified against garminconnect 0.3.8: {missing}"


# ── The native (garth-free) path ─────────────────────────────────────────────


def test_native_path_is_inert_without_a_di_bundle():
    """The state on 2026-08-06: the secret holds garth tokens only, so
    native_garmin_client must decline and let the garth path run. If this ever
    flips accidentally, Garmin ingestion breaks on a token family it does not
    have."""
    assert gl.native_garmin_client({"garth_tokens": "{}"}) is None


def test_native_path_declines_on_a_02x_layer(monkeypatch):
    """DI tokens present but the layer is still 0.2.40: fall back rather than
    crash, so the secret and the layer can be migrated in either order."""
    mod = types.ModuleType("garminconnect")
    mod.Garmin = _Garmin02x  # no `.client`
    monkeypatch.setitem(sys.modules, "garminconnect", mod)
    assert gl.native_garmin_client({gc.NATIVE_TOKEN_KEY: '{"di_token": "x"}'}) is None


def test_native_path_loads_resolves_and_writes_back(monkeypatch):
    loaded, saved = [], []

    class _NativeClient:
        def __init__(self):
            self.calls = []

        def loads(self, blob):
            loaded.append(blob)

        def connectapi(self, path, **kw):
            self.calls.append(path)
            return {"displayName": "matthew"}

        def dumps(self):
            return '{"di_token": "refreshed"}'

    class _Garmin:
        def __init__(self):
            self.client = _NativeClient()
            self.display_name = None

    mod = types.ModuleType("garminconnect")
    mod.Garmin = _Garmin
    monkeypatch.setitem(sys.modules, "garminconnect", mod)
    monkeypatch.setattr(gl, "save_secret", lambda s: saved.append(dict(s)))

    secret = {gc.NATIVE_TOKEN_KEY: '{"di_token": "stored"}'}
    api = gl.native_garmin_client(secret)

    assert api is not None
    assert loaded == ['{"di_token": "stored"}']
    assert api.display_name == "matthew"
    # Rotation durability (the #2076 class): a refreshed bundle must reach
    # Secrets Manager, or the next cold start resumes a dead token.
    assert secret[gc.NATIVE_TOKEN_KEY] == '{"di_token": "refreshed"}'
    assert saved and saved[0][gc.NATIVE_TOKEN_KEY] == '{"di_token": "refreshed"}'


def test_native_path_accepts_a_dict_bundle(monkeypatch):
    """Secrets Manager round-trips JSON; the bundle may arrive parsed."""
    seen = []

    class _NativeClient:
        def loads(self, blob):
            seen.append(blob)

        def connectapi(self, path, **kw):
            return {"displayName": "matthew"}

        def dumps(self):
            return "{}"

    class _Garmin:
        def __init__(self):
            self.client = _NativeClient()
            self.display_name = None

    mod = types.ModuleType("garminconnect")
    mod.Garmin = _Garmin
    monkeypatch.setitem(sys.modules, "garminconnect", mod)
    monkeypatch.setattr(gl, "save_secret", lambda s: None)

    gl.native_garmin_client({gc.NATIVE_TOKEN_KEY: {"di_token": "x"}})
    assert seen == ['{"di_token": "x"}']


# ── display_name resolution (shared by both paths) ───────────────────────────


def test_display_name_prefers_the_stored_secret():
    api = _Garmin03x()
    garth = _GarthClient()
    gc.resolve_display_name(api, garth.connectapi, {"display_name": "stored"})
    assert api.display_name == "stored"
    assert garth.calls == [], "no profile call should be made when the secret already has it"


def test_display_name_falls_through_a_failing_profile_endpoint():
    """The first endpoint 404s on some account tiers; the second must still be
    tried, otherwise every read 403s on a `None` display_name in the URL."""
    garth = _GarthClient(responses={"/userprofile-service/userdisplayname": "matthew"})

    def flaky(path, **kw):
        if path == "/userprofile-service/socialProfile":
            raise RuntimeError("404")
        return garth.connectapi(path, **kw)

    api = _Garmin03x()
    gc.resolve_display_name(api, flaky, {})
    assert api.display_name == "matthew"


# ── #2099 honest-manifest contract ───────────────────────────────────────────


def test_manifest_still_states_the_deployed_02x_truth():
    """This change is merge-safe ahead of the owner's layer rebuild.

    The build TARGET moves to 0.3.8 (a comment — the spec for the next build),
    while the uncommented, pip-audit-scannable pins keep saying what is actually
    running. Flipping the deployed pin here without a rebuild is exactly the
    #1778/#1780 failure mode that #2099's gate exists to catch, and it would red
    main for everyone else.
    """
    body = (_REPO / "lambdas" / "requirements" / "garmin.txt").read_text()
    pins = {ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")}
    assert "garminconnect==0.2.40" in pins, "deployed pin must keep reporting the live layer"
    assert "garminconnect==0.3.8" not in pins, "0.3.8 is a build target, not deployed — do not promote it by hand"
    assert "#   layer-build-target: garminconnect==0.3.8" in body
