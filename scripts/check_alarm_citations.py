#!/usr/bin/env python3
"""scripts/check_alarm_citations.py — the /wrap alarm-citation gate (#1959).

THE PROBLEM
  Nothing owned "an alarm red >72h must cite an incident row or issue #". The #1329
  standing-alarms step in `.claude/commands/wrap.md` existed but was scoped to
  freshness/staleness + secret-rotation alarms and was advisory (a note in
  next-picks, no fail condition, no `describe-alarms` enumeration). At the 2026-07-28
  /fullreview, 6 alarms were simultaneously red and the session ledger recorded
  exactly one incident row — a red board had normalized, and a NEW red could hide
  among the old ones.

THE FIX
  A deterministic, read-only gate mirroring `check_main_green.py`'s decode contract:
  enumerate every CloudWatch alarm currently in ALARM (`describe_alarms`, read-only —
  no writes, no alarm mutation), and require every one that has been red longer than
  ALARM_AGE_CITATION_HOURS to have an entry in the curated registry
  `docs/alarm_citations.json` (an issue `#N` or an incident-row reference, hand-
  maintained the same way `remediation/agent.py`'s MANUAL_ROTATION_SECRETS is —
  citations are asserted by an operator, not pattern-matched out of prose, because an
  alarm name rarely appears verbatim in the issue that explains it). An alarm with no
  entry is printed by name; the gate exits 1 unless `--decoded` (the operator wrote
  the shortfall explicitly into the handover, same shape as check_main_green.py).

  This folds the #1329 step's scope: freshness/staleness alarms ARE CloudWatch
  alarms and are covered here for free. Manual-rotation SECRET staleness is NOT a
  CloudWatch alarm (Secrets Manager DescribeSecret, not describe-alarms) and stays a
  separate reminder (docs/SECRETS_ROTATION.md "Monitoring" +
  remediation/agent.py's stale_secret_escalations) — one owner per signal type.

A CITATION STRING IS NOT AN OWNER (#2996)
  The two checks above ask whether a reference EXISTS. Neither asks whether it still
  means anything, so a citation outlives the issue it points at. Measured 2026-08-22:
  4 of 7 registry entries cited CLOSED issues and 3 of those were on alarms lit at
  that moment, two of them past the 72h threshold — the gate had reported a clean
  board over all of it. Two were not merely dead but semantically wrong:
  `qa-smoke-failures` cited #1921 (an August 1st decision about oracle partitioning)
  while its live cause was `recall:corpus_freshness`, owned by the then-open #2977.
  The right owner existed and the registry pointed elsewhere.

  So this gate ALSO reads `gh issue view` for every CURRENTLY-LIT alarm's citation
  and fails on a `#N` that is not OPEN. Deliberately narrow so it cannot manufacture
  a red: a citation with no `#N` is exempt (a dated, self-clearing state is honestly
  cited in prose — and `test_real_registry_file_is_well_formed` makes that prose
  carry a concrete ISO expiry date, while `issueless_ancient_reds` still forces a
  `#N` past 14 days), an unreadable issue is UNKNOWN rather than dead, and a stale
  entry on a RECOVERED alarm is a pruning chore, not a red. Degrades honestly when
  `gh` is unavailable, exactly like the two AWS reads.

  PRUNE RULE, as corrected while shipping this: remove a recovered alarm's entry once
  it has been OK for longer than the flap window (72h), not the moment it clears —
  pruning on recovery alone trades a stale entry for a #2912 flap-gate red.

FLAP VISIBILITY (#2912)
  Current-state duration is structurally blind to an alarm that fires and clears
  between wraps: `describe_alarms(StateValue="ALARM")` never returns it, so a real,
  recurring, once-a-day failure could fire and clear every night indefinitely and
  never once be surfaced at a wrap. Measured live 2026-08-20: qa-smoke-warnings
  oscillated OK->ALARM 28 times in ~2.5h off ONE planted datapoint (each ALARM
  standing 1-3 min), then held — every episode invisible to the >72h path. So this
  gate ALSO reads `describe_alarm_history` (read-only) over the same 72h window and
  flags every alarm with an ALARM episode that ENDED inside the window
  (old ALARM -> new not-ALARM) but no citation entry. A transition count is the
  honest signal; current-state duration is not (ADR-104).

DEGRADE HONESTLY
  If CloudWatch can't be reached (no creds, offline, throttled) this prints a clear
  UNVERIFIED notice and exits 0 — a gate that can't measure anything must not claim
  a clean board (mirrors the gh-unavailable fail-open shape in check_backlog_hygiene.py
  ). The handover should still say so rather than silently
  skipping the line. The same shape applies independently to the alarm-HISTORY read:
  if only that call fails, the current-state checks still gate and the flap check is
  explicitly reported UNVERIFIED rather than silently skipped.

USAGE
  python3 scripts/check_alarm_citations.py             # gate: uncited long-red or fired-and-cleared -> exit 1
  python3 scripts/check_alarm_citations.py --decoded    # operator named the shortfall; exit 0
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CITATIONS_PATH = ROOT / "docs" / "alarm_citations.json"
REGION = "us-west-2"

# Matches remediation/agent.py's ALARM_AGE_ESCALATION_HOURS (#1204) — the same 72h
# aging window, now also the citation-required threshold (#1959 widens the #1329
# step to the full alarm board). Kept as an INDEPENDENT constant on purpose: this
# script must run standalone and read-only without importing remediation/agent.py's
# module-level boto3 clients / drift_report dependency. tests/test_check_alarm_
# citations.py greps both source files to keep the two literals from drifting apart.
ALARM_AGE_CITATION_HOURS = 72

# #2378 (acceptance 3): an alarm in ALARM beyond this tenure is a MANDATORY
# issue-or-fix, not a citation line — its registry entry must reference a filed
# GitHub issue (`#N` somewhere in the citation string), or the gate red-flags it
# by name. Prose/incident-row citations satisfy the 72h gate above but stop
# sufficing here: qa-smoke-warnings sat structurally red 21+ days with a tidy
# citation the whole time, which is exactly how a red board normalizes.
ALARM_TENURE_ISSUE_DAYS = 14

# #2912: the fired-and-cleared lookback shares the citation gate's 72h window on
# purpose — one constant story: an ALARM episode is answerable at the first wrap
# within 72h of it, whether the alarm is still red (current-state path) or already
# cleared (history path). Wraps run far more often than every 72h, so no episode
# can slip between the two.
FLAP_WINDOW_HOURS = ALARM_AGE_CITATION_HOURS

# Bounded pagination for describe_alarm_history — 20 pages x 100 records is far
# beyond any observed 72h board (the worst measured storm was 56 items), and a
# bound means a pathological history can never hang the wrap.
_HISTORY_MAX_PAGES = 20

_ISSUE_REF = r"#\d+"


def _parse_ts(ts):
    """Parse a CloudWatch StateUpdatedTimestamp string into an aware datetime, or
    None if it can't be parsed — an unparseable stamp must never manufacture a
    false citation requirement."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def alarm_age_hours(alarm, now):
    """Hours `alarm` (a dict with an `updated` ISO timestamp) has been in its
    current state. None if the timestamp is missing/unparseable."""
    dt = _parse_ts(alarm.get("updated"))
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600.0


