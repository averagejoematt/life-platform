"""tests/personal_context_cases_6291.py — the known-answer cases for the one personal-context assembly (#6291, #6226).

Coach evaluations judge the reply; these judge what the coach was HANDED. A small synthetic store goes in, each
channel's REAL context builder renders, and the rendered text must contain the stored fact with its date (or must not
contain a fact that may never reach a coach). No model call, no AWS: the store is an in-memory table that evaluates
the real query shapes, every boto3 client is replaced by one that raises, and the clock is pinned.

THE CHANNELS (each one the code that builds that channel's context in production):
  telegram  `telegram_worker_lambda._assemble` -> `coach_chat.build_system_blocks` + `coach_chat.format_thread`
            — exactly the system prompt (cached prefix + dynamic tail) and the message list a turn sends.
  packet    `tools_coach_packet.tool_get_coach_session_packet` — the Claude app's pre-flight read. Its readers are
            limited to the two that carry personal context (`open_corrections`, `calibration_cadence`; plus `lift_history`, which the tool logs by name) and the
            training-charter block (`attach_coach_context`) is passed through: neither is under test here.
  brief     the daily brief's coach context. `_run_coach_v2_pipeline` assembles its prompt inline between two
            Lambda invokes, so the harness calls the SAME functions it calls for the personal parts:
            `platform_memory_block`, `_coach_corrections_block`, `daily_brief_lambda._latest_item` (the scan) and the
            domain builders `_build_<domain>_data` -> `coach_input_facts.coach_inputs`, formatted as the prompt does.
  Each of telegram / packet renders twice: the coach-context switch OFF (production today) and ON
  (`coach_context_pilot.LIVE` patched True for the render only). The brief does not consume the assembly.

THE CASES: 1-3 are the owner's 2026-11-23 ruling (#6226); 4-8 are the recorded misses of the November evaluation and
of #6300/#6301 (one case per miss, none speculative).

Every fixture value is SYNTHETIC: invented figures, invented words marked "synthetic", dates chosen by hand.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Optional
from unittest import mock

from boto3.dynamodb.conditions import AttributeBase, ConditionBase

TODAY = "2026-11-20"
NOW_UTC = "2026-11-20T17:30:00+00:00"
SYN_CYCLE = 17
LEAD = "eli_marsh"
COMPLETE_LOG_KCAL = 1200.0  # the complete-log line, pinned (the charter value is not under test)

# ── the in-memory table ─────────────────────────────────────────────────────────────────────


class ReadOnlyViolation(AssertionError):
    pass


def _eval_cond(cond, item) -> bool:
    op = cond.expression_operator
    vals = cond._values
    if op == "AND":
        return all(_eval_cond(c, item) for c in vals)
    if op == "OR":
        return any(_eval_cond(c, item) for c in vals)
    if op == "NOT":
        return not _eval_cond(vals[0], item)
    name = vals[0].name if isinstance(vals[0], AttributeBase) else vals[0]
    actual = item.get(name)
    other = [v.name if isinstance(v, AttributeBase) else v for v in vals[1:]]
    if op == "=":
        return actual == other[0]
    if op == "<>":
        return actual != other[0]
    if op in ("<", "<=", ">", ">="):
        return (
            actual is not None and {"<": actual < other[0], "<=": actual <= other[0], ">": actual > other[0], ">=": actual >= other[0]}[op]
        )
    if op == "BETWEEN":
        return actual is not None and other[0] <= actual <= other[1]
    if op == "begins_with":
        return isinstance(actual, str) and actual.startswith(other[0])
    if op == "attribute_not_exists":
        return name not in item
    if op == "attribute_exists":
        return name in item
    raise NotImplementedError(op)


class _Expr:
    """A recursive-descent evaluator for the string expressions this codebase writes: AND / OR / NOT, parentheses,
    `attribute_(not_)exists(x)`, `begins_with(x, :v)`, `x BETWEEN :a AND :b`, and the six comparisons. An expression
    it cannot parse raises, and the table records it — a fake that silently answers True is how a filter goes untested."""

    _TOK = re.compile(r"\s*(\(|\)|,|<>|<=|>=|=|<|>|[#:]?[A-Za-z_][A-Za-z0-9_.\-]*)")

    def __init__(self, text: str, names: dict, values: dict):
        self.toks, pos = [], 0
        text = text.strip()
        while pos < len(text):
            m = self._TOK.match(text, pos)
            if not m:
                raise NotImplementedError(f"cannot tokenise {text[pos:]!r}")
            self.toks.append(m.group(1))
            pos = m.end()
        self.i, self.names, self.values = 0, names or {}, values or {}

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _next(self):
        t = self._peek()
        self.i += 1
        return t

    def _name(self, t):
        return self.names.get(t, t)

    def _val(self, t):
        if t.startswith(":"):
            return self.values[t]
        return t

    def parse(self, item):
        self.item = item
        out = self._or()
        if self._peek() is not None:
            raise NotImplementedError(f"trailing tokens {self.toks[self.i:]}")
        return out

    def _or(self):
        v = self._and()
        while self._peek() and self._peek().upper() == "OR":
            self._next()
            v = self._and() or v
        return v

    def _and(self):
        v = self._not()
        while self._peek() and self._peek().upper() == "AND":
            self._next()
            r = self._not()
            v = v and r
        return v

    def _not(self):
        if self._peek() and self._peek().upper() == "NOT":
            self._next()
            return not self._not()
        return self._atom()

    def _atom(self):
        t = self._next()
        if t == "(":
            v = self._or()
            assert self._next() == ")"
            return v
        if t in ("attribute_not_exists", "attribute_exists", "begins_with"):
            assert self._next() == "("
            name = self._name(self._next())
            arg = None
            if t == "begins_with":
                assert self._next() == ","
                arg = self._val(self._next())
            assert self._next() == ")"
            actual = self.item.get(name)
            if t == "attribute_not_exists":
                return name not in self.item
            if t == "attribute_exists":
                return name in self.item
            return isinstance(actual, str) and actual.startswith(arg)
        name = self._name(t)
        op = self._next()
        actual = self.item.get(name)
        if op and op.upper() == "BETWEEN":
            lo = self._val(self._next())
            assert self._next().upper() == "AND"
            hi = self._val(self._next())
            return actual is not None and lo <= actual <= hi
        rhs = self._val(self._next())
        if op == "=":
            return actual == rhs
        if op == "<>":
            return actual != rhs
        if actual is None:
            return False
        return {"<": actual < rhs, "<=": actual <= rhs, ">": actual > rhs, ">=": actual >= rhs}[op]


class StoreTable:
    """A DynamoDB Table double that evaluates the real key and filter expressions (Key/Attr objects AND strings),
    applies Limit BEFORE the filter (as DynamoDB does), and REFUSES every write — a context read that writes is a
    finding, so `writes` is asserted empty by the tests."""

    def __init__(self, items: list[dict]):
        self.items = {(i["pk"], i["sk"]): dict(i) for i in items}
        self.writes: list = []
        self.unsupported: list = []
        self.queries = 0

    def _match(self, expr, item, names, values) -> bool:
        if isinstance(expr, ConditionBase):
            return _eval_cond(expr, item)
        try:
            return _Expr(expr, names, values).parse(item)
        except (NotImplementedError, AssertionError, KeyError) as e:
            self.unsupported.append((expr, repr(e)))
            raise

    def query(self, **kw):
        self.queries += 1
        names, values = kw.get("ExpressionAttributeNames") or {}, kw.get("ExpressionAttributeValues") or {}
        rows = [dict(i) for i in self.items.values() if self._match(kw["KeyConditionExpression"], i, names, values)]
        rows.sort(key=lambda i: i["sk"], reverse=not kw.get("ScanIndexForward", True))
        start = kw.get("ExclusiveStartKey")
        if start:
            idx = next((n for n, r in enumerate(rows) if (r["pk"], r["sk"]) == (start["pk"], start["sk"])), -1)
            rows = rows[idx + 1 :]
        limit = kw.get("Limit")
        page = rows[:limit] if limit else rows
        last = {"pk": page[-1]["pk"], "sk": page[-1]["sk"]} if limit and len(rows) > limit else None
        flt = kw.get("FilterExpression")
        if flt is not None:
            page = [r for r in page if self._match(flt, r, names, values)]
        out = {"Items": page, "Count": len(page)}
        if last:
            out["LastEvaluatedKey"] = last
        return out

    def get_item(self, Key, **_kw):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def _refuse(self, name, kw):
        self.writes.append((name, kw))
        raise ReadOnlyViolation(f"a context read attempted {name}")

    def put_item(self, **kw):
        self._refuse("put_item", kw)

    def update_item(self, **kw):
        self._refuse("update_item", kw)

    def delete_item(self, **kw):
        self._refuse("delete_item", kw)


# ── the synthetic store ─────────────────────────────────────────────────────────────────────

U = "USER#matthew#SOURCE#"
SCAN_DAY = "2025-12-01"  # before every cycle genesis on record: a historical scan by construction
SCAN_LEAN = "168.2"
DECISION_DAY = "2026-11-12"
CORRECTION_DAY = "2026-11-14"
NOTE_DAY = "2026-11-18"
RECORD_DAY = "2026-11-05"
WORDS = {
    "decision": "Swap the Saturday long walk for two short walks (synthetic decision delta)",
    "override": "synthetic reason: travelling",
    "correction": "Synthetic correction hotel: the long walk is on Sunday, not Saturday",
    "record": "Synthetic record echo: he lifts before work on weekdays",
    "private": "Synthetic record foxtrot, kept private",
    "interpretation": "Synthetic record golf, an interpretation he has not confirmed",
    "older": "Synthetic request alpha: what should my Saturday look like?",
    "older_same_day": "Synthetic request alpha-two: is the deload this week?",
    "newest": "Synthetic request bravo: move my Sunday walk to the morning",
    "note": "Synthetic note charlie: he asked about protein timing.",
    "profile_dispute": "Synthetic dispute india: the profile reads my consistency wrong, the plan changed that month",
    "profile_closed": "Synthetic dispute juliet: closed and kept as history",
}
PROFILE_DISPUTE_DAY = "2026-11-15"


def _days(n_back: int, end: str = TODAY) -> list[str]:
    from common.pacific_time import shift_day_key

    return [shift_day_key(end, -k) for k in range(n_back - 1, -1, -1)]


def synthetic_store() -> list[dict]:
    from coach import coach_chat, coach_corrections
    from common.constants import EXPERIMENT_START_DATE

    rows: list[dict] = []
    rows.append(
        {
            "pk": U + "dexa",
            "sk": f"DATE#{SCAN_DAY}",
            "scan_date": SCAN_DAY,
            "scan_type": "dexa",
            "provider": "synthetic_provider",
            "body_composition": {
                "total_mass_lb": Decimal("288.4"),
                "lean_mass_lb": Decimal(SCAN_LEAN),
                "fat_mass_lb": Decimal("112.6"),
                "body_fat_pct": Decimal("39.0"),
            },
        }
    )
    # Genesis-to-today synthetic weigh-ins (0.1 lb a day down), food log and Whoop energy; every 7th food day missing.
    from common.pacific_time import parse_day_key

    span = (parse_day_key(TODAY) - parse_day_key(str(EXPERIMENT_START_DATE))).days + 1
    for k, day in enumerate(_days(span)):
        rows.append({"pk": U + "withings", "sk": f"DATE#{day}", "date": day, "weight_lbs": Decimal(str(round(290 - 0.1 * k, 1)))})
        if k % 7:
            rows.append({"pk": U + "macrofactor", "sk": f"DATE#{day}", "date": day, "total_calories_kcal": Decimal("1900")})
        rows.append({"pk": U + "whoop", "sk": f"DATE#{day}", "date": day, "kilojoule": Decimal(str(round(2500 * 4.184, 1)))})
    rows.append(
        {
            "pk": U + "decisions",
            "sk": f"DECISION#{DECISION_DAY}T16:00:00.000Z",
            "date": DECISION_DAY,
            "decision": WORDS["decision"],
            "source": "daily_brief",
            "followed": False,
            "override_reason": WORDS["override"],
        }
    )
    rows.append(
        {
            "pk": coach_corrections.PK,
            "sk": f"CORRECTION#{CORRECTION_DAY}#c0ffee01",
            "status": "open",
            "error_class": "factual",
            "correction_text": WORDS["correction"],
            "item_ref": {"surface": "chat_coaching"},
            "created_at": f"{CORRECTION_DAY}T17:00:00+00:00",
            "cycle": SYN_CYCLE,
        }
    )
    # #6294: his open dispute of a development-profile line (and a closed one, which is history, never context)
    for sfx, status, text in (("d15p0001", "open", WORDS["profile_dispute"]), ("d15p0002", "closed", WORDS["profile_closed"])):
        rows.append(
            {
                "pk": coach_corrections.PK,
                "sk": f"CORRECTION#{PROFILE_DISPUTE_DAY}#{sfx}",
                "status": status,
                "error_class": "framing",
                "correction_text": text,
                "item_ref": {"surface": "development_profile", "signal": "development_profile:behavioural_consistency"},
                "created_at": f"{PROFILE_DISPUTE_DAY}T17:00:00+00:00",
                "cycle": SYN_CYCLE,
            }
        )
    pm = U + "platform_memory"
    base = {
        "pk": pm,
        "date": RECORD_DAY,
        "channel": "conversation",
        "category": "personal_record",
        "owner_reviewed_at": f"{RECORD_DAY}T18:00:00Z",
    }
    rows.append(
        dict(
            base,
            sk=f"MEMORY#personal_record#{RECORD_DAY}#a1",
            privacy_tier="coach_context",
            evidence_kind="owner_statement",
            text=WORDS["record"],
        )
    )
    rows.append(
        dict(
            base,
            sk=f"MEMORY#personal_record#{RECORD_DAY}#a2",
            privacy_tier="private",
            evidence_kind="owner_statement",
            text=WORDS["private"],
        )
    )
    rows.append(
        dict(
            base,
            sk=f"MEMORY#personal_record#{RECORD_DAY}#a3",
            privacy_tier="coach_context",
            evidence_kind="ai_interpretation",
            text=WORDS["interpretation"],
        )
    )
    # The lead's chat. On 11-19 the sort keys put alpha-two AFTER bravo, but bravo was sent later: key order is not
    # send order (the CHAT# suffix is random within a day), so only the stored timestamps can name the newest message.
    lead_pk = coach_chat.chat_pk(LEAD)
    chat = [
        ("CHAT#2026-11-16#aaaa0001", "matthew", WORDS["older"], "2026-11-16T17:00:00+00:00"),
        ("CHAT#2026-11-16#aaaa0002", "coach", "Synthetic reply one.", "2026-11-16T17:00:00+00:00"),
        ("CHAT#2026-11-19#0000aaaa", "matthew", WORDS["newest"], "2026-11-19T22:00:00+00:00"),
        ("CHAT#2026-11-19#0000aaab", "coach", "Synthetic reply three.", "2026-11-19T22:00:00+00:00"),
        ("CHAT#2026-11-19#ffff0001", "matthew", WORDS["older_same_day"], "2026-11-19T15:00:00+00:00"),
        ("CHAT#2026-11-19#ffff0002", "coach", "Synthetic reply two.", "2026-11-19T15:00:00+00:00"),
    ]
    for sk, role, text, ts in chat:
        rows.append({"pk": lead_pk, "sk": sk, "role": role, "text": text, "created_at": ts, "coach_id": LEAD})
    rows.append({"pk": lead_pk, "sk": f"CHAT#summary#{NOTE_DAY}", "text": WORDS["note"]})
    return rows


# ── hermetic environment: no AWS, pinned clock ──────────────────────────────────────────────


class _NoAws:
    """Every boto3 client/resource in a render: any call raises, so a reader that reaches past the store fails soft
    (its own contract) instead of reaching a real account."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        def _raise(*a, **k):
            raise ConnectionError(f"AWS is unreachable in the #6291 harness ({name})")

        return _raise

    def Table(self, *a, **k):  # noqa: N802 — boto3's own spelling
        return self


