// Canonical URL per object type (plan §C, §E1) and the BASE-aware href helper.
// `import.meta.env.BASE_URL` is "/" in production and "/next/v9/" on the preview path, so
// every internal link goes through href() and no template ever hard-codes a prefix.

export const PATH_OF = Object.freeze({
  chapter: (id) => `/story/${id}/`,
  episode: (id) => `/story/${id}/`,
  essay: (id) => `/story/essays/${id}/`,
  metric: (id) => `/data/${id}/`,
  insight: (id) => `/data/insights/${id}/`,
  experiment: (id) => `/data/experiments/${id}/`,
  prediction: (id) => `/system/ledger/${id}/`,
  disagreement: (id) => `/system/ledger/disagreements/${id}/`,
  coach: (id) => `/system/coaches/${id}/`,
  source: (id) => `/system/sources/${id}/`,
  method: (id) => `/system/methods/${id}/`,
  edition: () => `/`,
});

/** Join the build's base path and a site-absolute path, keeping the trailing slash. */
export function href(path, base = import.meta.env.BASE_URL) {
  const b = (base || "/").replace(/\/+$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}

/** The canonical path of an object (without base). Episodes live on their chapter page. */
export function pathOf(type, id, data) {
  if (type === "episode" && data && data.chapter_id) return `/story/${data.chapter_id}/#listen`;
  const fn = PATH_OF[type];
  if (!fn) throw new Error(`no canonical path for type ${type}`);
  return fn(id);
}
