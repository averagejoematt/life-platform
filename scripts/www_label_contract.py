#!/usr/bin/env python3
"""scripts/www_label_contract.py — #5953: every label on the v9 tiles names the number printed beside it.

The 2026-11-14 accuracy review found three labels that described a different number from the one they sat beside: the
front page's Sleep tile printed the latest night beside "This week's mean", the Vitals page counted a missing reading as
zero, and the Sleep headline dated a night by the wrong morning and called a still-recording night final. Each was fixed
on its own page; nothing proved the CLASS. This module is that proof, over the BUILT pages (`www/dist`) and the snapshot
they were built from (`www/content/snapshot`).

The rule: derive, from the snapshot alone, the number each label NAMES, and compare it with what the page PRINTS. The
derivations are written out here from the label's words, not imported from the page code — a template and its check
sharing one helper would agree with each other however wrong both were.

Surfaces (each label it reads, and what that label must equal):

  * The front page's portrait tiles (`index.html`, a tile per `data-spark-of` series):
      the figure            = the series' latest present reading;
      Sleep "Last night." / "The night before <day>"  = the newest reading's wake morning against the edition's day;
      Sleep "The last seven nights average X h" = the mean of the readings among the series' last seven days (and the
            wording says how many of the seven were measured when fewer than seven were);
      "the first of the N weeks drawn, Y" (Sleep, Recovery) = N weekly bars drawn, Y the first bar that has a mean.
  * The data room's tiles (`data/index.html`): the figure and its day (the last FULL day for a daily total whose newest
    day is still being logged), "K of N days", "<N> weekly means", and the still-recording words exactly when the
    snapshot's Day object marks that night provisional for the series' device.
  * Each series page (`data/<metric>/index.html`): "Latest", "Readings K of N days", the still-recording words on the
    latest figure and on every provisional chart point — and on no other point.
  * Each Day page (`data/day/<date>/index.html`): "Night of <day>" is the wake morning less one day, the
    still-recording note appears exactly when the mattress's night is provisional, and each "Recovery, decomposed" line
    prints the day's reading and the normal its label names (the 7-day or 30-day mean, its n, the sleep target).

A surface the build did not produce (a fixture without that series) is skipped, never failed: absence is not a label.

Run by `scripts/check_www_build.py`'s scan (CI's web gate on the fixture build, and the deploy's `--scan-only` on the live
build). `self_test()` plants a wrong number, a dropped provisional mark and a mis-dated night into a synthetic build and
reports any it fails to catch. Proven in tests/test_www_label_contract_5953.py.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import tempfile
from datetime import date, timedelta

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]

#: The series that measure a night (www/src/lib/provisional.js NIGHT_METRICS): only these carry a night's flag.
NIGHT_METRICS = {"sleep_duration_hours", "deep_pct", "rem_pct"}
#: A series whose day is a running total — its newest day can still be filling up (www/src/pages/data/index.astro).
DAILY_TOTALS = {"total_calories_kcal", "total_protein_g"}
STILL_RECORDING = "still recording"

_TAG = re.compile(r"<[^>]+>")
_NUM = r"(-?[\d,]+(?:\.\d+)?)"


# ── the snapshot ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _load(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_snapshot(snapshot_dir: str) -> dict:
    series = {}
    sdir = os.path.join(snapshot_dir, "series")
    if os.path.isdir(sdir):
        for name in sorted(os.listdir(sdir)):
            if name.endswith(".json"):
                payload = _load(os.path.join(sdir, name))
                if isinstance(payload, dict) and isinstance(payload.get("days"), list):
                    series[name[:-5]] = payload
    days = [d for d in (_load(os.path.join(snapshot_dir, "days.json")) or []) if isinstance(d, dict) and d.get("visibility") == "public"]
    editions = [
        e for e in (_load(os.path.join(snapshot_dir, "editions.json")) or []) if isinstance(e, dict) and e.get("visibility") == "public"
    ]
    edition = max(editions, key=lambda e: str(e.get("as_of") or ""), default=None)
    metrics = {m["id"]: m for m in (_load(os.path.join(snapshot_dir, "metrics.json")) or []) if isinstance(m, dict) and m.get("id")}
    return {"series": series, "days": {d["date"]: d for d in days if d.get("date")}, "edition": edition, "metrics": metrics}


# ── what each label names, derived ──────────────────────────────────────────────────────────────────────────────────


def _present(days: list[dict]) -> list[dict]:
    return [d for d in days if isinstance(d.get("value"), (int, float)) and not isinstance(d.get("value"), bool) and not d.get("gap")]


def _mean(vals: list[float]) -> float | None:
    if not vals:
        return None
    total = 0.0
    for v in vals:  # left to right, as the page's reduce adds them (Python 3.12's sum() compensates; the page does not)
        total += v
    return total / len(vals)


def weekly_chunks(days: list[dict], weeks: int = 8) -> list[float | None]:
    """The weekly bars: the last `weeks`·7 days in sevens from the first of them, each the mean of its readings."""
    tail = days[max(0, len(days) - weeks * 7) :]
    return [_mean([d["value"] for d in _present(tail[i : i + 7])]) for i in range(0, len(tail), 7)]


def short_day(iso: str) -> str:
    y, m, d = (int(x) for x in iso[:10].split("-"))
    return f"{d} {MONTHS[m - 1][:3]}"


def weekday_day(iso: str, year: bool = True) -> str:
    dt = date.fromisoformat(iso[:10])
    core = f"{DAYS[dt.weekday()]} {dt.day} {MONTHS[dt.month - 1]}"
    return f"{core} {dt.year}" if year else core


def provisional(snap: dict, metric: str, iso: str | None) -> bool:
    """The snapshot's Day object for `iso` marks this series' device's night still recording."""
    if metric not in NIGHT_METRICS or not iso:
        return False
    s = snap["series"].get(metric) or {}
    src = s.get("source_id") or (snap["metrics"].get(metric) or {}).get("source_id")
    dev = (((snap["days"].get(iso) or {}).get("night") or {}).get("by_device") or {}).get(src) if src else None
    return isinstance(dev, dict) and dev.get("provisional") is True


