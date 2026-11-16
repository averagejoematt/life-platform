"""#6116 — a test run cannot perform a real production write: the guard at the execution boundary.

THE INCIDENT (docs/INCIDENT_LOG.md, 2026-11-16). A draft unit test ran the REAL
`deploy/www_preview_sync.sh --target root --restore-previous` from a laptop. Its subprocess env set
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_PROFILE to "" — the CLI treats an empty value as unset and fell back to
the default (admin) profile in ~/.aws. The fix in #6109 lived in that one test and in an agent brief; the owner ruled
(2026-11-16) the class must be closed "at the execution boundary rather than only an agent instruction".

THREE LAYERS, each held here:
  1. deploy/lib/prod_write_guard.sh (+ its PATH shims) and deploy/lib/prod_write_guard.py — under a test runner a
     deploy script cannot call `aws` / `cdk deploy`, and a Python deploy entry point cannot make a botocore write,
     unless the test DECLARES its stub (LP_TEST_AWS_IS_STUB). Outside a test runner both do nothing.
  2. The SET: every deploy/ script whose text performs an AWS write sources / installs the guard. Derived by scanning
     the text for the write verbs (never a hand list), with a must-fail control that plants an unguarded writer.
  3. tests/conftest.py makes real AWS unreachable for the whole session and its children (credential files -> devnull,
     metadata off, non-empty fake keys, no profile, the LP_TEST_SESSION marker, the shims first on PATH); the ONE
     opt-in for live AWS is the `integration` marker.

Nothing here reaches AWS: every `aws` is a recording stub first on PATH, HOME points at tmp_path, the credential
files are os.devnull wherever the test is not deliberately reproducing the careless env.
"""

# premerge-gate: 6116: a set sweep of deploy/ (git ls-files) — a new deploy script that writes to AWS without sourcing deploy/lib/prod_write_guard.sh (or a Python entry point without install_prod_write_guard()) must red on the PR that adds it

from __future__ import annotations

import ast
import json
import os
import re
import site
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUARD_SH = REPO / "deploy" / "lib" / "prod_write_guard.sh"
GUARD_PY_DIR = REPO / "deploy" / "lib"
SHIM_DIR = REPO / "deploy" / "lib" / "prod_write_guard_bin"
WWW_SYNC = REPO / "deploy" / "www_preview_sync.sh"
EXIT_REFUSED = 97

sys.path.insert(0, str(GUARD_PY_DIR))
import prod_write_guard as pwg  # noqa: E402

# deploy/archive/ is NOT in the set: archived one-shot scripts, kept for the record, run by nobody (test or
# operator). The census of what it holds is in the #6116 PR; a revived archive script moves out of archive/ and
# then joins the set like any other.
_EXCLUDED_PREFIXES = ("deploy/archive/",)
_GUARD_FILES = {"deploy/lib/prod_write_guard.sh", "deploy/lib/prod_write_guard.py"}

# ── the scanner (shared by the set test and its must-fail controls) ──────────────────────────────────────────────

_READ_VERB = re.compile(
    r"^(get|list|describe|head|wait|ls|lookup|scan|query|filter|search|test|validate|estimate|simulate|batch-get|presign|help|tail)"
)
_AWS_CMD = re.compile(r"(?<![\w./$-])aws((?:\s+--[a-z-]+(?:[ =](?![a-z0-9-]+\s+[a-z])\S+)?)*)\s+([a-z0-9-]+)\s+([a-z0-9-]+)(.*)")
_CDK_CMD = re.compile(r"\bcdk\s+(?:--?\S+\s+)*(deploy|destroy|bootstrap|import|rollback|watch)\b")
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'|\S+')
_BOOL_FLAGS = {
    "--recursive",
    "--dryrun",
    "--quiet",
    "--only-show-errors",
    "--no-progress",
    "--delete",
    "--exact-timestamps",
    "--size-only",
    "--follow-symlinks",
    "--no-follow-symlinks",
    "--no-guess-mime-type",
    "--no-sign-request",
    "--debug",
    "--no-paginate",
    "--no-cli-pager",
}
_SOURCES_GUARD = re.compile(r"^\s*(?:source|\.)\s+.*prod_write_guard\.sh\b", re.M)


