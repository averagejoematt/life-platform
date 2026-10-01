#!/usr/bin/env python3
"""scripts/season_rebuild.py — rebuild the season through the Story Desk, in order (#4537).

Reads DynamoDB (read-only), calls Bedrock through the platform's one chokepoint, and writes
ONLY to a local staging directory — nothing here publishes, approves or writes to AWS. The
promote step is separate and is an owner act.

For each week, in order, using only that week's window and the ledger the previous week left:
  dossier → desk budget → Elena's post → checks (one corrective rewrite) →
  the Panel episode → checks (one corrective rewrite) → ledger.

Week 0 is the prologue pair: Elena's "Before the Numbers" post and the Panel's prologue with
the head coach. The sealed pre-registration prologue ("The Plan, On the Record") is not
rewritten — it is the commitment device, quoted to the writers as written.

    python3 scripts/season_rebuild.py --through-week 4 --out <dir>
    python3 scripts/season_rebuild.py --weeks 3 --out <dir>      # one week, ledger read from <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from content import story_checks, story_desk, story_dossier, story_ledger, story_writers  # noqa: E402

CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
PLAN_PROLOGUE_SK = "DATE#2026-09-05"
# Sources that are channels or admin feeds, not instruments on the body — excluded when the prologue
# describes what is measured (dated 2026-10-01; derive, don't restate, if the registry grows a kind facet).
INSTRUMENT_WORDS = {
    "whoop": "a WHOOP strap (sleep, recovery, heart-rate variability, strain)",
    "withings": "a Withings scale",
    "eightsleep": "an Eight Sleep mattress cover",
    "apple_health": "Apple Health on his phone (steps, and the continuous glucose monitor's readings)",
    "macrofactor": "MacroFactor, the food log",
    "hevy": "Hevy, the strength-training log",
    "strava": "Strava, for walks",
    "habitify": "a habit tracker",
    "notion": "a journal",
    "labs": "blood work",
    "supplements": "a supplement log",
    "measurements": "tape measurements",
    "weather": "the local weather",
}
_NOT_INSTRUMENTS = {"todoist", "youtube", "bluesky", "mastodon", "x", "instagram", "tiktok", "dropbox", "food_delivery", "progress_photos"}


def _table():
    import boto3

    return boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")


def _plan_prologue(table) -> str:
    it = table.get_item(Key={"pk": CHRONICLE_PK, "sk": PLAN_PROLOGUE_SK}).get("Item") or {}
    return str(it.get("content_markdown") or "")


def prologue_dossier(table) -> Dict[str, Any]:
    import json as _json

    from coach import persona_registry
    from common.repo_config import config_path
    from ingestion.source_registry import SOURCE_REGISTRY

    with open(config_path("user_goals.json"), encoding="utf-8") as fh:
        goals = _json.load(fh)
    prof = goals.get("athlete_profile") or {}
    eli = next((v for v in persona_registry.personas().values() if v.get("name") == "Dr. Eli Marsh"), {})
    team = story_dossier.roster()
    return {
        "week": 0,
        "window": {"start": None, "end": "2026-09-05", "experiment_days": "before Day 1 (Day 1 is 2026-09-06)"},
        "plan": {k: v for k, v in story_dossier.load_plan().items() if k != "plan_start_lbs"},
        "day_one_weigh_in": "not yet taken — the first official weigh-in is the morning of Day 1; the sealed plan's working figure is the pre-registered 326.2",
        "title_is_fixed": "Before the Numbers",
        "roster": team
        + [
            {
                "coach_id": "head_coach",
                "persona_id": "eli_marsh",
                "name": eli.get("name"),
                "title": eli.get("title"),
                "lens": eli.get("lens"),
                "bio": eli.get("short_bio"),
                "pronouns": eli.get("pronouns"),
            }
        ],
        "who": {
            "home": "Seattle",
            "work": "a senior director at a software company",
            "the_backstory": {
                "prior_transformation": prof.get("prior_transformation"),
                "prior_transformation_lbs_lost": (prof.get("prior_transformation") or {}).get("start_weight", 0)
                - (prof.get("prior_transformation") or {}).get("end_weight", 0),
                "the_lesson_he_drew": "the weight was never really the problem; the system collapsed when life disrupted the routine, so this time the experiment is about the whole person — sleep, mind, connection — not just the scale",
            },
            "mission": goals.get("mission"),
        },
        "instruments": {
            s: INSTRUMENT_WORDS.get(s, s) for s in sorted(SOURCE_REGISTRY) if s not in _NOT_INSTRUMENTS and s in INSTRUMENT_WORDS
        },
        "instrument_count": len([s for s in SOURCE_REGISTRY if s not in _NOT_INSTRUMENTS and s in INSTRUMENT_WORDS]),
        "instruments_rule": "these are ALL the instruments; name no other device (the watch feed is paused for this experiment)",
        "the_platform": "a system he built himself on AWS: every device feeds one store; a team of AI coaches reads it each day; a morning brief arrives with the day's one next thing",
        "the_narrator": "Elena Voss is an AI narrator — a character written by a language model from Matthew's data — and says so",
        "pre_registered": story_dossier.load_prereg().get("coaches"),
        "pre_registered_count": sum(len(c.get("predictions", [])) for c in (story_dossier.load_prereg().get("coaches") or {}).values()),
        "pre_registered_filed_by": [c.get("coach_name") for c in (story_dossier.load_prereg().get("coaches") or {}).values()],
        "head_coach_filed_predictions": False,
        "roster_note": (
            "The sealed pre-registration carries opening calls from eight specialists. Say it once, cleanly, if at all: the training "
            "calls came from Dr. Sarah Chen, a specialist consulted for the pre-registration who does not sit on the weekly team, and the "
            "physical coach's calls appear under the name Dr. Victor Reyes — the same seat Dr. Max Reyes holds on the weekly team. The "
            "weekly team is the seven coaches in the roster plus the head coach, Dr. Eli Marsh."
        ),
        "sealed_plan_prologue_is_separate": "'The Plan, On the Record' (published the day before Day 1) carries every target and prediction; this prologue introduces the person, the system and the narrator, and points to it",
    }


def _save(out: str, name: str, obj: Any) -> None:
    path = os.path.join(out, name)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(obj, str):
            fh.write(obj)
        else:
            json.dump(obj, fh, indent=1, default=str)


def _load(out: str, name: str) -> Optional[Any]:
    path = os.path.join(out, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read() if name.endswith((".md", ".txt")) else json.load(fh)


def _guest(dossier: Dict[str, Any], budget: Dict[str, Any]) -> Dict[str, Any]:
    want = (budget.get("featured_coaches") or [None])[0]
    return next((c for c in dossier.get("roster", []) if c.get("coach_id") == want), dossier.get("roster", [{}])[0])


MAX_REWRITES = 2


class _Gates:
    """Everything one week's installments are held to, built once per week."""

    def __init__(
        self,
        n: int,
        dossier: Dict[str, Any],
        budget: Dict[str, Any],
        prev_ledger: Dict[str, Any],
        prev_dossier: Optional[Dict[str, Any]] = None,
    ):
        self.n, self.dossier = n, dossier
        # the series' own record is grounding too: a bet's threshold, last week's scored result
        self.allowed = story_checks.allowed_numbers(
            dossier, {"week": n}, budget.get("bet"), budget.get("bet_scored"), prev_ledger.get("bets")
        )
        self.nye = ["macrofactor"] if (dossier.get("nutrition") or {}).get("not_yet_exported_dates") else []
        w = dossier.get("weight") or {}
        self.weights = [x["lbs"] for x in w.get("weigh_ins_in_window", [])] + [
            x for x in (w.get(k, {}).get("lbs") for k in ("first_weigh_in", "week_start", "week_end")) if x
        ]
        self.weights += [326.2, 327.34, 327.3]
        self.context = {
            "last_weeks_open_bet": story_ledger.last_open_bet(prev_ledger),
            "this_weeks_bet_scoring": budget.get("bet_scored"),
            "this_weeks_new_bet": budget.get("bet"),
            "previous_titles": prev_ledger.get("titles", []),
        }

    def post(self, md: str, stop: Optional[str]) -> List[str]:
        return story_checks.all_findings(
            md, stop_reason=stop, allowed=self.allowed, not_yet_exported=self.nye, footer_pattern=story_writers.CHRONICLE_FOOTER
        ) + story_writers.fact_check(md, self.dossier, context=self.context)

    def episode(self, ep: Dict[str, Any], stop: Optional[str]) -> List[str]:
        txt = story_writers.episode_text(ep)
        return (
            story_checks.completeness(txt, stop_reason=stop)
            + story_checks.story_door(txt, not_yet_exported=self.nye)
            + story_checks.ungrounded_numbers(txt, self.allowed)
            + story_writers.spoken_word_findings(ep.get("turns", []), body_weights=self.weights)
            + story_writers.fact_check(txt, self.dossier, context=self.context)
        )


