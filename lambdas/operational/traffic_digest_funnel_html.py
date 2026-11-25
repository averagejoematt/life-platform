"""operational/traffic_digest_funnel_html.py — the subscriber-funnel section of the weekly traffic digest.

Moved out of traffic_digest_lambda.py on 2026-11-24 to keep that module under the 1000-line ceiling (#1665); the lambda
re-exports `build_subscriber_funnel_html`, so callers and tests are unchanged. Pure: a dict in, an HTML string out.
"""


def build_subscriber_funnel_html(funnel, default_window_days=7):
    """Render the subscriber-funnel section. Must never raise — every key may
    be absent or error-shaped, and a crash here would take the whole Monday
    ops email down (same contract as build_green_report_html)."""
    parts = ['<h2 style="font-size:16px;margin-top:24px">Subscriber funnel</h2>']
    funnel = funnel or {}
    if funnel.get("error") or "by_status" not in funnel:
        reason = funnel.get("error") or "no subscriber reading in this run"
        parts.append(f'<p style="color:#6e665a;font-size:13px">not collected — {reason}</p>')
        return "".join(parts)
    status_pairs = funnel.get("by_status") or []
    if status_pairs:
        rows = "".join(
            f'<tr><td style="padding:4px 0;font-family:monospace">{k}</td>'
            f'<td style="padding:4px 0;text-align:right;font-variant-numeric:tabular-nums">{v}</td></tr>'
            for k, v in status_pairs
        )
    else:
        rows = '<tr><td colspan="2" style="color:#888;padding:6px 0">No subscribers yet.</td></tr>'
    parts.append(f'<table style="width:100%;border-collapse:collapse">{rows}</table>')
    window = funnel.get("window_days") or default_window_days
    # #3619 ROW1: the attempt stage, from the CF-log scan merged into `funnel` in
    # the handler. Absent (older callers, or a fail-soft aggregation error) simply
    # omits the line — never a crash, never a fabricated zero.
    if "subscribe_page_views_7d" in funnel:
        views = funnel.get("subscribe_page_views_7d") or 0
        attempts = funnel.get("subscribe_attempts_7d") or 0
        successes = funnel.get("subscribe_successes_7d") or 0
        confirmed_7d = funnel.get("new_confirmed_7d") or 0
        parts.append(
            f'<p style="margin:6px 0;font-size:13px">/subscribe/ views <strong>{views}</strong> &rarr; '
            f"POST /api/subscribe 2xx <strong>{successes}</strong> of <strong>{attempts}</strong> attempts &rarr; "
            f"confirmed <strong>{confirmed_7d}</strong> (last {window} days)</p>"
            '<p style="margin:2px 0 6px;color:#888;font-size:12px">Views and attempts are browser-like requests after a '
            "user-agent filter, with the platform's own tools left out: an estimate, not verified people.</p>"
        )
        if "subscribe_synthetic_attempts_7d" in funnel:
            syn_ok = funnel.get("subscribe_synthetic_successes_7d") or 0
            syn_all = funnel.get("subscribe_synthetic_attempts_7d") or 0
            internal_views = funnel.get("subscribe_internal_page_views_7d") or 0
            parts.append(
                '<p style="margin:6px 0;color:#6e665a;font-size:13px">Synthetic checks, not readers: canary POST 2xx '
                f"<strong>{syn_ok}</strong> of <strong>{syn_all}</strong> &middot; /subscribe/ views by the platform's own tools "
                f"<strong>{internal_views}</strong></p>"
            )
    parts.append(
        f'<p style="margin:6px 0;font-size:13px"><strong>{funnel.get("new_pending_7d") or 0}</strong> new pending · '
        f'<strong>{funnel.get("new_confirmed_7d") or 0}</strong> new confirmed in the last {window} days</p>'
    )
    oldest = funnel.get("oldest_pending_days")
    if oldest is not None and oldest > window:
        parts.append(
            f'<p style="margin:6px 0;color:#9a6700;font-size:13px">⚠ oldest pending confirmation is {oldest} days old — '
            "its confirmation link is long expired; the funnel is leaking</p>"
        )
    canary_rows = funnel.get("canary_rows") or 0
    if canary_rows:
        parts.append(
            f'<p style="margin:6px 0;color:#b42318;font-size:13px">✗ {canary_rows} synthetic canary row(s) in the subscriber '
            "partition — canary cleanup failed; these are excluded from the counts above but must be deleted (#1954)</p>"
        )
    parts.append(
        '<p style="color:#888;font-size:12px;margin:8px 0 0">Read-only join of the subscriber partition — counts exclude '
        "synthetic canary rows.</p>"
    )
    return "".join(parts)