def _s3_copy_is_write(rest: str) -> bool:
    """`aws s3 cp|sync SRC DST`: a write unless DST is provably local. An unknown destination is a write."""
    toks, pos, i = _TOKEN.findall(rest), [], 0
    while i < len(toks):
        t = toks[i]
        if t in ("|", "||", "&&", ";", ")") or t.startswith(("|", ";", ">", "2>")):
            break
        if t.startswith("--"):
            i += 1 if (t in _BOOL_FLAGS or "=" in t) else 2
            continue
        pos.append(t.strip("\"'"))
        i += 1
    if len(pos) < 2:
        return True
    src, dst = pos[0], pos[1]
    if "s3://" in dst:
        return True
    if dst == "-":
        return False
    return "s3://" not in src


def _strip_trailing_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            break
        out.append(ch)
    return "".join(out)


def shell_write_hits(text: str) -> list[tuple[int, str]]:
    """(line number, `service verb`) for every AWS write a shell script's text performs. Comments are skipped; a line
    that only echoes a command (`echo "  $ aws s3 sync …"`) is skipped unless it also pipes into or chains one."""
    hits: list[tuple[int, str]] = []
    lines = text.splitlines()
    n = 0
    while n < len(lines):
        start, line = n + 1, lines[n]
        while line.endswith("\\") and n + 1 < len(lines):
            n += 1
            line = line[:-1] + " " + lines[n]
        n += 1
        if line.lstrip().startswith("#"):
            continue
        line = _strip_trailing_comment(line)
        if re.match(r"\s*(echo|printf)\b", line) and not re.search(r"(\||;|&&)\s*(aws|cdk|npx)\b", line):
            continue
        for m in _AWS_CMD.finditer(line):
            svc, verb, rest = m.group(2), m.group(3), m.group(4)
            if svc == "s3" and verb in ("cp", "sync"):
                if _s3_copy_is_write(rest):
                    hits.append((start, f"s3 {verb}"))
            elif svc == "s3" and verb in ("mv", "rm", "mb", "rb"):
                hits.append((start, f"s3 {verb}"))
            elif svc != "s3" and not _READ_VERB.match(verb):
                hits.append((start, f"{svc} {verb}"))
        m = _CDK_CMD.search(line)
        if m:
            hits.append((start, "cdk " + m.group(1)))
    return hits


_PY_WRITE_METHODS = frozenset(
    "put_item update_item delete_item batch_write_item transact_write_items batch_writer put_object delete_object "
    "delete_objects copy_object upload_file upload_fileobj create_invalidation update_function_code "
    "update_function_configuration publish_version put_function_concurrency put_parameter delete_parameter publish "
    "send_email send_raw_email put_metric_data put_metric_alarm invoke put_rule put_targets update_alias create_alias "
    "put_secret_value update_secret put_retention_policy delete_log_group put_bucket_policy start_execution send_message "
    "delete_alarms update_table put_role_policy create_role update_assume_role_policy create_policy attach_role_policy "
    "restore_table_to_point_in_time delete_table put_bucket_lifecycle_configuration change_resource_record_sets "
    "create_schedule update_schedule delete_schedule put_events".split()
)