# ── what each page prints ───────────────────────────────────────────────────────────────────────────────────────────


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", fragment))).strip()


def _number(s: str) -> float:
    return float(s.replace(",", ""))


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def agrees(printed: str, derived: float | None) -> bool:
    """The printed figure is the derived one at the precision printed (half a unit in the last place)."""
    if derived is None:
        return False
    return abs(_number(printed) - derived) <= 0.5 * 10 ** -_decimals(printed) + 1e-9


def tiles(page: str) -> dict[str, str]:
    """{series key: the tile's html} for every tile carrying a weekly spark (`data-spark-of`)."""
    out: dict[str, str] = {}
    starts = [m.start() for m in re.finditer(r'<(?:a|div) class="tile"', page)]
    for k, a in enumerate(starts):
        b = starts[k + 1] if k + 1 < len(starts) else len(page)
        chunk = page[a:b]
        end = chunk.find("</a>") if chunk.startswith("<a") else -1
        chunk = chunk[: end + 4] if end >= 0 else chunk
        m = re.search(r'data-spark-of="([^"]+)"', chunk)
        if m:
            out[m.group(1)] = chunk
    return out


def _value(tile: str) -> str | None:
    m = re.search(r'<span class="v num[^"]*"[^>]*>([\s\S]*?)</span>', tile)
    if not m:
        return None
    n = re.search(_NUM, text(m.group(1)))
    return n.group(1) if n else None


def _span(tile: str, cls: str) -> str:
    m = re.search(rf'<span class="{cls}"[^>]*>([\s\S]*?)</span>', tile)
    return text(m.group(1)) if m else ""


# ── the checks ──────────────────────────────────────────────────────────────────────────────────────────────────────