@contextlib.contextmanager
def hermetic(table: StoreTable, day: str = TODAY, now_utc: str = NOW_UTC, *, pilot: bool = False):
    """Patch the clock, AWS and the switch for one render. `pilot` sets `coach_context_pilot.LIVE`."""
    from ai import platform_memory
    from coach import coach_checkin, coach_context_pilot, coach_corrections, telegram_worker_lambda as tw
    from common import pacific_time
    from common.pacific_time import PACIFIC
    from health import grounded_intake_facts as gif
    from training import program_structure

    now = datetime.fromisoformat(now_utc).astimezone(PACIFIC)
    patches = [
        mock.patch("boto3.client", _NoAws),
        mock.patch("boto3.resource", _NoAws),
        mock.patch.object(pacific_time, "pacific_now", lambda: now),
        mock.patch.object(pacific_time, "pacific_today", lambda: day),
        mock.patch.object(platform_memory, "pacific_now", lambda: now),
        mock.patch.object(coach_context_pilot, "LIVE", pilot),
        mock.patch.object(coach_context_pilot, "_today", lambda: day),
        mock.patch.object(coach_corrections, "read_cycle", lambda: SYN_CYCLE),
        mock.patch.object(coach_checkin, "read_cycle", lambda: SYN_CYCLE),
        mock.patch.object(gif, "default_complete_log_kcal", lambda: COMPLETE_LOG_KCAL),
        mock.patch.object(program_structure, "ACTIVE", False),  # the planned session is not under test
        mock.patch.object(tw, "_table", lambda: table),
        mock.patch.object(tw, "_s3_client", lambda: _NoAws()),
        mock.patch.object(tw, "_pacific_now", lambda: now),
    ]
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


