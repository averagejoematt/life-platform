#!/usr/bin/env python3
"""restart_hooks.py — the #1092 post-verify hook sequence for restart_pipeline.py.

Split out of restart_pipeline.py (#2612) rather than grown inside it: that module
sat 7 lines under the 1200-line hard ceiling (tests/test_module_size_guard.py), so
every further reset step had to be squeezed in sideways. This is the cohesive
helper the guard asks for — restart_pipeline re-exports build_post_verify_hooks,
so the public entrypoint and every caller are unchanged.
"""

from __future__ import annotations


def build_post_verify_hooks(
    with_preregistration: bool = False,
    dedup_sources: list[str] | None = None,
    skip_prologue_fix: bool = False,
    skip_predict_week_seed: bool = False,
    genesis: str | None = None,
) -> list[tuple[str, list[str]]]:
    """The #1092 post-verify hook sequence — the former manual Sunday-queue steps.

    Ordering constraint (verified): fix_prologue_cycle_and_subscribe_ttl reads SSM
    /life-platform/experiment-cycle, so it must run AFTER bump_cycle_ssm (which fires
    right after the intelligence wipe) — every post-verify position satisfies that.
    fix_prologue is default-ON (issue-sanctioned change to default behavior); the
    dedup/prereg hooks only run when their flags are passed, keeping the pipeline
    byte-compatible when the new flags are absent.

    Hook (d), predict-the-week re-seed (#2612, default-ON): step 2d
    (clear_predict_week_subject) DELETES site/config/current_challenge.json on every
    --apply, and nothing else writes it — no lambda, no wipe. Re-seeding it was an
    attended printed next-step, so the pipeline reliably created a hole it did not
    close: cycle 13 (genesis 2026-08-10) went dark for the whole genesis week, the
    same class as the cycle-11 dark week (#1952). It runs AFTER
    seed_genesis_preregistration because the subject derives from that freeze, and
    it carries --if-frozen so a reset whose freeze has not been re-landed SKIPS
    loudly (exit 0) instead of aborting the pipeline's final hooks.
    """
    hooks: list[tuple[str, list[str]]] = []
    if not skip_prologue_fix:
        hooks.append(("fix_prologue_cycle_and_subscribe_ttl", ["python3", "deploy/fix_prologue_cycle_and_subscribe_ttl.py", "--apply"]))
    if with_preregistration:
        hooks.append(("seed_genesis_preregistration", ["python3", "deploy/seed_genesis_preregistration.py", "--apply"]))
    for src in dedup_sources or []:
        hooks.append((f"dedup_{src}", ["python3", "deploy/dedup_source_records.py", "--source", src, "--apply"]))
    if not skip_predict_week_seed:
        cmd = ["python3", "deploy/build_genesis_predict_week.py"]
        if genesis:
            cmd += ["--genesis", genesis]
        hooks.append(("seed_predict_week_subject", cmd + ["--if-frozen", "--apply"]))
    return hooks
