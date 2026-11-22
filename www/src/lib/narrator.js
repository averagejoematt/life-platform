// The narrator, named the same way on every byline (#6178, owner ruling 2026-11-22 §7: "Use Elena Voss consistently
// as the named AI editorial narrator. Disclose clearly that Elena is an AI editorial persona."). The chapter page, the
// home page's latest-chapter card and the story index read these strings; the RSS channel (scripts/v4_build_rss.py) and
// the subscribe page (site/subscribe/index.html) carry NARRATOR_WHO verbatim — tests/test_narrator_byline_6178.py holds
// every surface to it. The canon behind the name is lambdas/content/elena_canon.py.
//
// Nothing here is first person: no sentence is written for Matthew. A first-person line he approved stays as it is,
// and the naming sits beside it, never inside it.

/** Who writes the chapters, in one phrase: the name and the plain AI disclosure. */
export const NARRATOR_WHO = "Elena Voss, an AI editorial persona (a language model writing from the platform's data)";

/** A byline on its own: the home card, where the approval is said in the owner's own approved sentence beside it. */
export const NARRATOR_BYLINE = `By ${NARRATOR_WHO}.`;

/** A published chapter's byline: who wrote it and that Matthew approved it before it published. */
export const CHAPTER_BYLINE = `${NARRATOR_BYLINE} Published after Matthew approved it.`;

/** The story index's line about every chapter. */
export const INDEX_BYLINE = `Each chapter is written by ${NARRATOR_WHO} and published only after Matthew approves it.`;
