// Editorial features (owner authorisation, review 14, 2026-11-24): a separately dated editorial retrospective at its own
// address, beside a chapter and never a rewrite of it. The approved text is ONE file in src/features/, published byte for
// byte; this module only places it. Pure, proven in tests/feature.test.mjs.
//
// What the page may add is presentation only, and scripts/check_www_build.py::feature_fingerprint rebuilds the exact
// approved bytes from the built page (the Chronicle edition verifier's block model, content.chapter_editions) on every
// build and every deploy scan:
//   * a block's markdown marker becomes its element — "# " the page heading, "## " a section heading, "### " a section
//     a reader opens (<details><summary>), "- " / "1. " list items; every other block is one paragraph;
//   * a site address written in the text ("/story/week-08/") becomes a link whose words are that address, unchanged,
//     and only when the build has the page (else it stays plain text);
//   * a phrase features.json names under `links` ("her coach page") becomes a link to its declared page, its words
//     unchanged (owner decision on PR #6263), again only when the build has the page;
//   * the dateline, the second block, is drawn above the heading (CSS order; the document order is the text's).
// Nothing else: no word is added inside the text, and the chrome (the path, the first-publication day) sits outside it.

import FEATURES from "../features/features.json" with { type: "json" };

export const FEATURE_LIST = FEATURES.features;

/** The feature with `id`, or null. */
export function featureMeta(id) {
  return FEATURE_LIST.find((f) => f && f.id === id) || null;
}

/** The blocks of an approved text: [{kind: "h1"|"h2"|"h3"|"p"|"ul"|"ol", text | items}]. Throws on a shape it cannot place
 *  exactly (so a text that would not round-trip never builds). */
export function featureBlocks(text) {
  const src = String(text ?? "");
  if (src.includes("\r")) throw new Error("feature text: carriage return");
  const blocks = [];
  for (const raw of src.split("\n\n")) {
    if (raw === "" || raw !== raw.trim() || raw.includes("  ")) throw new Error(`feature text: a block with stray whitespace: ${JSON.stringify(raw.slice(0, 40))}`);
    const lines = raw.split("\n");
    if (lines.every((l) => l.startsWith("- "))) {
      blocks.push({ kind: "ul", items: lines.map((l) => l.slice(2)) });
    } else if (lines.every((l, i) => l.startsWith(`${i + 1}. `))) {
      blocks.push({ kind: "ol", items: lines.map((l, i) => l.slice(`${i + 1}. `.length)) });
    } else if (lines.length !== 1) {
      throw new Error(`feature text: a multi-line block that is not a list: ${JSON.stringify(raw.slice(0, 40))}`);
    } else {
      const m = /^(#{1,3}) (.+)$/.exec(raw);
      blocks.push(m ? { kind: `h${m[1].length}`, text: m[2] } : { kind: "p", text: raw });
    }
  }
  return blocks;
}

/** The text again from its blocks — the inverse the deploy check runs on the built page (tests hold it to the bytes). */
export function featureText(blocks) {
  return blocks
    .map((b) => {
      if (b.kind === "ul") return b.items.map((x) => `- ${x}`).join("\n");
      if (b.kind === "ol") return b.items.map((x, i) => `${i + 1}. ${x}`).join("\n");
      if (b.kind === "p") return b.text;
      return `${"#".repeat(Number(b.kind.slice(1)))} ${b.text}`;
    })
    .join("\n\n");
}

/** The head of a feature: its title, dateline, summary (dek) and byline — the first four blocks, as approved. */
export function featureHead(text) {
  const b = featureBlocks(text);
  const [h, dateline, dek, byline] = b;
  if (!h || h.kind !== "h1" || [dateline, dek, byline].some((x) => !x || x.kind !== "p")) throw new Error("feature text: it opens with '# title', a dateline, a summary and a byline");
  return { title: h.text, dateline: dateline.text, dek: dek.text, byline: byline.text };
}

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
// a site address as written in the text: /story/…/, /data/…/, /system/…/
const ADDRESS = /\/(?:story|data|system)\/[A-Za-z0-9_\-/]*?\/(?=[\s);,.:]|$)/g;

