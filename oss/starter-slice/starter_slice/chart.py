"""One chart: daily maximum temperature over the ingested window.

Inline SVG, no chart library, no JavaScript, no network. The output is a single
self-contained HTML file you can open with a double-click or email to someone.

Deliberate choices, because a starter template teaches its habits:
  - one series, so no legend -- the title names it;
  - the y-axis is NOT forced to zero (temperature has no meaningful zero), and the
    axis says so rather than letting the reader assume it;
  - every point carries a native <title>, so hovering gives the exact value with
    no script;
  - a real <table> follows the chart, so the data is readable without color,
    without SVG, and by a screen reader.
"""

import html

W, H = 720, 320
PAD_L, PAD_R, PAD_T, PAD_B = 52, 18, 22, 38
GRID_LINES = 4


def _scale(rows):
    values = [r["temp_max_c"] for r in rows]
    lo, hi = min(values), max(values)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    lo, hi = lo - span * 0.12, hi + span * 0.12
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def x(i):
        return PAD_L + (plot_w if len(rows) == 1 else plot_w * i / (len(rows) - 1))

    def y(v):
        return PAD_T + plot_h * (hi - v) / (hi - lo)

    return lo, hi, x, y


def render_svg(rows: list[dict], title: str) -> str:
    if not rows:
        return '<p class="empty">No readings ingested yet — run the ingest step first.</p>'
    lo, hi, x, y = _scale(rows)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}" class="chart">']

    for i in range(GRID_LINES + 1):
        value = lo + (hi - lo) * i / GRID_LINES
        gy = round(y(value), 1)
        parts.append(f'<line class="grid" x1="{PAD_L}" y1="{gy}" x2="{W - PAD_R}" y2="{gy}" />')
        parts.append(f'<text class="tick" x="{PAD_L - 10}" y="{gy + 4}" text-anchor="end">{value:.0f}</text>')

    points = " ".join(f"{round(x(i), 1)},{round(y(r['temp_max_c']), 1)}" for i, r in enumerate(rows))
    parts.append(f'<polyline class="line" points="{points}" />')

    for i, row in enumerate(rows):
        cx, cy = round(x(i), 1), round(y(row["temp_max_c"]), 1)
        label = f"{row['date']}: {row['temp_max_c']:.1f} °C"
        parts.append(f'<circle class="dot" cx="{cx}" cy="{cy}" r="4"><title>{html.escape(label)}</title></circle>')

    last = rows[-1]
    parts.append(
        f'<text class="value" x="{round(x(len(rows) - 1), 1) - 6}" y="{round(y(last["temp_max_c"]), 1) - 12}" '
        f'text-anchor="end">{last["temp_max_c"]:.1f} °C</text>'
    )
    parts.append(f'<text class="tick" x="{PAD_L}" y="{H - 12}">{html.escape(rows[0]["date"])}</text>')
    parts.append(f'<text class="tick" x="{W - PAD_R}" y="{H - 12}" text-anchor="end">{html.escape(rows[-1]["date"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _table(rows: list[dict]) -> str:
    body = "".join(
        "<tr><td>{}</td><td>{:.1f}</td><td>{}</td></tr>".format(
            html.escape(r["date"]),
            r["temp_max_c"],
            "—" if r.get("temp_min_c") is None else f"{r['temp_min_c']:.1f}",
        )
        for r in rows
    )
    return f"<table><caption>The same readings, as data.</caption><thead><tr><th>date</th><th>high °C</th><th>low °C</th></tr></thead><tbody>{body}</tbody></table>"  # noqa: E501


_CSS = """
:root { --surface:#ffffff; --ink:#16181d; --muted:#5d6470; --grid:#e4e7ec; --accent:#1d4ed8; }
@media (prefers-color-scheme: dark) {
  :root { --surface:#12151b; --ink:#e9ebef; --muted:#9aa2af; --grid:#262b34; --accent:#84aaf8; }
}
body { background:var(--surface); color:var(--ink); font:16px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       margin:0; padding:2.5rem 1.25rem; }
main { max-width:780px; margin:0 auto; }
h1 { font-size:1.35rem; margin:0 0 .25rem; }
p.sub { color:var(--muted); margin:0 0 1.75rem; font-size:.9rem; }
figure { margin:0 0 2rem; overflow-x:auto; }
.chart { width:100%; height:auto; display:block; }
.grid { stroke:var(--grid); stroke-width:1; }
.line { fill:none; stroke:var(--accent); stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
.dot { fill:var(--accent); stroke:var(--surface); stroke-width:2; }
.tick { fill:var(--muted); font-size:12px; }
.value { fill:var(--ink); font-size:13px; font-weight:600; }
figcaption { color:var(--muted); font-size:.8rem; margin-top:.5rem; }
table { border-collapse:collapse; width:100%; font-size:.88rem; }
caption { text-align:left; color:var(--muted); font-size:.8rem; padding-bottom:.5rem; }
th,td { text-align:left; padding:.35rem .6rem; border-bottom:1px solid var(--grid); }
th { color:var(--muted); font-weight:600; }
"""


def render_page(rows: list[dict], subtitle: str) -> str:
    title = "Daily high temperature"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title} — starter slice</title><style>{_CSS}</style></head><body><main>"
        f'<h1>{title}</h1><p class="sub">{html.escape(subtitle)}</p>'
        f"<figure>{render_svg(rows, title)}"
        "<figcaption>The y-axis is not zero-based: temperature has no meaningful zero, so the range is the data's own. "
        "Hover a point for its exact reading.</figcaption></figure>"
        f"{_table(rows) if rows else ''}"
        "</main></body></html>"
    )
