# Life Platform — Ingest System

Automated drop-folder processing for all manual health data uploads.

## How it works

A single macOS launchd agent watches three drop folders. Any time a file lands in one, processing starts within seconds — no manual steps needed.

The drop folders live **inside the checkout**, under `datadrops/` — they are not siblings
of the repo and never were under `~/Documents`. `datadrops/` is gitignored, so a fresh
clone has none of them: create them before installing the agent (see Setup). launchd
cannot watch a directory that does not exist, and a watcher with no folder to watch fails
silently — the scan runs, finds nothing, and exits 0.

| Drop Folder | What to drop | Processed by | Status |
|---|---|---|---|
| `datadrops/habits_drop/` | Chronicling CSV export | `backfill_chronicling.py` | **ARCHIVED** — Chronicling replaced by Habitify (v2.7.0); folder still works for historical backfills |
| `datadrops/macrofactor_drop/` | MacroFactor nutrition or workout CSV | `backfill_macrofactor.py` / `backfill_macrofactor_workouts.py` | Active |
| `datadrops/apple_health_drop/` | Apple Health `.zip` or `export.xml` | `backfill_apple_health.py` | Active |

## Setup (one time)

```bash
cd /Users/matthewwalker/dev/life-platform
mkdir -p datadrops/{habits,macrofactor,apple_health}_drop   # gitignored; absent on a fresh clone
cd ingest
chmod +x install.sh process_all_drops.sh
./install.sh
```

This registers the launchd agent and disables the old `macrofactor-drop` watcher.

## Daily use

**Chronicling (habits) — ARCHIVED:**
Chronicling has been replaced by Habitify as of v2.7.0. Habitify syncs automatically via API (6:15 AM PT daily). The habits_drop folder still works if you need to backfill historical Chronicling data:
1. Open Chronicling → Settings → Export Data → **Events CSV** (not groups or categories)
2. Drop the file into `datadrops/habits_drop/`
3. Script is incremental: only dates newer than your last upload are written

**MacroFactor:**
1. More → Data Management → Data Export
2. Drop CSV into `datadrops/macrofactor_drop/`
3. Script auto-detects nutrition vs workout format

**Apple Health:**
1. Health app → profile pic → Export All Health Data → share the zip
2. Drop the `.zip` into `datadrops/apple_health_drop/`
3. Script unzips and processes

## Checking status

```bash
# Is the watcher running?
./install.sh status

# View recent logs
tail -50 ingest.log

# Test manually (runs all folders immediately)
bash process_all_drops.sh
```

## File lifecycle

```
habits_drop/
  my_export.csv          ← you drop it here
  processed/
    my_export_20260222143022.csv  ← moved here on success
```

Files that fail processing are left in the drop folder for retry on next run.

## Troubleshooting

**Nothing happening after drop:**
- Check `./install.sh status`
- Check `ingest.log` for errors
- Ensure the file ends in `.csv` (habits/macrofactor) or `.zip`/`.xml` (Apple Health)

**Chronicling schema error:**
- Open the CSV and check the first row — should be: `Date, HabitName1, HabitName2, ...`
- See `backfill_chronicling.py` header for supported date formats

**Re-running a file:**
- Move it back from `processed/` to the drop folder
- The watcher will pick it up again
