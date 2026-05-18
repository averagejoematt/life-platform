#!/usr/bin/env python3
"""
patch_n1_experiments.py — N=1 Experiment Framework

Adds 4 MCP tools for tracking personal experiments:
  1. create_experiment  — Start tracking a protocol change
  2. list_experiments   — View active/completed experiments
  3. get_experiment_results — Auto-compare before vs during metrics
  4. end_experiment     — Close an experiment with outcome notes

Schema:
  PK: USER#matthew#SOURCE#experiments
  SK: EXP#<experiment_id>

Board of Directors context:
  - Attia: N=1 is the gold standard for personal optimization — population
    studies tell you averages, self-experimentation tells you YOUR response
  - Huberman: Change one variable at a time, measure for 2+ weeks minimum
  - Ferriss: "What gets measured gets managed" — the minimum effective dose
    requires tracking both the intervention and the outcome

Usage:
  python3 patches/patch_n1_experiments.py
  (patches mcp_server.py in place)
"""

import re

MCP_FILE = "mcp_server.py"

def read_file(path):
    with open(path, "r") as f:
        return f.read()

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)

# ─────────────────────────────────────────────
# Patch 1: Tool functions — insert before Lambda handler
# ─────────────────────────────────────────────

TOOL_FNS = '''

# ── N=1 Experiment Framework (v2.34.0) ────────────────────────────────────────
EXPERIMENTS_PK = "USER#matthew#SOURCE#experiments"

# Metrics automatically compared in get_experiment_results.
# Each tuple: (source, field_path, display_name, higher_is_better)
# field_path supports nested access via "." (e.g. "activities.0.average_heartrate" would be complex;
# we stick to day-level aggregates).
_EXPERIMENT_METRICS = [
    # Sleep
    ("eightsleep", "sleep_score",                "Sleep Score",          True),
    ("eightsleep", "sleep_efficiency_pct",       "Sleep Efficiency %",   True),
    ("eightsleep", "deep_sleep_pct",             "Deep Sleep %",         True),
    ("eightsleep", "rem_sleep_pct",              "REM Sleep %",          True),
    ("eightsleep", "sleep_onset_latency_min",    "Sleep Onset Latency",  False),
    # Recovery
    ("whoop",      "recovery_score",             "Whoop Recovery",       True),
    ("whoop",      "hrv_rmssd",                  "HRV (rMSSD)",         True),
    ("whoop",      "resting_heart_rate",         "Resting HR",          False),
    # Stress & Energy
    ("garmin",     "average_stress_level",       "Garmin Stress",       False),
    ("garmin",     "body_battery_high",          "Body Battery Peak",   True),
    # Body
    ("withings",   "weight_lbs",                 "Weight (lbs)",        None),  # direction depends on goal
    # Nutrition
    ("macrofactor", "calories",                  "Calories",            None),
    ("macrofactor", "protein_g",                 "Protein (g)",         None),
    # Movement
    ("apple_health", "steps",                    "Steps",               True),
    # Glucose (if available)
    ("apple_health", "cgm_mean_glucose",         "Mean Glucose",        False),
    ("apple_health", "cgm_time_in_range_pct",    "CGM Time in Range %", True),
]


def _extract_metric(item, field_path):
    """Extract a numeric value from a DynamoDB item, handling nested dicts."""
    val = item
    for part in field_path.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def tool_create_experiment(args):
    """Create a new N=1 experiment.

    Tracks a specific protocol change (supplement, diet, sleep hygiene, training
    adjustment, etc.) with start date and metrics to monitor. The system will
    automatically compare the experiment period against the equivalent pre-period
    when you call get_experiment_results.

    Board of Directors rules:
      - One variable at a time (Huberman)
      - Minimum 14 days for meaningful signal (Attia)
      - Define success criteria upfront (Ferriss)
    """
    name       = (args.get("name") or "").strip()
    hypothesis = (args.get("hypothesis") or "").strip()
    start_date = (args.get("start_date") or "").strip()
    tags       = args.get("tags") or []
    notes      = (args.get("notes") or "").strip()

    if not name:
        raise ValueError("name is required (e.g. 'Creatine 5g daily', 'No caffeine after 10am')")
    if not hypothesis:
        raise ValueError("hypothesis is required (e.g. 'Will improve deep sleep % by >5%')")

    now = datetime.utcnow()
    if not start_date:
        start_date = now.strftime("%Y-%m-%d")

    # Generate a slug-style ID
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    exp_id = f"{slug}_{start_date}"
    sk = f"EXP#{exp_id}"

    # Check for duplicate
    existing = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if existing:
        raise ValueError(f"Experiment '{exp_id}' already exists. Choose a different name or start date.")

    item = {
        "pk":           EXPERIMENTS_PK,
        "sk":           sk,
        "experiment_id": exp_id,
        "name":         name,
        "hypothesis":   hypothesis,
        "start_date":   start_date,
        "end_date":     None,       # null = still active
        "status":       "active",   # active, completed, abandoned
        "tags":         tags,
        "notes":        notes,
        "outcome":      "",
        "created_at":   now.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Clean None values for DynamoDB
    clean_item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=clean_item)
    logger.info(f"create_experiment: created {exp_id}")

    return {
        "created":       True,
        "experiment_id": exp_id,
        "name":          name,
        "hypothesis":    hypothesis,
        "start_date":    start_date,
        "status":        "active",
        "tags":          tags,
        "board_of_directors": {
            "Huberman": "One variable at a time. Track for at least 2 weeks before drawing conclusions. Control for confounders: sleep timing, stress, travel.",
            "Attia":    "Define your primary endpoint now. What number would convince you this worked? Statistical noise requires ≥14 days of data.",
            "Ferriss":  "What does the minimum effective dose look like? Start with the smallest intervention that could produce a measurable change.",
        },
    }


def tool_list_experiments(args):
    """List all N=1 experiments with status and duration.

    Filter by status: active, completed, abandoned, or all.
    Shows days active, whether minimum duration (14d) has been met.
    """
    status_filter = args.get("status")  # None = all
    today = datetime.utcnow().strftime("%Y-%m-%d")

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(EXPERIMENTS_PK) & Key("sk").begins_with("EXP#"),
        ScanIndexForward=False,
    )
    items = resp.get("Items", [])

    results = []
    for item in items:
        status = item.get("status", "active")
        if status_filter and status != status_filter:
            continue

        start = item.get("start_date", "")
        end = item.get("end_date", today)
        try:
            days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
        except Exception:
            days = None

        results.append({
            "experiment_id": item.get("experiment_id", ""),
            "name":          item.get("name", ""),
            "hypothesis":    item.get("hypothesis", ""),
            "start_date":    start,
            "end_date":      item.get("end_date"),
            "status":        status,
            "days_active":   days,
            "min_duration_met": days is not None and days >= 14,
            "tags":          item.get("tags", []),
            "notes":         item.get("notes", ""),
            "outcome":       item.get("outcome", ""),
        })

    active = sum(1 for r in results if r["status"] == "active")
    completed = sum(1 for r in results if r["status"] == "completed")

    return {
        "total":     len(results),
        "active":    active,
        "completed": completed,
        "filter":    status_filter or "all",
        "experiments": results,
    }


def tool_get_experiment_results(args):
    """Auto-compare before vs during metrics for an experiment.

    Computes the mean of key health metrics for:
      - BEFORE period: same number of days immediately before the experiment start
      - DURING period: experiment start to end (or today if still active)

    Reports: metric name, before mean, during mean, delta, % change, direction.

    Board of Directors evaluates the results with context from the hypothesis.
    """
    exp_id = (args.get("experiment_id") or "").strip()
    if not exp_id:
        raise ValueError("experiment_id is required")

    sk = f"EXP#{exp_id}"
    item = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if not item:
        raise ValueError(f"No experiment found with id={exp_id}")

    start_date = item.get("start_date", "")
    end_date = item.get("end_date") or datetime.utcnow().strftime("%Y-%m-%d")
    status = item.get("status", "active")
    hypothesis = item.get("hypothesis", "")

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid start_date or end_date on experiment")

    during_days = (end_dt - start_dt).days
    if during_days < 1:
        return {"error": "Experiment has less than 1 day of data. Check back later."}

    # Before period = same number of days before start
    before_start = (start_dt - timedelta(days=during_days)).strftime("%Y-%m-%d")
    before_end = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    during_start = start_date
    during_end = end_date

    # Gather unique sources needed
    sources_needed = list(set(m[0] for m in _EXPERIMENT_METRICS))

    # Query before + during in parallel
    before_data = {}
    during_data = {}
    for src in sources_needed:
        try:
            before_items = query_source(src, before_start, before_end)
            during_items = query_source(src, during_start, during_end)
            before_data[src] = before_items
            during_data[src] = during_items
        except Exception as e:
            logger.warning(f"get_experiment_results: failed to query {src}: {e}")

    # Compute metric comparisons
    comparisons = []
    for source, field, display_name, higher_is_better in _EXPERIMENT_METRICS:
        before_vals = []
        during_vals = []

        for item_b in before_data.get(source, []):
            v = _extract_metric(item_b, field)
            if v is not None:
                before_vals.append(v)

        for item_d in during_data.get(source, []):
            v = _extract_metric(item_d, field)
            if v is not None:
                during_vals.append(v)

        # Need at least 3 data points in each period for meaningful comparison
        if len(before_vals) < 3 or len(during_vals) < 3:
            continue

        before_mean = sum(before_vals) / len(before_vals)
        during_mean = sum(during_vals) / len(during_vals)
        delta = during_mean - before_mean
        pct_change = (delta / before_mean * 100) if before_mean != 0 else None

        # Determine if change is favorable
        if higher_is_better is True:
            direction = "improved" if delta > 0 else ("worsened" if delta < 0 else "unchanged")
        elif higher_is_better is False:
            direction = "improved" if delta < 0 else ("worsened" if delta > 0 else "unchanged")
        else:
            direction = "increased" if delta > 0 else ("decreased" if delta < 0 else "unchanged")

        comparisons.append({
            "metric":        display_name,
            "source":        source,
            "before_mean":   round(before_mean, 2),
            "during_mean":   round(during_mean, 2),
            "delta":         round(delta, 2),
            "pct_change":    round(pct_change, 1) if pct_change is not None else None,
            "direction":     direction,
            "before_n":      len(before_vals),
            "during_n":      len(during_vals),
        })

    # Sort: improved first, then worsened, then unchanged
    order = {"improved": 0, "worsened": 1, "increased": 2, "decreased": 3, "unchanged": 4}
    comparisons.sort(key=lambda c: order.get(c["direction"], 5))

    improved = [c for c in comparisons if c["direction"] == "improved"]
    worsened = [c for c in comparisons if c["direction"] == "worsened"]

    # Minimum duration warning
    min_duration_met = during_days >= 14
    duration_warning = None
    if not min_duration_met:
        duration_warning = (
            f"Only {during_days} days of data. Board recommends minimum 14 days "
            f"for reliable signal. Results may be noise."
        )

    return {
        "experiment": {
            "id":         exp_id,
            "name":       item.get("name", ""),
            "hypothesis": hypothesis,
            "status":     status,
            "start_date": start_date,
            "end_date":   end_date if status != "active" else f"{end_date} (ongoing)",
        },
        "comparison_period": {
            "before": f"{before_start} → {before_end} ({during_days} days)",
            "during": f"{during_start} → {during_end} ({during_days} days)",
        },
        "duration_warning":  duration_warning,
        "metrics_compared":  len(comparisons),
        "improved_count":    len(improved),
        "worsened_count":    len(worsened),
        "comparisons":       comparisons,
        "board_of_directors": {
            "Attia": (
                f"{'✅ Minimum 14-day threshold met.' if min_duration_met else '⚠️ Under 14 days — treat as preliminary.'} "
                f"{'Strong signal: ' + str(len(improved)) + ' metrics improved.' if len(improved) > len(worsened) else ''} "
                f"Look at effect sizes, not just direction. A 1% change is noise; 5%+ over 14+ days is signal."
            ),
            "Huberman": (
                "Check for confounders: did sleep timing, stress, travel, or other habits change during this period? "
                "The strongest signal is when multiple related metrics move in the same direction."
            ),
            "Ferriss": (
                f"Hypothesis: '{hypothesis}'. "
                f"{'The data supports this hypothesis.' if len(improved) > len(worsened) else 'The data does not clearly support this hypothesis.'} "
                "Consider: is the juice worth the squeeze? Even a positive result needs to be sustainable."
            ),
        },
    }


def tool_end_experiment(args):
    """End an active experiment and record the outcome.

    Marks the experiment as 'completed' or 'abandoned' with outcome notes.
    Run get_experiment_results first to see the data before closing.
    """
    exp_id  = (args.get("experiment_id") or "").strip()
    outcome = (args.get("outcome") or "").strip()
    status  = (args.get("status") or "completed").strip()
    end_date = (args.get("end_date") or "").strip()

    if not exp_id:
        raise ValueError("experiment_id is required")
    if status not in ("completed", "abandoned"):
        raise ValueError("status must be 'completed' or 'abandoned'")

    sk = f"EXP#{exp_id}"
    existing = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if not existing:
        raise ValueError(f"No experiment found with id={exp_id}")
    if existing.get("status") != "active":
        raise ValueError(f"Experiment is already {existing.get('status')} — cannot end again")

    if not end_date:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")

    table.update_item(
        Key={"pk": EXPERIMENTS_PK, "sk": sk},
        UpdateExpression="SET #s = :s, outcome = :o, end_date = :e, ended_at = :ea",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s":  status,
            ":o":  outcome,
            ":e":  end_date,
            ":ea": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    logger.info(f"end_experiment: {exp_id} → {status}")

    start_date = existing.get("start_date", "")
    try:
        days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days
    except Exception:
        days = None

    return {
        "ended":         True,
        "experiment_id": exp_id,
        "name":          existing.get("name", ""),
        "status":        status,
        "start_date":    start_date,
        "end_date":      end_date,
        "days_run":      days,
        "outcome":       outcome,
        "tip":           "Run get_experiment_results to see the full before/after comparison.",
    }

'''