def python_write_hits(text: str) -> list[str]:
    """Every AWS write a Python module's AST performs: a boto3 write method call, an `["aws", svc, verb, …]` /
    `["npx", "cdk", "deploy"]` argv, or a string that IS an aws write command line."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ["<unparseable — counted as a writer>"]
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _PY_WRITE_METHODS:
            hits.add(node.func.attr)
        elif isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= 3:
            head = [e.value for e in node.elts[:3] if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(head) == 3 and head[0] == "aws" and shell_write_hits(" ".join(head) + " s3://x s3://y"):
                hits.add("argv " + " ".join(head))
            if len(head) == 3 and head[1:] in (["cdk", "deploy"], ["cdk", "destroy"]) or head[:2] == ["cdk", "deploy"]:
                hits.add("argv cdk deploy")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for line in node.value.splitlines():
                if line.lstrip().startswith("aws ") and shell_write_hits(line):
                    hits.add("command line " + shell_write_hits(line)[0][1])
    return sorted(hits)


def python_installs_guard(text: str) -> bool:
    """The FIRST call in the module's `if __name__ == "__main__":` block is install_prod_write_guard()."""
    tree = ast.parse(text)
    for node in tree.body:
        if not (isinstance(node, ast.If) and "__name__" in ast.unparse(node.test) and "__main__" in ast.unparse(node.test)):
            continue
        for stmt in node.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                continue
            return (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Call)
                and ast.unparse(stmt.value.func).endswith("install_prod_write_guard")
            )
    return False


def unguarded_writers(root: Path, paths: list[str]) -> dict[str, str]:
    """{path: why} for every writing deploy script in `paths` that does not carry the guard."""
    out: dict[str, str] = {}
    for rel in paths:
        if rel in _GUARD_FILES or rel.startswith(_EXCLUDED_PREFIXES) or not rel.startswith("deploy/"):
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".sh"):
            hits = shell_write_hits(text)
            if not hits:
                continue
            src = _SOURCES_GUARD.search(text)
            if src is None:
                out[rel] = f"writes ({', '.join(sorted({h for _, h in hits}))}) and never sources deploy/lib/prod_write_guard.sh"
            else:
                src_line = text[: src.start()].count("\n") + 1
                if src_line > hits[0][0]:
                    out[rel] = f"sources the guard at line {src_line}, after its first write at line {hits[0][0]} ({hits[0][1]})"
        elif rel.endswith(".py"):
            hits = python_write_hits(text)
            if hits and not python_installs_guard(text):
                out[rel] = f"writes ({', '.join(hits)}) and its __main__ block does not start with install_prod_write_guard()"
    return out


def writing_scripts(root: Path, paths: list[str]) -> set[str]:
    out = set()
    for rel in paths:
        if rel in _GUARD_FILES or rel.startswith(_EXCLUDED_PREFIXES) or not rel.startswith("deploy/"):
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if (rel.endswith(".sh") and shell_write_hits(text)) or (rel.endswith(".py") and python_write_hits(text)):
            out.add(rel)
    return out


def _tracked_deploy_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "deploy"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split() if p.endswith((".sh", ".py"))]


# ── 2. the set ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_writing_deploy_script_carries_the_guard():
    paths = _tracked_deploy_files()
    writers = writing_scripts(REPO, paths)
    # the scan is not vacuous: the incident script and the fleet's main writers are in it
    for must in ("deploy/www_preview_sync.sh", "deploy/sync_site_to_s3.sh", "deploy/deploy_lambda.sh", "deploy/restart_pipeline.py"):
        assert must in writers, f"the writer scan no longer sees {must} — it has gone blind"
    assert len(writers) >= 80, f"only {len(writers)} writing deploy scripts found — the scan has gone blind"
    offenders = unguarded_writers(REPO, paths)
    assert not offenders, "deploy scripts that can write to AWS without the #6116 guard:\n" + "\n".join(
        f"  {p}: {why}" for p, why in sorted(offenders.items())
    )


