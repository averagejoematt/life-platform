"""Doc-command arg floor (#4877): a ``deploy_lambda.sh`` call in a doc must carry both arguments.

``deploy/deploy_lambda.sh`` exits 1 below two arguments (``<function-name> <source-file>``), so a
doc that shows a one-argument call hands a new hire a command that fails on day one.
Scans fenced blocks and inline code spans in ``docs/*.md`` (CHANGELOG.md and INCIDENT_LOG.md are dated history, skipped),
and checks the QUICKSTART stack list names every stack ``cdk/app.py`` instantiates.
"""

import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SKIP = {"CHANGELOG.md", "INCIDENT_LOG.md"}
CALL = re.compile(r"deploy_lambda\.sh([^`\n|]*)")


def _scannable(text):
    """Yield (lineno, line) for lines inside fences, plus inline-code spans elsewhere."""
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            yield n, line
        else:
            for span in re.findall(r"`([^`]*)`", line):
                yield n, span


def offenders(files):
    bad = []
    for f in files:
        for n, chunk in _scannable(f.read_text(encoding="utf-8")):
            for m in CALL.finditer(chunk):
                tail = m.group(1)
                if not tail.strip() or not tail.startswith(" "):
                    continue  # prose mention of the script name, not a call
                try:
                    args = [a for a in shlex.split(tail) if not a.startswith("--")]
                except ValueError:
                    args = tail.split()
                if len(args) < 2:
                    bad.append(f"{f.name}:{n}: {chunk.strip()}")
    return bad


def _docs():
    return [p for p in sorted(DOCS.glob("*.md")) if p.name not in SKIP]


def test_deploy_lambda_calls_carry_both_arguments():
    bad = offenders(_docs())
    assert not bad, "deploy_lambda.sh needs <function-name> <source-file>:\n" + "\n".join(bad)


def test_arg_floor_scanner_catches_a_one_arg_call(tmp_path):
    """Mutation control: a one-argument call must be flagged."""
    f = tmp_path / "X.md"
    f.write_text("```bash\nbash deploy/deploy_lambda.sh life-platform-mcp\n```\n", encoding="utf-8")
    assert offenders([f])
    f.write_text("```bash\nbash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py\n```\n", encoding="utf-8")
    assert not offenders([f])


def test_quickstart_stack_list_equals_app_stacks():
    app = (ROOT / "cdk" / "app.py").read_text(encoding="utf-8")
    in_app = set(re.findall(r'"(LifePlatform\w+)"', app))
    section = (DOCS / "QUICKSTART.md").read_text(encoding="utf-8").split("### Stack names", 1)[1].split("---", 1)[0]
    in_doc = set(re.findall(r"`(LifePlatform\w+)`", section))
    assert in_doc == in_app, f"QUICKSTART stack list drifted: missing {in_app - in_doc}, extra {in_doc - in_app}"
