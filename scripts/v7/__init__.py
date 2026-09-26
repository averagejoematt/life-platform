"""scripts/v7 — the per-page body templates the v7 builder (scripts/v7_build.py) pours (#4182).

One module per page. Each exposes the same three names so the builder's registry stays a
flat dict and a new page is one import + one entry:

    HEAD     extra <head> markup (the page's own stylesheet link), or ""
    SCRIPTS  extra end-of-body markup (the page's own ES module), or ""
    body(base) -> str   the <main> inner HTML; `base` is the viewer prefix ("/" or "/next/")

A template writes NO chrome (the masthead, bar and footer come from v4_chrome under
EDITION="v7") and NO data: every number is fetched and rendered by the page's module at
runtime, and the static body reads correctly with scripts off.
"""