# ── the channel renderers (the real builders) ───────────────────────────────────────────────


@dataclass
class Rendered:
    text: str  # everything the model would be handed, flattened
    cached_prefix: str = ""  # the prompt-cache prefix (telegram only); personal context must never be in it


def render_telegram(table: StoreTable, persona: str, *, pilot: bool, day: str = TODAY) -> Rendered:
    from coach import coach_chat, telegram_worker_lambda as tw

    with hermetic(table, day, pilot=pilot):
        a = tw._assemble(persona, persona)
    blocks = coach_chat.build_system_blocks(a["persona"], a["memory"], a["facts_block"], a["coach_name"], colleagues_block=a["colleagues"])
    cached = "\n\n".join(b["text"] for b in blocks if b.get("cache_control"))
    tail = "\n\n".join(b["text"] for b in blocks if not b.get("cache_control"))
    thread = "\n".join(f"[{m['role']}] {m['content']}" for m in coach_chat.format_thread(a["thread"]))
    return Rendered(f"SYSTEM (cached prefix):\n{cached}\n\nSYSTEM (dynamic tail):\n{tail}\n\nTHREAD:\n{thread}", cached)


def _flatten(value: Any, path: str = "") -> list[str]:
    """A tool payload as the model reads it: one `path: value` line per leaf; a multi-line string kept as its own
    paragraph; a blank line between top-level fields."""
    if isinstance(value, dict):
        out: list[str] = []
        for k, v in value.items():
            out += _flatten(v, f"{path}.{k}" if path else k)
            if not path or path.count(".") < 1:
                out.append("")
        return out
    if isinstance(value, list):
        out = []
        for n, v in enumerate(value):
            out += _flatten(v, f"{path}[{n}]")
        return out
    if isinstance(value, str) and "\n" in value:
        return ["", f"{path}:", value, ""]
    return [f"{path}: {json.dumps(value, default=str) if not isinstance(value, str) else value}"]


