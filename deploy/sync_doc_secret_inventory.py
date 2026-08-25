"""deploy/sync_doc_secret_inventory.py — the `--refresh-secrets` discovery leg of
`sync_doc_metadata.py`, extracted whole (#1665 module-size ratchet: the parent sat at
exactly its 1253-line baseline, and the 2026-08-25 catalog-stamp fix needed room; the
guard's sanctioned growth path is extraction, never a baseline bump).

Behaviour is unchanged and the seam is thin on purpose: `sync_doc_metadata.py --refresh-secrets`
still calls `refresh_secret_count()`, which still rewrites the `"secret_count"` literal
IN `sync_doc_metadata.py` (the literal deliberately stays in the parent — it is part of
PLATFORM_FACTS, and this module is a discovery command, not a second facts home).

Why this is a flag and not another `_auto_discover_*` (#1957): the secret inventory
exists only in AWS — nothing in the repo can derive it. Discovering it inline would make
the sync's OUTPUT depend on whether the caller happened to hold credentials, so a
credentialed `--apply` and a credential-free `--check` would stamp different numbers and
fight each other forever. Instead discovery is an explicit, deterministic-output command:
it updates the literal + its verification date, and `scripts/doc_facts_ops.py` reds CI
when that date goes stale (>90d). That closes the "manufactured freshness" hole — the
doc-sync re-stamping "Last updated" over a count nobody had verified since 2026-07-10 —
without introducing environment-dependent docs.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The file whose `"secret_count"` literal this command rewrites.
_FACTS_FILE = Path(__file__).parent / "sync_doc_metadata.py"


def refresh_secret_count() -> int:
    """Read the LIVE Secrets Manager inventory and rewrite the `secret_count` literal
    (number + `live-verified` date) in sync_doc_metadata.py. Read-only in AWS."""
    import boto3

    client = boto3.client("secretsmanager", region_name="us-west-2")
    names = []
    kwargs: dict = {"MaxResults": 100}
    while True:
        page = client.list_secrets(**kwargs)
        names += [s["Name"] for s in page.get("SecretList", [])]
        token = page.get("NextToken")
        if not token:
            break
        kwargs["NextToken"] = token
    live = sorted(n for n in names if n.startswith("life-platform/"))
    src = _FACTS_FILE.read_text(encoding="utf-8")
    today = datetime.now(timezone.utc).date().isoformat()
    new_src, n = re.subn(
        r'"secret_count": \d+,  # live-verified \d{4}-\d{2}-\d{2}',
        f'"secret_count": {len(live)},  # live-verified {today}',
        src,
        count=1,
    )
    if n != 1:
        print("error: could not locate the secret_count literal to rewrite", file=sys.stderr)
        sys.exit(2)
    _FACTS_FILE.write_text(new_src, encoding="utf-8")
    print(f"  secret_count → {len(live)} (live-verified {today}, region us-west-2)")
    for name in live:
        print(f"    {name}")
    print("\n  Next: python3 deploy/sync_doc_metadata.py --apply   (propagate to the docs)")
    return len(live)
