#!/usr/bin/env python3
"""scripts/ci_local_composite.py — what a LOCAL composite action's steps actually run (#4254).

``scripts/ci_dark_flag_sweep.py`` (#3315) derives each CI job's installed set from its
``run:`` blocks. A ``uses: ./.github/actions/<name>`` step used to be opaque to it, which
was harmless while no local composite installed packages (``setup-ci`` installs none, per
the #3234 lesson). #4254 moved the visual-QA jobs' copied Playwright install into
``.github/actions/playwright-browser``, so the sweep has to see through a local composite.
Otherwise every visual-QA step would read as reaching playwright/boto3/pillow while its
job "never installs" them.

``local_composite_run(uses, with_, repo)`` returns the concatenated ``run:`` text of the
composite's steps, with each ``${{ inputs.X }}`` replaced by the caller's ``with:`` value
or the input's declared default. It returns "" for a remote action, a missing action.yml
or a non-composite action. Any other ``${{ … }}`` expression is left in place, and the
sweep's regexes already skip ``$``-prefixed tokens.
"""

from __future__ import annotations

import os
import re

_INPUT_EXPR = re.compile(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}")


def local_composite_run(uses: str, with_: dict, repo: str) -> str:
    if not uses.startswith("./"):
        return ""
    path = os.path.join(repo, uses[2:].split("@")[0], "action.yml")
    if not os.path.isfile(path):
        return ""
    import yaml  # local, like every other yaml reader in scripts/: keeps the module importable

    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    runs = doc.get("runs") or {}
    if runs.get("using") != "composite":
        return ""
    values = {k: str((v or {}).get("default", "")) for k, v in (doc.get("inputs") or {}).items()}
    values.update({k: str(v) for k, v in (with_ or {}).items()})
    text = "\n".join(str(st.get("run") or "") for st in runs.get("steps") or [] if isinstance(st, dict))
    return _INPUT_EXPR.sub(lambda m: values.get(m.group(1), m.group(0)), text)