def render_packet(table: StoreTable, *, pilot: bool, day: str = TODAY) -> Rendered:
    from mcp import config as mcfg, core as mcore, plan_helpers, tools_coach_packet as pkt

    readers = {k: pkt.READERS[k] for k in ("open_corrections", "calibration_cadence", "lift_history")}
    with (
        hermetic(table, day, pilot=pilot),
        mock.patch.object(mcfg, "table", table),
        mock.patch.object(mcore, "table", table),
        mock.patch.object(pkt, "READERS", readers),
        mock.patch.object(plan_helpers, "attach_coach_context", lambda out, *a, **k: out),
    ):
        out = pkt.tool_get_coach_session_packet({"target_date": day})
    return Rendered("\n".join(_flatten(out)))


def render_brief(table: StoreTable, coach_id: str, *, day: str = TODAY) -> Rendered:
    import os

    for k, v in (("EMAIL_RECIPIENT", "owner@example.invalid"), ("EMAIL_SENDER", "brief@example.invalid")):
        os.environ.setdefault(k, v)  # the brief module refuses to import without them; nothing here sends
    from ai import ai_calls, platform_memory
    from coach import coach_input_facts
    from emails import daily_brief_lambda as dbl

    domains = {
        "physical_coach": ("physical", ai_calls._build_physical_data),
        "nutrition_coach": ("nutrition", ai_calls._build_nutrition_data),
    }
    label, build = domains[coach_id]
    with hermetic(table, day), mock.patch.object(dbl, "table", table):
        data = {"dexa": dbl._latest_item("dexa") or {}}
        memory = platform_memory.platform_memory_block(coach_id=coach_id, table=table)
        domain = coach_input_facts.coach_inputs(coach_id, build(data), data, table=table)
        corrections = ai_calls._coach_corrections_block(coach_id, table=table)
    text = f"{memory}\n\n{label.upper()} DATA:\n{json.dumps(domain, indent=2, default=str)}\n\n{corrections}"
    return Rendered(text)