def test_the_set_scan_is_not_blind(tmp_path):
    """Must-fail controls: a planted unguarded writer of each kind is named; the same file guarded is not; a read-only
    script and a printed command line are not writers; an s3 sync to a variable destination IS a write."""
    d = tmp_path / "deploy"
    (d / "lib").mkdir(parents=True)
    plants = {
        "deploy/planted_sync.sh": 'set -e\nDST="s3://b/site"\naws s3 sync ./site "$DST"\n',
        "deploy/planted_var_dest.sh": 'aws s3 sync "$src" "$dst" --delete\n',
        "deploy/lib/planted_lib.sh": 'f() {\n  aws --region us-west-2 cloudfront create-invalidation \\\n    --distribution-id X --paths "/*"\n}\n',
        "deploy/planted_cdk.sh": "cd cdk && npx cdk deploy LifePlatformWeb --require-approval never\n",
        "deploy/planted_writer.py": 'import boto3\n\ndef main():\n    boto3.client("s3").put_object(Bucket="b", Key="k", Body=b"")\n\nif __name__ == "__main__":\n    main()\n',
        "deploy/planted_argv.py": 'import subprocess\n\nif __name__ == "__main__":\n    subprocess.run(["aws", "lambda", "update-function-code", "--function-name", "f"])\n',
        "deploy/planted_late_source.sh": 'aws s3 rm s3://b/k\nsource "$(dirname "$0")/lib/prod_write_guard.sh"\n',
    }
    clean = {
        "deploy/reader.sh": 'aws s3 ls s3://b/\nX=$(aws s3 cp "s3://b/LATEST" - 2>/dev/null)\naws cloudformation describe-stacks --stack-name S\n',
        "deploy/printer.sh": 'echo "  $ aws s3 sync s3://a s3://b"   # a rehearsal line\n# aws s3 rm s3://b/k\n',
        "deploy/guarded.sh": 'source "$(dirname "$0")/lib/prod_write_guard.sh"\naws s3 sync ./site s3://b/site\n',
        "deploy/guarded.py": (
            'import boto3\n\nif __name__ == "__main__":\n    from lib.prod_write_guard import install_prod_write_guard\n\n'
            '    install_prod_write_guard()\n    boto3.client("s3").put_object(Bucket="b", Key="k", Body=b"")\n'
        ),
        "deploy/archive/old.sh": "aws s3 rm s3://b/k\n",
    }
    for rel, body in {**plants, **clean}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    named = unguarded_writers(tmp_path, list(plants) + list(clean))
    assert set(named) == set(plants), f"named {sorted(named)}, expected exactly the plants {sorted(plants)}"
    assert "after its first write" in named["deploy/planted_late_source.sh"]


# ── 4. the incident, as a must-fail control ──────────────────────────────────────────────────────────────────────

_STUB = """#!/bin/bash
echo "$*" >> "{calls}"
case "$1 $2" in
  "s3 cp") case "$*" in *LATEST*) echo build123 ;; esac ;;
  "cloudformation describe-stacks") echo EDIST ;;
  "cloudfront create-invalidation") echo I1 ;;
esac
exit 0
"""


def _stub_aws(tmp_path: Path) -> tuple[Path, Path]:
    bindir, calls = tmp_path / "stubbin", tmp_path / "aws-calls"
    bindir.mkdir()
    (bindir / "aws").write_text(_STUB.format(calls=calls))
    (bindir / "aws").chmod(0o755)
    return bindir, calls


