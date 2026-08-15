"""#2655 — a DENIED config channel must never read as an ABSENT one.

Background. `ai-quality-canary` failed 100% of its runs from 2026-08-10 to
2026-08-14. The cause was a missing `s3:GetObject` grant on `config/*`; the
resulting `AccessDenied` was absorbed by `_from_s3_boto`'s bare
`except Exception: return None`, so the only operator-visible signal was
"content-filter vocabulary unavailable from every channel source" — a sentence
that is equally true of a laptop that was never configured. Four days of a dark
AI-quality gate were spent on the difference between those two readings.

§9a — is the fixture the wire? The subject here crosses a service boundary, so
the error codes below are NOT invented. They were captured from live S3
(us-west-2, boto3) on 2026-08-15:

    get_object("matthew-life-platform", "config/<absent key>") -> NoSuchKey    HTTP 404
    get_object("amazon-reviews-pds", "x")   [other account]    -> AccessDenied HTTP 403
    get_object("<nonexistent bucket>", "x")                    -> NoSuchBucket HTTP 404

The assumption this file encodes: S3 reports "not there" and "you may not look"
as distinct `Error.Code` values, and only the first class is a legitimate
absence. What would invalidate it: S3 collapsing 403 into 404 for unauthorized
reads (it does this for `ListBucket`-less principals on HeadObject — which is
why NoSuchKey/NoSuchBucket are treated as absence and everything else is not).

The assertions are written over the SET of denial codes rather than over one
string, so a future channel that swallows `ExpiredToken` fails here too.
"""

import logging

import pytest
from privacy import content_filter_channel as cfc

# Real botocore error envelopes. `ClientError.response` is the parsed wire body.
_DENIAL_CODES = ["AccessDenied", "InvalidAccessKeyId", "ExpiredToken", "AccountProblem"]
_ABSENCE_CODES = ["NoSuchKey", "NoSuchBucket"]


def _client_error(code, http_status):
    from botocore.exceptions import ClientError

    return ClientError(
        {
            "Error": {"Code": code, "Message": f"{code} (captured shape)"},
            "ResponseMetadata": {"HTTPStatusCode": http_status, "RequestId": "TEST"},
        },
        "GetObject",
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No env / local channel, so every test resolves via the S3 channel only."""
    monkeypatch.delenv("CONTENT_FILTER_JSON", raising=False)
    monkeypatch.setattr(cfc, "_from_local_file", lambda: None)
    monkeypatch.setattr(cfc, "_from_s3_cli", lambda bucket: None)
    cfc.reset_cache()
    yield
    cfc.reset_cache()


def _fail_s3_with(monkeypatch, exc):
    """Make the real _from_s3_boto body run, with boto3's get_object raising `exc`."""

    class _FakeS3:
        def get_object(self, **kwargs):
            raise exc

    fake_boto3 = type("boto3", (), {"client": staticmethod(lambda *a, **k: _FakeS3())})
    monkeypatch.setitem(__import__("sys").modules, "boto3", fake_boto3)


@pytest.mark.parametrize("code", _DENIAL_CODES)
def test_denial_is_named_in_the_failclosed_message(monkeypatch, code):
    """A denial must be reported as a denial. Pre-fix this message was identical
    for every cause, which is exactly why #2655 took four days to read."""
    _fail_s3_with(monkeypatch, _client_error(code, 403))

    with pytest.raises(cfc.ContentFilterUnavailable) as excinfo:
        cfc.load(require=True)

    assert code in str(excinfo.value), f"{code} was swallowed — message: {excinfo.value}"


@pytest.mark.parametrize("code", _DENIAL_CODES)
def test_denial_logs_at_error(monkeypatch, caplog, code):
    """The operator must see the cause without reading a traceback."""
    _fail_s3_with(monkeypatch, _client_error(code, 403))

    with caplog.at_level(logging.ERROR, logger=cfc.__name__):
        assert cfc.load() is None  # contract unchanged: still degrades to None

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, f"{code} produced no ERROR record"
    assert code in errors[0].getMessage()


@pytest.mark.parametrize("code", _ABSENCE_CODES)
def test_genuine_absence_stays_quiet(monkeypatch, caplog, code):
    """The other half of the contract: a never-configured environment must NOT
    page. Without this, the fix would just move the noise."""
    _fail_s3_with(monkeypatch, _client_error(code, 404))

    with caplog.at_level(logging.ERROR, logger=cfc.__name__):
        assert cfc.load() is None

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], f"absence code {code} logged an ERROR"


def test_no_vocabulary_leaks_into_the_error_path(monkeypatch):
    """ER-06: the artifact that hides the vocabulary must not print it while failing."""
    _fail_s3_with(monkeypatch, _client_error("AccessDenied", 403))

    with pytest.raises(cfc.ContentFilterUnavailable) as excinfo:
        cfc.load(require=True)

    message = str(excinfo.value)
    assert "blocked_vice_keywords" not in message
    for reason in cfc.last_channel_errors():
        assert reason.startswith(("s3:", "aws-cli:", "boto3"))