# ── the cases ───────────────────────────────────────────────────────────────────────────────


def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _dated(text: str, iso: str) -> bool:
    from common.pacific_time import day_in_words

    return iso in text or day_in_words(iso) in text


_MARKED = re.compile(r"\b(latest|most recent)\b", re.I)


def _latest_marker(text: str, newest: str, *older: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if _MARKED.search(ln)]
    out = []
    if not any(newest in ln for ln in lines):
        out.append(f"his newest message ({newest[:30]!r}) is not the one marked latest")
    for o in older:
        if any(o in ln for ln in lines):
            out.append(f"an older item ({o[:30]!r}) is marked latest")
    return out


def case_scan(text: str) -> list[str]:
    paras = [p for p in _paragraphs(text) if SCAN_LEAN in p]
    if not paras:
        return [f"the stored scan's figures (lean mass {SCAN_LEAN}) are not in the context"]
    p = paras[0]
    out = []
    if not _dated(p, SCAN_DAY):
        out.append(f"the scan is not labelled with its date {SCAN_DAY}")
    if not re.search(r"historical|old evidence|not (his )?current|on that date", p, re.I):
        out.append("the scan is not labelled as old evidence")
    return out


def case_intake(text: str) -> list[str]:
    paras = [p for p in _paragraphs(text) if re.search(r"implied", p, re.I) and re.search(r"logged", p, re.I)]
    if not paras:
        return ["no logged-against-implied intake analysis is in the context"]
    p = paras[0]
    out = []
    if not _dated(p, TODAY):
        out.append("the analysis does not name its window (ending today)")
    if not re.search(r"estimate", p, re.I):
        out.append("the analysis carries no caveat that implied intake is an estimate")
    return out


