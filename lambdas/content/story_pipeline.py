"""content/story_pipeline.py — one week through the Story Desk: gates, writers with corrective rewrites, the dek (#4535).

Shared by the season runner (scripts/season_rebuild.py) and the live Wednesday chronicle (wednesday_chronicle_lambda's
desk path) so the two can never drift: the same gates hold a rebuilt season and a live week.
"""

from __future__ import annotations

import os as _os
import re
from typing import Any, Dict, List, Optional

from content import story_checks, story_craft, story_editor, story_ledger, story_writers

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
            for f in story_checks.ungrounded_numbers(top_line, self.allowed) + story_checks.story_door(top_line) + self.craft_dek(top_line)
        ] + [f"dek: {f}" for f in story_writers.fact_check(top_line, self.dossier, context=self.context)]

    def craft_dek(self, top_line: str) -> List[str]:
        return story_craft.banned(top_line) + story_craft.top_line_findings(top_line)

    def craft_post(self, md: str) -> List[str]:
        """Only story_craft's verdict on a chronicle post: what routes the week to the preview (#4545, owner ruling "b")."""
        _title, body = story_writers.split_title(md)
        return (
            story_craft.chronicle_findings(body, week=self.n, weight_known=self.weight_known)
            + story_craft.callback_findings(body, self.previous)
            + story_craft.quote_findings(body, self.corpus)
            + story_craft.repeat_findings(body, self.previous, self.owner_lines)
        )

    def craft_episode(self, ep: Dict[str, Any]) -> List[str]:
        txt = story_writers.episode_text(ep)
        return (
            story_craft.episode_findings(ep.get("turns", []), segments=self.n > 0)
            + story_craft.callback_findings(txt, self.previous)
            + story_craft.repeat_findings(txt, self.previous, self.owner_lines)
        )

    def post(self, md: str, stop: Optional[str]) -> List[str]:
        return (
            story_checks.all_findings(
                md, stop_reason=stop, allowed=self.allowed, not_yet_exported=self.nye, footer_pattern=story_writers.CHRONICLE_FOOTER
            )
            + self.craft_post(md)
            + story_writers.fact_check(md, self.dossier, context=self.context)
        )

    # ── the hard gates alone (#6179) ─────────────────────────────────────────
    # With the editor on, the writer's corrective rewrites and the final verdict use these: every check of ``post``
    # except story_craft's STYLE findings (``chronicle_findings``, ``repeat_findings``), which become the editor's
    # notes. The quote and callback checks live in story_craft but are claims about sources and numbers, so they stay
    # here, hard. tests/test_story_editor_6179.py holds ``post_hard`` equal to ``post`` minus its style findings.

    def post_deterministic(self, md: str, stop: Optional[str]) -> List[str]:
        """The hard gates that need no model call: completeness, the story door, the figures against the dossier, the
        exact-quote gate and the callback gate."""
        _title, body = story_writers.split_title(md)
        return (
            story_checks.all_findings(
                md, stop_reason=stop, allowed=self.allowed, not_yet_exported=self.nye, footer_pattern=story_writers.CHRONICLE_FOOTER
            )
            + story_craft.callback_findings(body, self.previous)
            + story_craft.quote_findings(body, self.corpus)
        )

    def post_hard(self, md: str, stop: Optional[str]) -> List[str]:
        """``post_deterministic`` plus the fact read: the verifier's full verdict on one installment."""
        return self.post_deterministic(md, stop) + story_writers.fact_check(md, self.dossier, context=self.context)

    def dek_hard(self, top_line: str) -> List[str]:
        """The dek's truth checks (figures, the story door, the fact read). Its length, figure count and jargon are
        style (``craft_dek``) and, with the editor on, advisory."""
        if not top_line:
            return []
        return [f"dek: {f}" for f in story_checks.ungrounded_numbers(top_line, self.allowed) + story_checks.story_door(top_line)] + [
            f"dek: {f}" for f in story_writers.fact_check(top_line, self.dossier, context=self.context)
        ]

    def episode(self, ep: Dict[str, Any], stop: Optional[str]) -> List[str]:
        txt = story_writers.episode_text(ep)
        return (
            story_checks.completeness(txt, stop_reason=stop)
            + story_checks.story_door(txt, not_yet_exported=self.nye)
            + story_checks.ungrounded_numbers(txt, self.allowed)
            + story_writers.spoken_word_findings(ep.get("turns", []), body_weights=self.weights)
            + self.craft_episode(ep)
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


def _write_post_edited(g: _Gates, dossier, budget, ledger, n, previous, log=print):
    """#6179, behind ``STORY_EDITOR=on``: the writer drafts; corrective rewrites answer only the HARD findings; the
    editor revises (at most two rounds, every revision checked for new claims and new hard findings); then the hard
    gates run, unchanged, on the text the editor hands back. Returns ``(md, hard_findings, editor_record)``.

    The verifier's verdict on the final text is stored exactly as the off path stores it, so a revised draft that
    fails any hard gate is held exactly as before."""
    from content import story_editor

    md, stop = story_writers.write_chronicle(dossier, budget, ledger, week=n, previous=previous)
    findings = g.post_hard(md, stop)
    for _ in range(MAX_REWRITES):
        if not findings:
            break
        print(f"  wk{n} post: {len(findings)} hard finding(s) → corrective rewrite: {[f[:160] for f in findings]}")
        md, stop = story_writers.write_chronicle(dossier, budget, ledger, week=n, previous=previous, fix=findings, prior_draft=md)
        findings = g.post_hard(md, stop)
    if stop != "end_turn":
        return md, findings, {"accepted": 0, "rounds": [], "advisory": ["editor skipped: the writer's draft was cut off"], "cost_usd": 0.0}
    record = story_editor.revise(
        md,
        packet=story_editor.packet_for(dossier, budget, ledger, n, previous),
        allowed=g.allowed | story_editor.packet_numbers(dossier, budget, ledger),
        notes_for=lambda body: story_editor.craft_notes(
            body, dossier=dossier, weight_known=g.weight_known, previous=g.previous, owner_lines=g.owner_lines
        )
        + story_editor.review_notes(body, dossier),
        hard_check=lambda text: g.post_deterministic(text, "end_turn"),
        log=log,
    )
    if record.get("accepted"):
        md = record["text"]
        findings = g.post_hard(md, "end_turn")  # the verifier, on the revised text — the same gates, never fewer
    record.pop("text", None)
    return md, findings, record


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


def _published_before(table: Any, chronicle_pk: str, date_str: str, n: int) -> Dict[int, str]:
    """The last two published installments before ``date_str``, keyed n-1 and n-2: the writer's continuity and the
    callback/repeat gates' memory. One read for the desk and the legacy audit, so the two gates see the same past."""
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(chronicle_pk) & Key("sk").between("DATE#", f"DATE#{date_str}~"), ScanIndexForward=False
    )
    prior = [
        it
        for it in resp.get("Items", [])
        if it.get("status") == "published" and not it.get("tombstone") and not it.get("unlisted") and it.get("date", "") < date_str
    ][:2]
    return {max(0, n - 1 - i): str(it.get("content_markdown") or "") for i, it in enumerate(prior)}