def front_page(page: str, snap: dict, rel: str = "index.html") -> list[str]:
    out = []
    edition_day = (snap["edition"] or {}).get("as_of")
    for key, tile in sorted(tiles(page).items()):
        s = snap["series"].get(key)
        if not s:
            continue
        present = _present(s["days"])
        if not present:
            continue
        last = present[-1]
        printed = _value(tile)
        if printed is None or not agrees(printed, last["value"]):
            out.append(f"{rel}: the {key} tile prints {printed!r}; its latest reading is {last['value']} ({last['date']})")
        note = _span(tile, "note")
        bars = weekly_chunks(s["days"])
        first_bar = next((v for v in bars if v is not None), None)
        drawn = f"{WORDS[len(bars)] if len(bars) < len(WORDS) else len(bars)} {'week' if len(bars) == 1 else 'weeks'}"
        m = re.search(r"[Tt]he first of the (\w+ weeks?) drawn,? (?:averaged )?" + _NUM, note)
        if m:
            if m.group(1) != drawn:
                out.append(f"{rel}: the {key} note says {m.group(1)!r} drawn; the spark draws {drawn}")
            if not agrees(m.group(2), first_bar):
                out.append(f"{rel}: the {key} note's first week reads {m.group(2)}; the first weekly mean is {first_bar}")
        elif "weeks drawn" in note or "week drawn" in note:
            out.append(f"{rel}: the {key} note names a first week the contract cannot read: {note!r}")
        if key == "sleep_duration_hours":
            want = "Last night." if last["date"] == edition_day else f"The night before {short_day(last['date'])}"
            if not note.startswith(want):
                out.append(f"{rel}: the sleep note opens {note[:48]!r}; the newest reading names {want!r}")
            seven = _present(s["days"][-7:])
            m = re.search(r"The (last seven nights|\d+ measured of the last seven nights) average " + _NUM, note)
            if seven:
                words = "last seven nights" if len(seven) == 7 else f"{len(seven)} measured of the last seven nights"
                if not m:
                    out.append(f"{rel}: the sleep note does not state the last seven nights' mean: {note!r}")
                else:
                    if m.group(1) != words:
                        out.append(f"{rel}: the sleep note says {m.group(1)!r}; {len(seven)} of the last seven nights were measured")
                    mean = _mean([d["value"] for d in seven])
                    if not agrees(m.group(2), mean):
                        out.append(f"{rel}: the sleep note's last-seven-nights mean reads {m.group(2)}; the mean is {mean}")
    return out


def data_room(page: str, snap: dict, rel: str = os.path.join("data", "index.html")) -> list[str]:
    out = []
    for key, tile in sorted(tiles(page).items()):
        s = snap["series"].get(key)
        if not s:
            continue
        present = _present(s["days"])
        if not present:
            continue
        last = present[-1]
        partial = key in DAILY_TOTALS and bool(s.get("behavioral")) and last["date"] == (s.get("window") or {}).get("to")
        shown = next((d for d in reversed(present) if d["date"] < last["date"]), None) if partial else last
        shown = shown or last
        printed = _value(tile)
        if printed is None or not agrees(printed, shown["value"]):
            out.append(f"{rel}: the {key} tile prints {printed!r}; the reading it names is {shown['value']} ({shown['date']})")
        caption = _span(tile, "muted")
        if not caption.startswith(short_day(shown["date"])):
            out.append(f"{rel}: the {key} caption opens {caption[:24]!r}; the figure is {short_day(shown['date'])}'s")
        m = re.search(r"(\d+) of (\d+) days", caption)
        if not m or (int(m.group(1)), int(m.group(2))) != (len(present), len(s["days"])):
            out.append(
                f"{rel}: the {key} caption counts {m.group(0) if m else None!r}; the series has {len(present)} of {len(s['days'])} days"
            )
        k = sum(1 for v in weekly_chunks(s["days"]) if v is not None)
        want = f"{WORDS[k] if k < len(WORDS) else k} weekly {'mean' if k == 1 else 'means'}"
        if want not in caption:
            out.append(f"{rel}: the {key} caption does not say {want!r} (the spark draws {k}): {caption!r}")
        flagged = provisional(snap, key, shown["date"])
        said = STILL_RECORDING in caption
        if flagged != said:
            out.append(
                f"{rel}: the {key} tile's {shown['date']} night is {'provisional' if flagged else 'final'} in the snapshot; "
                f"the caption {'does not say' if flagged else 'says'} {STILL_RECORDING!r}"
            )
    return out


