"""tests/public_claims_registry.py — the public-claims registry (Phase D2, epic #3042).

WHY THIS EXISTS
---------------
The external diligence review that seeded #3042 produced 52 findings and the fact-check
graded it 4.47/10 — but the false positives were not the reviewer being careless. They
were **manufactured by this platform's own prose**. The site and the contributor docs
state behavioural claims about how the machine governs itself, and nothing anywhere
checked those sentences against the machine:

  * ``/method/build`` and the org-chart essay both describe the remediation agent's merge
    authority. The agent was demoted to ``shadow`` on 2026-07-06 (ADR-129). The essay
    still read as if the gate self-merged until someone hand-edited a parenthetical into
    it. Nothing would have caught the next demotion, or the re-promotion.
  * The org-chart essay quotes ``remediation/automerge.py``'s caps **verbatim** — "a
    60-line diff cap", "a three-merges-a-day cap". Those are two integers in a Python
    file that a PR may change without anyone opening an HTML file in ``site/journal/``.
  * ``site/privacy/index.html`` promises a reader that unsubscribing anonymizes their
    address "on the spot" and that a hard delete happens "within 7 days". #3044 changed
    the signed retention policy underneath that page nine days ago.

A stale self-description is not a cosmetic defect here. It is the platform lying about
its own controls to the exact audience — a reviewer, a subscriber, a contributor — that
came to check them. **D2's rule: self-description DERIVES, it does not drift.**

WHAT THIS FILE IS
-----------------
One registry entry per public behavioural CLAIM:

    claim id → stated-where (the real public surfaces) → derived-from (checkable
    sources) → comparator (the function that reads both and reports mismatches)

``tests/test_public_claims_registry_3042.py`` is the guard, and it sweeps **both**
directions, per the ``tests/derived_artifact_registry.py`` (#2986) template:

  (a) every registered claim's comparator passes — the prose still matches the machine;
  (b) ``discover_claim_statements()`` finds no public surface asserting a registered
      claim SUBJECT that the claim's ``stated`` globs do not already cover — a new page,
      a new generator, or a copy-pasted paragraph joins the registry or reds the build.

Direction (b) is the "guard the SET, not the instance" half, and it is not theoretical:
the remediation-mode sentence lives in ONE generator editorial and is emitted into
**31 published pages**. A registry that named one page would have been a hand-list of
one instance of a claim that exists in dozens.

FIXTURE MUST BE THE WIRE
------------------------
Every comparator reads the **shipped** surfaces — ``site/**/index.html`` as published,
``CONTRIBUTING.md`` as committed, the generator source as it renders — and the **real**
source of truth (``remediation/automerge.py``, ``deploy/github_posture.json``,
``lambdas/content/subscriber_retention.py``, the workflow files). No comparator reads a
copy of a claim, and none reads a fixture that restates one. A comparator that compared
two copies of the prose would pass forever and check nothing.

RUNTIME STATE WITHOUT REQUIRING AWS IN CI
-----------------------------------------
One claim's truth is **live runtime state**: the remediation agent's mode is an SSM
parameter, not a repo fact. ``scripts/v4_build_permanence_terms.py`` set the precedent
for exactly this — it bakes the edition it was *built from* into the page as a data
attribute and lets a live reconciliation speak up if the two diverge, rather than
pretending a build-time read is a runtime read.

Same shape here. ``RECORDED_RUNTIME`` carries the operator-signed value with the date
and the decision that set it. The comparator runs **offline, always**, against that
recorded value plus the code paths that make it enforceable. A separate, explicitly
opt-in reconciliation (``CLAIMS_LIVE_RECONCILE=1``) reads live SSM and asserts the
recorded value is still true — and SKIPS **loudly** when it cannot, because a silent
pass is a check that never ran.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── The public surfaces this registry is responsible for ─────────────────────
#
# "Public" means a surface a reader, subscriber or contributor is invited to trust:
# the published site, the contributor entry point, and the generators that render
# them. Deliberately NOT `docs/**` — the engineering wiki is an internal surface with
# its own drift gates (`deploy/sync_doc_metadata.py`, `scripts/check_doc_facts.py`),
# and folding it in here would merge two contracts that fail differently.
SCAN_ROOTS = ("site", "scripts", "CONTRIBUTING.md", "README.md")
SCAN_SUFFIXES = (".html", ".md", ".py")

# Trees inside a scan root that are deliberately out of scope, each with its reason.
# A blanket "skip anything awkward" list is how a discovery sweep becomes decorative.
EXCLUDED_TREES = {
    # The frozen v3 site, preserved verbatim for rollback and never linked from the UI
    # (ADR-071). Its sentences describe the platform as it was; editing them to match
    # today would destroy the archive, which is the only thing it is for.
    "site/legacy": "frozen v3 archive, never linked from the UI — a historical record, not a live claim",
    # Dated build dispatches are a published record of what was true on their date.
    # A dispatch is not a standing self-description and must not be rewritten.
    "site/story/build": "dated build-beat dispatches — a record of what was true then, not a standing claim",
}


def _word_to_int(word: str) -> int | None:
    return {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }.get(word.strip().lower())


def _read(path: str | Path) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def _module_constants(rel_path: str) -> dict[str, object]:
    """Module-level literal assignments from `rel_path`, by AST.

    AST, never import: `remediation/automerge.py` constructs boto3 clients at module
    scope, so importing it in CI would need a region and credentials — and a comparator
    that needs AWS to read a Python constant is a comparator that will be skipped.
    """
    tree = ast.parse(_read(rel_path))
    out: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            out[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            continue
    return out


def _default_of_param_call(rel_path: str, func: str, first_arg: str) -> object | None:
    """The literal 2nd argument of `func(<first_arg>, <literal>)` in `rel_path`.

    This is how the shipped fallback is read rather than assumed: `automerge.py` calls
    `_param(MODE_PARAM, "shadow")`, so an unreadable SSM leaves the gate in the safe
    mode. That fallback is part of the claim and must be checked, not trusted.
    """
    for node in ast.walk(ast.parse(_read(rel_path))):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != func:
            continue
        if len(node.args) != 2:
            continue
        head = node.args[0]
        if isinstance(head, ast.Name) and head.id == first_arg:
            try:
                return ast.literal_eval(node.args[1])
            except (ValueError, TypeError, SyntaxError):
                return None
    return None


# ── Recorded runtime state (the permanence-terms pattern) ────────────────────
#
# The value an operator signed, when, and the decision that set it. This is the
# "built-from edition" of `v4_build_permanence_terms.py`: honest about being a
# recording, reconciled against live state when live state is reachable.
RECORDED_RUNTIME = {
    "remediation_mode": {
        "param": "/life-platform/remediation-mode",
        "value": "shadow",
        "recorded": "2026-08-23",
        "source": (
            "ADR-129 (demoted 2026-07-06 on zero merged safe-class PRs in ~6 weeks). Re-promotion to "
            "`auto` requires the numeric 10-consecutive-clean-run bar in the 2026-07-20 amendment (#1337) "
            "plus an explicit operator SSM flip — never automatic, so a recorded value has a real shelf life."
        ),
    },
}


def recorded_runtime(key: str) -> str:
    return str(RECORDED_RUNTIME[key]["value"])


# ── Comparators ──────────────────────────────────────────────────────────────
#
# Every comparator returns a list of mismatch strings; empty means the prose and the
# machine still agree. Returning findings rather than asserting keeps them callable
# from a mutation proof, which is the only way to know a comparator can fail at all.


def compare_remediation_mode(runtime_mode: str | None = None) -> list[str]:
    """CLAIM: the merge gate runs in shadow — every fix, safe class included, lands as a
    pull request a human merges.

    READS   the recorded SSM value for `/life-platform/remediation-mode` (injectable, so
            a live or mutated value can be passed straight in) + `remediation/automerge.py`.
    COMPARES the mode against the gate's own precondition: `automerge.py` no-ops unless
            mode == "auto", so "a human merges" is true exactly while mode != "auto".
            Also checks the shipped SSM-unreadable fallback still lands on the same side.
    """
    mode = runtime_mode if runtime_mode is not None else recorded_runtime("remediation_mode")
    consts = _module_constants("remediation/automerge.py")
    src = _read("remediation/automerge.py")
    findings: list[str] = []

    if consts.get("MODE_PARAM") != RECORDED_RUNTIME["remediation_mode"]["param"]:
        findings.append(
            f"automerge.py reads mode from {consts.get('MODE_PARAM')!r}, but the registry records "
            f"{RECORDED_RUNTIME['remediation_mode']['param']!r} — the recorded value describes a different parameter"
        )

    # The gate's own precondition, read from source rather than restated here.
    if not re.search(r"if\s+mode\s*!=\s*\"auto\"", src):
        findings.append(
            'automerge.py no longer carries the `if mode != "auto"` no-op guard — the published claim '
            "'a human merges' is derived from that guard, so it can no longer be derived at all"
        )

    if mode == "auto":
        findings.append(
            f"remediation mode is {mode!r}: the gate CAN self-merge, but /method/build and the org-chart essay "
            "both tell readers every fix lands as a pull request a human merges. Prose and machine disagree."
        )

    fallback = _default_of_param_call("remediation/automerge.py", "_param", "MODE_PARAM")
    if fallback == "auto":
        findings.append(
            f"automerge.py falls back to {fallback!r} when SSM is unreadable — an SSM outage would silently "
            "grant self-merge, contradicting the published claim without any parameter ever being flipped"
        )
    return findings


def compare_deploy_lanes() -> list[str]:
    """CLAIM: engine deploys require a human approval; the static site ships itself on merge.

    READS   `deploy/github_posture.json` (the documented GitHub control posture),
            `.github/workflows/ci-cd.yml`, and `.github/workflows/site-deploy.yml`.
    COMPARES the two-lane assertion against three facts: production requires reviewers,
            the engine deploy job is bound to `environment: production`, and the site
            workflow triggers on a push to main touching `site/**` with NO environment
            binding at all (which is what "ships itself" means, mechanically).
    """
    findings: list[str] = []

    posture = json.loads(_read("deploy/github_posture.json"))
    env = posture.get("environment_production", {})
    if env.get("name") != "production" or env.get("required_reviewers") is not True:
        findings.append(
            f"deploy/github_posture.json's environment_production is {env.get('name')!r} / "
            f"required_reviewers={env.get('required_reviewers')!r} — the published claim that engine deploys "
            "need a human click derives from a reviewer-protected production environment"
        )

    ci = _read(".github/workflows/ci-cd.yml")
    if not re.search(r"^\s*environment:\s*production\b", ci, re.M):
        findings.append(
            ".github/workflows/ci-cd.yml has no job bound to `environment: production` — the engine lane's "
            "approval gate is the mechanism behind 'the approval button is mine'"
        )

    site = _read(".github/workflows/site-deploy.yml")
    site_yaml = _strip_yaml_comments(site)
    if re.search(r"^\s*environment:", site_yaml, re.M):
        findings.append(
            ".github/workflows/site-deploy.yml now binds a deployment `environment:` — the published claim that "
            "a merged site change 'ships itself' says the site lane is NOT gated. One of the two must change."
        )
    if not re.search(r"^\s*-\s*'site/\*\*'|^\s*-\s*\"site/\*\*\"", site_yaml, re.M):
        findings.append(
            ".github/workflows/site-deploy.yml no longer filters on `site/**` — the claim that merging a site "
            "change ships it is derived from that path filter"
        )
    if not re.search(r"^\s*branches:\s*\[\s*main\s*\]", site_yaml, re.M):
        findings.append(".github/workflows/site-deploy.yml no longer triggers on pushes to main — 'auto-deploys on merge' is not derivable")
    return findings


def _strip_yaml_comments(text: str) -> str:
    """Drop whole-line `#` comments. site-deploy.yml's header comment *describes*
    ci-cd.yml's `environment: production` gate; matching that prose would let the
    comparator conclude the site lane is gated when only the commentary mentions it."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def compare_deletion_promise() -> list[str]:
    """CLAIM (site/privacy/index.html): unsubscribing anonymizes the address "on the spot";
    on request the whole record is "hard-deleted within 7 days".

    READS   `lambdas/content/subscriber_retention.py` (the signed window + mode, by AST),
            `lambdas/operational/delete_user_data_lambda.py` (the on-request path), and
            `cdk/stacks/operational_stack.py` (the backstop sweep's cron).
    COMPARES the numeral the reader is shown against the sweep's real worst-case cadence
            in days, and the "on the spot" wording against window==0 / mode=="anonymize".
    """
    findings: list[str] = []
    page = _read("site/privacy/index.html")
    consts = _module_constants("lambdas/content/subscriber_retention.py")

    window = consts.get("RETENTION_WINDOW_DAYS")
    mode = consts.get("RETENTION_MODE")

    if "anonymized on the spot" in page:
        if window != 0:
            findings.append(
                f"site/privacy/index.html promises anonymization 'on the spot', but the signed "
                f"RETENTION_WINDOW_DAYS is {window!r} — a non-zero window means the address survives the click"
            )
        if mode != "anonymize":
            findings.append(
                f"site/privacy/index.html describes anonymization (address overwritten, hash kept), but the signed "
                f"RETENTION_MODE is {mode!r} — the page describes a mechanism the platform no longer runs"
            )

    stated = re.search(r"hard-deleted within (\d+) days", page)
    if not stated:
        findings.append("site/privacy/index.html no longer states a hard-delete SLA — the promise the comparator derives has gone missing")
    else:
        promised_days = int(stated.group(1))
        cadence = _sweep_cadence_days()
        if cadence is None:
            findings.append(
                "cdk/stacks/operational_stack.py's subscriber_retention_sweep rule has no readable cron — the "
                f"page promises {promised_days} days against a backstop nobody can measure"
            )
        elif promised_days < cadence:
            findings.append(
                f"site/privacy/index.html promises a hard delete within {promised_days} days, but the backstop sweep "
                f"runs every {cadence} days — the promise is faster than the mechanism that keeps it"
            )

    delete_src = _read("lambdas/operational/delete_user_data_lambda.py")
    if 'event.get("subscriber_email")' not in delete_src:
        findings.append(
            "lambdas/operational/delete_user_data_lambda.py no longer exposes the `subscriber_email` event path — "
            "the on-request hard delete the privacy page offers has no enactment path"
        )
    return findings


