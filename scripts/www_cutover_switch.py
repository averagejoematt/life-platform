#!/usr/bin/env python3
"""scripts/www_cutover_switch.py — flip (or read) the v9 cut-over switch in www/owned_paths.json (#5534).

The switch is ONE committed bit, `live_at_root`. While it is false the v9 build is served at /next/v9/
only and `/` is the v8 kit page from site/. When it is true: every `www/**` merge deploys the build to
`/` (web-preview-deploy.yml, target root), qa/qa_manifest.py describes `/`, /story/, /data/, /privacy/
and 404.html as the v9 pages, scripts/v4_build_sitemap.py stops writing sitemap.xml (the build writes
it), and tests/test_site_nav_reach_ratchet.py reads www/reach.json. Flipping it is a one-line PR; the
owner's go is that merge (his five-reader bar is recorded on #5529 first — that is his, not this
script's). Nothing else in the repo flips it.

  python3 scripts/www_cutover_switch.py            # print the current state
  python3 scripts/www_cutover_switch.py --live     # set live_at_root=true, stamp flipped_on=today
  python3 scripts/www_cutover_switch.py --preview  # set it back to false (the deliberate un-launch's repo half)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(REPO, "www", "owned_paths.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--live", action="store_true")
    g.add_argument("--preview", action="store_true")
    ap.add_argument("--path", default=PATH)
    args = ap.parse_args(argv)
    with open(args.path, encoding="utf-8") as fh:
        data = json.load(fh)
    if args.live or args.preview:
        data["live_at_root"] = bool(args.live)
        data["flipped_on"] = dt.date.today().isoformat() if args.live else None
        with open(args.path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    state = "LIVE at / (every www/** merge deploys the root)" if data.get("live_at_root") else "preview only (/next/v9/)"
    print(
        f"www cut-over switch: live_at_root={json.dumps(data.get('live_at_root'))} flipped_on={json.dumps(data.get('flipped_on'))} — {state}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