def series_page(page: str, key: str, snap: dict, rel: str) -> list[str]:
    s = snap["series"].get(key)
    if not s:
        return []
    present = _present(s["days"])
    if not present:
        return []
    out = []
    last = present[-1]
    m = re.search(r">Latest</span>([\s\S]*?)<div>", page)
    block = m.group(1) if m else ""
    printed = _value(block)
    if printed is None or not agrees(printed, last["value"]):
        out.append(f"{rel}: Latest prints {printed!r}; the latest reading is {last['value']} ({last['date']})")
    words = text(block)
    if weekday_day(last["date"]) not in words:
        out.append(f"{rel}: Latest is not dated {weekday_day(last['date'])!r}: {words!r}")
    if provisional(snap, key, last["date"]) != (STILL_RECORDING in words):
        out.append(f"{rel}: Latest's still-recording words disagree with the snapshot's {last['date']} night")
    m = re.search(r">Readings</span>([\s\S]*?)</div>", page)
    r = re.search(r"(\d+) of (\d+) days", text(m.group(1)) if m else "")
    if not r or (int(r.group(1)), int(r.group(2))) != (len(present), len(s["days"])):
        out.append(f"{rel}: Readings counts {r.group(0) if r else None!r}; the series has {len(present)} of {len(s['days'])} days")
    m = re.search(r'data-chart-a[^>]*>[\s\S]*?data-points="([^"]*)"', page)
    if m:
        try:
            points = json.loads(html.unescape(m.group(1)))
        except ValueError:
            points = []
        for p in points:
            if provisional(snap, key, p.get("date")) != (STILL_RECORDING in str(p.get("label"))):
                out.append(f"{rel}: the chart point {p.get('date')} is labelled {p.get('label')!r} against the snapshot's night")
    return out


#: The Day page's "Recovery, decomposed" lines: a pattern over the page's words, and per group (field, which number) —
#: None is the day's reading, mean7/mean30/n30 its normal, "target" the platform's sleep target.
DECOMPOSED = (
    (r"Recovery \d+ (\d+) of 100 · 7-day mean (\d+)", (("recovery_pct", None), ("recovery_pct", "mean7"))),
    (r"HRV [\d.]+ ([\d.]+) ms · 30-day mean ([\d.]+) \(n=(\d+)\)", (("hrv_ms", None), ("hrv_ms", "mean30"), ("hrv_ms", "n30"))),
    (r"Resting HR \d+ (\d+) bpm · 7-day mean (\d+)", (("rhr_bpm", None), ("rhr_bpm", "mean7"))),
    (r"Sleep [\d.]+ ([\d.]+) h of a ([\d.]+) h target", (("sleep_hours", None), ("sleep_hours", "target"))),
)


def day_page(page: str, iso: str, snap: dict, rel: str) -> list[str]:
    d = snap["days"].get(iso)
    if not d:
        return []
    out = []
    bed = ((d.get("night") or {}).get("by_device") or {}).get("eightsleep")
    m = re.search(r"Night of ([A-Z][a-z]+ \d{1,2} [A-Z][a-z]+)", text(page))
    if m:
        want = weekday_day((date.fromisoformat(iso) - timedelta(days=1)).isoformat(), year=False)
        if m.group(1) != want:
            out.append(f"{rel}: 'Night of {m.group(1)}' on the morning of {iso}; the night is {want!r} (the wake morning less one)")
    # "Recovery, decomposed": each figure and the normal its label names (the readings and normals the Day object carries)
    words = text(page)
    readings, normals = d.get("readings") or {}, d.get("normals") or {}
    for pattern, pairs in DECOMPOSED:
        m = re.search(pattern, words)
        if not m:
            continue
        for group, (field, key) in enumerate(pairs, start=1):
            want = (
                readings.get(field) if key is None else (normals.get(field) or {}).get(key) if key != "target" else d.get("sleep_target_h")
            )
            if not agrees(m.group(group), want):
                out.append(f"{rel}: {m.group(0)!r} — {field}{'' if key is None else ' ' + key} is {want}")
    flagged = isinstance(bed, dict) and bed.get("provisional") is True
    if flagged != ("data-night-provisional" in page):
        out.append(
            f"{rel}: the night is {'provisional' if flagged else 'final'} in the snapshot; the still-recording note is {'missing' if flagged else 'shown'}"
        )
    return out