def load_citations(path=CITATIONS_PATH):
    """The curated alarm-name -> citation registry. Missing/malformed file degrades
    to an empty registry (every long-red alarm then reads as uncited, which is the
    honest and safe direction to fail in)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def uncited_long_reds(alarms, citations, now=None, threshold_hours=ALARM_AGE_CITATION_HOURS):
    """(alarm_name, age_hours) for every ALARM-state alarm older than
    threshold_hours with no entry in `citations`. Pure and deterministic — no I/O —
    so it's exercised directly by the regression test with synthetic input,
    independent of live AWS/registry state (per the #1959 negative-test requirement).
    """
    now = now or datetime.now(timezone.utc)
    out = []
    for a in alarms:
        name = a.get("name") or "?"
        age = alarm_age_hours(a, now)
        if age is None or age <= threshold_hours:
            continue
        entry = citations.get(name)
        if not entry or not str(entry.get("citation", "")).strip():
            out.append((name, age))
    return out


def issueless_ancient_reds(alarms, citations, now=None, threshold_days=ALARM_TENURE_ISSUE_DAYS):
    """(alarm_name, age_hours) for every ALARM-state alarm older than
    threshold_days whose citation carries no filed-issue reference (`#N`) —
    including alarms with no citation at all. #2378: past this tenure a
    citation LINE no longer clears the board; the alarm is a mandatory
    issue-or-fix. Pure and deterministic, mirroring uncited_long_reds."""
    import re

    now = now or datetime.now(timezone.utc)
    out = []
    for a in alarms:
        name = a.get("name") or "?"
        age = alarm_age_hours(a, now)
        if age is None or age <= threshold_days * 24.0:
            continue
        entry = citations.get(name) or {}
        citation = str(entry.get("citation", ""))
        if not re.search(_ISSUE_REF, citation):
            out.append((name, age))
    return out


def flapped_uncited(history, citations, now=None, window_hours=FLAP_WINDOW_HOURS):
    """(alarm_name, fired_count, cleared_count) for every alarm with an ALARM
    episode that both STARTED (a transition INTO ALARM) and ENDED (a transition
    FROM ALARM to any other state) within the window, and no entry in `citations`.

    #2912: `describe_alarms(StateValue="ALARM")` is blind to these by construction
    (the alarm is no longer in ALARM when the wrap looks), so a QA failure that
    fires and clears between wraps was never forced to be answered. The condition
    deliberately also catches an alarm that is *currently* red but young: its
    earlier fired-and-cleared episodes in the window are still surfaced instead of
    hiding behind a <72h current state (the 08-20 storm shape: 35 cleared episodes,
    then a final still-open one).

    Requiring BOTH a fire and a clear in-window is deliberate: a clear-only entry
    is the recovery of a red that predates the window — visible to prior wraps via
    current state, and whose registry entry is correctly PRUNED on recovery
    (the #2917 lifecycle). Flagging recoveries would demand the entry back the
    moment it is rightly removed — a re-cite treadmill that trains reflexive
    --decoded. Cross-wrap coverage holds anyway: wraps run far more often than the
    72h window, so any episode's fire lands inside some wrap's window.

    `history` items are dicts with `name`, `timestamp` (ISO), `old`, `new` state
    values, as returned by fetch_alarm_history(). Pure and deterministic — no I/O —
    exercised directly by the regression test with a planted fired-then-cleared
    history (the #2912 planted-proof requirement).
    """
    now = now or datetime.now(timezone.utc)
    fired = {}
    cleared = {}
    for item in history:
        dt = _parse_ts(item.get("timestamp"))
        if dt is None:
            continue  # an unparseable stamp must never manufacture a flag
        age_hours = (now - dt).total_seconds() / 3600.0
        if age_hours > window_hours or age_hours < 0:
            continue
        name = item.get("name") or "?"
        if item.get("new") == "ALARM":
            fired[name] = fired.get(name, 0) + 1
        elif item.get("old") == "ALARM":
            cleared[name] = cleared.get(name, 0) + 1
    out = []
    for name in sorted(set(fired) | set(cleared)):
        if fired.get(name, 0) < 1:
            continue  # clear-only: recovery of a pre-window red — see docstring
        if cleared.get(name, 0) < 1:
            continue  # episode still open -> the current-state paths above own it
        entry = citations.get(name)
        if not entry or not str(entry.get("citation", "")).strip():
            out.append((name, fired.get(name, 0), cleared.get(name, 0)))
    return out


def cited_issue_refs(alarms, citations):
    """The issue numbers cited by alarms that are CURRENTLY lit, as strings.

    Scoped to `alarms` (which is the ALARM-state read) rather than the whole
    registry: a stale entry on a recovered alarm is a pruning chore, not a red.
    """
    import re

    refs = set()
    for a in alarms:
        entry = citations.get(a.get("name") or "?") or {}
        refs.update(re.findall(r"#(\d+)", str(entry.get("citation", ""))))
    return sorted(refs)


def dead_citations(alarms, citations, issue_states):
    """(alarm_name, "#N") for every CURRENTLY-lit alarm whose citation names an
    issue that is not OPEN — the #2996 class.

    The #1959 gate asserts a citation *string* exists and, past
    ALARM_TENURE_ISSUE_DAYS, that it contains a `#N`. Neither asks whether that
    issue is still open, so a citation outlives the issue it points at and the
    board reads green while nobody owns the red. Measured 2026-08-22: 4 of 7
    entries cited closed issues, 3 of them on alarms that were lit at the time.

    Deliberately narrow in two ways, so it cannot manufacture a red:
      * a citation with NO `#N` is not flagged — a dated, self-clearing window is
        honestly cited in prose, and `issueless_ancient_reds` already forces a
        `#N` past 14 days;
      * an issue whose state could not be read (absent from `issue_states`, or
        None) is UNKNOWN, never dead.

    Pure and deterministic — `issue_states` is injected, so the regression test
    drives it with synthetic input exactly like the sibling checks.
    """
    import re

    out = []
    for a in alarms:
        name = a.get("name") or "?"
        entry = citations.get(name) or {}
        for num in re.findall(r"#(\d+)", str(entry.get("citation", ""))):
            state = issue_states.get(num)
            if state is not None and str(state).upper() != "OPEN":
                out.append((name, f"#{num}"))
    return out


# #3258: a citation note may not assert that a fixed cause has NOT COME BACK
# unless it says where it looked. The measured instance: qa-smoke-warnings' entry
# read "Home-hero temporal framing (539c6d, 08-16..08-23) — fixed by #3066/PR#3075
# …, no recurrence since" while the identical fingerprint `539c6d` was in
# /aws/lambda/life-platform-qa-smoke inside the last 72h. Nothing checked it,
# because the claim was prose re-verified by a human's memory.
#
# The rule is deliberately ASYMMETRIC and that asymmetry is the point: a
# recurrence-negative is unfalsifiable from the registry alone, so it must carry
# its derivation (the log group it was read from, or the query that read it). A
# positive claim needs no marker — it is checkable by looking. The check
# UNDER-catches by construction (a novel wording slips through) and that is the
# safe direction for a doc lint: it can only fail to flag a sloppy note, never
# suppress a real signal. That is the opposite of the #2959/#3003/#3199
# phrase-matched SUPPRESSOR family, where under-catching means going blind.
_RECURRENCE_NEGATIVE = re.compile(
    r"\bno (?:further )?recurrence\b|\b(?:has|have)(?: not|n't) recurred\b|\bnot recurred\b|\bnever recurred\b|\bno repeat\b",
    re.I,
)
# What counts as "derived": the note names the log group it was read from, or the
# read itself. Both are things a reviewer can re-run; a date alone is not.
_DERIVATION_MARKERS = ("/aws/lambda/", "/aws/", "filter-log-events", "describe-alarm-history", "start-query")

# The marker must sit NEAR the claim, not merely somewhere in the same entry. The
# first draft of this check tested the whole note, and its own must-fail mutation
# passed vacuously: appending "…, no recurrence since" to the end of a long entry
# that happened to name a log group 1,900 characters earlier was not flagged. A
# derivation attaches to a claim, not to a paragraph. Same shape as #3208's
# `_FRACTION_CONTEXT_CHARS` and for the same reason.
_DERIVATION_CONTEXT_CHARS = 240


def unfalsifiable_negatives(citations):
    """(alarm_name, matched_phrase) for every citation asserting a recurrence
    NEGATIVE without naming how it was derived (#3258).

    A claim is derived when a derivation marker appears within
    `_DERIVATION_CONTEXT_CHARS` of it. EVERY recurrence-negative in an entry must
    be derived — one derived claim does not license a second undated one.

    Pure and offline — it reads the committed registry only, so it is enforced by
    the unit suite on every PR rather than only on a /wrap run against live AWS.
    """
    out = []
    for name, entry in sorted((citations or {}).items()):
        if not isinstance(entry, dict):
            continue
        text = f"{entry.get('citation', '')} {entry.get('note', '')}"
        for m in _RECURRENCE_NEGATIVE.finditer(text):
            window = text[max(0, m.start() - _DERIVATION_CONTEXT_CHARS) : m.end() + _DERIVATION_CONTEXT_CHARS]
            if any(marker in window for marker in _DERIVATION_MARKERS):
                continue
            out.append((name, m.group(0)))
    return out


def fetch_issue_states(refs):
    """Live `gh issue view N --json state` per ref — read-only. Returns
    (states, error) in the same degrade-honestly shape as fetch_alarms(): on any
    failure `states` is {} and `error` is a human string, and the caller must
    report the dead-citation check UNVERIFIED rather than clean. A single ref that
    cannot be read is simply absent from the map (UNKNOWN, never dead)."""
    import subprocess

    if not refs:
        return {}, None
    states = {}
    for num in refs:
        try:
            proc = subprocess.run(
                ["gh", "issue", "view", str(num), "--json", "state", "-q", ".state"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as e:  # gh missing, not on PATH, timeout
            return {}, str(e)
        if proc.returncode != 0:
            continue  # unreadable single ref -> UNKNOWN, not dead
        value = proc.stdout.strip()
        if value:
            states[str(num)] = value
    return states, None


def fetch_alarms():
    """Live `describe_alarms(StateValue="ALARM")` read — read-only, no writes, no
    alarm mutation. Returns (alarms, error): `error` is a human string when AWS is
    unreachable (missing creds, network, throttling, IAM), in which case `alarms`
    is always `[]` — callers must treat that as UNVERIFIED, never as a clean board.
    """
    try:
        import boto3

        cw = boto3.client("cloudwatch", region_name=REGION)
        resp = cw.describe_alarms(StateValue="ALARM", MaxRecords=100)
    except Exception as e:  # noqa: BLE001 — any AWS/boto3 failure must degrade, not crash
        return [], str(e)
    alarms = [{"name": a.get("AlarmName", "?"), "updated": str(a.get("StateUpdatedTimestamp", ""))} for a in resp.get("MetricAlarms", [])]
    return alarms, None


def fetch_alarm_history(window_hours=FLAP_WINDOW_HOURS):
    """Live `describe_alarm_history(HistoryItemType="StateUpdate")` over the flap
    window — read-only, no writes, no alarm mutation. Returns (items, error) in the
    same degrade-honestly shape as fetch_alarms(): on any AWS failure `items` is []
    and `error` is a human string — callers must report the flap check UNVERIFIED,
    never as a clean history."""
    from datetime import timedelta

    try:
        import boto3

        cw = boto3.client("cloudwatch", region_name=REGION)
        start = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        items = []
        token = None
        for _ in range(_HISTORY_MAX_PAGES):
            kwargs = {"HistoryItemType": "StateUpdate", "StartDate": start, "MaxRecords": 100}
            if token:
                kwargs["NextToken"] = token
            resp = cw.describe_alarm_history(**kwargs)
            for it in resp.get("AlarmHistoryItems", []):
                try:
                    data = json.loads(it.get("HistoryData") or "{}")
                except (json.JSONDecodeError, TypeError):
                    data = {}
                items.append(
                    {
                        "name": it.get("AlarmName", "?"),
                        "timestamp": str(it.get("Timestamp", "")),
                        "old": (data.get("oldState") or {}).get("stateValue", ""),
                        "new": (data.get("newState") or {}).get("stateValue", ""),
                    }
                )
            token = resp.get("NextToken")
            if not token:
                break
    except Exception as e:  # noqa: BLE001 — any AWS/boto3 failure must degrade, not crash
        return [], str(e)
    return items, None


def render(uncited, unreachable_error, ancient=(), flapped=(), history_error=None, dead=(), issue_error=None):
    """(exit_code, message) for a computed result. Pure — unit-tested offline."""
    if unreachable_error is not None:
        return 0, (
            f"⚠️  check_alarm_citations: CloudWatch unreachable ({unreachable_error}) — "
            "alarm citations UNVERIFIED this run. Note that explicitly in the handover "
            "(`**Alarms:** unverified — AWS unreachable`) rather than claiming a clean board."
        )
    if not uncited and not ancient and not flapped and not dead:
        message = (
            "✅ every alarm in ALARM state >72h cites an incident row or issue, and every one "
            f"red >{ALARM_TENURE_ISSUE_DAYS}d cites a filed issue (#N) — or none are that old. "
            f"No uncited fired-and-cleared episodes in the last {FLAP_WINDOW_HOURS}h (#2912). "
            "Every lit alarm's cited `#N` is OPEN (#2996)."
        )
        if history_error is not None:
            message += (
                f"\n⚠️  BUT the alarm-history read failed ({history_error}) — the fired-and-cleared "
                "check is UNVERIFIED this run. Note that explicitly in the handover "
                "(`**Alarms:** flap check unverified — history unreachable`) rather than claiming it clean."
            )
        if issue_error is not None:
            message += (
                f"\n⚠️  BUT the cited-issue state read failed ({issue_error}) — the dead-citation "
                "check (#2996) is UNVERIFIED this run. Note that explicitly in the handover rather "
                "than claiming every citation still has an owner."
            )
        return 0, message
    lines = []
    if uncited:
        lines.append(f"❌ {len(uncited)} alarm(s) in ALARM >72h with no citation in {CITATIONS_PATH.relative_to(ROOT)}:")
        for name, age in sorted(uncited):
            lines.append(f"   - {name}  (red {age / 24:.1f}d / {age:.0f}h)")
        lines.append(
            '   Add an entry to docs/alarm_citations.json — {"<AlarmName>": {"citation": "#N", '
            '"note": "..."}} — or write the shortfall explicitly into the handover '
            "(`**Alarms:** <M> uncited — named: ...`) and re-run with --decoded."
        )
    if ancient:
        lines.append(
            f"🚩 {len(ancient)} alarm(s) in ALARM >{ALARM_TENURE_ISSUE_DAYS} DAYS without a filed-issue citation "
            "— MANDATORY issue-or-fix (#2378), a citation line alone no longer clears this tenure:"
        )
        for name, age in sorted(ancient):
            lines.append(f"   - {name}  (red {age / 24:.1f}d)")
        lines.append(
            "   Either FIX the alarm this session, or file a GitHub issue for it and put `#N` in its "
            "docs/alarm_citations.json citation. Prose/incident-row citations stop counting at this tenure — "
            "that is how qa-smoke-warnings stayed structurally red 21+ days behind a tidy citation."
        )
    if flapped:
        lines.append(
            f"❌ {len(flapped)} alarm(s) FIRED AND CLEARED within the last {FLAP_WINDOW_HOURS}h with no citation "
            f"in {CITATIONS_PATH.relative_to(ROOT)} (#2912) — invisible to current-state duration by construction:"
        )
        for name, fired_n, cleared_n in sorted(flapped):
            lines.append(f"   - {name}  (entered ALARM x{fired_n}, cleared x{cleared_n} in the window)")
        lines.append(
            "   A transition count is the honest signal; current-state duration is not (ADR-104). "
            "A failure that flaps between wraps still gets answered: add a docs/alarm_citations.json entry "
            "explaining the episode, or write it explicitly into the handover and re-run with --decoded."
        )
    if dead:
        lines.append(f"❌ {len(dead)} lit alarm(s) whose citation points at a CLOSED issue (#2996) — a citation " "string is not an owner:")
        for name, ref in sorted(dead):
            lines.append(f"   - {name}  → {ref} is closed")
        lines.append(
            "   Re-point the entry at the issue that actually owns the live cause, file one if none exists, "
            "or — if the alarm is correct on a dated, self-clearing state — replace the `#N` with prose "
            "naming the window and its expiry."
        )
    if history_error is not None:
        lines.append(
            f"⚠️  Alarm-history read failed ({history_error}) — the fired-and-cleared check is UNVERIFIED "
            "this run; note that explicitly in the handover rather than claiming it clean."
        )
    if issue_error is not None:
        lines.append(
            f"⚠️  Cited-issue state read failed ({issue_error}) — the dead-citation check (#2996) is "
            "UNVERIFIED this run; note that explicitly rather than claiming every citation has an owner."
        )
    return 1, "\n".join(lines)


def main():
    decoded = "--decoded" in sys.argv
    alarms, err = fetch_alarms()
    citations = load_citations()
    uncited = [] if err else uncited_long_reds(alarms, citations)
    ancient = [] if err else issueless_ancient_reds(alarms, citations)
    if err:
        history, history_err, flapped = [], None, []  # whole board already UNVERIFIED
        issue_err, dead = None, []
    else:
        history, history_err = fetch_alarm_history()
        flapped = [] if history_err else flapped_uncited(history, citations)
        issue_states, issue_err = fetch_issue_states(cited_issue_refs(alarms, citations))
        dead = [] if issue_err else dead_citations(alarms, citations, issue_states)
    code, message = render(uncited, err, ancient=ancient, flapped=flapped, history_error=history_err, dead=dead, issue_error=issue_err)
    print(message)
    if code == 0:
        return 0
    if decoded:
        print("   --decoded acknowledged: the handover MUST name each uncited alarm explicitly.")
        return 0
    print("   The wrap may not report a clean alarm board over this. Either add citations, or --decoded after naming the shortfall.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
