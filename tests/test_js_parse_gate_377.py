"""tests/test_js_parse_gate_377.py — the site-deploy JS parse gate (#377).

evidence.js (~3k lines) renders all 44 archive pages; a one-char typo would break
every Data/Protocols/Method page at once. The sync script must syntax-check site JS
before uploading. This drift-guard pins that the gate exists and — critically — uses
`--input-type=module`: plain `node --check <file>` auto-detection silently MISSES real
errors in ES-module files, so that flag is load-bearing, not cosmetic.
"""

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SYNC = os.path.join(_ROOT, "deploy", "sync_site_to_s3.sh")


def _script():
    with open(_SYNC) as f:
        return f.read()


def test_sync_script_exists():
    assert os.path.isfile(_SYNC)


def test_parse_gate_present_and_module_mode():
    s = _script()
    assert "JS parse gate" in s, "the #377 parse gate must be present in the site sync script"
    # The load-bearing correctness detail — module mode via stdin (file-mode misses errors).
    assert "node --check --input-type=module" in s
    # It must fail closed: an unhandled parse error aborts the publish.
    assert "publish blocked" in s and "exit 1" in s


def test_gate_runs_before_the_s3_upload():
    s = _script()
    gate = s.find("JS parse gate")
    first_sync = s.find("aws s3 sync")
    assert gate != -1 and first_sync != -1
    assert gate < first_sync, "the parse gate must run BEFORE any S3 upload"
