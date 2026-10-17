#!/usr/bin/env python3
"""scripts/hooks/session_preflight.py — SessionStart: the state a session must not guess.

WHY
  Session E lost three of its four rework cycles to gates that were knowable at boot. The
  canonical evidence: `wrap_gates.py` printed COACH_STANCE.md at 0d headroom in the boot
  output, and that exact doc redded a PR an hour later. Session F pre-flighted the same
  four classes and lost zero.

  Sessions also repeatedly BOOT ON A RED MAIN inherited from the previous wrap, and find a
  stranded production deploy lease every single session — in three of them, approving the
  lease would have rolled back live-deployed fixes.

WHAT IT PRINTS
  Only things a session would otherwise guess or discover expensively: main's real state,
  any waiting deploy lease, worktree hygiene, and the corpus gate. Everything is derived
  live; nothing is remembered. Each line degrades to an explicit "unverified" rather than
  a silent omission — a check that cannot run must say so, because a blank line reads as
  a pass (the #2578 class this repo has paid for repeatedly).

NEVER BLOCKS
  SessionStart output is context, not a gate. It always exits 0.

HEARD (#4260, verified against the hook contract)
  Unlike PreToolUse/PostToolUse, SessionStart's plain stdout on exit 0 IS added to the
  model's context, so this hook keeps printing plain text — it is the one hook in this
  layer that was never silent. It reads the payload so `branch=` names the checkout the
  session actually started in (payload `cwd`), not the checkout this script lives in.
"""

import datetime as _dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import ROOT, gh, git, read_payload  # noqa: E402


def _main_green() -> str:
    code, out = git("rev-parse", "--abbrev-ref", "HEAD")
    branch = out if code == 0 else "?"
    code, out = gh(
        "api",
        "repos/averagejoematt/life-platform/actions/runs?branch=main&per_page=8",
        "--jq",
        '[.workflow_runs[]|select(.name=="CI/CD")][0]|"\\(.conclusion // .status) \\(.head_sha[0:9])"',
    )
    if code != 0 or not out or out.startswith("null"):
        state = "UNVERIFIED (could not query — this is not a pass)"
    else:
        state = out
    return f"branch={branch}  main CI/CD={state}"


def _site_deploy() -> str:
    """The newest site-deploy.yml run's conclusion (#4703, incident 2026-10-14).

    A failed site deploy is silent: the workflow has no production gate and nothing pages
    on its red, so merged `site/**` work can revert or never publish for days — 3 d in
    #3878 (2026-09-16→19), 23 h in #4703 (2026-10-14→15). This line is the one place
    every session reads it. A query failure prints UNVERIFIED, never a blank.
    """
    code, out = gh(
        "api",
        "repos/averagejoematt/life-platform/actions/workflows/site-deploy.yml/runs?per_page=1",
        "--jq",
        '.workflow_runs[0]|"\\(.conclusion // .status) \\(.head_sha[0:9]) \\(.created_at)"',
    )
    if code != 0 or not out or out.startswith("null"):
        return "UNVERIFIED (could not query — this is not a pass)"
    flag = "  <- RED: merged site/** work is NOT live; find out why before anything else" if out.startswith("failure") else ""
    return out + flag


CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
REVIEW_WINDOW_HOURS = 48  # chronicle-approve's stale-draft sweep: past this a draft is held daily, never sent


def _fmt_age(delta: _dt.timedelta) -> str:
    secs = max(int(delta.total_seconds()), 0)
    days, rem = divmod(secs, 86400)
    hours = rem // 3600
    return f"{days}d{hours:02d}h" if days else f"{hours}h{(rem % 3600) // 60:02d}m"


def chronicle_queue_lines(items: list, now: _dt.datetime) -> list[str]:
    """Pure: one line per chronicle `DATE#` row with `status=draft` (the approve queue), or
    one line saying the queue is empty. Rows are the wire shape `chronicle_approve_lambda`'s
    sweep reads (`status`, `generated_at`, `week_number`, `tombstone`, `phase`).

    #4531 (incident 2026-10-14): week 6 was drafted by the legacy writer after the desk
    failed, the preview email went out, and nobody approved it — the 48-hour sweep then
    HELD it daily (an unaudited draft never auto-publishes, #4694) and the subscribers'
    Wednesday simply did not arrive. Two sessions booted inside that window with no line
    telling them a draft was waiting. This is that line. A tombstoned or non-current-phase
    draft is history the sweep skips; it is still printed, flagged, never hidden.
    """
    drafts = [it for it in items if str(it.get("status") or "") == "draft"]
    if not drafts:
        return ["  chronicle   no draft awaiting approval"]
    out: list[str] = []
    for it in sorted(drafts, key=lambda it: str(it.get("sk") or "")):
        sk = str(it.get("sk") or "?")
        week = it.get("week_number")
        label = f"{sk} (week {int(week)})" if week not in (None, "") else sk
        ga = str(it.get("generated_at") or "")
        try:
            age = now - _dt.datetime.fromisoformat(ga.replace("Z", "+00:00"))
            age_s = _fmt_age(age)
            held = age >= _dt.timedelta(hours=REVIEW_WINDOW_HOURS)
        except ValueError:
            age_s, held = "age unknown", False
        if it.get("tombstone") or (it.get("phase") not in (None, "", "experiment")):
            out.append(f"  chronicle   DRAFT {label} unapproved {age_s} — tombstoned/non-current phase: history, the sweep skips it")
            continue
        tail = (
            " — HELD by the 48-h sweep daily, nothing reaches subscribers: approve it from the preview email or force the desk"
            if held
            else " — inside the review window: approve it from the preview email before the 48-h sweep holds it"
        )
        out.append(f"  chronicle   DRAFT {label} unapproved {age_s}{tail}")
    return out


