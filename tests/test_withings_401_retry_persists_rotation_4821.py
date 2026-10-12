"""#4821: a refresh-token rotation inside _withings_get's 401 retry must be persisted."""

import io
import json
import os
from unittest import mock

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import withings_lambda as wl

# Shape of a real Withings `requesttoken` refresh response (status 0, body with rotating token).
REFRESH_RESPONSE = {
    "status": 0,
    "body": {
        "userid": "12345678",
        "access_token": "NEW_ACCESS",
        "refresh_token": "NEW_REFRESH",
        "scope": "user.info,user.metrics,user.activity",
        "expires_in": 10800,
        "token_type": "Bearer",
    },
}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_401_retry_rotation_is_written_to_secrets_manager(monkeypatch):
    monkeypatch.setattr(wl, "_get_nonce", lambda *a: "n")
    monkeypatch.setattr(wl, "_post_form", lambda url, data: REFRESH_RESPONSE)
    replies = iter([{"status": 401}, {"status": 0, "body": {"measuregrps": []}}])
    import common.http_retry as hr

    monkeypatch.setattr(hr, "urlopen_with_retry", lambda req, timeout=30: _Resp(json.dumps(next(replies)).encode()))
    client = mock.MagicMock()
    with mock.patch("boto3.client", return_value=client):
        secret = {"client_id": "c", "client_secret": "s", "access_token": "OLD", "refresh_token": "OLD_R"}
        body, out = wl._withings_get(secret, "http://x", {"action": "getmeas"})
    assert out["refresh_token"] == "NEW_REFRESH"
    client.update_secret.assert_called_once()
    kw = client.update_secret.call_args.kwargs
    assert kw["SecretId"] == wl.SECRET_NAME
    assert json.loads(kw["SecretString"])["refresh_token"] == "NEW_REFRESH"