# ─────────────────────────────────────────────
# Patch 2: TOOLS dict entries
# ─────────────────────────────────────────────

TOOLS_ENTRIES = '''    "create_experiment": {
        "fn": tool_create_experiment,
        "schema": {
            "name": "create_experiment",
            "description": (
                "Start tracking a new N=1 experiment. An experiment is a specific protocol change "
                "(supplement, diet shift, sleep hygiene tweak, training adjustment) with a hypothesis "
                "and start date. The system will automatically compare before/after metrics when you "
                "call get_experiment_results. Board rules: one variable at a time, minimum 14 days, "
                "define success criteria upfront. "
                "Use for: 'I'm starting creatine today', 'track my no-caffeine-after-10am experiment', "
                "'create experiment for cold plunge protocol', 'I want to test if X improves Y'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name":       {"type": "string", "description": "Short name of the intervention (e.g. 'Creatine 5g daily', 'No screens after 9pm')."},
                    "hypothesis": {"type": "string", "description": "What you expect to happen (e.g. 'Will improve deep sleep % by >5%')."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to today."},
                    "tags":       {"type": "array", "items": {"type": "string"},
                                   "description": "Optional tags (e.g. ['sleep', 'supplement', 'caffeine'])."},
                    "notes":      {"type": "string", "description": "Additional context or protocol details."},
                },
                "required": ["name", "hypothesis"],
            },
        },
    },
    "list_experiments": {
        "fn": tool_list_experiments,
        "schema": {
            "name": "list_experiments",
            "description": (
                "List all N=1 experiments with their status, duration, and whether minimum "
                "data threshold (14 days) has been met. Filter by status. "
                "Use for: 'what experiments am I running?', 'show active experiments', "
                "'list completed experiments', 'any experiments ready to evaluate?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter: 'active', 'completed', 'abandoned'. Omit for all."},
                },
                "required": [],
            },
        },
    },
    "get_experiment_results": {
        "fn": tool_get_experiment_results,
        "schema": {
            "name": "get_experiment_results",
            "description": (
                "Auto-compare before vs during metrics for an N=1 experiment. "
                "Automatically queries sleep, recovery, stress, body composition, nutrition, "
                "movement, and glucose metrics for both the pre-experiment baseline period "
                "and the experiment period. Reports deltas, % changes, and direction "
                "(improved/worsened). Board of Directors evaluates results against hypothesis. "
                "Use for: 'how is my creatine experiment going?', 'did cutting caffeine help my sleep?', "
                "'show experiment results', 'evaluate my N=1', 'did this actually work?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string", "description": "The experiment_id from create_experiment or list_experiments."},
                },
                "required": ["experiment_id"],
            },
        },
    },
    "end_experiment": {
        "fn": tool_end_experiment,
        "schema": {
            "name": "end_experiment",
            "description": (
                "End an active N=1 experiment and record the outcome. "
                "Run get_experiment_results first to review the data. "
                "Status can be 'completed' (ran full course) or 'abandoned' (stopped early). "
                "Use for: 'end my creatine experiment', 'I'm stopping the no-caffeine experiment', "
                "'mark experiment as completed', 'abandon experiment X'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string", "description": "The experiment_id to end."},
                    "outcome":       {"type": "string", "description": "What happened — did it work? What did you learn?"},
                    "status":        {"type": "string", "description": "'completed' (default) or 'abandoned'."},
                    "end_date":      {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["experiment_id"],
            },
        },
    },
'''


