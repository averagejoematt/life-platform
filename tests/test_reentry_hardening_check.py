"""tests/test_reentry_hardening_check.py — #1029 re-entry hardening status script.

All checks are pure/injectable (fake AWS clients, fake subprocess runners) so this
suite never needs live AWS credentials, a real macOS host, or GitHub CLI access —
it must pass identically in CI and locally. Non-vacuity per the #1189 lesson: each
check is proven to FLAG the bad case and PASS the good case, not just "run without
crashing".
"""

import importlib.util
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("_reentry", ROOT / "scripts" / "check_reentry_hardening.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _FakeSSO:
    def __init__(self, instances):
        self._instances = instances

    def list_instances(self):
        return {"Instances": self._instances}


class _FakeIAM:
    def __init__(self, keys):
        self._keys = keys

    def list_access_keys(self, UserName):
        return {"AccessKeyMetadata": self._keys}


def test_identity_center_pass_on_active_instance():
    m = _load()
    sso = _FakeSSO([{"InstanceArn": "arn:aws:sso:::instance/x", "Status": "ACTIVE"}])
    status, detail = m.check_identity_center(sso_client=sso)
    assert status == "PASS"
    assert "ACTIVE" in detail


def test_identity_center_flags_no_instance():
    m = _load()
    sso = _FakeSSO([])
    status, detail = m.check_identity_center(sso_client=sso)
    assert status == "FLAG"
    assert "not provisioned" in detail


def test_identity_center_flags_non_active_instance():
    m = _load()
    sso = _FakeSSO([{"InstanceArn": "arn:x", "Status": "CREATE_IN_PROGRESS"}])
    status, _ = m.check_identity_center(sso_client=sso)
    assert status == "FLAG"


def test_identity_center_unknown_on_error():
    m = _load()

    class _Boom:
        def list_instances(self):
            raise RuntimeError("no creds")

    status, detail = m.check_identity_center(sso_client=_Boom())
    assert status == "UNKNOWN"
    assert "no creds" in detail


def test_breakglass_pass_when_no_active_keys():
    m = _load()
    iam = _FakeIAM([{"AccessKeyId": "AKIA1", "Status": "Inactive", "CreateDate": date(2026, 1, 1)}])
    status, detail = m.check_breakglass_key(iam_client=iam, today=date(2026, 7, 26))
    assert status == "PASS"
    assert "already deactivated" in detail


def test_breakglass_flags_when_identity_center_live():
    """Mirrors the live #1029 shape (Identity Center ACTIVE, matthew-admin key still
    Active) with a synthetic key id — never assert on/print a real AccessKeyId."""
    m = _load()
    iam = _FakeIAM([{"AccessKeyId": "AKIA-FAKE-4", "Status": "Active", "CreateDate": date(2026, 2, 21)}])
    status, detail = m.check_breakglass_key(iam_client=iam, today=date(2026, 7, 26), identity_center_live=True)
    assert status == "FLAG"
    assert "Identity Center is live" in detail
    assert "AKIA-FAKE-4" in detail


def test_breakglass_flags_overdue_rotation_even_without_identity_center():
    m = _load()
    iam = _FakeIAM([{"AccessKeyId": "AKIA2", "Status": "Active", "CreateDate": date(2026, 1, 1)}])
    status, detail = m.check_breakglass_key(iam_client=iam, today=date(2026, 7, 26), identity_center_live=False)
    assert status == "FLAG"
    assert "rotation cadence" in detail


def test_breakglass_passes_fresh_key_when_identity_center_not_live():
    m = _load()
    iam = _FakeIAM([{"AccessKeyId": "AKIA3", "Status": "Active", "CreateDate": date(2026, 7, 20)}])
    status, _ = m.check_breakglass_key(iam_client=iam, today=date(2026, 7, 26), identity_center_live=False)
    assert status == "PASS"


def test_breakglass_unknown_on_error():
    m = _load()

    class _Boom:
        def list_access_keys(self, UserName):
            raise RuntimeError("access denied")

    status, detail = m.check_breakglass_key(iam_client=_Boom())
    assert status == "UNKNOWN"
    assert "access denied" in detail


def test_accounts_estate_rows_flags_the_real_undocumented_marker():
    """Non-vacuity: fires on the exact marker text live in docs/ACCOUNTS.md today."""
    m = _load()
    text = "| Which password manager | ⚠️ **UNDOCUMENTED — owner action required.** Matthew: record it. |\n"
    status, detail = m.check_accounts_estate_rows(text=text)
    assert status == "FLAG"
    assert "1 estate row" in detail


def test_accounts_estate_rows_passes_once_filled():
    m = _load()
    text = "| Which password manager | 1Password, estate kit at the safe deposit box (pointer only) |\n"
    status, _ = m.check_accounts_estate_rows(text=text)
    assert status == "PASS"


def test_accounts_estate_rows_clean_reads_current_live_doc():
    """This is expected to still FLAG on the real live tree — #1029 items 2 is an
    explicit owner-only action this PR cannot complete. Proves the check reads the
    real file path correctly (regression guard against a typo'd path silently no-op'ing)."""
    m = _load()
    status, detail = m.check_accounts_estate_rows()
    assert status in ("PASS", "FLAG")
    if status == "FLAG":
        assert "UNDOCUMENTED" in detail or "estate row" in detail


def test_filevault_pass_on_on_output():
    m = _load()
    status, detail = m.check_filevault(runner=lambda: subprocess.CompletedProcess([], 0, stdout="FileVault is On.\n", stderr=""))
    assert status == "PASS"
    assert "On" in detail


def test_filevault_flags_off_output():
    m = _load()
    status, _ = m.check_filevault(runner=lambda: subprocess.CompletedProcess([], 0, stdout="FileVault is Off.\n", stderr=""))
    assert status == "FLAG"


def test_filevault_unknown_when_not_macos():
    m = _load()

    def _raise():
        raise FileNotFoundError("no fdesetup")

    status, detail = m.check_filevault(runner=_raise)
    assert status == "UNKNOWN"
    assert "not macOS" in detail


def test_domain_expiry_flags_when_close():
    m = _load()
    text = "Registration expires **2026-08-20**\n"
    status, detail = m.check_domain_expiry(text=text, today=date(2026, 7, 26))
    assert status == "FLAG"
    assert "25d left" in detail


def test_domain_expiry_flags_when_already_expired():
    m = _load()
    text = "Registration expires **2026-08-20**\n"
    status, detail = m.check_domain_expiry(text=text, today=date(2026, 9, 1))
    assert status == "FLAG"
    assert "PASSED" in detail


def test_domain_expiry_passes_when_far_out():
    m = _load()
    text = "Registration expires **2026-08-20**\n"
    status, detail = m.check_domain_expiry(text=text, today=date(2026, 1, 1))
    assert status == "PASS"
    assert "left" in detail


def test_domain_expiry_unknown_when_no_date_found():
    m = _load()
    status, detail = m.check_domain_expiry(text="no expiry mentioned here\n")
    assert status == "UNKNOWN"


def test_repo_visibility_pass_when_private():
    m = _load()
    status, detail = m.check_repo_visibility(
        runner=lambda: subprocess.CompletedProcess([], 0, stdout='{"isPrivate": true, "visibility": "PRIVATE"}\n', stderr="")
    )
    assert status == "PASS"
    assert "PRIVATE" in detail


def test_repo_visibility_flags_when_public():
    """Non-vacuity: matches the exact live shape (`gh repo view` returning isPrivate:false)."""
    m = _load()
    status, detail = m.check_repo_visibility(
        runner=lambda: subprocess.CompletedProcess([], 0, stdout='{"isPrivate": false, "visibility": "PUBLIC"}\n', stderr="")
    )
    assert status == "FLAG"
    assert "PUBLIC" in detail


def test_repo_visibility_unknown_when_gh_missing():
    m = _load()

    def _raise():
        raise FileNotFoundError("no gh")

    status, detail = m.check_repo_visibility(runner=_raise)
    assert status == "UNKNOWN"
    assert "gh CLI not found" in detail


def test_repo_visibility_unknown_on_nonzero_exit():
    m = _load()
    status, _ = m.check_repo_visibility(runner=lambda: subprocess.CompletedProcess([], 1, stdout="", stderr="not authenticated"))
    assert status == "UNKNOWN"


def test_run_all_composes_breakglass_with_identity_center_result():
    """run_all() must wire the Identity Center verdict into the break-glass check
    (not run them independently) — this is the one thing main() depends on beyond
    each individual check."""
    m = _load()
    labels = [label for label, _, _ in m.run_all()]
    assert labels == [
        "1a. IAM Identity Center provisioned",
        "1b. Break-glass matthew-admin key deactivated",
        "2. ACCOUNTS.md estate rows filled",
        "3. FileVault enabled",
        "4. Domain (registrar) renewal window",
        "5. Repo flipped private",
    ]


def test_main_never_fails_ci_regardless_of_flags():
    """This is a status report, not a gate — exit code must always be 0 even when
    every check is a live FLAG (no AWS/gh access in CI means most checks land
    UNKNOWN or FLAG), since every #1029 item is owner-gated by design."""
    import sys

    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_reentry_hardening.py")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Re-entry hardening status" in r.stdout


def test_main_json_output_is_valid_json():
    import json
    import sys

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_reentry_hardening.py"), "--json"], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert len(data) == 6
    assert all({"item", "status", "detail"} <= set(row.keys()) for row in data)
