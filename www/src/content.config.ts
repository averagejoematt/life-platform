// The content model — eleven collections plus the dated edition, every entry wrapped in
// the publication envelope. This file is the registry primitive (CHARTER §1): a field the
// snapshot does not declare here fails the build, a dangling reference fails the build,
// and `visibility` is a literal `"public"` so a held or private object can never render.
//
// The producer is scripts/publish_snapshot.py (the ONE publication boundary); the
// Python side mirrors these shapes in `SCHEMA` so the two are a contract, not a convention
// (tests/test_web_publication_snapshot_5530.py checks the field sets agree).
import { defineCollection, reference } from "astro:content";
import { file } from "astro/loaders";
import { z } from "astro/zod";

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[a-z0-9][a-z0-9._:-]*$/i;

export const OBJECT_TYPES = [
  "chapter",
  "episode",
  "essay",
  "metric",
  "insight",
  "experiment",
  "prediction",
  "disagreement",
  "coach",
  "source",
  "method",
  "edition",
] as const;

const edge = z.object({
  type: z.enum(OBJECT_TYPES),
  id: z.string().regex(ID),
  rel: z.string().min(1).max(40).optional(),
});

const approval = z
  .object({
    by: z.string().min(1),
    at: z.string().min(1),
    via: z.string().min(1),
  })
  .nullable();

/** The publication envelope every object carries (plan §D2). */
const envelope = <T extends z.ZodRawShape>(type: (typeof OBJECT_TYPES)[number], fields: T) =>
  z
    .object({
      id: z.string().regex(ID),
      type: z.literal(type),
      // The gate: anything that is not public is not content.
      visibility: z.literal("public"),
      as_of: z.string().regex(ISO_DAY),
      data_through: z.string().regex(ISO_DAY).nullable(),
      source: z.array(z.string().min(1)),
      state: z.enum(["ok", "stale", "absent"]),
      absent_text: z.string().nullable(),
      approved: approval,
      method_ids: z.array(z.string().regex(ID)),
      edges: z.array(edge),
      sample: z.boolean(),
      title: z.string().min(1),
      summary: z.string().nullable(),
    })
    .extend(fields)
    .strict();

const snapshot = (name: string) => file(`content/snapshot/${name}.json`);

const chapters = defineCollection({
  loader: snapshot("chapters"),
  schema: envelope("chapter", {
    week: z.number().int().nullable(),
    week_label: z.string().min(1),
    date: z.string().regex(ISO_DAY),
    status: z.enum(["published", "held", "skipped", "pending"]),
    excerpt: z.string().nullable(),
    body_html: z.string().nullable(),
    word_count: z.number().int().nullable(),
    read_minutes: z.number().int().nullable(),
    url_legacy: z.string().nullable(),
    episode_id: z.string().regex(ID).nullable(),
  }),
});

const episodes = defineCollection({
  loader: snapshot("episodes"),
  schema: envelope("episode", {
    number: z.number().int(),
    date: z.string().regex(ISO_DAY),
    duration_sec: z.number().int().nullable(),
    audio_url: z.string().nullable(),
    transcript_url: z.string().nullable(),
    byline: z.string().nullable(),
    chapter_id: z.string().regex(ID).nullable(),
    transcript: z.array(z.object({ speaker: z.string(), line: z.string() })).nullable(),
  }),
});

const essays = defineCollection({
  loader: snapshot("essays"),
  schema: envelope("essay", {
    date: z.string().regex(ISO_DAY),
    body_html: z.string().nullable(),
    url_legacy: z.string().nullable(),
  }),
});

const metrics = defineCollection({
  loader: snapshot("metrics"),
  schema: envelope("metric", {
    label: z.string().min(1),
    unit: z.string(),
    source_id: z.string().regex(ID).nullable(),
    decimals: z.number().int().min(0).max(3),
    sentence: z.string().nullable(),
    instrument: z.string().nullable(),
    series_url: z.string().nullable(),
  }),
});

const insights = defineCollection({
  loader: snapshot("insights"),
  schema: envelope("insight", {
    date: z.string().regex(ISO_DAY),
    kind: z.enum(["insight", "hypothesis"]),
    status: z.string().min(1),
    text: z.string().min(1),
    metric_id: z.string().regex(ID).nullable(),
  }),
});