def main():
    content = read_file(MCP_FILE)

    # Check if already patched
    if "EXPERIMENTS_PK" in content:
        print("⏭️  mcp_server.py already has experiment tools — skipping")
        return

    # Insert tool functions before Lambda handler
    anchor = "# ── Lambda handler"
    if anchor not in content:
        raise ValueError(f"Could not find anchor '{anchor}' in {MCP_FILE}")
    content = content.replace(anchor, TOOL_FNS + anchor)

    # Insert TOOLS dict entries before the closing brace of TOOLS dict
    # The TOOLS dict ends with:  "    },\n\n}\n"
    # We need to add our entries between the last tool and the closing }
    tools_close = "    },\n\n}\n\n\n# ── MCP protocol handlers"
    if tools_close not in content:
        # Try without triple newline
        tools_close = "    },\n\n}\n\n# ── MCP protocol handlers"
    if tools_close not in content:
        raise ValueError("Could not find TOOLS dict closing pattern before MCP protocol handlers")
    new_tools_close = "    },\n" + TOOLS_ENTRIES + "\n}\n\n# ── MCP protocol handlers"
    content = content.replace(tools_close, new_tools_close, 1)

    # Add 'import re' if not already present (needed for slug generation in create_experiment)
    if "import re\n" not in content:
        content = content.replace("import json\n", "import json\nimport re\n", 1)
        print("  Added 'import re' to imports")

    write_file(MCP_FILE, content)

    # Verify tool count
    tool_count = content.count('"fn":')
    print(f"✅ mcp_server.py patched with N=1 experiment framework ({tool_count} tools)")


if __name__ == "__main__":
    main()