# ── the legacy writer's door (#6155, #6178) ──────────────────────────────────
#
# When the desk declines or fails, the legacy writer drafts the week behind the same approval door. It never had the
# desk's quote or ledger checks, so a legacy week could carry a quote the platform does not hold (the 2026-10 wk6
# interview) or repeat a title the season already used.
#
# Switch OFF (the default, #6155 behaviour): the legacy draft runs the desk's quote, callback and title checks and is
# ALWAYS held, the reasons named.
# Switch ON (``CHRONICLE_LEGACY_ELIGIBLE=on`` on the chronicle Lambda; owner ruling 2026-11-22 §7, #6178): the draft runs
# EXACTLY the checks the desk's ``_Gates.post`` runs — the same functions, on the same dossier, ledger and published
# past: completeness + story door + figure grounding + staged encounters (``story_checks.all_findings``), the craft,
# callback, quote and repeat gates (``_Gates.craft_post``) and the fact read (``story_writers.fact_check``) — plus the
# season-title check. It then becomes ELIGIBLE for the owner's approve click when every non-craft finding is clear, the
# way a desk draft does. It is never published by anything but that click. A check that cannot run holds the draft and
# names which.

LEGACY_HOLD = "legacy_hold"
LEGACY_NOTE = (
    "legacy writer: the Story Desk did not write this draft, so its fact read and craft gates did not run and the "
    "season ledger will not advance on publish — held for the owner"
)
LEGACY_ELIGIBLE_ENV = "CHRONICLE_LEGACY_ELIGIBLE"
_STAT_HEADER = re.compile(r"^\s*\[[^\]\n]*\]\s*$")


