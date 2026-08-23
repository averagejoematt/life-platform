"""scripts/doc_facts_governance.py — the DATA_GOVERNANCE.md fact gate (#1351/#3043).

Extracted from check_doc_facts.py 2026-08-23 when the D0.5 site-surface scan pushed
that module past the #1665 1200-line ceiling — the gate itself is unchanged; every
public name is re-exported by check_doc_facts.py so the CLI surface, main()'s
DG_SKIP_NOTICES printing, and the importlib-based tests keep their single entrypoint.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── #1351/#3043: DATA_GOVERNANCE.md fact gate (repo visibility, deletion-lambda
# status, Verified-header freshness) ──────────────────────────────────────────
# The compliance-answer doc misstated a load-bearing privacy control in BOTH
# directions at once: it claimed the repo was "still PUBLIC" three days after it
# actually flipped PRIVATE (2026-07-13, understating a real fix as an open exposure),
# and claimed delete_user_data_lambda was merely "scaffolded; not yet wired" after it
# had been implemented, CDK-deployed with an error alarm, and unit-tested. Neither
# direction had a gate. This adds one, plus a Verified-header staleness ceiling (the
# existing per-doc freshness ceiling machinery is check_doc_index.py's canonical-doc
# sweep — this is DATA_GOVERNANCE-specific per the #1351 acceptance criterion).
#
# #3043 (DIL-001): the original repo-visibility check HARDCODED "truth is PRIVATE" —
# which inverted the moment the repo deliberately flipped public (2026-07-20): for 34
# days the gate would have redded the honest correction while blessing the stale
# "PRIVATE" claim. The truth is now read LIVE from the GitHub API (gh). When live
# visibility cannot be determined (offline / no gh / no token), every visibility
# claim is reported as an explicit SKIP via DG_SKIP_NOTICES — printed loudly by
# main(), never a silent pass (INDEX_review_discipline: a gate that cannot fail is
# not a gate; the can-it-fail proof lives in tests/test_wiki_checkers.py).
#
# PRECISION: HISTORICAL-framed lines are exempt as everywhere else, so a corrected doc
# is free to narrate "was PUBLIC until 2026-07-13" without re-tripping the gate.
DATA_GOVERNANCE_PATH = ROOT / "docs" / "DATA_GOVERNANCE.md"
DATA_GOVERNANCE_VERIFIED_MAX_AGE_DAYS = 90
# A present-tense claim about the repo's visibility: "the repo is PUBLIC",
# "the repository has been PRIVATE since ...", "the repo stays public", etc.
REPO_VISIBILITY_CLAIM = re.compile(
    r"\brepo(?:sitory)?\b[^\n]{0,60}?\b(?:is|has\s+been|stays|remains)\s+(?:still\s+)?(?:deliberately\s+)?(PUBLIC|PRIVATE)\b",
    re.I,
)
DELETE_LAMBDA_STALE_CLAIM = re.compile(r"scaffolded;?\s*not\s+yet\s+wired", re.I)

# Explicit-skip channel for the live-visibility check (#3043). _data_governance_hits
# (the only writer) clears it at entry; main() prints anything left in it so an
# unverifiable claim is a loud SKIP in the gate's own output, never a silent pass.
DG_SKIP_NOTICES: list[str] = []

_REPO_VIS_UNSET = object()  # sentinel: "resolve live" (tests inject True/False/None)


def _live_repo_private():
    """LIVE repo visibility via the GitHub API: True=private, False=public,
    None=undeterminable (offline / gh missing / no token). #3043 — the truth is
    the API, never a hardcoded constant."""
    import subprocess

    try:
        proc = subprocess.run(
            ["gh", "api", "repos/{owner}/{repo}", "--jq", ".private"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ROOT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    val = proc.stdout.strip().lower()
    if proc.returncode == 0 and val in ("true", "false"):
        return val == "true"
    return None


VERIFIED_HEADER_RE = re.compile(r"\*\*Verified:\*\*\s*(\d{4}-\d{2}-\d{2})")
# Deliberately NARROWER than the shared HISTORICAL regex: the shared one treats any
# "as of <date>" as historical framing (right for a dated cost/count snapshot like
# "$75 as of 2026-05"), but the EXACT pre-fix #1351 defect line was itself framed
# "As of 2026-07-10 the repo is still PUBLIC..." — a genuine current-state claim, not
# history, just dated. Reusing the shared regex here would silently exempt that exact
# defect (proven by the vacuous-scan test below), so these two checks use true
# past-tense/superseded language only.
_DG_HISTORICAL = re.compile(r"\bwas\b|\bwere\b|formerly|previously|used to|no longer|retired|superseded|\bold\b", re.I)


def _data_governance_hits(doc_path: Path, today=None, repo_private=_REPO_VIS_UNSET) -> list[str]:
    """DATA_GOVERNANCE.md-specific fact checks (#1351/#3043). `today` is injectable
    (a `datetime.date`) so the regression test never depends on wall-clock — the
    live gate (called with today=None from main()) uses the real date.
    `repo_private` is likewise injectable (True/False/None) so the regression test
    never depends on the network; the live gate resolves it via _live_repo_private().
    None means "could not determine" and downgrades visibility claims to explicit
    SKIP notices in DG_SKIP_NOTICES — never a silent pass."""
    import datetime as _dt

    DG_SKIP_NOTICES.clear()
    if not doc_path.exists():
        return []
    today = today or _dt.date.today()
    if repo_private is _REPO_VIS_UNSET:
        repo_private = _live_repo_private()
    text = doc_path.read_text(encoding="utf-8")
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if _DG_HISTORICAL.search(line):
            continue
        for mo in REPO_VISIBILITY_CLAIM.finditer(line):
            claimed_private = mo.group(1).upper() == "PRIVATE"
            if repo_private is None:
                DG_SKIP_NOTICES.append(
                    f"docs/DATA_GOVERNANCE.md:{lineno}: SKIP — claims the repo is "
                    f"{mo.group(1).upper()}, but live visibility could not be verified "
                    f"(gh unavailable / offline / no token) (#3043)\n      | {line.strip()[:120]}"
                )
            elif claimed_private != repo_private:
                truth = "PRIVATE" if repo_private else "PUBLIC"
                hits.append(
                    f"docs/DATA_GOVERNANCE.md:{lineno}: claims the repo is {mo.group(1).upper()} — live "
                    f"GitHub visibility is {truth} (gh api repos/{{owner}}/{{repo}} .private) (#3043)\n"
                    f"      | {line.strip()[:120]}"
                )
        if DELETE_LAMBDA_STALE_CLAIM.search(line):
            hits.append(
                f"docs/DATA_GOVERNANCE.md:{lineno}: claims delete_user_data_lambda is 'scaffolded; not yet "
                f"wired' — it is implemented, CDK-deployed (life-platform-delete-user-data, operational_stack.py) "
                f"with an error alarm, and unit-tested (tests/test_delete_user_data.py) (#1351)\n      | {line.strip()[:120]}"
            )
    mo = VERIFIED_HEADER_RE.search(text)
    if not mo:
        hits.append("docs/DATA_GOVERNANCE.md: no '**Verified:** YYYY-MM-DD' header found (#1351)")
    else:
        try:
            verified = _dt.date.fromisoformat(mo.group(1))
        except ValueError:
            hits.append(f"docs/DATA_GOVERNANCE.md: Verified header {mo.group(1)!r} is not a valid date (#1351)")
        else:
            age_days = (today - verified).days
            if age_days > DATA_GOVERNANCE_VERIFIED_MAX_AGE_DAYS:
                hits.append(
                    f"docs/DATA_GOVERNANCE.md: Verified header is {age_days}d stale ({mo.group(1)}, today {today}) — "
                    f"re-verify within {DATA_GOVERNANCE_VERIFIED_MAX_AGE_DAYS}d (#1351)"
                )
    return hits
