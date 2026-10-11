"""content/story_pipeline.py — one week through the Story Desk: gates, writers with corrective rewrites, the dek (#4535).

Shared by the season runner (scripts/season_rebuild.py) and the live Wednesday chronicle (wednesday_chronicle_lambda's
desk path) so the two can never drift: the same gates hold a rebuilt season and a live week.
"""

from __future__ import annotations

import os as _os
import re
from typing import Any, Dict, List, Optional

from content import story_checks, story_craft, story_ledger, story_writers

MAX_REWRITES = int(_os.environ.get("STORY_DESK_MAX_REWRITES", "2"))  # live: 1 (the 900s Lambda ceiling, #4535)


class _Gates:
    """Everything one week's installments are held to, built once per week."""

    def __init__(
        self,
        n: int,
        dossier: Dict[str, Any],
        budget: Dict[str, Any],
        prev_ledger: Dict[str, Any],
        prev_dossier: Optional[Dict[str, Any]] = None,
        previous: Optional[Dict[int, str]] = None,
    ):
        self.n, self.dossier = n, dossier
        self.previous = previous or {}  # week -> that installment's post + episode text (callback checks)
        self.corpus = story_craft.quote_corpus(dossier)
        self.owner_lines = [a.get("quotable") or a.get("answer") or "" for a in (dossier.get("owner_voice") or {}).get("answers", [])]
        # the series' own record is grounding too: a bet's threshold, last week's scored result
        self.allowed = story_checks.allowed_numbers(
            dossier, {"week": n}, budget.get("bet"), budget.get("bet_scored"), prev_ledger.get("bets"), prev_dossier or {}
        )
        self.nye = ["macrofactor"] if (dossier.get("nutrition") or {}).get("not_yet_exported_dates") else []
        w = dossier.get("weight") or {}
        # a week with a weigh-in: the opening must say which way the scale went (#4545)
        self.weight_known = bool(w.get("available"))
        self.weights = [x["lbs"] for x in w.get("weigh_ins_in_window", [])] + [
            x for x in (w.get(k, {}).get("lbs") for k in ("first_weigh_in", "week_start", "week_end")) if x
        ]
        self.weights += [326.2, 327.34, 327.3]
        self.context = {
            "last_weeks_open_bet": story_ledger.last_open_bet(prev_ledger),
            "this_weeks_bet_scoring": budget.get("bet_scored"),
            "this_weeks_new_bet": budget.get("bet"),
            "previous_titles": prev_ledger.get("titles", []),
            # last week's facts: an installment may recall them, so the fact read must be able to check them
            "previous_week_dossier": prev_dossier or {},
        }

    def dek(self, top_line: str) -> List[str]:
        """The desk's top line sits above the piece and is added after the writer's gates — so it gets its own."""
        if not top_line:
            return []
        return [
            f"dek: {f}"
            for f in story_checks.ungrounded_numbers(top_line, self.allowed)
            + story_checks.story_door(top_line)
            + story_craft.banned(top_line)
            + story_craft.top_line_findings(top_line)
        ] + [f"dek: {f}" for f in story_writers.fact_check(top_line, self.dossier, context=self.context)]

    def post(self, md: str, stop: Optional[str]) -> List[str]:
        _title, body = story_writers.split_title(md)
        return (
            story_checks.all_findings(
                md, stop_reason=stop, allowed=self.allowed, not_yet_exported=self.nye, footer_pattern=story_writers.CHRONICLE_FOOTER
            )
            + story_craft.chronicle_findings(body, week=self.n, weight_known=self.weight_known)
            + story_craft.callback_findings(body, self.previous)
            + story_craft.quote_findings(body, self.corpus)
            + story_craft.repeat_findings(body, self.previous, self.owner_lines)
            + story_writers.fact_check(md, self.dossier, context=self.context)
        )

    def episode(self, ep: Dict[str, Any], stop: Optional[str]) -> List[str]:
        txt = story_writers.episode_text(ep)
        return (
            story_checks.completeness(txt, stop_reason=stop)
            + story_checks.story_door(txt, not_yet_exported=self.nye)
            + story_checks.ungrounded_numbers(txt, self.allowed)
            + story_writers.spoken_word_findings(ep.get("turns", []), body_weights=self.weights)
            + story_craft.episode_findings(ep.get("turns", []), segments=self.n > 0)
            + story_craft.callback_findings(txt, self.previous)
            + story_craft.repeat_findings(txt, self.previous, self.owner_lines)
            + story_writers.fact_check(txt, self.dossier, context=self.context)
        )


