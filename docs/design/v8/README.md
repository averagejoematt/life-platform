# v8: the kit

**This is the approved direction.** The owner rejected six generated designs on
2026-10-03 as "cluttered, messy, unprofessional" and approved exactly one:
"definitely WAY better"; "clean, organized, professional". One calm column, one
typeface, one accent, one idea per section.

The kit is the **only** way to build a reader page under epic #4580. A kit page loads
`site/assets/css/clean.css` and nothing else for its look: not `tokens.css`, not
`fonts.css`, not a page-scoped `<style>` block. If a page needs something the kit does
not have, the page goes without it until the owner has approved the addition on a real
screen. Do not add a colour, a typeface, a size, a border, a shadow, a card style, an
icon or an uppercase label.

`docs/DESIGN_SYSTEM_V5.md` still governs every page that does not load `clean.css`.

## What is frozen

| | |
|---|---|
| Sheet | `site/assets/css/clean.css` (under 12 KB; `tests/test_css_tokens.py` holds the cap) |
| Specimen | `site/kit/index.html`, served at `/kit/`, unlisted and `noindex` |
| Typeface | Geist, weights 400 to 600, one self-hosted file: `site/assets/fonts/clean/geist-latin.woff2` |
| Column | 680 px, 24 px side padding (20 px at 480 px and under) |
| Colour | eight tokens, light and dark: `--ck-bg`, `--ck-fg`, `--ck-soft`, `--ck-faint`, `--ck-line`, `--ck-panel`, `--ck-accent`, `--ck-accent-wash` |
| Type scale | `--ck-fs-small`, `--ck-fs-body`, `--ck-fs-lead`, `--ck-fs-h2`, `--ck-fs-h1` |
| Spacing | `--ck-gap-section` (88 px, 72 px on a phone), `--ck-gap-block` (20 px), `--ck-gap-row` (14 px) |
| Dark mode | follows `prefers-color-scheme`; `data-theme="light"` or `"dark"` on `<html>` overrides it |

## The twelve components

| # | Component | Class | Parts |
|---|---|---|---|
| 1 | Edition header | `ck-header` | `ck-header__brand` or `ck-header__back`, `ck-header__day`; `ck-who` for the photo and name |
| 2 | Premise | `ck-premise` | `ck-newhere` is the "New here?" strip that sits under it |
| 3 | Chapter lead | `ck-lead` | `ck-badge`, an `h1`, `ck-premise ck-soft`, `ck-quote ck-quote--chapter`, `ck-actions` with `ck-btn` and `ck-btn--ghost`, `ck-small` |
| 4 | Today block | `ck-today` | `ck-num` for the number and its sentence; `ck-big`, `ck-track` and `ck-ends` for the large number with a progress track; `ck-today--ruled` adds the rule above |
| 5 | Coach row | `ck-coach` | `ck-coach__who` and the line; `ck-coach--record` for name, job and record, with `ck-coach__name`, `ck-coach__job`, `ck-coach__record`, `ck-meter` |
| 6 | Row list | `ck-rows` | `ck-rows__key`, `ck-dot` and `ck-dot--off`; `ck-rows--chapters` (`ck-rows__value`, `ck-rows__now`); `ck-rows--steps`; `ck-rows--more` |
| 7 | Bet card | `ck-bet` | `ck-small` for the date, a bold question, `ck-soft` for the sides |
| 8 | Verdict pair | `ck-verdicts` | `ck-verdicts__tag`, `ck-verdicts__tag--right` |
| 9 | Quote | `ck-quote` | his words; `ck-quote--chapter` is the chapter's own line, with the rule |
| 10 | Chart | `ck-chart` | `ck-chart__area`, `ck-chart__line`, `ck-chart__now` |
| 11 | Follow box | `ck-follow` | an `h2`, `ck-soft`, `ck-btn` |
| 12 | Footer | `ck-footer` | plain links |

Page plumbing, not components: `ck-page` (the column), `ck-main`, `ck-section`
(`--tight`, `--wide`), `ck-label` (the small line above a heading), `ck-soft`,
`ck-small`, `ck-link`, `ck-actions`, `ck-btn`.

## The accent

The accent is for progress and "new" only. It appears on: the track and meter fill, the
chart line, the "New this week" badge, the rule beside the new chapter's quote, the
current chapter in the chapter list, the filled status dot, the "Right" tag, and the
keyboard focus ring. Section labels use the soft text colour.

## Two changes from the prototype

1. **The faint grey passes AA.** `#8A9399` measured 3.13:1 on white. `--ck-faint` is
   `#6A7176`: 4.96:1 on white and 4.61:1 on the panel grey, where the bet card puts it.
   The dark value is unchanged (5.03:1 on the page, 4.63:1 on the panel).
2. **Section labels are not accent.** "The story so far", "Today · …" and the rest use
   `--ck-soft`.

Nothing else was changed. The class names gained the `ck-` prefix.

## A proposal the owner has not approved yet: the daily mark

`ck-mark` (#4586) is one column a day for the last four weeks, drawn the same way every
day in a frame whose height is the whole distance from the start weight to the goal:
`ck-mark__gone` (accent) is what is gone as of that day, `ck-mark__left` is what is left,
and a day with no weigh-in leaves a gap. It is
the only addition to the sheet since the kit was approved, it is on the preview path only,
and it comes out if he says no.

## The sources

`prototype/` holds the three approved sources exactly as the owner saw them:

- `template.html`: the base styles (its `{{PHOTO}}` and `{{CHART}}` slots are unfilled)
- `edition.html`: the front page
- `ai-coaches.html`: a layer-2 page

Each is an artifact body (title, style, content), not a full document. They load Geist
from Google Fonts; the live site never does. The file in `site/assets/fonts/clean/` is
the latin subset Google serves for `Geist:wght@400;500;600`
(`fonts.gstatic.com/s/geist/v5/gyByhwUxId8gMEwcGFWNOITd.woff2`, SIL Open Font License).
The figures in the sources and the specimen are true as of 2026-10-03.