def _write_post(g: _Gates, dossier, budget, ledger, n, previous, md=None, findings=None):
    stop: Optional[str] = "end_turn"
    if md is None:
        md, stop = story_writers.write_chronicle(dossier, budget, ledger, week=n, previous=previous)
        findings = g.post(md, stop)
    for _ in range(MAX_REWRITES):
        if not findings:
            break
        print(f"  wk{n} post: {len(findings)} finding(s) → corrective rewrite: {[f[:160] for f in findings]}")
        md, stop = story_writers.write_chronicle(dossier, budget, ledger, week=n, previous=previous, fix=findings, prior_draft=md)
        findings = g.post(md, stop)
    return md, findings or []


def _write_ep(g: _Gates, dossier, budget, ledger, n, body, previous_episode, guest, ep=None, findings=None):
    stop: Optional[str] = "end_turn"
    if ep is None:
        ep, stop = story_writers.write_episode(
            dossier, budget, ledger, week=n, chronicle=body, previous_episode=previous_episode, guest=guest
        )
        findings = g.episode(ep, stop)
    for _ in range(MAX_REWRITES):
        if not findings:
            break
        print(f"  wk{n} episode: {len(findings)} finding(s) → corrective rewrite: {[f[:160] for f in findings]}")
        ep, stop = story_writers.write_episode(
            dossier, budget, ledger, week=n, chronicle=body, previous_episode=previous_episode, guest=guest, fix=findings, prior=ep
        )
        findings = g.episode(ep, stop)
    return ep, findings or []