def issues(dist: str, snapshot_dir: str) -> list[str]:
    """Every label on the built tiles, series pages and Day pages that names a number other than the one it prints."""
    snap = load_snapshot(snapshot_dir)
    out: list[str] = []

    def read(*parts: str) -> str | None:
        path = os.path.join(dist, *parts)
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    front = read("index.html")
    if front is not None:
        out.extend(front_page(front, snap))
    room = read("data", "index.html")
    if room is not None:
        out.extend(data_room(room, snap))
    for key in sorted(snap["series"]):
        page = read("data", key, "index.html")
        if page is not None:
            out.extend(series_page(page, key, snap, os.path.join("data", key, "index.html")))
    for iso in sorted(snap["days"]):
        page = read("data", "day", iso, "index.html")
        if page is not None:
            out.extend(day_page(page, iso, snap, os.path.join("data", "day", iso, "index.html")))
    return out


# ── the planted controls ────────────────────────────────────────────────────────────────────────────────────────────


def _synthetic(root: str, mutate: str | None = None) -> tuple[str, str]:
    """A two-week snapshot and the pages a correct build prints from it; `mutate` plants one wrong label."""
    snap_dir, dist = os.path.join(root, "snapshot"), os.path.join(root, "dist")
    for p in (os.path.join(snap_dir, "series"), os.path.join(dist, "data", "deep_pct"), os.path.join(dist, "data", "day", "2026-10-14")):
        os.makedirs(p, exist_ok=True)
    start = date(2026, 10, 1)
    hours = [7.0, 7.5, 8.0, None, 6.5, 7.2, 7.8, 8.1, 7.6, 6.9, 7.3, 7.4, 7.9, 8.1]
    deep = [15.0, 16.0, 17.0, 18.0, 16.5, 15.5, 17.5, 16.0, 15.0, 18.5, 17.0, 16.0, 15.5, 14.0]

    def series(key, src, vals):
        days = [
            {"date": (start + timedelta(i)).isoformat(), "value": v, "present": v is not None, "gap": False} for i, v in enumerate(vals)
        ]
        return {
            "metric": key,
            "source_id": src,
            "behavioral": False,
            "window": {"from": days[0]["date"], "to": days[-1]["date"]},
            "days": days,
        }

    s_sleep, s_deep = series("sleep_duration_hours", "whoop", hours), series("deep_pct", "eightsleep", deep)
    for k, s in (("sleep_duration_hours", s_sleep), ("deep_pct", s_deep)):
        with open(os.path.join(snap_dir, "series", f"{k}.json"), "w", encoding="utf-8") as fh:
            json.dump(s, fh)
    day = {
        "date": "2026-10-14",
        "visibility": "public",
        "night": {
            "by_device": {
                "eightsleep": {"night_of": "2026-10-13", "provisional": True},
                "whoop": {"night_of": "2026-10-13", "provisional": None},
            }
        },
        "readings": {"recovery_pct": 69, "hrv_ms": 53.9, "rhr_bpm": 60, "sleep_hours": 7.0},
        "normals": {"recovery_pct": {"mean7": 64.4}, "hrv_ms": {"mean30": 50.52, "n30": 14}, "rhr_bpm": {"mean7": 58.1}},
        "sleep_target_h": 7.5,
    }
    with open(os.path.join(snap_dir, "days.json"), "w", encoding="utf-8") as fh:
        json.dump([day], fh)
    with open(os.path.join(snap_dir, "editions.json"), "w", encoding="utf-8") as fh:
        json.dump([{"visibility": "public", "as_of": "2026-10-14"}], fh)
    with open(os.path.join(snap_dir, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump([{"id": "sleep_duration_hours", "source_id": "whoop"}, {"id": "deep_pct", "source_id": None}], fh)

    last_sleep = "8.0" if mutate == "figure" else "8.1"
    opening = "This week's mean." if mutate == "night" else "Last night."
    vals7 = [v for v in hours[-7:] if v is not None]
    seven = f"{_mean(vals7) + (0.5 if mutate == 'mean' else 0):.1f}"
    first = f"{weekly_chunks(s_sleep['days'])[0]:.1f}"
    front = (
        '<div class="tiles"><a class="tile" href="/data/sleep_duration_hours/"><span class="label">Sleep</span>'
        f'<span class="v num ">{last_sleep}<small> h</small></span><span class="spark" data-spark-of="sleep_duration_hours"></span>'
        f'<span class="note">{opening} The last seven nights average {seven} h; the first of the {"eight" if mutate == "weeks" else "two"} weeks drawn, {first} h.</span></a></div>'
    )
    present_deep = _present(s_deep["days"])
    provisional_words = "" if mutate == "provisional" else " · still recording when read, provisional"
    room = (
        '<div class="tiles"><a class="tile" href="/data/deep_pct/"><span class="label">Deep</span>'
        f'<span class="v num" style="font-size:30px">{deep[-1]:.1f} <small>%</small></span><span class="spark" data-spark-of="deep_pct"></span>'
        f'<span class="muted" style="font-size:13px">14 Oct{provisional_words} · {len(present_deep)} of 14 days · two weekly means</span></a></div>'
    )
    pts = [
        {
            "date": d["date"],
            "label": f"{weekday_day(d['date'])} · {d['value']} %" + (provisional_words if d["date"] == "2026-10-14" else ""),
        }
        for d in present_deep
    ]
    series_html = (
        f'<div class="facts"><div><span class="label">Latest</span><span class="v num">{deep[-1]:.1f} <small>%</small></span>'
        f'<span class="muted">Wednesday 14 October 2026{provisional_words}</span></div>'
        f'<div><span class="label">Readings</span><span class="v num">14 <small>of 14 days</small></span></div></div>'
        f'<div class="chart" data-chart-a><svg data-points="{html.escape(json.dumps(pts))}"></svg></div>'
    )
    night = "Wednesday 14 October" if mutate == "night_of" else "Tuesday 13 October"
    day_html = (
        f'<p class="small">Night of {night}: <b>7.2 h by the bed</b></p>'
        + ("" if mutate == "provisional" else "<p data-night-provisional>Still recording.</p>")
        + f'<span class="k">Recovery</span> <span class="v">69</span> <span class="note">69 of 100 · 7-day mean {"71" if mutate == "decomposed" else "64"}</span>'
        + '<span class="k">HRV</span> <span class="v">53.9</span> <span class="note">53.9 ms · 30-day mean 50.5 (n=14)</span>'
        + '<span class="k">Resting HR</span> <span class="v">60</span> <span class="note">60 bpm · 7-day mean 58 · lower is better</span>'
        + '<span class="k">Sleep</span> <span class="v">7.0</span> <span class="note">7.0 h of a 7.5 h target</span>'
    )
    for path, body in (
        (os.path.join(dist, "index.html"), front),
        (os.path.join(dist, "data", "index.html"), room),
        (os.path.join(dist, "data", "deep_pct", "index.html"), series_html),
        (os.path.join(dist, "data", "day", "2026-10-14", "index.html"), day_html),
    ):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    return dist, snap_dir


#: Each planted wrong label, and a fragment of the issue that must name it.
PLANTED = {
    "figure": "sleep_duration_hours tile prints",
    "night": "the sleep note opens",
    "mean": "last-seven-nights mean",
    "weeks": "drawn; the spark draws",
    "provisional": "provisional in the snapshot",
    "night_of": "the wake morning less one",
    "decomposed": "recovery_pct mean7 is",
}


def self_test() -> list[str]:
    """[] when the clean synthetic build passes and every planted wrong label is caught; else what went unseen."""
    blind: list[str] = []
    with tempfile.TemporaryDirectory() as root:
        found = issues(*_synthetic(os.path.join(root, "clean")))
        if found:
            blind.append(f"clean build flagged: {found}")
        for name, fragment in PLANTED.items():
            found = issues(*_synthetic(os.path.join(root, name), mutate=name))
            if not any(fragment in f for f in found):
                blind.append(f"planted {name!r} not caught (got {found})")
    return blind


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    blind = self_test()
    if blind:
        print("BLIND:", *blind, sep="\n  ")
        sys.exit(2)
    found = issues(os.path.join(here, "www", "dist"), os.path.join(here, "www", "content", "snapshot"))
    for f in found:
        print(f"  ✗ {f}")
    print(f"label contract: {len(found)} mismatch(es)")
    sys.exit(1 if found else 0)