def _sweep_cadence_days() -> int | None:
    """The subscriber-retention backstop sweep's cadence, in days, from the CDK rule.

    Weekly (`cron(... ? * MON *)`) is 7. Read from the stack rather than hard-coded:
    the whole point is that a cron change must move the reader-facing SLA with it.
    """
    stack = _read("cdk/stacks/operational_stack.py")
    idx = stack.find("subscriber_retention_sweep")
    if idx < 0:
        return None
    window = stack[max(0, idx - 1500) : idx]
    crons = re.findall(r"cron\(([^)]*)\)", window)
    if not crons:
        return None
    fields = crons[-1].split()
    if len(fields) < 5:
        return None
    day_of_week = fields[4]
    if day_of_week not in ("?", "*"):
        return 7  # a named weekday => once a week
    day_of_month = fields[2]
    return 1 if day_of_month in ("*", "?") else None


def compare_automerge_caps() -> list[str]:
    """CLAIM (org-chart essay, quoting the gate verbatim): an exact-file allowlist, a
    denylist of substrings covering auth/secrets/budget/deploy/the gate itself, a
    60-line diff cap, a lint-and-test run, and a three-merges-a-day cap.

    READS   `remediation/automerge.py`'s MAX_LINES / MAX_PER_DAY / ALLOWLIST /
            DENYLIST_SUBSTR by AST + the essay body as published.
    COMPARES the numerals the essay quotes against the constants, and each denylist
            CATEGORY the essay names against a real DENYLIST_SUBSTR entry.
    """
    findings: list[str] = []
    consts = _module_constants("remediation/automerge.py")
    essay = _read("site/journal/essays/org-chart-of-one/body.html")

    line_cap = re.search(r"a (\d+)-line diff cap", essay)
    if not line_cap:
        findings.append(
            "the org-chart essay no longer quotes a '<N>-line diff cap' — the quoted cap the comparator derives has gone missing"
        )
    elif int(line_cap.group(1)) != consts.get("MAX_LINES"):
        findings.append(
            f"the org-chart essay tells readers the gate caps diffs at {line_cap.group(1)} lines, but "
            f"remediation/automerge.py's MAX_LINES is {consts.get('MAX_LINES')!r}"
        )

    per_day = re.search(r"a ([a-z]+)-merges-a-day cap", essay)
    if not per_day:
        findings.append(
            "the org-chart essay no longer quotes a '<n>-merges-a-day cap' — the quoted cap the comparator derives has gone missing"
        )
    else:
        spelled = _word_to_int(per_day.group(1))
        if spelled is None:
            findings.append(
                f"the org-chart essay's merges-a-day cap reads {per_day.group(1)!r}, which is not a number this comparator can resolve"
            )
        elif spelled != consts.get("MAX_PER_DAY"):
            findings.append(
                f"the org-chart essay tells readers the gate merges at most {spelled} PRs a day, but "
                f"remediation/automerge.py's MAX_PER_DAY is {consts.get('MAX_PER_DAY')!r}"
            )

    allowlist = consts.get("ALLOWLIST")
    if "exact-file allowlist" in essay and not (isinstance(allowlist, tuple) and allowlist):
        findings.append(f"the essay describes an 'exact-file allowlist', but automerge.py's ALLOWLIST is {allowlist!r}")

    # The essay names the denylist by CATEGORY, so the comparator checks categories.
    # A category with no matching substring entry is a promise with nothing behind it.
    denylist = consts.get("DENYLIST_SUBSTR") or ()
    if "a denylist of substrings" in essay:
        for category, needles in (
            ("auth", ("auth",)),
            ("secrets", ("secret", "credential")),
            ("budget", ("budget_guard", "budget")),
            ("deploy", ("deploy/",)),
            ("the gate itself", ("remediation/",)),
        ):
            if not any(any(n in entry for n in needles) for entry in denylist):
                findings.append(
                    f"the org-chart essay tells readers the denylist covers {category!r}, but no DENYLIST_SUBSTR "
                    f"entry in remediation/automerge.py matches it. Entries: {list(denylist)}"
                )
    return findings