def run_week(
    table, wk: Dict[str, Any], out: str, ledger: Dict[str, Any], previous_post: Optional[str], previous_episode: Optional[str]
) -> Dict[str, Any]:
    n = wk["week"]
    if n == 0:
        dossier, _nye = prologue_dossier(table), []
    else:
        dossier, _nye = story_dossier.week_dossier(table, wk)
    _save(out, f"wk{n}_dossier.json", dossier)
    budget = story_desk.run_desk(dossier, ledger, week=n)
    _save(out, f"wk{n}_budget.json", budget)
    g = _Gates(n, dossier, budget, ledger)

    md, findings = _write_post(g, dossier, budget, ledger, n, previous_post)
    _save(out, f"wk{n}_chronicle.md", md)
    title, body = story_writers.split_title(md)

    guest = _guest(dossier, budget) if n else next(c for c in dossier["roster"] if c.get("coach_id") == "head_coach")
    ep, efind = _write_ep(g, dossier, budget, ledger, n, body, previous_episode, guest)
    ep["guest"] = {"name": guest.get("name"), "coach_id": guest.get("coach_id"), "persona_id": guest.get("persona_id")}
    _save(out, f"wk{n}_episode.json", ep)
    _save(out, f"wk{n}_episode.txt", story_writers.episode_text(ep))

    new_ledger = story_ledger.apply_budget(ledger, budget, week=n, date=wk.get("date") or "2026-09-05", title=title)
    _save(out, f"wk{n}_ledger.json", new_ledger)
    report = {
        "week": n,
        "title": title,
        "episode_title": ep.get("title"),
        "guest": guest.get("name"),
        "post_findings": findings,
        "episode_findings": efind,
        "post_words": len(body.split()),
        "episode_words": len(story_writers.episode_text(ep).split()),
    }
    _save(out, f"wk{n}_report.json", report)
    print(
        f"  wk{n}: {title!r} ({report['post_words']} words) · episode {ep.get('title')!r} with {guest.get('name')} ({report['episode_words']} words) · findings post={len(findings)} episode={len(efind)}"
    )
    return {"ledger": new_ledger, "post": md, "episode": story_writers.episode_text(ep)}