def case_latest_over_older_request(text: str) -> list[str]:
    return _latest_marker(text, WORDS["newest"], WORDS["older"], WORDS["older_same_day"])


def case_latest_over_dated_note(text: str) -> list[str]:
    return _latest_marker(text, WORDS["newest"], WORDS["note"])


def case_decision(text: str) -> list[str]:
    paras = [p for p in _paragraphs(text) if WORDS["decision"] in p]
    if not paras:
        return ["the recorded decision is not in the context"]
    p = paras[0]
    out = []
    if not _dated(p, DECISION_DAY):
        out.append(f"the decision is not dated {DECISION_DAY}")
    if not re.search(r"overr(ode|idden)|did not follow", p, re.I):
        out.append("the decision does not carry his followed/overrode answer")
    if re.search(r"priorit", p, re.I):
        out.append("the decision is presented as a priority he set")
    return out


def case_correction(text: str) -> list[str]:
    return [] if WORDS["correction"] in text else ["the open correction is not in the context"]


def case_personal_record(text: str) -> list[str]:
    out = []
    lines = [ln for ln in text.splitlines() if WORDS["record"] in ln]
    if not lines:
        out.append("the owner-approved coach_context personal record is not in the context")
    elif not any("his statement" in ln for ln in lines):
        out.append("the personal record is not carried with its evidence label")
    if WORDS["private"] in text:
        out.append("a PRIVATE personal record reached the context")
    if WORDS["interpretation"] in text:
        out.append("an interpretation reached the context as fact")
    return out


def case_cycle_day_confined(text: str) -> list[str]:
    bad = [ln.strip()[:90] for ln in text.splitlines() if re.search(r"\bDay \d+\b", ln) and "Cycle calendar" not in ln]
    return [f"a bare cycle-day count is handed over as a fact: {b!r}" for b in bad]