def _chronicle_queue() -> list[str]:
    """The chronicle approve queue at boot (#4531). Read-only DynamoDB; any failure prints
    UNVERIFIED, never a blank or an empty-queue line the read did not earn."""
    if os.environ.get("CLAUDE_HOOK_INERT") == "1":
        return ["  chronicle   UNVERIFIED (hook inert — no AWS read; a draft may be waiting)"]
    try:
        import boto3
        from boto3.dynamodb.conditions import Key
        from botocore.config import Config

        cfg = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})
        table = boto3.resource("dynamodb", region_name="us-west-2", config=cfg).Table("life-platform")
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(CHRONICLE_PK) & Key("sk").begins_with("DATE#"),
            ProjectionExpression="sk, #s, generated_at, week_number, tombstone, phase",
            ExpressionAttributeNames={"#s": "status"},
        )
        return chronicle_queue_lines(list(resp.get("Items") or []), _dt.datetime.now(_dt.timezone.utc))
    except Exception as exc:  # noqa: BLE001 — fail open, say so
        return [f"  chronicle   UNVERIFIED ({type(exc).__name__}: {exc})"]


def _waiting_lease() -> str:
    code, out = gh(
        "api",
        "repos/averagejoematt/life-platform/actions/runs?status=waiting&per_page=10",
        "--jq",
        '[.workflow_runs[]|"\\(.head_sha[0:9]) \\(.created_at)"]|join("; ")',
    )
    if code != 0:
        return "UNVERIFIED (could not query)"
    if not out or out == "null":
        return "none"
    return f"{out}  — dispose it: approve or REJECT, never leave waiting"


def _worktrees() -> str:
    code, out = git("worktree", "list")
    if code != 0:
        return "UNVERIFIED"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    # Path containment, NOT a substring test: `<repo>-worktrees/` starts with `<repo>`,
    # so `str(ROOT) in path` called eleven external worktrees "inside the repo". A
    # pre-flight that cries wolf every session is a pre-flight nobody reads.
    inside = []
    for ln in lines:
        cand = Path(ln.split()[0])
        if cand == ROOT:
            continue
        try:
            cand.relative_to(ROOT)
            inside.append(ln)
        except ValueError:
            pass
    note = f"{len(lines)} total"
    if inside:
        note += f"; {len(inside)} INSIDE the repo — repo-wide sweeps walk them"
    return note


def _boot_brief() -> list[str]:
    """The boot contract (#3314): the architecture facts a session reads FROM THE MODEL,
    rendered by scripts/boot_brief.py. Loaded by path (this hook runs outside any
    package). A failure prints an explicit UNVERIFIED line — never a blank."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_boot_brief", ROOT / "scripts" / "boot_brief.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = mod  # spec-loaded modules must be registered before exec
        spec.loader.exec_module(mod)
        return mod.render_lines(mod.load_model())
    except Exception as exc:  # noqa: BLE001 — fail open, say so
        return [f"  model       UNVERIFIED (boot brief failed: {type(exc).__name__}: {exc})"]


def _red_alarms() -> list[str]:
    """#4709: alarms in ALARM now (name + red duration) and those that fired+cleared in 24h.
    Read-only CloudWatch; any failure prints UNVERIFIED, never a blank or a 'none'."""
    if os.environ.get("CLAUDE_HOOK_INERT") == "1":
        return ["  red alarms  UNVERIFIED (hook inert — no AWS read; this is not a clean board)"]
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_boot_brief_alarms", ROOT / "scripts" / "boot_brief.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod.red_alarm_lines()
    except Exception as exc:  # noqa: BLE001
        return [f"  red alarms  UNVERIFIED ({type(exc).__name__}: {exc})"]


def main() -> int:
    read_payload()  # records the payload cwd for git(); an empty/garbage stdin is fine
    print("── session pre-flight " + "─" * 46)
    print(f"  main        {_main_green()}")
    print(f"  site-deploy {_site_deploy()}")
    for line in _chronicle_queue():
        print(line)
    print(f"  deploy lease {_waiting_lease()}")
    print(f"  worktrees   {_worktrees()}")
    for line in _boot_brief():
        print(line)
    for line in _red_alarms():
        print(line)
    print("  gates       python3 scripts/wrap_gates.py           (headroom per lane)")
    print("              python3 scripts/skill_lint.py --offline  (skill corpus)")
    print("─" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