def repair_week(out: str, n: int, notes: Optional[List[str]] = None, episode_notes: Optional[List[str]] = None) -> int:
    """Re-gate a STAGED week and fix only what the gates (and an editor's notes) still find, in the post and the
    episode, without re-running the desk. The budget and the ledger later weeks were built on are kept; only the
    installment's title in the ledger follows a retitled post."""
    dossier = _load(out, f"wk{n}_dossier.json")
    budget = _load(out, f"wk{n}_budget.json")
    prev_ledger = _load(out, f"wk{n - 1}_ledger.json") if n > 0 else story_ledger.empty_ledger()
    ledger = _load(out, f"wk{n}_ledger.json")
    report = _load(out, f"wk{n}_report.json")
    prev_post = _load(out, f"wk{n - 1}_chronicle.md") if n > 0 else None
    prev_ep = _load(out, f"wk{n - 1}_episode.txt") if n > 0 else None
    g = _Gates(n, dossier, budget, prev_ledger, _load(out, f"wk{n - 1}_dossier.json") if n > 0 else None)

    md = _load(out, f"wk{n}_chronicle.md")
    pf = [f"editor's note: {x}" for x in (notes or [])] + g.post(md, "end_turn")
    md, pf = _write_post(g, dossier, budget, prev_ledger, n, prev_post, md=md, findings=pf)
    _save(out, f"wk{n}_chronicle.md", md)
    title, body = story_writers.split_title(md)

    ep = _load(out, f"wk{n}_episode.json")
    guest = ep.get("guest") or {}
    full_guest = next((c for c in dossier.get("roster", []) if c.get("coach_id") == guest.get("coach_id")), guest)
    ef = [f"editor's note: {x}" for x in (episode_notes or [])] + g.episode(ep, "end_turn")
    ep, ef = _write_ep(g, dossier, budget, prev_ledger, n, body, prev_ep, full_guest, ep=ep, findings=ef)
    ep["guest"] = guest
    _save(out, f"wk{n}_episode.json", ep)
    _save(out, f"wk{n}_episode.txt", story_writers.episode_text(ep))

    for t in ledger.get("titles", []):
        if t.get("week") == n:
            t["title"] = title
    _save(out, f"wk{n}_ledger.json", ledger)
    report.update(
        {
            "title": title,
            "episode_title": ep.get("title"),
            "post_findings": pf,
            "episode_findings": ef,
            "repaired": True,
            "post_words": len(body.split()),
        }
    )
    _save(out, f"wk{n}_report.json", report)
    print(f"  wk{n} after repair: {title!r} · post findings={len(pf)} · episode findings={len(ef)}")
    return 0 if not (pf or ef) else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--through-week", type=int, default=None)
    ap.add_argument("--weeks", type=str, default=None, help="e.g. '3' or '2-4'; earlier weeks' ledger/text are read from --out")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repair", type=int, default=None, help="re-gate and fix a staged week's post without re-running the desk")
    ap.add_argument("--note", action="append", default=[], help="with --repair: an editor's note on the POST (repeatable)")
    ap.add_argument("--episode-note", action="append", default=[], help="with --repair: an editor's note on the EPISODE (repeatable)")
    args = ap.parse_args(argv)
    if args.repair is not None:
        return repair_week(args.out, args.repair, args.note, args.episode_note)
    os.makedirs(args.out, exist_ok=True)
    os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")
    table = _table()
    cal = story_dossier.season_weeks()
    last = args.through_week if args.through_week is not None else 4
    if args.weeks:
        a, _, b = args.weeks.partition("-")
        todo = list(range(int(a), int(b or a) + 1))
    else:
        todo = list(range(0, last + 1))
    by_week = {0: {"week": 0, "date": "2026-08-31", "day_last": 0}, **{w["week"]: w for w in cal}}
    first = todo[0]
    ledger = _load(args.out, f"wk{first - 1}_ledger.json") if first > 0 else story_ledger.empty_ledger()
    if ledger is None:
        print(f"no ledger for week {first - 1} in {args.out}; run the earlier weeks first")
        return 2
    prev_post = _load(args.out, f"wk{first - 1}_chronicle.md") if first > 0 else None
    if first == 1:
        prev_post = (prev_post or "") + "\n\n(Then, the day before Day 1, the sealed plan was published as:)\n\n" + _plan_prologue(table)
    prev_ep = _load(args.out, f"wk{first - 1}_episode.txt") if first > 0 else None
    for n in todo:
        print(f"week {n}…")
        res = run_week(table, by_week[n], args.out, ledger, prev_post, prev_ep)
        ledger, prev_post, prev_ep = res["ledger"], res["post"], res["episode"]
        if n == 0:
            prev_post = prev_post + "\n\n(Then, the day before Day 1, the sealed plan was published as:)\n\n" + _plan_prologue(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
