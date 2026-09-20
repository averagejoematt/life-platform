#!/usr/bin/env python3
"""deploy/doc_drift_verdict.py — `sync_doc_metadata --check`'s verdict, partitioned by OWNER (#3646).

THE PROBLEM. Since #3533 keyed the push-to-main concurrency group on the commit sha,
a merge commit's Docs CI run is no longer cancelled mid-flight by the reconcile bot's
follow-up push — so every merge to main concluded an honest `failure` on the doc-sync
literals for the ~60 s until `chore(reconcile): regenerate derived artifacts after merge
[skip-reconcile]` landed with the regenerated values. Three specimens 2026-09-06
(6fedae2dd, 1efec2f99, d20a0e959): `Docs CI :: Wiki drift gates :: Literal-drift gate
(sync_doc_metadata --check)` red on each merge commit, green on each reconcile commit.
The failure was the bot's own FUTURE commit, not a defect — but every green-reader
(the badge, `check_main_green.py`, the #3530 cancelled-rollup reader) saw a real red.

THE PARTITION, and why it is NOT "is the rule in RULES".
A `!` record ("rule pattern matched NOTHING") is produced BY a rule in `RULES` and is
still un-fixable by the bot: `--apply` rewrites nothing for it, so classifying it as
bot-owned would mint a gate that can never red while the doc stays broken forever
(the #3851 shape). The load-bearing property is therefore not membership in `RULES`
but **would `--apply` — the exact command the reconcile job runs — rewrite this record
in this same tree?**

  bot-owned    a `  ~ ` record: the regenerated rewrite `--apply` performs. The bot's
               next commit carries it, so the merge commit is PENDING, not wrong.
  human-owned  anything else `--check` counts as drift: `  ! ` (pattern matched
               nothing / markers missing / discovery returned None), a `SKIP (not
               found)` for a doc a rule names. `--apply` leaves every one of them, so
               the bot's commit would NOT clear them and a red is the honest verdict.

FAIL-CLOSED. `human = total - bot`, computed from the caller's OWN drift accounting, so
a drift source added to `--check` later is human-owned until someone proves otherwise.
`  i ` INFO lines (the #3384 pull_request exemption) are excluded from `total` upstream
and so are invisible here — they are not drift in either direction.

WHY AN EXIT CODE, NOT A STDOUT MARKER. A caller classifies on `$?`. `--check` prints the
drifted literals themselves — doc text, verbatim — so any `grep` over its stdout is a
text matcher reading content it does not own, which is how a guard ends up reading the
comment that explains it (2026-09-16, four times in one night). `3` cannot be forged by
a doc that happens to contain the word. The `VERDICT: <name>` line is printed for humans
and for an annotation reader; it is never the classifier.

WHY THE EVENT BRANCH IS HERE AND NOT IN THE WORKFLOW STEP. The tolerance is event-scoped
— a reconcile commit follows a push to main, and nothing follows a branch, so a
pull_request must still red and the author still runs `--apply`. The obvious home for
that branch is a `run: |` block in `docs-ci.yml`, and it is the wrong one:
`deploy/restart_verify_gates.py` DERIVES the doc-gate list by parsing single-line
`run: python3 …` steps out of that workflow (#3477/#3534), and both `restart_pipeline`
and `scripts/wrap_gates.py` consume the derivation. A block scalar is invisible to that
parser, so moving the logic into shell would silently DELETE the literal gate from the
reset's and the wrap battery's gate lists — the "derived silently as nothing" rot those
two issues exist to stop. So the step stays one line and the event is read here, from
`GITHUB_EVENT_NAME`/`GITHUB_REF`, exactly as `deploy/doc_platform_counts.py` already
reads them for its own PR exemption (#3384).

`3` is still what a non-push caller gets: a laptop, a PR run, `wrap_gates`, the reset
sweep all see a distinct non-zero code and red. Only a push to `refs/heads/main` — the
one context where the reconcile job is literally the next thing to run — converts it to
a `::warning::` and exit 0.
"""

import os
import subprocess
import sys

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
# 3, not 2: `--check --apply` already exits 2 (mutually-exclusive flags), and a usage
# error must never be read as "the bot will fix it".
EXIT_PENDING_RECONCILE = 3

# The change-record prefix `sync_doc_metadata`/`doc_platform_counts`/`doc_alarm_inventory`
# emit for a rewrite `--apply` performs. `  ! ` and `  SKIP ` are the un-appliable ones.
BOT_REWRITE_PREFIX = "  ~"

VERDICT_SUCCESS = "success"
VERDICT_FAILURE = "failure"
VERDICT_PENDING_RECONCILE = "pending-reconcile"

_EXIT_FOR = {
    VERDICT_SUCCESS: EXIT_SUCCESS,
    VERDICT_FAILURE: EXIT_FAILURE,
    VERDICT_PENDING_RECONCILE: EXIT_PENDING_RECONCILE,
}


