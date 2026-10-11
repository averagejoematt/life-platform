"""#4276 follow-up: `call_json` absorbs Bedrock's "compiled grammar is too large" refusal.

Measured live 2026-10-02 on the Story Desk's BUDGET_SCHEMA: Bedrock refuses a large strict schema
with a ValidationException whose message does NOT name `output_config`. `_schema_rejected` required
that word, so a `call_json` site whose schema crossed the grammar limit raised instead of re-sending
schema-less — the opposite of the module's promise that an unsupported schema "never fails the caller".

The fixture is the wire: a real botocore `ClientError` built from the service's error shape, so the
string the predicate reads is the string boto3 raises.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import structured_json  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

GRAMMAR_MSG = (
    "The compiled grammar is too large, which would cause performance issues. "
    "Simplify your tool schemas or reduce the number of strict tools."
)
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def _client_error(code: str, message: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "InvokeModel")


def _body():
    return {"model": "m", "max_tokens": 20, "messages": [{"role": "user", "content": "x"}]}


def test_a_grammar_too_large_refusal_falls_back_schema_less(capsys):
    sent = []

    def call(body):
        sent.append(body)
        if "output_config" in body:
            raise _client_error("ValidationException", GRAMMAR_MSG)
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"ok": true}'}]}

    assert "output_config" not in str(_client_error("ValidationException", GRAMMAR_MSG))  # the wire really omits it
    assert structured_json.call_json(call, _body(), schema=SCHEMA, label="probe") == {"ok": True}
    assert ["output_config" in b for b in sent] == [True, False]  # strict once, then schema-less once
    out = capsys.readouterr().out
    assert "label=probe fallback=schema_rejected" in out and "compiled grammar is too large" in out


def test_an_output_config_refusal_still_falls_back():
    sent = []

    def call(body):
        sent.append(body)
        if "output_config" in body:
            raise _client_error("ValidationException", "output_config.format.schema: additionalProperties must be false")
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"ok": false}'}]}

    assert structured_json.call_json(call, _body(), schema=SCHEMA, label="probe") == {"ok": False}
    assert len(sent) == 2


NOT_SCHEMA_ERRORS = [
    ("ThrottlingException", "Too many requests, please wait before trying again."),
    ("ValidationException", "max_tokens: must be less than or equal to 64000"),
    ("ServiceUnavailableException", "The compiled grammar service is down"),
]


def test_other_errors_are_not_absorbed():
    """Every non-schema error re-raises after ONE send; all offenders are reported together."""
    offenders = []
    for code, message in NOT_SCHEMA_ERRORS:
        sent = []

        def call(body, _c=code, _m=message, _s=sent):
            _s.append(body)
            raise _client_error(_c, _m)

        try:
            structured_json.call_json(call, _body(), schema=SCHEMA, label="probe")
            offenders.append(f"{code}: absorbed (no raise)")
        except ClientError:
            if len(sent) != 1:
                offenders.append(f"{code}: sent {len(sent)} times")
    assert not offenders, offenders
