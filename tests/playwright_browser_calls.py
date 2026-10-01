"""The visual-QA install composite, expanded for the workflow text guards (#4254).

Four visual-QA jobs (ci-cd.yml, site-deploy.yml, visual-qa.yml and webkit-mobile-qa.yml)
used to carry a copied "Install Playwright + <browser>" run block. Each copy was pinned by
text guards: boto3 installed (#2938), pillow installed (#2973), playwright resolved through
scripts/ci_pins.py (#2609) and the webkit engine installed (#1434). #4254 moved the block
into ONE composite, ``.github/actions/playwright-browser``, so a caller now says only
``browser:`` and, optionally, ``pins:``.

``expanded(text)`` appends to a workflow's text the two lines each composite call
actually executes, so those guards keep asserting what the RUNNER does rather than a
string that has moved. ``tests/test_site_deploy_workflow.py`` pins the composite's own
run block to the shape this expansion assumes, so the two cannot drift apart silently.
"""

from __future__ import annotations

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTION_REF = "./.github/actions/playwright-browser"
ACTION_PATH = os.path.join(REPO_ROOT, ".github", "actions", "playwright-browser", "action.yml")

_CALL = re.compile(
    r"uses:\s*" + re.escape(ACTION_REF) + r"\s*\n(?P<indent>\s*)with:\s*\n(?P<body>(?:(?P=indent)  [\w-]+:[^\n]*\n)+)",
)


def action_text() -> str:
    with open(ACTION_PATH, encoding="utf-8") as f:
        return f.read()


def default_pins() -> str:
    m = re.search(r"\n  pins:\n(?:    [^\n]*\n)*?    default: '([^']*)'", action_text())
    assert m, f"{ACTION_PATH} declares no default for the `pins` input"
    return m.group(1)


def calls(text: str) -> list[dict[str, str]]:
    """Each composite call's inputs, with the composite's defaults filled in."""
    out = []
    for m in _CALL.finditer(text):
        inputs = dict(re.findall(r"^\s*([\w-]+):\s*(.*?)\s*$", m.group("body"), re.M))
        inputs.setdefault("pins", default_pins())
        out.append(inputs)
    return out


def expanded(text: str) -> str:
    """The workflow text plus the install lines every composite call executes."""
    lines = []
    for c in calls(text):
        lines.append(f"PINS=$(python3 scripts/ci_pins.py {c['pins']})")
        lines.append(f"python -m playwright install --with-deps {c.get('browser', '')}")
    return text + ("\n" + "\n".join(lines) + "\n" if lines else "")
