#!/usr/bin/env python3
"""
add_reading_path_ctas.py — Inject reading path CTAs into key pages.

Implements Task 20 from WEBSITE_STRATEGY.md Phase 1.

The reading path (David Perell's "reading path" concept):
  /story/        → See where I am today          → /live/
  /live/         → How the score is computed      → /character/
  /character/    → The habits that feed the score → /habits/
  /habits/       → What I'm actively testing      → /experiments/
  /experiments/  → What the data has proven       → /discoveries/
  /discoveries/  → How the AI works               → /intelligence/
  /intelligence/ → Ask the data yourself          → /ask/

Run from repo root:
    python3 deploy/add_reading_path_ctas.py

Then deploy:
    aws s3 sync site/ s3://matthew-life-platform/site/ --delete
    aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR  = REPO_ROOT / "site"

# Reading path: (page_dir, next_url, cta_label, cta_sub)
READING_PATH = [
    ("story",        "/live/",          "See where I am today →",
     "Live data, updated daily from 19 sources"),
    ("live",         "/character/",     "How the score is computed →",
     "The 7-pillar character system that turns data into growth"),
    ("character",    "/habits/",        "The habits that feed the score →",
     "52 weeks of habit data — the inputs behind every pillar"),
    ("habits",       "/experiments/",   "What I'm actively testing →",
     "N=1 experiments with real hypotheses and measured outcomes"),
    ("experiments",  "/discoveries/",   "What the data has proven →",
     "Confirmed findings — correlations, patterns, anomalies"),
    ("discoveries",  "/intelligence/",  "How the AI works →",
     "14+ intelligence features running every day on live data"),
    ("intelligence", "/ask/",           "Ask the data yourself →",
     "Ask anything — the platform's 19 data sources will answer"),
]

CTA_TEMPLATE = """\
<!-- Reading path CTA (Task 20, Phase 1) -->
<section class="reading-path" style="
  padding: var(--space-10) var(--page-padding);
  border-top: 1px solid var(--border);
  background: var(--surface);
  text-align: center;
">
  <span style="
    font-size: var(--text-2xs);
    letter-spacing: var(--ls-tag);
    text-transform: uppercase;
    color: var(--text-faint);
    display: block;
    margin-bottom: var(--space-3);
    font-family: var(--font-mono);
  ">Continue the story</span>
  <a href="{next_url}" style="
    font-family: var(--font-display);
    font-size: var(--text-h3);
    color: var(--accent);
    text-decoration: none;
    letter-spacing: var(--ls-display);
    transition: opacity 0.15s;
  " onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">{cta_label}</a>
  <p style="
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin: var(--space-2) 0 0;
    font-family: var(--font-mono);
  ">{cta_sub}</p>
</section>
"""

INJECTION_MARKER = "<!-- Mobile bottom nav -->"


def inject_cta(page_dir: str, next_url: str, cta_label: str, cta_sub: str) -> bool:
    page_path = SITE_DIR / page_dir / "index.html"
    if not page_path.exists():
        print(f"  ⚠ SKIP: {page_path} does not exist")
        return False

    content = page_path.read_text(encoding="utf-8")

    if "reading-path" in content or "Continue the story" in content:
        print(f"  ✓ SKIP: /{page_dir}/ already has reading-path CTA")
        return True

    if INJECTION_MARKER not in content:
        print(f"  ⚠ SKIP: /{page_dir}/ — injection marker not found")
        return False

    cta_html = CTA_TEMPLATE.format(
        next_url=next_url,
        cta_label=cta_label,
        cta_sub=cta_sub,
    )

    new_content = content.replace(
        INJECTION_MARKER,
        cta_html + "\n" + INJECTION_MARKER,
        1,
    )

    page_path.write_text(new_content, encoding="utf-8")
    print(f"  ✅ /{page_dir}/ → {next_url}  \"{cta_label}\"")
    return True


def main():
    print(f"\n[add_reading_path_ctas] Site: {SITE_DIR}\n")
    success = 0
    for page_dir, next_url, cta_label, cta_sub in READING_PATH:
        ok = inject_cta(page_dir, next_url, cta_label, cta_sub)
        if ok:
            success += 1

    print(f"\n[done] {success}/{len(READING_PATH)} pages updated")
    if success < len(READING_PATH):
        print("[warn] Some pages were skipped — check output above")


if __name__ == "__main__":
    main()
