"""The offline AWS credential stub, shared by the eval harnesses (#4796).

Importing this module installs the stub only when it cannot shadow a real chain."""

import os
import sys


def install_credential_stub():
    """Inject the 'testing' stub only when it cannot shadow a real chain (#4796).

    Environment credentials outrank the shared credentials file, so an unconditional stub
    made every real-mode Bedrock/SSM call sign with 'testing'. Stub only for --dry-run, or
    when no chain resolves at all (CI, the hermetic golden-surface tests).
    """
    if "AWS_ACCESS_KEY_ID" in os.environ or "AWS_SECRET_ACCESS_KEY" in os.environ:
        return
    if "--dry-run" not in sys.argv:
        try:
            import boto3

            if boto3.Session().get_credentials() is not None:
                return
        except Exception:
            pass
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"


install_credential_stub()