def _careless_env(bindir: Path, home: Path) -> dict:
    """What the 2026-11-16 draft built: the session env minus every AWS_* key, the keys present but EMPTY. HOME moves
    to tmp_path so even a broken guard plus a broken stub could not find ~/.aws — the stub is first on PATH regardless."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY="", AWS_PROFILE="", HOME=str(home))
    env["PATH"] = f"{bindir}{os.pathsep}{os.environ['PATH']}"
    return env


_RESTORE = ["bash", str(WWW_SYNC), "--target", "root", "--restore-previous"]


def test_the_incident_command_is_refused_before_any_aws_call_and_runs_against_a_declared_stub(tmp_path):
    bindir, calls = _stub_aws(tmp_path)
    careless = _careless_env(bindir, tmp_path)
    # (a) the careless env, (b) the same with the two env markers stripped too — only the process ancestry is left,
    # (c) an `env -i`-style rebuild: PATH and HOME and nothing else
    stripped = {k: v for k, v in careless.items() if k not in ("PYTEST_CURRENT_TEST", "LP_TEST_SESSION")}
    bare = {"PATH": careless["PATH"], "HOME": str(tmp_path)}
    failures = []
    for label, env in (("careless", careless), ("markers stripped", stripped), ("env -i", bare)):
        r = subprocess.run(_RESTORE, capture_output=True, text=True, env=env, cwd=REPO, timeout=60)
        if r.returncode != EXIT_REFUSED or "prod_write_guard: REFUSED `aws s3 cp" not in r.stderr or calls.exists():
            failures.append(f"{label}: rc={r.returncode} calls={calls.read_text() if calls.exists() else 0}\n{r.stdout}{r.stderr}")
    assert not failures, "the real restore was NOT refused before its first aws call:\n" + "\n".join(failures)
    # the opt-in: the same command, the stub declared — the stub IS reached and the restore runs to the end, so the
    # refusal above is the guard, not a script that cannot run
    env = dict(careless, LP_TEST_AWS_IS_STUB=str(bindir / "aws"))
    r = subprocess.run(_RESTORE, capture_output=True, text=True, env=env, cwd=REPO, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    log = calls.read_text()
    assert "s3 sync s3://matthew-life-platform/www-previous/build123 s3://matthew-life-platform/site" in log, log
    assert "cloudfront create-invalidation --distribution-id EDIST" in log, log
    # a declared stub is a PATH, not a switch: "1" declares nothing
    calls.unlink()
    r = subprocess.run(_RESTORE, capture_output=True, text=True, env=dict(careless, LP_TEST_AWS_IS_STUB="1"), cwd=REPO, timeout=60)
    assert r.returncode == EXIT_REFUSED and not calls.exists(), r.stdout + r.stderr


def _run_detached(argv: list[str], env: dict, tmp_path: Path, tag: str) -> tuple[int, str, str]:
    """Run `argv` with NO pytest in its ancestry: a double fork whose middle process exits at once, so the child is
    re-parented to init/launchd before it starts. The env is exactly `env` (no PYTEST_CURRENT_TEST, no marker)."""
    out, err, rc = tmp_path / f"{tag}.out", tmp_path / f"{tag}.err", tmp_path / f"{tag}.rc"
    quoted = " ".join("'" + a.replace("'", "'\\''") + "'" for a in argv)
    inner = f"( sleep 1; {quoted} >'{out}' 2>'{err}'; echo $? >'{rc}' ) </dev/null >/dev/null 2>&1 &"
    subprocess.run(["/usr/bin/env", "-i", *[f"{k}={v}" for k, v in env.items()], "bash", "-c", inner], check=True, cwd=REPO)
    deadline = time.time() + 90
    while time.time() < deadline and not (rc.exists() and rc.read_text().strip()):
        time.sleep(0.2)
    assert rc.exists(), f"{tag}: the detached run never finished"
    return int(rc.read_text().strip()), out.read_text(), err.read_text()


def test_outside_a_test_runner_the_guard_changes_nothing(tmp_path):
    """The two environments the guard must NOT touch, each run with no pytest ancestor: an attended deploy from a shell
    and a CI deploy job (GITHUB_ACTIONS + OIDC-shaped credentials). The same real restore, the stub on PATH and NOT
    declared — it is reached, exactly as a real `aws` would be today; and sourcing the guard defines nothing."""
    bindir, calls = _stub_aws(tmp_path)
    path = f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin{os.pathsep}/usr/sbin{os.pathsep}/sbin"
    attended = {"PATH": path, "HOME": str(tmp_path), "USER": "operator", "SHELL": "/bin/zsh", "TERM": "xterm-256color"}
    ci = {
        "PATH": path,
        "HOME": str(tmp_path),
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_SHA": "0" * 40,
        "AWS_REGION": "us-west-2",
        "AWS_ACCESS_KEY_ID": "ASIAEXAMPLEEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "example",
        "AWS_SESSION_TOKEN": "example",
    }
    probe = f'source "{GUARD_SH}"; echo "type=$(type -t aws) path=$PATH session=${{LP_TEST_SESSION:-}}"'
    for label, env in (("attended", attended), ("ci-deploy", ci)):
        if calls.exists():
            calls.unlink()
        rc, out, err = _run_detached(_RESTORE, env, tmp_path, label)
        assert rc == 0 and "REFUSED" not in err, f"{label}: rc={rc}\n{out}{err}"
        assert "s3 sync s3://matthew-life-platform/www-previous/build123" in calls.read_text(), f"{label}: the stub was not reached"
        rc, out, err = _run_detached(["bash", "-c", probe], env, tmp_path, label + "-probe")
        assert rc == 0 and out.strip() == f"type=file path={path} session=", f"{label}: sourcing the guard changed the shell: {out}{err}"


def test_the_ancestry_signal_names_pytest_and_not_a_shell_that_mentions_it():
    yes = [
        "/opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python -m pytest tests/ -n 8",
        "/usr/bin/python3 -m pytest -q",
        "python3 -mpytest tests/x.py",
        "/home/runner/.local/bin/pytest tests/",
        "python3 /usr/local/bin/pytest -q",
    ]
    no = [
        "/bin/zsh -c python3 -m pytest tests/ && bash deploy/deploy_lambda.sh",
        "bash deploy/www_preview_sync.sh --target root",
        "python3 deploy/restart_pipeline.py --apply",
        "python3 -m pytest_cov",
        "node /usr/local/bin/claude",
    ]
    wrong = [a for a in yes if not pwg.is_pytest_command(a)] + [a for a in no if pwg.is_pytest_command(a)]
    shell = 'source "$1"; shift; for a in "$@"; do _lp_pwg_is_pytest_cmd "$a" && echo Y || echo N; done'
    r = subprocess.run(["bash", "-c", shell, "_", str(GUARD_SH), *yes, *no], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    got = r.stdout.split()
    assert got == ["Y"] * len(yes) + ["N"] * len(no), f"shell twin disagrees: {got}\n{r.stderr}"
    assert not wrong, f"python twin misclassifies: {wrong}"


# ── the Python twin ──────────────────────────────────────────────────────────────────────────────────────────────

_PY_PROBE = f"""
import os, sys
sys.path.insert(0, {str(GUARD_PY_DIR)!r})
if os.environ.get("PROBE_IMPORT_BOTO3_FIRST"):  # a script that imports boto3 at module level, before __main__
    import boto3