/** One line of text as HTML: escaped, each site address the build has (linkFor(path) → href | null) as a link whose
 *  words are the address itself, and each declared phrase (`phrases`: words → path) as a link to its page. */
export function inline(text, linkFor = () => null, phrases = {}) {
  const t = String(text);
  const hits = [...t.matchAll(ADDRESS)].map((m) => ({ at: m.index, words: m[0], path: m[0] }));
  for (const [words, path] of Object.entries(phrases || {})) {
    let i = t.indexOf(words);
    while (i >= 0) {
      hits.push({ at: i, words, path });
      i = t.indexOf(words, i + words.length);
    }
  }
  hits.sort((a, b) => a.at - b.at);
  let out = "";
  let at = 0;
  for (const h of hits) {
    if (h.at < at) continue;
    const to = linkFor(h.path);
    if (!to) continue;
    out += esc(t.slice(at, h.at)) + `<a href="${esc(to)}">${esc(h.words)}</a>`;
    at = h.at + h.words.length;
  }
  return out + esc(t.slice(at));
}

/** Every site address the text names, in order, once each (the page's link check reads this). */
export function featureAddresses(text) {
  return [...new Set([...String(text).matchAll(ADDRESS)].map((m) => m[0]))];
}

const blockHtml = (b, linkFor, phrases) => {
  if (b.kind === "ul" || b.kind === "ol") return `<${b.kind}>${b.items.map((x) => `<li>${inline(x, linkFor, phrases)}</li>`).join("")}</${b.kind}>`;
  if (b.kind === "p") return `<p>${inline(b.text, linkFor, phrases)}</p>`;
  return `<${b.kind}>${inline(b.text, linkFor, phrases)}</${b.kind}>`;
};

/** The approved text as the page's HTML: the head; the story; "## The evidence" (the last "## ") with its one-line
 *  introduction and its "### " sections, each closed until a reader opens it. */
export function renderFeature(text, linkFor = () => null, phrases = {}) {
  const b = featureBlocks(text);
  featureHead(text);
  const [h, dateline, dek, byline, ...rest] = b;
  const ev = rest.map((x) => x.kind).lastIndexOf("h2");
  const firstSection = rest.findIndex((x) => x.kind === "h3");
  if (ev < 0 || firstSection < ev || rest[ev + 1]?.kind !== "p") throw new Error("feature text: the evidence is the last '## ' section, a one-line introduction, then its '### ' sections");
  const story = rest.slice(0, ev);
  if (story.some((x) => x.kind === "h3" || x.kind === "h1")) throw new Error("feature text: the story holds '## ' sections only");
  const sections = [];
  for (const x of rest.slice(ev + 2)) {
    if (x.kind === "h3") sections.push({ title: x.text, blocks: [] });
    else if (sections.length && x.kind !== "h1" && x.kind !== "h2") sections[sections.length - 1].blocks.push(x);
    else throw new Error("feature text: the evidence holds '### ' sections only");
  }
  return [
    `<header class="fx-head"><h1>${inline(h.text, linkFor)}</h1><p class="fx-dateline">${inline(dateline.text, linkFor)}</p><p class="fx-dek">${inline(dek.text, linkFor)}</p><p class="fx-byline">${inline(byline.text, linkFor)}</p></header>`,
    `<div class="fx-story">${story.map((x) => blockHtml(x, linkFor, phrases)).join("")}</div>`,
    `<h2 class="fx-evidence">${inline(rest[ev].text, linkFor)}</h2><p class="fx-ev-intro">${inline(rest[ev + 1].text, linkFor)}</p>`,
    sections
      .map((s, i) => `<details${i === sections.length - 1 ? ' class="last"' : ""}><summary>${inline(s.title, linkFor)}</summary><div class="fx-body">${s.blocks.map((x) => blockHtml(x, linkFor, phrases)).join("")}</div></details>`)
      .join(""),
  ].join("");
}