# ── The registry ─────────────────────────────────────────────────────────────
#
# `stated` globs are the SET of public surfaces permitted to assert this claim.
# `phrases` are the assertions themselves — the regexes discovery sweeps for. They are
# deliberately whole-assertion, not keywords: "shadow" appears in unrelated prose, but
# "runs in shadow mode" is the claim. A keyword sweep produces noise and then gets
# narrowed until it finds nothing, which is how a set guard dies.

CLAIMS: dict[str, dict] = {
    "remediation_agent_mode": {
        "subject": "the remediation agent's merge authority (shadow; opens PRs, does not self-merge)",
        "stated": (
            "scripts/v4_build_evidence.py",
            "site/method/index.html",
            "site/method/*/index.html",
            "site/journal/essays/org-chart-of-one/body.html",
            "site/journal/essays/org-chart-of-one/index.html",
        ),
        "phrases": (
            r"runs in shadow mode",
            r"lands as a pull request a human merges",
            r"demoted to shadow mode",
        ),
        "derived_from": (
            "SSM /life-platform/remediation-mode (recorded; reconciled live when reachable)",
            "remediation/automerge.py",
        ),
        "comparator": "compare_remediation_mode",
        "runtime": True,
        "reason": (
            "The one claim here whose truth is live state rather than repo state, and the one that already went "
            "stale once: ADR-129 demoted the agent on 2026-07-06 and the essay was corrected by hand afterwards. "
            "Re-promotion to `auto` is an operator SSM flip with no repo diff at all, so nothing but a recorded "
            "value plus a live reconciliation can catch the prose going wrong in that direction."
        ),
    },
    "deploy_approval_lanes": {
        "subject": "the two deploy lanes — engine gated on a human approval, site auto-deploys on merge",
        "stated": (
            "scripts/v4_build_evidence.py",
            "site/method/index.html",
            "site/method/*/index.html",
            "site/journal/essays/org-chart-of-one/body.html",
            "site/journal/essays/org-chart-of-one/index.html",
            "CONTRIBUTING.md",
        ),
        "phrases": (
            r"require a human click on a production approval",
            r"production deploy approval is never bypassed",
            r"a merged site change ships itself",
            r"`site/\*\*` auto-deploys on merge",
            r"deploy \(production-approval\)",
        ),
        "derived_from": (
            "deploy/github_posture.json",
            ".github/workflows/ci-cd.yml",
            ".github/workflows/site-deploy.yml",
        ),
        "comparator": "compare_deploy_lanes",
        "runtime": False,
        "reason": (
            "This is the claim the platform stakes its accountability argument on — 'the approval button is mine' — "
            "and it is the one a GitHub-side change can falsify with no code diff whatsoever. It has ALREADY "
            "silently broken once: the 2026-07-13 private-repo flip dropped the production environment's required "
            "reviewers entirely (#1319), which nobody noticed until the drift sentinel was pointed at it."
        ),
    },
    "subscriber_deletion_promise": {
        "subject": "the subscriber deletion/anonymization promise (on-the-spot anonymize, hard delete within 7 days)",
        "stated": ("site/privacy/index.html",),
        "phrases": (
            r"anonymized on the spot",
            r"hard-deleted within \d+ days",
        ),
        "derived_from": (
            "lambdas/content/subscriber_retention.py (RETENTION_WINDOW_DAYS, RETENTION_MODE)",
            "lambdas/operational/delete_user_data_lambda.py (the subscriber_email path)",
            "cdk/stacks/operational_stack.py (the backstop sweep cron)",
        ),
        "comparator": "compare_deletion_promise",
        "runtime": False,
        "reason": (
            "The only claim on this list made TO a third party about their own personal data, which makes a stale "
            "sentence a broken promise rather than a documentation defect. The section is hand-authored and sits "
            "OUTSIDE the generated permanence-terms markers on the same page, so #1400's generator gives it no "
            "cover — and #3044 rewrote the signed policy underneath it on 2026-08-23."
        ),
    },
    "automerge_caps": {
        "subject": "the auto-merge gate's caps — exact-file allowlist, substring denylist, 60-line diff, 3/day",
        "stated": (
            "site/journal/essays/org-chart-of-one/body.html",
            "site/journal/essays/org-chart-of-one/index.html",
        ),
        "phrases": (
            r"a \d+-line diff cap",
            r"a [a-z]+-merges-a-day cap",
            r"an exact-file allowlist",
        ),
        "derived_from": ("remediation/automerge.py (MAX_LINES, MAX_PER_DAY, ALLOWLIST, DENYLIST_SUBSTR)",),
        "comparator": "compare_automerge_caps",
        "runtime": False,
        "reason": (
            "The essay quotes two integers out of a Python file verbatim, in prose, in a different tree. Retuning a "
            "cap is a one-character diff in remediation/automerge.py that no reviewer would connect to an essay in "
            "site/journal/, and #2611 is the proof the gate's contents really do move: the IAM family was removed "
            "from the ALLOWLIST on 2026-08-13 while the essay's description of the gate stayed put."
        ),
    },
}


