#!/usr/bin/env python3
"""scripts/check_reentry_hardening.py — read-only status snapshot for the #1029
re-entry hardening checklist (epic #1024, stolen-laptop resilience audit).

#1029's five items are explicitly owner-gated ("Owner: Matthew (human-only — no
AI session can do these)") — enabling/rotating AWS IAM, filling in personal
estate/password-manager pointers, confirming laptop disk encryption, logging
into the domain registrar, and deciding on repo visibility (a cost trade-off:
private repos cap free GitHub Actions at 2,000 min/mo). No script can DO those
things. What this script gives instead is a fast, read-only, re-runnable status
check so "done vs. still open" never has to be re-derived from memory or a stale
handover — the #722 discipline ("no item carried unactioned across sessions"
needs a cheap way to re-verify, not just re-assert).

Every check is read-only:
  - IAM Identity Center: `sso-admin:ListInstances` (no mutation)
  - break-glass key: `iam:ListAccessKeys` for matthew-admin (no mutation)
  - estate rows: parses docs/ACCOUNTS.md for the UNDOCUMENTED markers
  - FileVault: `fdesetup status` (macOS, no mutation)
  - domain expiry: parses the expiry date already recorded in docs/ACCOUNTS.md
  - repo visibility: `gh repo view --json isPrivate,visibility` (no mutation)

Any check that can't run (no AWS creds, not on macOS, `gh` not installed, no
network) reports UNKNOWN rather than failing — this script never mutates
anything and never fails CI (see main()'s fixed exit code 0: it is a status
report, not a gate).

Usage:
    python3 scripts/check_reentry_hardening.py            # human-readable report
    python3 scripts/check_reentry_hardening.py --json      # machine-readable
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_PATH = ROOT / "docs" / "ACCOUNTS.md"

UNDOCUMENTED_MARKER = "UNDOCUMENTED — owner action required"
DOMAIN_EXPIRY_RE = re.compile(r"expires \*\*(\d{4}-\d{2}-\d{2})\*\*")

# 90-day rotation cadence for the matthew-admin break-glass key (docs/AWS_ACCESS.md §3).
BREAKGLASS_ROTATION_DAYS = 90
# Flag the domain renewal inside this window regardless of whois/registrar access.
DOMAIN_WARNING_DAYS = 30


def check_identity_center(sso_client=None):
    """(status, detail) — status in {PASS, FLAG, UNKNOWN}. PASS = an ACTIVE
    IAM Identity Center instance exists (item 1's "enable" half)."""
    try:
        if sso_client is None:
            import boto3

            sso_client = boto3.client("sso-admin", region_name="us-west-2")
        resp = sso_client.list_instances()
        instances = resp.get("Instances", [])
        active = [i for i in instances if i.get("Status") == "ACTIVE"]
        if active:
            return "PASS", f"IAM Identity Center ACTIVE ({active[0].get('InstanceArn', 'unknown arn')})"
        if instances:
            return "FLAG", f"Identity Center instance present but not ACTIVE: {instances}"
        return "FLAG", "no IAM Identity Center instance found — still not provisioned"
    except Exception as e:  # pragma: no cover - network/creds dependent
        return "UNKNOWN", f"could not query sso-admin:ListInstances: {e}"


def check_breakglass_key(iam_client=None, user_name="matthew-admin", today=None, identity_center_live=None):
    """(status, detail) — reports the matthew-admin break-glass key's Active
    keys and age. FLAG once Identity Center is live (item 1's "deactivate"
    half) or once a key is past the 90-day rotation cadence regardless."""
    today = today or date.today()
    try:
        if iam_client is None:
            import boto3

            iam_client = boto3.client("iam")
        resp = iam_client.list_access_keys(UserName=user_name)
        keys = resp.get("AccessKeyMetadata", [])
    except Exception as e:  # pragma: no cover - network/creds dependent
        return "UNKNOWN", f"could not query iam:ListAccessKeys for {user_name}: {e}"

    active_keys = [k for k in keys if k.get("Status") == "Active"]
    if not active_keys:
        return "PASS", f"no Active access keys on {user_name} — already deactivated/parked"

    parts = []
    overdue = False
    for k in active_keys:
        create = k.get("CreateDate")
        if hasattr(create, "date"):
            create = create.date()
        age_days = (today - create).days if create else None
        if age_days is not None and age_days > BREAKGLASS_ROTATION_DAYS:
            overdue = True
        age_str = f"{age_days}d old" if age_days is not None else "age unknown"
        parts.append(f"{k.get('AccessKeyId', '?')} ({age_str})")
    detail_keys = "; ".join(parts)

    if identity_center_live:
        return (
            "FLAG",
            f"{user_name} has {len(active_keys)} Active key(s) [{detail_keys}] — Identity Center is live, "
            "park them: `aws iam update-access-key --user-name matthew-admin --access-key-id <id> --status Inactive`",
        )
    if overdue:
        return (
            "FLAG",
            f"{user_name} has {len(active_keys)} Active key(s) [{detail_keys}] past the "
            f"{BREAKGLASS_ROTATION_DAYS}-day rotation cadence (docs/AWS_ACCESS.md §3), independent of Identity Center status",
        )
    return "PASS", f"{user_name} has {len(active_keys)} Active key(s) [{detail_keys}] — within rotation cadence"


def check_accounts_estate_rows(text=None):
    """(status, detail) — FLAG while docs/ACCOUNTS.md still carries an
    UNDOCUMENTED estate-row marker (item 2)."""
    text = text if text is not None else ACCOUNTS_PATH.read_text(encoding="utf-8")
    open_rows = [line.strip() for line in text.splitlines() if UNDOCUMENTED_MARKER in line]
    if open_rows:
        return "FLAG", f"{len(open_rows)} estate row(s) still UNDOCUMENTED in docs/ACCOUNTS.md — owner action, personal detail"
    return "PASS", "no UNDOCUMENTED estate rows remain in docs/ACCOUNTS.md"


def check_filevault(runner=None):
    """(status, detail) — runs `fdesetup status` (macOS only, read-only)."""
    runner = runner or (lambda: subprocess.run(["fdesetup", "status"], capture_output=True, text=True, timeout=10))
    try:
        result = runner()
    except FileNotFoundError:
        return "UNKNOWN", "fdesetup not found (not macOS, or not run on the laptop in question)"
    except Exception as e:  # pragma: no cover
        return "UNKNOWN", f"could not run `fdesetup status`: {e}"
    out = (result.stdout or "").strip()
    if "FileVault is On" in out:
        return "PASS", out
    if "FileVault is Off" in out:
        return "FLAG", out
    return "UNKNOWN", out or (result.stderr or "").strip() or "unrecognized fdesetup output"


def check_domain_expiry(text=None, today=None):
    """(status, detail) — parses the domain expiry date recorded in
    docs/ACCOUNTS.md and flags when the renewal window (item 4) is close."""
    text = text if text is not None else ACCOUNTS_PATH.read_text(encoding="utf-8")
    today = today or date.today()
    m = DOMAIN_EXPIRY_RE.search(text)
    if not m:
        return "UNKNOWN", "could not find a domain expiry date in docs/ACCOUNTS.md"
    expiry = datetime.strptime(m.group(1), "%Y-%m-%d").date()
    days_left = (expiry - today).days
    if days_left < 0:
        return "FLAG", f"averagejoematt.com expiry {expiry} has PASSED ({-days_left}d ago) — verify NameCheap login + renewal NOW"
    if days_left <= DOMAIN_WARNING_DAYS:
        return (
            "FLAG",
            f"averagejoematt.com expires {expiry} — {days_left}d left, confirm NameCheap login + auto-renew works without this laptop",
        )
    return "PASS", f"averagejoematt.com expires {expiry} — {days_left}d left"


def check_repo_visibility(runner=None):
    """(status, detail) — `gh repo view --json isPrivate,visibility` (item 5)."""
    runner = runner or (
        lambda: subprocess.run(
            ["gh", "repo", "view", "averagejoematt/life-platform", "--json", "isPrivate,visibility"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    )
    try:
        result = runner()
    except FileNotFoundError:
        return "UNKNOWN", "gh CLI not found"
    except Exception as e:  # pragma: no cover
        return "UNKNOWN", f"could not query repo visibility: {e}"
    if result.returncode != 0:
        return "UNKNOWN", (result.stderr or result.stdout or "gh repo view failed").strip()
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "UNKNOWN", f"unparseable `gh repo view` output: {result.stdout!r}"
    if data.get("isPrivate"):
        return "PASS", "repo is PRIVATE"
    return (
        "FLAG",
        "repo is PUBLIC — standing rec (#1029 item 5) is to flip private; note the ~2,000 min/mo free "
        "GitHub Actions cap that applies once private (heavy CI here may mean ~$4/mo GitHub Pro)",
    )


def run_all(today=None):
    """Runs every check and returns a list of (label, status, detail). The
    break-glass check is composed with the Identity Center result so its
    recommendation reflects whether SSO is actually live."""
    results = []

    ic_status, ic_detail = check_identity_center()
    results.append(("1a. IAM Identity Center provisioned", ic_status, ic_detail))

    ic_live = True if ic_status == "PASS" else (False if ic_status == "FLAG" else None)
    bg_status, bg_detail = check_breakglass_key(today=today, identity_center_live=ic_live)
    results.append(("1b. Break-glass matthew-admin key deactivated", bg_status, bg_detail))

    for label, fn in (
        ("2. ACCOUNTS.md estate rows filled", check_accounts_estate_rows),
        ("3. FileVault enabled", check_filevault),
        ("4. Domain (registrar) renewal window", lambda: check_domain_expiry(today=today)),
        ("5. Repo flipped private", check_repo_visibility),
    ):
        try:
            status, detail = fn()
        except Exception as e:  # pragma: no cover
            status, detail = "UNKNOWN", f"check crashed: {e}"
        results.append((label, status, detail))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    results = run_all()

    if args.json:
        print(json.dumps([{"item": label, "status": status, "detail": detail} for label, status, detail in results], indent=2))
    else:
        print("Re-entry hardening status (#1029) — read-only, changes nothing\n")
        icons = {"PASS": "PASS", "FLAG": "FLAG", "UNKNOWN": "UNKNOWN"}
        for label, status, detail in results:
            print(f"[{icons[status]}] {label}")
            print(f"    {detail}\n")
        flagged = [r for r in results if r[1] == "FLAG"]
        if flagged:
            print(f"{len(flagged)} item(s) need owner attention (see docs/ACCOUNTS.md, docs/AWS_ACCESS.md, issue #1029).")
        else:
            print("No FLAGged items from what this script can see — some checks may still be UNKNOWN (no AWS/gh access here).")

    # Informational only — every remaining #1029 item is explicitly owner-gated
    # (no AI session can act on it), so this never fails CI.
    return 0


if __name__ == "__main__":
    sys.exit(main())
