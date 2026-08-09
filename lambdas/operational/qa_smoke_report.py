"""qa_smoke_report.py — the nightly QA email's HTML renderer.

Extracted from qa_smoke_lambda.py 2026-08-09 (#2335): the handler sat 2 lines
under the 1200-line module-size ceiling, so the next check added would land as
an unplanned refactor under a red gate — this move is that refactor, done once,
leaving real headroom. Pure rendering: no AWS calls, no check logic.
qa_smoke_lambda imports the symbol into its own namespace, so the existing
monkeypatch seam (tests/test_qa_smoke_fault_isolation_2307.py patches
``qa.build_report_html``) keeps working — the handler resolves its own global.
"""

from operational.qa_check import CONTENT_TRUTH, DEPLOY_HEALTH


def build_report_html(all_checks, run_time_str):
    fails = [c for c in all_checks if c.passed is False]
    warns = [c for c in all_checks if c.passed is None]
    paused = [c for c in all_checks if c.paused]
    passes = [c for c in all_checks if c.passed is True and not c.paused]

    # #1921: the email must say which SIDE failed. A content-truth failure no
    # longer reverts the fleet, so this line is the reader's only cue that a red
    # run did not (and should not have) triggered a rollback.
    n_deploy = sum(1 for c in fails if c.partition == DEPLOY_HEALTH)
    n_content = sum(1 for c in fails if c.partition == CONTENT_TRUTH)
    split = f" &middot; {n_deploy} deploy-health &middot; {n_content} content-truth" if fails else ""

    overall = "ALL CLEAR" if not fails else f"{len(fails)} FAILURE(S)"
    banner_emoji = "✅" if not fails else "🔴"
    hdr_bg = "#064e3b" if not fails else "#450a0a"
    hdr_fg = "#d1fae5" if not fails else "#fecaca"

    cats = {}
    for c in all_checks:
        cats.setdefault(c.category, []).append(c)

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f0f23;font-family:'SF Pro Display','Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;background:#1a1a2e;">
  <div style="background:{hdr_bg};padding:20px 24px;border-bottom:3px solid #2d2d5e;">
    <p style="color:#94a3b8;font-size:10px;margin:0 0 4px;font-weight:700;">LIFE PLATFORM · QA SMOKE TEST</p>
    <h1 style="color:{hdr_fg};font-size:24px;font-weight:700;margin:0 0 4px;">{banner_emoji} {overall}</h1>
    <p style="color:#94a3b8;font-size:11px;margin:0;">{run_time_str} &middot; {len(passes)} passed &middot; {len(paused)} paused &middot; {len(warns)} warnings &middot; {len(fails)} failed{split}</p>
  </div>"""

    for cat, checks in cats.items():
        cat_fails = sum(1 for c in checks if c.passed is False)
        cat_warns = sum(1 for c in checks if c.passed is None)
        cat_paused = sum(1 for c in checks if c.paused)
        if cat_fails:
            icon = "🔴"
        elif cat_warns:
            icon = "🟡"
        elif cat_paused and cat_paused == len(checks):
            icon = "⏸️"
        else:
            icon = "🟢"
        html += f"""
  <div style="padding:14px 24px;border-bottom:1px solid #2d2d5e;">
    <p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;">{icon} {cat.upper()}</p>"""
        for c in checks:
            if c.paused:
                ci, cc = ("⏸️", "#94a3b8")
            elif c.passed is True:
                ci, cc = ("✅", "#22c55e")
            elif c.passed is False:
                ci, cc = ("❌", "#f87171")
            else:
                ci, cc = ("⚠️", "#fbbf24")
            html += f"""    <p style="margin:2px 0;font-size:11px;">
      <span style="color:{cc}">{ci} <strong>{c.name}</strong></span>
      <span style="color:#9ca3af;"> — {c.message}</span></p>"""
        html += "\n  </div>"

    html += """
  <div style="background:#111827;padding:10px 24px;text-align:center;">
    <p style="color:#374151;font-size:9px;margin:0;">Life Platform QA · auto-generated</p>
  </div>
</div></body></html>"""

    return html
