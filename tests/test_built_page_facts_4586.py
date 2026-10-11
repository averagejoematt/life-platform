"""tests/test_built_page_facts_4586.py — every STATIC fact on "How it's built" is pinned to
its source of truth (#4586, epic #4580).

The page at site/next/v8/built/ reads its counts, its spend and the coaches' record live
from public routes, so those cannot go stale. What is left in the page's own bytes is a
short list of facts a route does not serve: how many programs run on a timer, the tier
bands, the forecast's cadence and early-month rule, who approves what, and the figures in
the incident list. Each is checked here against the file that decides it, so the build
goes red when the system moves and the page has not. ONE test reports every offender.

It also holds the page's standing rules: noindex, no count of earlier starts, no
honorific, and first-person wording only inside the section labelled as a draft.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "site" / "next" / "v8" / "built" / "index.html"
MODULE = ROOT / "site" / "assets" / "js" / "ck_built.js"
GOVERNOR = ROOT / "lambdas" / "operational" / "cost_governor_lambda.py"
DRAFT_LABEL = "Draft wording. Matthew has not rewritten this yet."
_FIRST_PERSON = r"\b(?:I|I’m|I’ve|[Mm]y|[Mm]e|[Mm]yself)\b"


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _incident_row(log: str, date: str, needle: str) -> str:
    rows = [ln for ln in log.splitlines() if ln.startswith(f"| {date} |") and needle in ln]
    return rows[0] if rows else ""


def built_page_findings(page: str, module: str) -> list[str]:
    """Every static fact on the page that disagrees with its source. Empty = in agreement."""
    out: list[str] = []
    text = _text(page)

    # 1. Programs on a timer — the one count no public route serves.
    m = re.search(r"SCHEDULED = \{ count: (\d+), asOf: \"(\d{4}-\d{2}-\d{2})\" \}", module)
    model = json.loads((ROOT / "model" / "platform_model.json").read_text(encoding="utf-8"))["meta"]["counts"]["scheduled_lambdas"]
    if not m:
        out.append("ck_built.js no longer declares SCHEDULED = { count, asOf }")
    elif int(m.group(1)) != model:
        out.append(
            f"ck_built.js SCHEDULED.count is {m.group(1)} but model/platform_model.json counts {model} scheduled programs — "
            "update the count AND its asOf date"
        )

    # 2. Tier bands, the early-month rule and the forecast cadence — the cost governor.
    gov = GOVERNOR.read_text(encoding="utf-8")
    ref = float(re.search(r"_THRESHOLD_REFERENCE_CEILING = ([\d.]+)", gov).group(1))
    bands = {
        tier: round(float(usd) / ref * 100)
        for usd, tier in re.findall(r"\((\d+), (\d)\)", re.search(r"_TIER_THRESHOLDS = \[(.*?)\]", gov).group(1))
    }
    for tier, pct in sorted(bands.items()):
        if not re.search(rf"Tier {tier} From about {pct}%", text):
            out.append(f"the page does not state tier {tier} as 'From about {pct}%' — the governor's band is {pct}% of the ceiling")
    early = float(re.search(r"EARLY_MONTH_DAYS = ([\d.]+)", gov).group(1))
    if "min(projected_tier, actual_tier + 1)" not in gov:
        out.append("the governor no longer caps the tier at one step above actual spend — the page says it does")
    g = re.search(r"GOVERNOR = \{ shares: \[(\d+) / (\d+), (\d+) / \2, (\d+) / \2\], earlyDays: (\d+), windowDays: (\d+) \}", module)
    usd_steps = sorted(
        float(usd) for usd, _tier in re.findall(r"\((\d+), (\d)\)", re.search(r"_TIER_THRESHOLDS = \[(.*?)\]", gov).group(1))
    )
    window = re.search(r"trailing_start = max\(now - timedelta\(days=(\d+)\), month_start\)", gov)
    if not g:
        out.append("ck_built.js no longer declares GOVERNOR = { shares, earlyDays, windowDays }")
    else:
        if [float(g.group(1)), float(g.group(3)), float(g.group(4))] != usd_steps or float(g.group(2)) != ref:
            out.append(f"ck_built.js GOVERNOR.shares disagree with the governor's thresholds {usd_steps} over {ref:g}")
        if float(g.group(5)) != early:
            out.append(f"ck_built.js GOVERNOR.earlyDays is {g.group(5)}; EARLY_MONTH_DAYS is {early:g}")
        if not window or g.group(6) != window.group(1):
            out.append(
                f"ck_built.js GOVERNOR.windowDays is {g.group(6)}; the governor's trailing window is {window.group(1) if window else 'not found'} days"
            )
    if "tier = min(projected_tier, actual_tier)" not in gov:
        out.append("the governor no longer holds the tier to actual spend in the early-month window — the page says it does")
    stack = (ROOT / "cdk" / "stacks" / "operational_stack.py").read_text(encoding="utf-8")
    cadence = re.search(r'schedule="cron\(0 0/(\d+) \* \* \? \*\)",\s*# every \d+h[^\n]*Cost Explorer', stack)
    if not cadence or f"every {cadence.group(1)} hours" not in text:
        out.append(
            f"the page's forecast cadence does not match the cost governor's schedule ({cadence.group(1) if cadence else 'not found'}h)"
        )

    # 3. Who approves what (ADR-158: code ships on green; only the IAM/CDK deploy waits).
    ci = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    gated = re.findall(r"^  ([\w-]+):\n(?:(?!^  [\w-]+:\n).)*?^    environment: production\b", ci, re.M | re.S)
    if gated != ["deploy-iam"]:
        out.append(
            f"ci-cd.yml's jobs behind `environment: production` are {gated}, not ['deploy-iam'] — the page says only a permissions change waits"
        )
    for said in (
        "approves one thing by hand: a change to what the programs are permitted to do",
        "Permissions only",
        "The one thing I approve by hand",
    ):
        if said not in text:
            out.append(f"the page no longer says {said!r} — the approval claim must be one statement in the row, the picture and the draft")
    if "public demonstration of engineering practice" not in (ROOT / "docs" / "PROPORTIONALITY.md").read_text(encoding="utf-8"):
        out.append("docs/PROPORTIONALITY.md no longer states the 'public demonstration of engineering practice' standard the page restates")
    agent = (ROOT / "remediation" / "agent.py").read_text(encoding="utf-8")
    if '"Bash(gh pr merge *)"' not in agent:
        out.append("remediation/agent.py no longer disallows `gh pr merge` — the page says the repair agent cannot merge")
    cron = re.search(
        r'cron: "\d+ \d+ \* \* ([\d,]+)"', (ROOT / ".github" / "workflows" / "remediation-agent.yml").read_text(encoding="utf-8")
    )
    days = len(cron.group(1).split(",")) if cron else 0
    if days != 3 or "runs three times a week" not in text:
        out.append(f"the repair agent's schedule has {days} day(s) a week — the page says three")

    # 4. The incident list — figures quoted from docs/INCIDENT_LOG.md rows.
    log = (ROOT / "docs" / "INCIDENT_LOG.md").read_text(encoding="utf-8")
    quoted = (
        (
            "2026-09-01",
            "board_ask",
            ("~34h", "~31h escalation", "QG_INVOKE_TIMEOUT_S = 10", "≈2-5s"),
            ("about 34 hours", "about 31 hours", "10-second limit", "2 to 5 seconds"),
        ),
        ("2026-08-26", "#3200", ("NEVER FIRED", "not an alarm"), ("had never worked", "not by an alarm")),
        ("2026-08-11", "fabricated numbers", ("92 / 92 / 82",), ("92, 92 and 82",)),
    )
    for date, needle, in_log, on_page in quoted:
        row = _incident_row(log, date, needle)
        if not row:
            out.append(f"docs/INCIDENT_LOG.md has no {date} row mentioning {needle!r} — the page cites it")
            continue
        out += [f"the {date} incident row no longer carries {s!r}, which the page restates" for s in in_log if s not in row]
        out += [f"the page no longer states {s!r} for the {date} incident" for s in on_page if s not in text]
        if f'datetime="{date}"' not in page:
            out.append(f"the page carries no dated entry for the {date} incident")

    # 5. Standing rules for the page.
    if 'content="noindex,nofollow"' not in page:
        out.append("the page is not noindex")
    if re.search(r"\bcycle\b|\breset\b|\bDr\.", text, re.I):
        out.append("the page names a cycle, a reset or an honorific")
    if re.search(r"<style\b", page, re.I) or len(re.findall(r'rel="stylesheet"', page)) != 1 or "/assets/css/clean.css" not in page:
        out.append("the page must load clean.css alone, with no page-scoped <style>")
    draft = re.search(r'<section class="ck-section" id="ck-draft">(.*?)</section>', page, re.S)
    if not draft or DRAFT_LABEL not in draft.group(1):
        out.append(f"the first-person section is missing or does not carry the label {DRAFT_LABEL!r}")
    outside = _text(page.replace(draft.group(0), "") if draft else page)
    first_person = re.findall(_FIRST_PERSON, outside.replace("first-person line", ""))
    if first_person:
        out.append(f"first-person wording outside the labelled draft section: {sorted(set(first_person))}")
    code = "\n".join(ln for ln in module.splitlines() if not ln.lstrip().startswith(("//", "*", "/**")))
    spoken = [lit for lit in re.findall(r"`[^`]*`|\"[^\"\n]*\"", code) if re.search(_FIRST_PERSON, re.sub(r"\$\{[^}]*\}", "", lit))]
    if spoken:
        out.append(f"ck_built.js writes first-person wording, which renders outside the labelled draft section: {spoken[:2]}")
    return out


def test_every_static_fact_on_the_built_page_matches_its_source():
    findings = built_page_findings(PAGE.read_text(encoding="utf-8"), MODULE.read_text(encoding="utf-8"))
    assert not findings, "How it's built disagrees with its sources:\n  - " + "\n  - ".join(findings)


def test_mutation_a_stale_count_a_wrong_band_and_stray_first_person_are_each_caught():
    page, module = PAGE.read_text(encoding="utf-8"), MODULE.read_text(encoding="utf-8")
    stale = built_page_findings(page, module.replace("SCHEDULED = { count: ", "SCHEDULED = { count: 1"))
    assert any("scheduled programs" in f for f in stale), stale
    band = built_page_findings(page.replace("From about 87%", "From about 85%"), module)
    assert any("tier 2" in f for f in band), band
    voice = built_page_findings(page.replace("<h2>One picture.</h2>", "<h2>My picture.</h2>"), module)
    assert any("first-person wording outside" in f for f in voice), voice
    unlabelled = built_page_findings(page.replace(DRAFT_LABEL, ""), module)
    assert any("does not carry the label" in f for f in unlabelled), unlabelled


def test_the_build_cap_sentence_matches_the_laptop_cap_module():
    """The page says what stops building-and-testing spend (red team round 7: the control
    was real, #4623, and the page omitted it). The two amounts are the cap module's."""
    src = (ROOT / "lambdas" / "ai" / "dev_session_cap.py").read_text()
    run = float(re.search(r"^PER_RUN_USD = ([0-9.]+)", src, re.M).group(1))
    day = float(re.search(r"^PER_DAY_USD = ([0-9.]+)", src, re.M).group(1))
    sentence = re.search(r'export const BUILD_CAP = "([^"]+)"', MODULE.read_text()).group(1)
    assert f"${run:g} in one run" in sentence and f"${day:g} in any 24 hours" in sentence, sentence
