"""tests/test_platform_logger_sweep_5106.py — #5106 / #5203 / #3283: a coach module the telegram worker imports must
log through the platform logger, not a bare `logging.getLogger`.

Why: a Lambda's root logger surfaces WARNING only, so a bare logger's INFO line (the operational proof line — "sent",
"wrote", a skip reason) never reaches CloudWatch. 2026-10-25: `[evening-checkin] <day>: sent` was missing at the 03:00Z
run though the ledger said `sent`. `common.platform_logger.get_logger` owns an INFO stdout handler and does not propagate.

Held here:
  * the evening check-in's closing INFO line is heard on the PLATFORM logger's own handler (not caplog, which only
    hears root — exactly the blindness that hid the bug);
  * a guard walks `lambdas/coach/*.py`, takes the telegram worker's transitive import closure, and fails on a bare
    `logging.getLogger(` in any member (the `except ImportError` fallback beside a `get_logger` import is allowed);
    a justified exception sits in ALLOWED with a reason, and must itself never call `.info(`;
  * a planted-module negative control proves the scan can fail (mutation-proven below).

This is a test, not a registered gate: it adds no `scripts/gate_census.py` entry (it is a unit guard over one directory,
like the other per-package structure tests) — the census pins are unchanged.
"""

# premerge-gate: #5106: globs lambdas/coach/*.py and parses every module's imports + getLogger calls

from __future__ import annotations

import ast
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lambdas"))

COACH = REPO / "lambdas" / "coach"
ROOT_MODULE = "telegram_worker_lambda"

# Modules in the worker's closure that may keep a bare logger: they never log at INFO (so nothing is dropped), which
# this test enforces below. Add INFO and the module must move to the platform logger instead.
ALLOWED = {
    "coach_chat": "no INFO line — WARNING+ only reaches root, which is what a Lambda surfaces",
    "coach_chat_grounding": "no INFO line",
    "coach_domain_facts": "no INFO line",
    "coach_open_loops": "no INFO line",
    "coach_team_texture": "no INFO line",
    "coach_vision": "no INFO line",
    "coach_voice": "no INFO line",
    "persona_core": "no INFO line",
    "persona_registry": "no INFO line",
    "progress_capture": "no INFO line",
    "response_protocol": "no INFO line",
    "telegram_gateway": "no INFO line",
}
# Fixed in open PR #5332 (the dead-man's own #5203 lane); drop this entry once that merges.
PENDING_ELSEWHERE = {"calibration_deadman_alert": "#5332"}


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text())


def _coach_modules(root: Path) -> set[str]:
    return {p.stem for p in root.glob("*.py")}


def _deps(tree: ast.AST, mods: set[str]) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.module == "coach" or (n.level and n.module is None):
                out |= {a.name for a in n.names}
            elif n.module and n.module.startswith("coach."):
                out.add(n.module.split(".")[1])
            elif n.module:
                out.add(n.module)
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name.split(".")[1] if a.name.startswith("coach.") else a.name)
    return out & mods


def closure(root: Path, start: str = ROOT_MODULE) -> set[str]:
    mods = _coach_modules(root)
    seen: set[str] = set()
    todo = [start]
    while todo:
        m = todo.pop()
        if m in seen or m not in mods:
            continue
        seen.add(m)
        todo += list(_deps(_tree(root / f"{m}.py"), mods))
    return seen


def bare_getloggers(tree: ast.AST) -> list[int]:
    """Line numbers of `logging.getLogger(` calls NOT inside an `except ImportError` fallback."""
    fallback: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler) and isinstance(n.type, ast.Name) and n.type.id == "ImportError":
            fallback |= {id(c) for c in ast.walk(n)}
    return sorted(
        c.lineno
        for c in ast.walk(tree)
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == "getLogger"
        and isinstance(c.func.value, ast.Name)
        and c.func.value.id == "logging"
        and id(c) not in fallback
    )


def calls_info(tree: ast.AST) -> bool:
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "info" for c in ast.walk(tree))


def offenders(root: Path) -> dict[str, str]:
    bad: dict[str, str] = {}
    for m in sorted(closure(root)):
        tree = _tree(root / f"{m}.py")
        lines = bare_getloggers(tree)
        if not lines or m in PENDING_ELSEWHERE:
            continue
        if m not in ALLOWED:
            bad[m] = f"bare logging.getLogger at line(s) {lines}: use common.platform_logger.get_logger('telegram-worker')"
        elif calls_info(tree):
            bad[m] = "allowlisted for having no INFO line, but it now calls .info( — move it to the platform logger"
    return bad


def test_the_worker_closure_is_found_and_holds_the_known_modules():
    c = closure(COACH)
    assert {"telegram_worker_lambda", "evening_checkin", "coach_outbound", "telegram_group", "coach_chat"} <= c


def test_no_module_the_worker_imports_logs_info_through_a_bare_logger():
    bad = offenders(COACH)
    assert not bad, "INFO lines dropped by the Lambda root logger (#3283):\n" + "\n".join(f"  {m}: {why}" for m, why in bad.items())


def test_the_guard_can_fail_a_planted_module_and_an_allowlisted_info_creep(tmp_path):
    (tmp_path / "telegram_worker_lambda.py").write_text("from coach import planted_bare, planted_ok\n")
    (tmp_path / "planted_bare.py").write_text("import logging\nlogger = logging.getLogger(__name__)\nlogger.info('sent')\n")
    (tmp_path / "planted_ok.py").write_text(
        "import logging\ntry:\n    from common.platform_logger import get_logger\n    logger = get_logger('x')\n"
        "except ImportError:\n    logger = logging.getLogger('x')\n"
    )
    assert closure(tmp_path) == {"telegram_worker_lambda", "planted_bare", "planted_ok"}
    assert list(offenders(tmp_path)) == ["planted_bare"]  # the fallback beside get_logger is NOT an offender
    ALLOWED["planted_bare"] = "negative control"
    try:
        assert "calls .info(" in offenders(tmp_path)["planted_bare"]
    finally:
        del ALLOWED["planted_bare"]


class _Recorder(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_the_evening_checkin_sent_line_reaches_the_platform_loggers_handler():
    from coach import evening_checkin as ec
    from common.pacific_time import PACIFIC
    from common.platform_logger import PlatformLogger, get_logger

    assert isinstance(ec.logger, PlatformLogger) and ec.logger.propagate is False and ec.logger.handlers
    assert ec.logger.isEnabledFor(logging.INFO)

    class Table:
        def __init__(self):
            self.store = {}

        def get_item(self, Key, **kw):
            return {"Item": self.store[(Key["pk"], Key["sk"])]} if (Key["pk"], Key["sk"]) in self.store else {}

        def put_item(self, Item, ConditionExpression=None, **kw):
            k = (Item["pk"], Item["sk"])
            if ConditionExpression and k in self.store:
                from botocore.exceptions import ClientError

                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
            self.store[k] = dict(Item)

        def update_item(self, Key, **kw):
            self.store.setdefault((Key["pk"], Key["sk"]), {"pk": Key["pk"], "sk": Key["sk"]})

    evening = datetime(2026, 10, 28, 20, 0, tzinfo=PACIFIC)
    rec = _Recorder()
    get_logger("telegram-worker").addHandler(rec)
    try:
        out = ec.run_prompt(Table(), evening, lambda p: ("tok", 4242), lambda *a: True, now_utc=evening.astimezone(timezone.utc))
    finally:
        get_logger("telegram-worker").removeHandler(rec)
    assert out["reason"] == "sent"
    assert "[evening-checkin] 2026-10-28: sent" in rec.lines