def legacy_eligibility_on(env=None) -> bool:
    """The #6178 switch, default OFF: only the literals on/1/true turn it on."""
    return str((_os.environ if env is None else env).get(LEGACY_ELIGIBLE_ENV) or "").strip().lower() in ("on", "1", "true")


def _legacy_text(md: str):
    """``(title, md_for_the_gates)``: the legacy draft as the desk's gates read a desk post — the quoted title, then the
    body, without the legacy machine header (a parsed data field, never prose)."""
    title, body = story_writers.split_title(md)
    body = "\n".join(line for line in body.splitlines() if not _STAT_HEADER.match(line))
    return title, f'"{title}"\n\n{body.strip()}', body


def _title_findings(title: str, ledger: Dict[str, Any]) -> List[str]:
    used = {str((t or {}).get("title") if isinstance(t, dict) else t).strip().lower() for t in ledger.get("titles", [])}
    return [f"ledger: the title {title!r} repeats one the season has already used"] if title and title.strip().lower() in used else []


def legacy_findings(g: _Gates, md: str, ledger: Dict[str, Any]) -> List[str]:
    """The desk's quote and ledger checks on a legacy draft: exact quotes against what the platform holds, callbacks
    against the published installments, and the title against the season's titles. Pure."""
    title, _md, body = _legacy_text(md)
    out = story_craft.quote_findings(body, g.corpus) + story_craft.callback_findings(body, g.previous)
    return out + _title_findings(title, ledger)


def legacy_gate_findings(g: _Gates, md: str, ledger: Dict[str, Any], *, fact_check=None) -> List[str]:
    """#6178: the desk's FULL post gate on a legacy draft — the three parts of ``_Gates.post`` called one by one, so a
    part that cannot run is named. ``stop_reason`` is None: the legacy writer does not carry the model's stop signal, so
    completeness reads the text (a cut last line, a missing footer). Returns the findings; a part that raised adds a
    ``legacy audit: … could not run`` item, which blocks (it is not a craft note). ``fact_check`` defaults to the desk's."""
    title, gmd, _body = _legacy_text(md)
    fact = fact_check or story_writers.fact_check
    parts = (
        (
            "source, privacy and figure checks",
            lambda: story_checks.all_findings(
                gmd, stop_reason=None, allowed=g.allowed, not_yet_exported=g.nye, footer_pattern=story_writers.CHRONICLE_FOOTER
            ),
        ),
        ("quote, callback, craft and repeat checks", lambda: g.craft_post(gmd)),
        ("fact read", lambda: fact(gmd, g.dossier, context=g.context)),
    )
    out: List[str] = []
    for name, run in parts:
        try:
            out += list(run())
        except Exception as e:  # noqa: BLE001 — a check that cannot run holds the draft, named
            out.append(f"legacy audit: the {name} could not run ({type(e).__name__}: {e})")
    return out + _title_findings(title, ledger)


def legacy_audit(
    table: Any, date_str: str, md: str, *, chronicle_pk: str = "USER#matthew#SOURCE#chronicle", eligible=None, fact_check=None
) -> List[str]:
    """Every finding on a LEGACY-written draft for the week ending ``date_str`` (#6155, #6178). Never empty.

    Switch off (``eligible`` defaults to ``legacy_eligibility_on()``): the first item is ``LEGACY_NOTE`` (blocking), then
    the desk's quote/callback/title findings. Switch on: the first item is ``autopublish_audit.LEGACY_CHECKED_NOTE`` (an
    information line the audit does not block on), then every finding of the desk's full post gate. Either way, a week
    the checks cannot read (not a season week end, a read failure) is held with ``LEGACY_NOTE`` and the reason — never a
    silent pass."""
    from content import autopublish_audit, story_dossier

    on = legacy_eligibility_on() if eligible is None else bool(eligible)
    try:
        wk = next((w for w in story_dossier.season_weeks(through=date_str) if w["end"] == date_str), None)
        if wk is None:
            return [LEGACY_NOTE, f"legacy audit: {date_str} is not a season week end, so the desk's quote and ledger checks had no dossier"]
        n = wk["week"]
        dossier, _nye = story_dossier.week_dossier(table, wk)
        ledger = story_ledger.latest_visible(table, chronicle_pk, date_str)
        previous = _published_before(table, chronicle_pk, date_str, n)
    except Exception as e:  # noqa: BLE001 — a check that cannot run holds the week, it never passes it
        return [LEGACY_NOTE, f"legacy audit: the desk's quote and ledger checks could not run ({type(e).__name__}: {e})"]
    g = _Gates(n, dossier, {}, ledger, None, previous)
    if not on:
        return [LEGACY_NOTE] + legacy_findings(g, md, ledger)
    return [autopublish_audit.LEGACY_CHECKED_NOTE] + legacy_gate_findings(g, md, ledger, fact_check=fact_check)


