#!/usr/bin/env python3
"""
scripts/expected_csp.py — print the Content-Security-Policy the deployed
averagejoematt.com distribution is EXPECTED to serve, derived from source
(#3048, DIL-015).

The source of truth is cdk/stacks/csp.py (stdlib-only by design — ADR-149) plus
the native-embeds context flag in cdk/cdk.json. deploy/smoke_test_site.sh
compares the live response header against this output, so:

  * the smoke assertion can never drift from the policy the CDK would deploy;
  * a csp.py edit that re-widens script-src is caught by
    tests/test_csp_hardening_3048.py (source pin), while a live distribution
    that drifts from source is caught by the smoke compare — together they are
    mutation-proof in both directions.

Usage:
    python3 scripts/expected_csp.py            # the hardened main-domain policy
    python3 scripts/expected_csp.py --legacy   # the /legacy/* compat policy
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "cdk"))

from stacks.csp import AMJ_CONNECT_SRC, NATIVE_EMBED_CONTEXT_KEY, build_site_csp, native_embeds_enabled  # noqa: E402


def expected_amj_csp(hardened: bool = True) -> str:
    ctx = json.loads((_ROOT / "cdk" / "cdk.json").read_text(encoding="utf-8")).get("context", {})
    return build_site_csp(
        connect_src=AMJ_CONNECT_SRC,
        hardened_scripts=hardened,
        native_social_embeds=native_embeds_enabled(ctx.get(NATIVE_EMBED_CONTEXT_KEY)),
    )


if __name__ == "__main__":
    print(expected_amj_csp(hardened="--legacy" not in sys.argv[1:]))