from prod_write_guard import install_prod_write_guard
print("reason=" + str(install_prod_write_guard()), flush=True)
import boto3  # a script that imports it lazily, inside main()
s3 = boto3.client("s3", region_name="us-west-2", endpoint_url="http://127.0.0.1:9", aws_access_key_id="x", aws_secret_access_key="x")
try:
    s3.list_objects_v2(Bucket="b")
except Exception as e:
    print("read-reached-network " + type(e).__name__, flush=True)
try:
    s3.put_object(Bucket="b", Key="k", Body=b"")
except Exception as e:
    print("write-reached-network " + type(e).__name__, flush=True)
"""


def test_the_python_twin_refuses_a_write_from_a_test_subprocess_and_honours_a_declared_stub_endpoint(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    # (no AWS_PROFILE="": botocore, unlike the CLI, raises ProfileNotFound on an empty profile name)
    env.update(AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY="", HOME=str(tmp_path), AWS_MAX_ATTEMPTS="1")
    env["PYTHONUSERBASE"] = site.getuserbase()  # HOME moved; boto3 may live in the user site
    for order in ("lazy", "module-level"):
        probe_env = dict(env, PROBE_IMPORT_BOTO3_FIRST="1") if order == "module-level" else env
        r = subprocess.run([sys.executable, "-c", _PY_PROBE], capture_output=True, text=True, env=probe_env, timeout=120)
        assert r.returncode == EXIT_REFUSED, f"{order}: " + r.stdout + r.stderr
        assert "read-reached-network" in r.stdout, f"{order}: a read must stay allowed (a dry-run path is unchanged)"
        assert "write-reached-network" not in r.stdout and "REFUSED `s3 PutObject`" in r.stderr, f"{order}: " + r.stdout + r.stderr
    env["LP_TEST_AWS_IS_STUB"] = "http://127.0.0.1:9"
    r = subprocess.run([sys.executable, "-c", _PY_PROBE], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0 and "write-reached-network" in r.stdout, r.stdout + r.stderr


def test_the_python_twin_changes_nothing_outside_a_test_runner_or_inside_the_pytest_process(tmp_path):
    assert pwg.install_prod_write_guard() is None, "in-process the conftest hermetic env governs; the twin must not patch botocore here"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "AWS_MAX_ATTEMPTS": "1", "PYTHONUSERBASE": site.getuserbase()}
    rc, out, err = _run_detached([sys.executable, "-c", _PY_PROBE], env, tmp_path, "py-attended")
    assert rc == 0 and "reason=None" in out and "write-reached-network" in out, out + err


# ── 3. the session: real AWS is unreachable by default ───────────────────────────────────────────────────────────


def test_the_session_makes_real_aws_unreachable_for_itself_and_its_children(tmp_path):
    want = {
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "AWS_EC2_METADATA_DISABLED": "true",
        "LP_TEST_SESSION": "1",
    }
    probe = "import json, os; print(json.dumps({k: os.environ.get(k) for k in %r + ['AWS_PROFILE', 'AWS_ACCESS_KEY_ID', 'PATH']}))" % list(
        want
    )
    child = json.loads(subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout)
    for k, v in want.items():
        assert os.environ.get(k) == v and child[k] == v, f"{k}: session {os.environ.get(k)!r}, child {child[k]!r}"
    assert (
        child["AWS_PROFILE"] is None and child["AWS_ACCESS_KEY_ID"]
    ), "no profile; keys present and NON-empty (empty is what fell through)"
    assert child["PATH"].split(os.pathsep)[0] == str(SHIM_DIR), "the guard's shims go first on the session PATH"
    # a test that shells `aws` by name reaches the shim, which refuses — a recording stub behind it is never called
    bindir, calls = _stub_aws(tmp_path)
    env = dict(os.environ, PATH=f"{SHIM_DIR}{os.pathsep}{bindir}{os.pathsep}{os.environ['PATH']}")
    r = subprocess.run(["aws", "s3", "rm", "s3://matthew-life-platform/site/index.html"], capture_output=True, text=True, env=env)
    assert r.returncode == EXIT_REFUSED and not calls.exists(), r.stdout + r.stderr


def test_the_integration_opt_in_restores_the_credential_files_too(tmp_path):
    """The ONE live-AWS opt-in is @pytest.mark.integration (tests/conftest.py::_hermetic_aws_credentials). On a laptop
    the real credentials live in ~/.aws, so the restore must bring back AWS_CONFIG_FILE / AWS_SHARED_CREDENTIALS_FILE,
    not only the key variables — derived from the controller's stash exactly as #3917 does for the keys."""
    here = str(Path(__file__).resolve().parent)
    probe = f"import json, sys; sys.path.insert(0, {here!r}); import conftest; print(json.dumps(conftest._REAL_AWS_ENV))"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "LP_REAL_AWS_ENV__"))}
    env.update(AWS_CONFIG_FILE=str(tmp_path / "config"), PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env, cwd=REPO, check=True).stdout
    restore = json.loads(out.strip().splitlines()[-1])
    assert restore["AWS_CONFIG_FILE"] == str(tmp_path / "config"), restore
    assert restore["AWS_SHARED_CREDENTIALS_FILE"] is None and restore["AWS_EC2_METADATA_DISABLED"] is None, restore