def strip_dek(md: str) -> str:
    """The model never writes the dek; drop any italic dek lines right under the title before a rewrite."""
    title, body = story_writers.split_title(md)
    paras = body.split("\n\n")
    while paras and re.fullmatch(r"\*[^*].*[^*]\*", paras[0].strip()) and not paras[0].strip().startswith("*Week"):
        paras.pop(0)
    return f'"{title}"\n\n' + "\n\n".join(paras)


def with_dek(md: str, dossier: Dict[str, Any], ledger: Dict[str, Any], budget: Dict[str, Any], n: int) -> str:
    """The two italic lines a stranger reads first, rendered by code after the gates ran: the desk's plain top line
    and the scoreboard (never the model's numbers)."""
    title, body = story_writers.split_title(md)
    if n == 0:
        return md
    top = story_craft.tts_clean(budget.get("top_line") or "")  # the dek is prose a reader sees first: same cleanup
    sb = story_craft.scoreboard_line(story_craft.scoreboard(dossier, ledger))
    dek = "\n\n".join(f"*{x}*" for x in (top, sb) if x)
    return f'"{title}"\n\n{dek}\n\n{body}'


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


def stats_line(week: int, dossier: Dict[str, Any]) -> str:
    """The post's machine stat line (the manifest's dek under the title), computed from the dossier."""
    if week == 0:
        return "Prologue | Before Day 1 | Seattle, WA"
    w = dossier.get("weight") or {}
    t = dossier.get("training") or {}
    parts = [(dossier.get("window") or {}).get("experiment_days", "")]
    if w.get("available"):
        if w.get("week_change_lbs"):
            parts.append(f"{w['week_end']['lbs']} lbs ({w['week_change_lbs']:+} this week)")
        else:
            parts.append(f"{w['week_end']['lbs']} lbs at the first weigh-in")
    parts.append(f"{t.get('session_count', 0)} training sessions")
    return " · ".join(p for p in parts if p)


def live_week(table: Any, date_str: str, *, chronicle_pk: str = "USER#matthew#SOURCE#chronicle", log=print) -> Optional[Dict[str, Any]]:
    """One live week through the desk (#4535): the week ending ``date_str``, built from that window only, picking up
    the season ledger the last published installment left. Returns the installment + its episode + the ledger the
    week will leave on publish, or None when ``date_str`` is not a week end (the caller keeps the legacy path)."""
    from boto3.dynamodb.conditions import Key

    from content import story_desk, story_dossier

    wk = next((w for w in story_dossier.season_weeks(through=date_str) if w["end"] == date_str), None)
    if wk is None:
        return None
    n = wk["week"]
    dossier, _nye = story_dossier.week_dossier(table, wk)
    ledger = story_ledger.latest_visible(table, chronicle_pk, date_str)
    # the last two published installments: the writer's continuity and the callback/repeat gates' memory
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(chronicle_pk) & Key("sk").between("DATE#", f"DATE#{date_str}~"), ScanIndexForward=False
    )
    prior = [
        it
        for it in resp.get("Items", [])
        if it.get("status") == "published" and not it.get("tombstone") and not it.get("unlisted") and it.get("date", "") < date_str
    ][:2]
    previous = {max(0, n - 1 - i): str(it.get("content_markdown") or "") for i, it in enumerate(prior)}
    previous_post = previous.get(n - 1)
    budget = story_desk.run_desk(dossier, ledger, week=n, log=log)
    g = _Gates(n, dossier, budget, ledger, None, previous)
    md, findings = _write_post(g, dossier, budget, ledger, n, previous_post)
    findings += g.dek(budget.get("top_line") or "")
    title, body = story_writers.split_title(md)
    roster = dossier.get("roster", [])
    want = (budget.get("featured_coaches") or [None])[0]
    guest = next((c for c in roster if c.get("coach_id") == want), roster[0] if roster else {})
    ep, efind = _write_ep(g, dossier, budget, ledger, n, body, None, guest)
    ep["guest"] = {"name": guest.get("name"), "coach_id": guest.get("coach_id"), "persona_id": guest.get("persona_id")}
    ep["bet"] = budget.get("bet")
    new_ledger = story_ledger.apply_budget(ledger, budget, week=n, date=date_str, title=title)
    md = with_dek(md, dossier, new_ledger, budget, n)
    _t, body_with_dek = story_writers.split_title(md)
    sl = stats_line(n, dossier)
    return {
        "week": n,
        "title": title,
        "stats_line": sl,
        "raw_installment": f'"{title}"\n\n[{sl}]\n\n{body_with_dek}',
        "budget": budget,
        "episode": ep,
        "ledger": new_ledger,
        "findings": {"post": findings, "episode": efind},
    }