def live_week(table: Any, date_str: str, *, chronicle_pk: str = "USER#matthew#SOURCE#chronicle", log=print) -> Optional[Dict[str, Any]]:
    """One live week through the desk (#4535): the week ending ``date_str``, built from that window only, picking up
    the season ledger the last published installment left. Returns the installment + its episode + the ledger the
    week will leave on publish, or None when ``date_str`` is not a week end (the caller keeps the legacy path)."""
    from content import story_desk, story_dossier

    wk = next((w for w in story_dossier.season_weeks(through=date_str) if w["end"] == date_str), None)
    if wk is None:
        return None
    n = wk["week"]
    dossier, _nye = story_dossier.week_dossier(table, wk)
    ledger = story_ledger.latest_visible(table, chronicle_pk, date_str)
    previous = _published_before(table, chronicle_pk, date_str, n)  # the writer's continuity and the callback/repeat gates' memory
    previous_post = previous.get(n - 1)
    budget = story_desk.run_desk(dossier, ledger, week=n, log=log)
    g = _Gates(n, dossier, budget, ledger, None, previous)
    editor: Optional[Dict[str, Any]] = None
    if story_editor.enabled():  # #6179: the editor revises, the verifier verifies; off = the lines below it, unchanged
        md, findings, editor = _write_post_edited(g, dossier, budget, ledger, n, previous_post, log=log)
        findings += g.dek_hard(budget.get("top_line") or "")
    else:
        md, findings = _write_post(g, dossier, budget, ledger, n, previous_post)
        findings += g.dek(budget.get("top_line") or "")
    title, body = story_writers.split_title(md)
    roster = dossier.get("roster", [])
    want = (budget.get("featured_coaches") or [None])[0]
    guest = next((c for c in roster if c.get("coach_id") == want), roster[0] if roster else {})
    ep, efind = _write_ep(g, dossier, budget, ledger, n, body, None, guest)
    ep["guest"] = {"name": guest.get("name"), "coach_id": guest.get("coach_id"), "persona_id": guest.get("persona_id")}
    ep["bet"] = budget.get("bet")
    new_ledger = story_ledger.apply_budget(
        ledger, budget, week=n, date=date_str, title=title, owner_answers=(dossier.get("owner_voice") or {}).get("answers")
    )
    md = with_dek(md, dossier, new_ledger, budget, n)
    _t, body_with_dek = story_writers.split_title(md)
    sl = stats_line(n, dossier)
    if editor is not None:
        # the craft verdict is the editor's input and the owner's ADVISORY notes; never empty, so a revised week always
        # routes to the preview and waits for his click (publish_holds / craft_hold), whatever PREVIEW_MODE says
        craft = story_editor.advisory_lines(editor) + [
            story_editor.ADVISORY_PREFIX + f for f in g.craft_episode(ep) + g.craft_dek(budget.get("top_line") or "")
        ]
        return {
            "week": n,
            "title": title,
            "stats_line": sl,
            "raw_installment": f'"{title}"\n\n[{sl}]\n\n{body_with_dek}',
            "budget": budget,
            "episode": ep,
            "ledger": new_ledger,
            "findings": {"post": findings, "episode": efind},
            "craft_findings": craft,
            "editor": editor,
        }
    return {
        "week": n,
        "title": title,
        "stats_line": sl,
        "raw_installment": f'"{title}"\n\n[{sl}]\n\n{body_with_dek}',
        "budget": budget,
        "episode": ep,
        "ledger": new_ledger,
        "findings": {"post": findings, "episode": efind},
        # story_craft's residual verdict on the final texts: any of these routes the week to the preview, never auto-published (#4545 "b")
        "craft_findings": g.craft_post(f'"{title}"\n\n{body}') + g.craft_episode(ep) + g.craft_dek(budget.get("top_line") or ""),
    }
