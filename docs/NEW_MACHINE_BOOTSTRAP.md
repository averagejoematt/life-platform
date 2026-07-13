# New-Machine Bootstrap — bare metal to operational

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-13 (reconciled #1026 status — memory backup landed + live; datadrops + ingest are manual by decision, no FDA grant, §3c; fixed the datadrops S3 prefix; added .config.json regen §3b)
> **Sources of truth:** `docs/AWS_ACCESS.md` (auth) · `docs/QUICKSTART.md` (toolchain + deploy tree) · `docs/CONTINUITY.md` (the laptop-only state surfaces) · `ingest/README.md` (drop-folder runtime) · `requirements-dev.txt` (pinned dev deps)

This is the **from-zero rebuild runbook**: a fresh Mac, nothing installed, no
credentials — to a machine that can operate and deploy the platform again. It is the
layer *below* `docs/QUICKSTART.md`: QUICKSTART assumes you already have the toolchain and
AWS access and jumps to "run tests / deploy a Lambda"; this page gets you to that
starting line and restores the two assets that live **only on the laptop**.

It exists because of the 2026-07-11 stolen-laptop resilience audit (epic **#1024**):
`docs/CONTINUITY.md` §7–8 documents each piece of the local runtime, but no single
*ordered* runbook stitched them into one rebuild. Companion pages from the same audit:
**#1027** adds the "stolen/lost laptop" rotation scenario to `docs/DISASTER_RECOVERY.md`;
**#1026** is the scheduled backup that keeps the laptop-only state restorable (its status
is called out in step 4).

**The bar:** with only this repo, AWS access, and the S3 backups, a competent engineer
rebuilds an operable machine in well under an hour — nothing irreplaceable dies with the
laptop.

> **This page duplicates nothing.** Each step points at the one authoritative doc and
> states only the *order* and the *rebuild-specific* gotchas. Follow the links.

---

## What actually lives only on the laptop

Almost everything has a durable home already: **code** is in git (GitHub), **normalized
data + platform memory** is in DynamoDB (PITR), **raw data** is in S3, the **backlog** is
GitHub Issues. Two things are laptop-only and are the whole reason this runbook exists
(`docs/CONTINUITY.md` §4 + §7):

1. **Claude Code file-memory dir** — `~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/` (`MEMORY.md` + ~104 topic files). Not in git. Backed up to `s3://matthew-life-platform/claude-memory-backup/`.
2. **The macOS launchd ingest runtime** — the drop-folder watchers that pull manual sources (Apple Health, MacroFactor). The *code* survives in git (`ingest/`); the *running agent* dies with the laptop. Scheduled AWS ingestion keeps running; manual-drop sources silently stop until the agent is reinstalled.

A third, softer asset: **`datadrops/`** (gitignored) holds the original source drops
(genome, physicals xlsx, Apple Health exports, backfill CSVs). Its S3 archive is what
**#1026** provisions — see step 4 for its current status.

A fourth, **regenerable** asset: **`.config.json`** (repo root, gitignored) — the local
MCP bridge config `mcp_bridge.py` reads (Claude Desktop → the `life-platform-mcp` Lambda).
It holds `api_key` + `function_name` + `region`. It is NOT a single point of loss: the
`api_key` is just a copy of the `life-platform/mcp-api-key` secret, so a new machine
recreates it from Secrets Manager (step 3b below). Never commit it.

---

## Prerequisites — the toolchain

Install these first (Homebrew is the easy path on macOS). Versions and verify-commands
are the authoritative table in **`docs/QUICKSTART.md` → "System Requirements"** — match
them, don't guess:

| Tool | Version | Why |
|---|---|---|
| Python | **3.12 exactly** (not 3.13) | the Lambda runtime is 3.12; tests must run on what production runs |
| Node.js | 18+ | CDK CLI requirement |
| AWS CLI | 2.x | all AWS access |
| GitHub CLI (`gh`) | current | clone over HTTPS + issue/PR workflow |
| CDK CLI (`aws-cdk`) | pinned — see below | infra deploys |

```bash
brew install python@3.12 node awscli gh git
python3 --version   # → 3.12.x
aws --version       # → aws-cli/2.x
```

The CDK **CLI** is a pinned global npm package; the CDK **libraries** are Python packages
in `cdk/requirements.txt`. Both pins are load-bearing (#814) — install them in step 2b at
the versions QUICKSTART pins, never "whatever npm resolves as latest".

---

## Step 1 — Clone the repo

The canonical clone path is `~/Documents/Claude/life-platform` (the memory-dir slug,
several scripts, and the launchd plists all encode this exact path — cloning elsewhere
breaks the drop folders and the memory-dir location).

```bash
gh auth login                                   # or: use an SSH key with github.com:averagejoematt
git clone https://github.com/averagejoematt/life-platform.git \
  ~/Documents/Claude/life-platform
cd ~/Documents/Claude/life-platform
```

(SSH form: `git clone git@github.com:averagejoematt/life-platform.git ~/Documents/Claude/life-platform` — same as `docs/QUICKSTART.md` §1.)

---

## Step 2 — Python env + dev deps

This is verbatim `docs/QUICKSTART.md` §1 "Clone + install" and "CDK setup" — the pins in
`requirements-dev.txt` and `cdk/requirements.txt` must match CI's enforced gate versions
(black/ruff/flake8/playwright), so install from the files, not by hand.

### 2a. Runtime + dev tooling

```bash
python3 -m venv .venv                 # python3 must be 3.12.x
source .venv/bin/activate
pip install -r requirements-dev.txt   # pytest, black, ruff, flake8, playwright, boto3 — pinned to CI
pip install -r cdk/requirements.txt   # aws-cdk-lib + constructs (pinned)
playwright install chromium           # browser for tests/visual_qa.py (local visual QA)
bash scripts/install_hooks.sh         # pre-commit: black/ruff gate + doc-metadata sync
```

There is **no** `pip install anthropic` — runtime inference is AWS Bedrock via boto3/IAM
(ADR-062). There is **no** `.env` file anywhere: every credential is either a human AWS
identity (step 3) or a service secret in Secrets Manager (see "Secrets" below).

### 2b. CDK CLI (first time only)

```bash
npm install -g aws-cdk@2.1129.0                 # match the pin in .github/workflows/ci-cd.yml
cdk bootstrap aws://205930651321/us-west-2      # one-time per account (usually already bootstrapped)
```

Full detail (and why both pins move together as one deliberate PR): `docs/QUICKSTART.md` → "CDK setup".

---

## Step 3 — AWS access

**The one authoritative procedure is `docs/AWS_ACCESS.md`. Follow it; this is only the
order + the rebuild caveat.** The platform is account **205930651321**, region
**us-west-2** (Oregon).

- **Primary path — IAM Identity Center (SSO):** `aws configure sso` once, then
  `aws sso login` daily (`docs/AWS_ACCESS.md` §2).
- **Rebuild caveat (audit finding):** Identity Center is flagged **"being provisioned as
  of 2026-07-10"** in `docs/AWS_ACCESS.md` §2. If SSO is not yet live on this account, a
  fresh machine must bootstrap with the **break-glass `matthew-admin` access keys**
  (`docs/AWS_ACCESS.md` §3) — which means the keys must be reachable from *off* the lost
  laptop (a password manager / hardware token, never the repo). This owner-only re-entry
  risk is exactly what epic **#1024** and the **#1027** rotation scenario track.

Human keys live **only** in `~/.aws/credentials` (or the OS keychain) — never in `.env`,
never in the repo, never in Secrets Manager (`docs/AWS_ACCESS.md` §3, "The rule").

Verify before continuing:

```bash
aws sts get-caller-identity                                  # → Account: 205930651321
aws s3 ls s3://matthew-life-platform/site/ --region us-west-2 | head   # harmless read
```

### Secrets (nothing to "restore")

Service credentials (Whoop, Garmin, Withings, …) live in **Secrets Manager** under the
`life-platform/` prefix (`docs/SECRETS_MAP.md`) — they are account-side, not laptop-side,
so a new machine inherits them the moment AWS auth works. Nothing to copy. OAuth tokens
that rotate (Whoop/Garmin) may need a browser re-auth — that is a *data-source* task, not
a bootstrap task: see `docs/RUNBOOK_REENTRY.md`.

### 3b. Recreate `.config.json` (local MCP bridge)

`mcp_bridge.py` (Claude Desktop → the MCP Lambda) reads a gitignored `.config.json` at the
repo root. Its `api_key` is the `life-platform/mcp-api-key` secret, so regenerate it from
Secrets Manager rather than restoring a copy:

```bash
cd ~/Documents/Claude/life-platform
KEY=$(aws secretsmanager get-secret-value --secret-id life-platform/mcp-api-key \
  --region us-west-2 --query SecretString --output text)
cat > .config.json <<JSON
{"api_key": "$KEY", "function_name": "life-platform-mcp", "region": "us-west-2"}
JSON
```

### 3c. TCC posture — no Full Disk Access grant (by decision, 2026-07-13)

macOS TCC blocks launchd agents from reading `~/Documents` (the launchd-TCC trap). The
obvious "fix" — granting Full Disk Access to `/bin/bash` — is **rejected**: it would hand
FDA to *every* shell script on the machine, far too broad. Instead we accept that the two
things which read `~/Documents` are **low-churn and run manually**, while the one
high-churn asset (Claude memory) lives in `~/.claude` and backs up automatically with no
grant at all. So there is **nothing to grant here** — the split is:

| Asset | Cadence | How |
|---|---|---|
| Claude memory dir | high (every session) | **automated** daily launchd (step 5b) + `/wrap` sync — reads `~/.claude`, never TCC-blocked |
| `datadrops/` originals | low (new genome/labs/export) | **manual** push from a Terminal (step 4b/5b) |
| Manual-drop ingest | occasional CSV/zip | **manual** run from a Terminal (step 5a) |

An interactive Terminal launched from Finder already has disk access via your login
session, so the manual commands "just work" without any standing grant. If you later
decide you *want* these two automated, the secure route is relocating their folders out of
`~/Documents` (TCC only protects Documents/Desktop/Downloads/iCloud) — not an FDA grant.

---

## Step 4 — Restore the laptop-only state from S3

### 4a. Claude Code file-memory dir

Restore the memory dir from its S3 backup into the exact per-machine path
(`docs/CONTINUITY.md` §4):

```bash
aws s3 sync s3://matthew-life-platform/claude-memory-backup/ \
  ~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/ \
  --region us-west-2
```

> **Freshness.** The scheduled backup job (**#1026**) has **landed and runs daily** via
> launchd (`com.matthewwalker.claude-memory-backup`, step 5b) — the memory leg reads
> `~/.claude`, which TCC never blocks, so it works today. The `/wrap`-step manual sync
> (`docs/CONTINUITY.md` §4) stays as belt-and-suspenders. So the restored memory is at
> worst one day stale, not one session stale.

Never commit this directory or its export to the repo — even with the repo private (since
2026-07-13), memory files carry personal + security-incident detail by design and stay out
of git (`docs/CONTINUITY.md` §4; visibility can flip back).

### 4b. `datadrops/` originals

```bash
# datadrops lands under the TOP-LEVEL, delete-protected datadrops-archive/ prefix
# (NOT uploads/ — that expires in 30 days). Restore into the repo's datadrops/:
aws s3 sync s3://matthew-life-platform/datadrops-archive/ \
  ~/Documents/Claude/life-platform/datadrops/ --region us-west-2
```

**The archive fills from a manual push, not the daily job (see §3c).** `datadrops/` is
low-churn and backed up by running the push from a Terminal whenever you add a drop:

```bash
BACKUP_DATADROPS=1 bash ~/.local/bin/claude-memory-backup.sh   # reads ~/Documents; run from Terminal
```

If that push has never been run on the source machine, `datadrops-archive/` may be empty
and the originals (genome, physicals xlsx, Apple Health exports) live only on the old
laptop — treat an empty archive as "the manual push was never run," not a bug.

---

## Step 5 — Reinstall the launchd runtime

### 5a. The ingest drop-folder watcher

> **No-FDA posture (§3c):** the watcher's folders live under `~/Documents`, so the launchd
> agent can't auto-fire without a Full Disk Access grant we deliberately don't make. Under
> the current posture, **ingest is manual**: drop your CSV/zip, then process it from a
> Terminal (which has disk access via your login session):
> ```bash
> cd ~/Documents/Claude/life-platform && bash ingest/process_all_drops.sh
> ```
> Installing the agent below is still fine (harmless, and it works instantly if you ever
> do relocate the drop folders out of `~/Documents`), but don't rely on it auto-firing.

The ingest agent is installed with **one command** (`docs/CONTINUITY.md` §7,
`ingest/README.md`):

```bash
cd ~/Documents/Claude/life-platform/ingest
chmod +x install.sh process_all_drops.sh
./install.sh
```

This registers `com.matthewwalker.life-platform-ingest` with launchd and starts watching:

| Drop folder | Source | Status |
|---|---|---|
| `~/Documents/Claude/habits_drop/` | Chronicling CSV | archived (Habitify replaced it; still works for historical backfills) |
| `~/Documents/Claude/macrofactor_drop/` | MacroFactor nutrition/workout CSV | active |
| `~/Documents/Claude/apple_health_drop/` | Apple Health `.zip` / `export.xml` | active |

**Re-point the drop folders:** the watched folders are siblings of the repo under
`~/Documents/Claude/`. `install.sh` creates the launchd agent, but if you cloned to the
canonical path they resolve automatically; recreate the three folders if the fresh Mac
doesn't have them (`mkdir -p ~/Documents/Claude/{habits,macrofactor,apple_health}_drop`).
Confirm with `./install.sh status`.

There is a second launchd plist — the calendar-sync agent
(`setup/com.matthewwalker.calendar-sync.plist`); install it the same way if calendar sync
is in use.

### 5b. The scheduled backup job (#1026)

**#1026 has landed** (commit `48f635e3`); its installer + plist live in `backup/`. Install
the daily agent that snapshots the step-4 state into versioned, private S3:

```bash
cd ~/Documents/Claude/life-platform/backup
bash install.sh   # copies backup.sh → ~/.local/bin, loads the launchd plist
```

This registers `com.matthewwalker.claude-memory-backup` (daily + RunAtLoad). The **memory
leg works immediately** (it reads `~/.claude`, never TCC-blocked). The daily job **skips
the datadrops leg by design** (§3c) — back that up manually when you add a drop:
`BACKUP_DATADROPS=1 bash ~/.local/bin/claude-memory-backup.sh` from a Terminal.

---

## Step 6 — Verify the machine is operational

Run these in order; each proves one layer of the rebuild.

**Auth + toolchain**

```bash
aws sts get-caller-identity          # → Account: 205930651321  (step 3)
python3 --version                    # → 3.12.x                 (prereq)
python3 -m pytest tests/ -v          # the suite CI runs — green means the code env is sound
flake8 lambdas/ mcp/                 # lint gate parity
```

**The live platform is reachable** — `/version.json` is the site build fingerprint (it
equals the deployed git HEAD; see the build-fingerprint note in project memory):

```bash
curl -s https://averagejoematt.com/version.json    # → JSON with the live commit SHA
```

**Deploy paths resolve** (don't actually deploy from a rebuild unless you mean to — deploy
happens from `main`; see `docs/CONVENTIONS.md`):

```bash
cd cdk && npx cdk diff LifePlatformCore   # synth + diff works → CDK toolchain is wired
```

**Laptop-only state restored**

```bash
# One memory read round-trips:
head -20 ~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/MEMORY.md

# One manual drop round-trips end-to-end (ingest runtime is live):
#   drop a small MacroFactor CSV into ~/Documents/Claude/macrofactor_drop/
#   → within seconds it moves to processed/ and appears in ingest.log
tail -20 ~/Documents/Claude/life-platform/ingest/ingest.log
```

If `aws sts get-caller-identity` returns the right account, the pytest suite is green,
`/version.json` responds, a memory read works, and a manual drop round-trips — the machine
is fully operational.

---

## Where to go next

- `docs/QUICKSTART.md` — "I edited X, what do I run?" deploy decision tree + first Lambda deploy.
- `docs/ONBOARDING.md` — the mental model (what this system is, in one page).
- `docs/CONTINUITY.md` — the full map of every state surface outside `docs/` and how to read/export each.
- `docs/AWS_ACCESS.md` — the authoritative auth procedure (SSO, break-glass, CI's OIDC roles).
- `docs/DISASTER_RECOVERY.md` — restore procedures + (per #1027) the stolen/lost-laptop rotation scenario.
- `docs/RUNBOOK.md` — daily operations and troubleshooting.