def case_profile_dispute(text: str) -> list[str]:
    out = []
    lines = [ln for ln in text.splitlines() if WORDS["profile_dispute"] in ln]
    if not lines:
        out.append("his open dispute of a development-profile line is not in the context")
    elif not any(_dated(ln, PROFILE_DISPUTE_DAY) for ln in lines):
        out.append("the dispute is not dated")
    if WORDS["profile_closed"] in text:
        out.append("a CLOSED profile correction reached the context")
    return out


@dataclass
class Case:
    n: int
    name: str
    check: Callable[[str], list]
    seats: dict  # channel -> persona/coach, or a "n/a: reason" string
    source: str = ""


NA = "n/a: "
CASES = [
    Case(
        1,
        "historical body-composition scan, dated",
        case_scan,
        {"telegram": "physical_coach", "packet": LEAD, "brief": "physical_coach"},
        "ruling 2026-11-23",
    ),
    Case(
        2,
        "qualified intake analysis",
        case_intake,
        {"telegram": "nutrition_coach", "packet": LEAD, "brief": "nutrition_coach"},
        "ruling 2026-11-23",
    ),
    Case(
        3,
        "his actual newest request is the one marked latest",
        case_latest_over_older_request,
        {"telegram": LEAD, "packet": LEAD, "brief": NA + "a brief answers no request"},
        "ruling 2026-11-23",
    ),
    Case(
        4,
        "newest owner message beats an older dated note",
        case_latest_over_dated_note,
        {"telegram": LEAD, "packet": LEAD, "brief": NA + "a brief answers no request"},
        "November evaluation miss",
    ),
    Case(
        5,
        "recorded decision: date + followed/overrode, never a priority",
        case_decision,
        {"telegram": LEAD, "packet": LEAD, "brief": "physical_coach"},
        "November miss",
    ),
    Case(
        6, "open correction present", case_correction, {"telegram": "nutrition_coach", "packet": LEAD, "brief": "nutrition_coach"}, "#6149"
    ),
    Case(
        7,
        "approved coach_context record in, private + interpretation out",
        case_personal_record,
        {"telegram": "physical_coach", "packet": LEAD, "brief": "physical_coach"},
        "#6300",
    ),
    Case(
        8,
        "reflective turn: cycle-day count confined to its labelled line",
        case_cycle_day_confined,
        {
            "telegram": LEAD,
            "packet": NA + "the packet carries no cycle-day line",
            "brief": NA + "the cycle-day line is defined only in the Telegram domain pack",
        },
        "November miss",
    ),
    Case(
        9,
        "his open dispute of a development-profile line, attributed and dated",
        case_profile_dispute,
        {"telegram": LEAD, "packet": LEAD, "brief": NA + "the brief does not read the development_profile surface (#6294)"},
        "#6294 owner ruling 2026-11-26",
    ),
]

COLUMNS = ("telegram/off", "telegram/on", "packet/off", "packet/on", "brief")


def run_case(case: Case, column: str, store_rows: Optional[list] = None) -> dict:
    channel, _, mode = column.partition("/")
    seat = case.seats[channel]
    if seat.startswith(NA):
        return {"verdict": "n/a", "why": seat[len(NA) :]}
    table = StoreTable(store_rows if store_rows is not None else synthetic_store())
    if channel == "telegram":
        r = render_telegram(table, seat, pilot=(mode == "on"))
    elif channel == "packet":
        r = render_packet(table, pilot=(mode == "on"))
    else:
        r = render_brief(table, seat)
    findings = case.check(r.text)
    return {
        "verdict": "fail" if findings else "pass",
        "why": findings,
        "writes": list(table.writes),
        "unsupported": list(table.unsupported),
    }


def matrix(store_rows: Optional[list] = None) -> dict:
    return {(c.n, col): run_case(c, col, store_rows) for c in CASES for col in COLUMNS}


def matrix_markdown(m: dict) -> str:
    head = "| # | case | " + " | ".join(COLUMNS) + " |\n|---|---|" + "---|" * len(COLUMNS)
    rows = [f"| {c.n} | {c.name} | " + " | ".join(m[(c.n, col)]["verdict"].upper() for col in COLUMNS) + " |" for c in CASES]
    return "\n".join([head, *rows])


__all__ = [
    "CASES",
    "COLUMNS",
    "StoreTable",
    "hermetic",
    "matrix",
    "matrix_markdown",
    "render_brief",
    "render_packet",
    "render_telegram",
    "run_case",
    "synthetic_store",
]
