"""#4849: every Lambda log group a Monitoring filter names is created by a stack Monitoring depends on.

`logs.LogGroup.from_log_group_name` produces no CloudFormation reference, so without an explicit
`monitoring.add_dependency(<owner>)` in cdk/app.py a paired first apply deploys Monitoring first and the
MetricFilter CREATE_FAILs ("log group does not exist"). Source-level, no synth.
"""

import ast
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACKS = os.path.join(ROOT, "cdk", "stacks")
# stack module -> the variable app.py binds it to
OWNER_VAR = {
    "ingestion_stack": "ingestion",
    "compute_stack": "compute",
    "email_stack": "email",
    "operational_stack": "operational",
    "serve_stack": "serve",
    "mcp_stack": "mcp",
}


def _read(path):
    with open(path) as f:
        return f.read()


def _declared_deps():
    deps = set()
    for node in ast.walk(ast.parse(_read(os.path.join(ROOT, "cdk", "app.py")))):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            if any(isinstance(n, ast.Call) and ast.unparse(n.func) == "monitoring.add_dependency" for n in ast.walk(node)):
                deps |= {e.id for e in node.iter.elts if isinstance(e, ast.Name)}
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "monitoring.add_dependency":
            deps |= {a.id for a in node.args if isinstance(a, ast.Name)}
    return deps


def _watched_functions():
    names = set()
    for path in glob.glob(os.path.join(STACKS, "monitoring*.py")):
        names |= set(re.findall(r"/aws/lambda/([A-Za-z0-9_-]+)", _read(path)))
    return names


def _owner_of(fn):
    owners = set()
    for mod in OWNER_VAR:
        if re.search(r"function_name\s*=\s*[\"']%s[\"']" % re.escape(fn), _read(os.path.join(STACKS, mod + ".py"))):
            owners.add(mod)
    return owners


def test_monitoring_depends_on_every_stack_owning_a_filtered_log_group():
    deps = _declared_deps()
    assert deps, "cdk/app.py declares no monitoring.add_dependency"
    offenders = []
    for fn in sorted(_watched_functions()):
        for mod in _owner_of(fn):
            if OWNER_VAR[mod] not in deps:
                offenders.append(f"{fn} (owned by {mod}) -> add monitoring.add_dependency({OWNER_VAR[mod]})")
    assert not offenders, "\n".join(offenders)


def test_inbound_auth_gate_owner_is_found_and_ordered():
    # the specimen: guard against the owner lookup silently matching nothing
    assert _owner_of("inbound-auth-gate") == {"operational_stack"}
    assert "operational" in _declared_deps()