# ── Discovery: the SET direction ─────────────────────────────────────────────


def _scan_files(root: Path | None = None) -> list[Path]:
    base = root if root is not None else REPO
    files: list[Path] = []
    for entry in SCAN_ROOTS:
        target = base / entry
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(p for p in target.rglob("*") if p.is_file() and p.suffix in SCAN_SUFFIXES)
    out = []
    for path in sorted(files):
        rel = path.relative_to(base).as_posix()
        if any(rel == tree or rel.startswith(tree + "/") for tree in EXCLUDED_TREES):
            continue
        out.append(path)
    return out


def discover_claim_statements(root: Path | None = None) -> dict[str, set[str]]:
    """Sweep the public surfaces and return `relative path -> {claim ids it asserts}`.

    `root` is overridable so the sweep can be run against a synthetic tree in a mutation
    proof rather than only ever against the real one — the #2372 derivation's own
    lesson, and the only way to demonstrate this direction can actually fail.
    """
    base = root if root is not None else REPO
    compiled = {cid: [re.compile(p) for p in entry["phrases"]] for cid, entry in CLAIMS.items()}
    found: dict[str, set[str]] = {}
    for path in _scan_files(base):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(base).as_posix()
        for cid, patterns in compiled.items():
            if any(p.search(text) for p in patterns):
                found.setdefault(rel, set()).add(cid)
    return found


def is_registered_surface(claim_id: str, rel_path: str) -> bool:
    """True if `rel_path` is covered by `claim_id`'s declared `stated` globs."""
    return any(fnmatch.fnmatchcase(rel_path, pattern) for pattern in CLAIMS[claim_id]["stated"])


def unregistered_statements(root: Path | None = None) -> dict[str, set[str]]:
    """The (b) direction: surfaces asserting a registered claim that the claim's own
    `stated` globs do not cover. Non-empty means a claim escaped its registry entry."""
    out: dict[str, set[str]] = {}
    for rel, claim_ids in discover_claim_statements(root).items():
        loose = {cid for cid in claim_ids if not is_registered_surface(cid, rel)}
        if loose:
            out[rel] = loose
    return out


def comparator_for(claim_id: str):
    return globals()[CLAIMS[claim_id]["comparator"]]


def live_reconcile_enabled() -> bool:
    """Live SSM reconciliation is opt-in and never a CI requirement (the permanence-terms
    pattern). Offline, the guard SKIPS loudly rather than passing quietly."""
    return os.environ.get("CLAIMS_LIVE_RECONCILE") == "1"
