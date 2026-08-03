# seeds/

Test/dev bootstrap **data generators** for DynamoDB state (`seed_*.py`). Idempotent
scripts that write starter records; not throwaway fixtures, and not one-shot migrations
(those go to `patches/`/`backfill/`). See `docs/REPO_STRUCTURE.md`.

**No JSON catalogs live here any more (#2084).** `challenges_catalog.json` and
`content_filter.json` used to sit in this directory and reach production through a
one-time `aws s3 cp` into the bucket-root `config/` prefix. That gave those live objects
a traceable origin and *no integrity assertion* — and the challenges catalog duly drifted,
leaving `/api/challenges` serving a superseded cast for weeks while every gate reported
green. Both are now `config/` twins: byte-asserted by `deploy/config_twin_sync.py`,
deployed on merge by `.github/workflows/site-deploy.yml`, and audited daily by
`deploy/config_mirror_audit.py`.

**If you are about to add a JSON file here that something will read in production: don't.**
Put it in `config/`. It joins the derived twin set automatically.