const experiments = defineCollection({
  loader: snapshot("experiments"),
  schema: envelope("experiment", {
    name: z.string().min(1),
    status: z.string().min(1),
    hypothesis: z.string().nullable(),
    pillar: z.string().nullable(),
    start_date: z.string().regex(ISO_DAY).nullable(),
    end_date: z.string().regex(ISO_DAY).nullable(),
    pre_registered: z.boolean(),
    metric_id: z.string().regex(ID).nullable(),
  }),
});

const predictions = defineCollection({
  loader: snapshot("predictions"),
  schema: envelope("prediction", {
    coach_id: reference("coaches"),
    metric_id: z.string().regex(ID).nullable(),
    claim: z.string().min(1),
    logged_date: z.string().regex(ISO_DAY),
    due_date: z.string().regex(ISO_DAY).nullable(),
    settled_date: z.string().regex(ISO_DAY).nullable(),
    kind: z.enum(["number", "direction", "yes_no", "sealed", "interval", "observation", "unknown"]),
    status: z.enum(["pending", "confirmed", "refuted", "expired", "inconclusive", "observation"]),
    verdict_text: z.string().nullable(),
    grading: z
      .object({
        how: z.string().nullable(),
        actual_text: z.string().nullable(),
        tolerance_text: z.string().nullable(),
        outcome_notes: z.string().nullable(),
      })
      .nullable(),
    simple_guess: z
      .object({
        state: z.string(),
        right: z.boolean().nullable(),
        text: z.string().nullable(),
      })
      .nullable(),
    // Phase 3: emitted by the grader, never computed in a page (owner requirement A).
    quality_flags: z.array(z.enum(["logging_gap", "low_power", "proxy_metric"])),
    sealed: z.boolean(),
    confidence: z.number().min(0).max(1).nullable(),
  }),
});

const disagreements = defineCollection({
  loader: snapshot("disagreements"),
  schema: envelope("disagreement", {
    topic: z.string().min(1),
    coach_a: reference("coaches"),
    coach_b: reference("coaches"),
    claim_a: z.string().nullable(),
    claim_b: z.string().nullable(),
    status: z.enum(["open", "resolved", "void"]),
    resolved_date: z.string().regex(ISO_DAY).nullable(),
    verdict: z.string().nullable(),
    metric_id: z.string().regex(ID).nullable(),
  }),
});

const coaches = defineCollection({
  loader: snapshot("coaches"),
  schema: envelope("coach", {
    name: z.string().min(1),
    domain: z.string().min(1),
    tier: z.enum(["lead", "staff"]),
    retired: z.boolean(),
    retired_date: z.string().regex(ISO_DAY).nullable(),
    short_bio: z.string().nullable(),
    record: z
      .object({
        right: z.number().int().nullable(),
        n: z.number().int(),
        through: z.string().regex(ISO_DAY).nullable(),
      })
      .nullable(),
    comparison_text: z.string().nullable(),
    instrument_absent: z.object({ absent: z.boolean(), reason: z.string().nullable() }).nullable(),
  }),
});

const sources = defineCollection({
  loader: snapshot("sources"),
  schema: envelope("source", {
    label: z.string().min(1),
    category: z.string().nullable(),
    since: z.string().nullable(),
    latest: z.string().nullable(),
    status: z.enum(["live", "stale", "paused", "behavioral-stale", "unknown"]),
    stale_hours: z.number().int().nullable(),
    instrument_for: z.string().regex(ID).nullable(),
    behavioral: z.boolean(),
  }),
});

const methods = defineCollection({
  loader: snapshot("methods"),
  schema: envelope("method", {
    name: z.string().min(1),
    category: z.string().nullable(),
    formula: z.string().nullable(),
    window: z.string().nullable(),
    limitations: z.string().nullable(),
    min_n: z.number().int().nullable(),
    used_by: z.array(z.string()),
  }),
});

// The dated edition: the front page's document, one entry per snapshot day. Its blocks
// keep the Site API's five-key contract (state · as_of · source · absent_text · data).
const block = z.object({
  state: z.enum(["ok", "stale", "absent", "unavailable"]),
  as_of: z.string().nullable(),
  source: z.union([z.string(), z.array(z.string())]),
  absent_text: z.string().nullable(),
  data: z.unknown(),
});

const editions = defineCollection({
  loader: snapshot("editions"),
  schema: envelope("edition", {
    day_n: z.number().int().nullable(),
    start_date: z.string().regex(ISO_DAY).nullable(),
    order: z.array(z.string()),
    blocks: z.record(block),
  }),
});

export const collections = {
  chapters,
  episodes,
  essays,
  metrics,
  insights,
  experiments,
  predictions,
  disagreements,
  coaches,
  sources,
  methods,
  editions,
};