def reconcile_bot_follows_this_run():
    """True only on a push to `main` inside GitHub Actions — the one context where the
    `reconcile` job (ci-cd.yml Job 0, `push` + `branches: [main]`) is the next thing to
    run and will commit the regenerated literals. Deliberately narrow: a branch push, a
    pull_request, a workflow_dispatch and a laptop all get the strict verdict."""
    return os.environ.get("GITHUB_EVENT_NAME") == "push" and os.environ.get("GITHUB_REF") == "refs/heads/main"


def _checked_out_ref_is_main():
    """True when the tree under test IS `main` (#3984). Inside GitHub Actions `GITHUB_REF`
    is authoritative (`refs/pull/N/merge` and `refs/heads/<branch>` are both off-main);
    on a laptop it is the checked-out branch name. A detached HEAD is off-main. If git
    cannot answer, the answer is MAIN — fail-closed to the strict verdict."""
    ref = os.environ.get("GITHUB_REF")
    if ref:
        return ref == "refs/heads/main"
    try:
        out = subprocess.run(  # nosec B603 B607 — fixed argv
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if out.returncode != 0:
        return True
    return out.stdout.strip() == "main"


def bot_owns_pending_drift_here():
    """True wherever `~` (bot-owned) drift is NOT this checkout's to fix (#3984):
    on a push to main the reconcile job commits it next; OFF main the only writer of
    those files is that same job, later, on main — a branch that regenerated them would
    be carrying files it may not carry (#3101). The strict `pending-reconcile` exit
    survives in exactly one place: `main` with no bot following (a laptop on main, a
    `workflow_dispatch` on main), where a human has to run `--apply` and commit."""
    return reconcile_bot_follows_this_run() or not _checked_out_ref_is_main()


def bot_owned(records):
    """The subset of `records` that `--apply` would itself rewrite."""
    return [c for c in records if c.startswith(BOT_REWRITE_PREFIX)]


def classify(total_drift, bot_drift):
    """`(verdict, human_drift)` — fail-closed: anything not proven bot-owned is human."""
    human_drift = max(total_drift - bot_drift, 0)
    if total_drift == 0:
        return VERDICT_SUCCESS, 0
    if human_drift == 0:
        return VERDICT_PENDING_RECONCILE, 0
    return VERDICT_FAILURE, human_drift


def report(total_drift, bot_drift, drifted_docs, out=None):
    """Print the verdict block and return the exit code the caller should exit with."""
    out = out or sys.stdout
    verdict, human_drift = classify(total_drift, bot_drift)
    if verdict == VERDICT_SUCCESS:
        print("  ✅ CHECK PASSED — every literal above matches its discovered value.", file=out)
    elif verdict == VERDICT_PENDING_RECONCILE:
        print(f"  ⏳ PENDING RECONCILE — {total_drift} stale literal(s) across {len(drifted_docs)} file(s),", file=out)
        print("     every one of them a value `--apply` regenerates. On a push to main the reconcile", file=out)
        print("     job rewrites and commits these within ~60 s (#3646); this is not a red main.", file=out)
        for d in drifted_docs:
            print(f"       - {d}", file=out)
        print("  Fix (on main, where no bot follows): python3 deploy/sync_doc_metadata.py --apply", file=out)
        if reconcile_bot_follows_this_run():
            print(
                "::warning title=pending-reconcile::Doc-sync literals are stale and every one of them "
                "is a value the reconcile bot's next commit regenerates — not a red main (#3646). "
                "Confirm the chore(reconcile) commit lands within ~60 s.",
                file=out,
            )
            print(f"  VERDICT: {verdict} (tolerated: a push to main, the reconcile job runs next)", file=out)
            print(f"{'='*60}\n", file=out)
            return EXIT_SUCCESS
        if bot_owns_pending_drift_here():
            # #3984: off main these files are not this branch's to regenerate — the
            # reconcile job rewrites them on main after the merge. A notice, never a red.
            print(
                "::notice title=pending-reconcile::Doc-sync literals are stale off main and every one of them "
                "is bot-owned — the reconcile job regenerates them on main after this merges (#3984). "
                "Do NOT commit lambdas/web/platform_counts.py on a branch.",
                file=out,
            )
            print(f"  VERDICT: {verdict} (tolerated: off main, the reconcile job owns these files)", file=out)
            print(f"{'='*60}\n", file=out)
            return EXIT_SUCCESS
    else:
        print(f"  ❌ CHECK FAILED — {total_drift} stale literal(s) across {len(drifted_docs)} file(s),", file=out)
        print(f"     {human_drift} of them NOT repairable by --apply (a rule matched nothing, a marker", file=out)
        print("     pair is missing, or a doc a rule names is gone). The reconcile bot cannot clear this.", file=out)
        for d in drifted_docs:
            print(f"       - {d}", file=out)
        print("  Fix: python3 deploy/sync_doc_metadata.py --apply, then fix what it leaves behind.", file=out)
    print(f"  VERDICT: {verdict}", file=out)
    print(f"{'='*60}\n", file=out)
    return _EXIT_FOR[verdict]
