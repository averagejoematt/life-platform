// The permanence panel on /privacy/policy/ (#5920) — the v9 port of site/assets/js/privacy_permanence.js (#2574).
// It fills "the archive right now" from the two published archive documents, same origin (CSP connect-src 'self').
// Two rules, both ADR-104: never render a number that was not read, and never let the terms depend on the fetch —
// the clause list is static and stands whether or not these two documents answer. One change from the v8 script:
// the build time is stated in words (the v9 rule: no ISO date in rendered text).
const ABSENT = "not available";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export function mib(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return null;
  if (bytes < 1024) return `${bytes} bytes`;
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(0)} KB`;
}

export function stampInWords(iso) {
  if (typeof iso !== "string" || !iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function mount(panel = document.getElementById("perm-live")) {
  if (!panel) return Promise.resolve();
  const slot = (name) => panel.querySelector(`[data-perm="${name}"]`);
  const absent = (name) => {
    const el = slot(name);
    if (!el) return;
    el.textContent = ABSENT;
    el.setAttribute("data-absent", "1");
  };
  const fill = (name, value) => {
    const el = slot(name);
    if (!el) return;
    if (value === null || value === undefined || value === "") return absent(name);
    el.textContent = value;
    el.removeAttribute("data-absent");
  };
  const note = (text) => {
    const el = slot("note");
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
  };
  const getJSON = (url) =>
    fetch(url, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(`${url} ${r.status}`);
      return r.json();
    });

  // "unreadable" is a document that did not answer; "incomplete" answered with a shape no number can be stated
  // from (a half-written nightly). Both must SAY so: an unexplained absence reads as an empty box, a box as zero.
  const unreadable = [];
  const incomplete = [];
  let mismatch = null;

  const manifest = getJSON("/archive/manifest.json")
    .then((m) => {
      if (!m || typeof m !== "object") throw new Error("manifest: not an object");
      const arc = m.archive && typeof m.archive === "object" ? m.archive : {};
      const built = stampInWords(m.generated_at);
      const size = mib(arc.bytes);
      const count = typeof m.entry_count === "number" ? plural(m.entry_count, "file") : null;
      const sha = typeof arc.sha256 === "string" && arc.sha256 ? arc.sha256 : null;
      fill("built", built);
      fill("bytes", size);
      fill("entries", count);
      fill("sha", sha);
      if (built === null || size === null || count === null || sha === null) incomplete.push("the manifest");
    })
    .catch(() => {
      ["built", "bytes", "entries", "sha"].forEach(absent);
      unreadable.push("the manifest");
    });

  const continuity = getJSON("/archive/continuity.json")
    .then((c) => {
      if (!c || typeof c !== "object") throw new Error("continuity: not an object");
      const days = typeof c.days_silent === "number" ? c.days_silent : null;
      const state = typeof c.state === "string" ? c.state : null;
      if (state === null) {
        absent("state");
        incomplete.push("the continuity clock");
      } else if (c.measurement_failed || state === "unknown") fill("state", "not measured on the last run");
      else fill("state", state + (days === null ? "" : ` · ${plural(days, "day")} since the last signal`));

      const live = c.terms && typeof c.terms.version === "string" ? c.terms.version : null;
      const list = document.querySelector(".perm-clauses");
      const built = list ? list.getAttribute("data-built-version") : null;
      fill("version", live);
      if (live === null && !incomplete.includes("the continuity clock")) incomplete.push("the continuity clock");
      if (live && built && live !== built) {
        mismatch =
          `The published edition of these terms is ${live}, but the clauses on this page were rendered from edition ${built}. ` +
          "Read the published document as authoritative until this page catches up.";
      }
    })
    .catch(() => {
      absent("state");
      absent("version");
      unreadable.push("the continuity clock");
    });

  return Promise.all([manifest, continuity]).then(() => {
    const lines = [];
    if (unreadable.length) {
      let line = `Could not read ${unreadable.join(" or ")} just now, so those numbers are shown as unavailable rather than guessed.`;
      // Hedge about the download only when the manifest is what failed: if it answered, this panel has just shown
      // the archive's build time, size and checksum, and a warning would contradict it.
      if (unreadable.includes("the manifest")) {
        line += " The download address above is fixed and does not move, but it may not answer either until the next nightly build.";
      }
      lines.push(line);
    }
    if (incomplete.length) {
      lines.push(
        `The last published copy of ${incomplete.join(" and ")} did not carry every number this panel states, so the missing ones are left unavailable rather than filled in.`,
      );
    }
    if (mismatch) lines.push(mismatch);
    if (lines.length) note(lines.join(" "));
  });
}

if (typeof document !== "undefined") mount();
