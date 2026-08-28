"""tests/skill_paths.py — resolve a Claude Code skill's prompt file, for tests.

Thin shim over the ONE registry (`scripts/skill_registry.py`) so no test hard-codes a
`.claude/commands/<name>.md` literal. Twelve of them did before #skills-registry, and
every one would have gone stale — silently, as a passing test on a file that no longer
exists at that path is indistinguishable from a passing test on the real thing until
someone reads it.

Use `require_skill("wrap")` when the test's whole point depends on that skill existing:
it raises with both candidate layouts named, rather than returning None into an
`open()` that fails three frames later with a bare ENOENT.
"""

import importlib.util
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    spec = importlib.util.spec_from_file_location("_skill_registry", os.path.join(_ROOT, "scripts", "skill_registry.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_reg = _load()

skills = _reg.skills
skill_names = _reg.skill_names
skill_files = _reg.skill_files
skill_path = _reg.skill_path
require_skill = _reg.require_skill
agents = _reg.agents
agent_files = _reg.agent_files
prompt_files = _reg.prompt_files
duplicates = _reg.duplicates
