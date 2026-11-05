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
  "day",
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
    // the program week's explicit interval (/api/chapters), null for a prologue — never inferred from `date`
    week_start: z.string().regex(ISO_DAY).nullable(),
    week_end: z.string().regex(ISO_DAY).nullable(),
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

// #5610 (owner decision D, 2026-11-02): one correction on a prediction — the served shape of
// lambdas/web/correction_history.FIELDS + aggregate_impact, pinned equal to CORRECTION_FIELDS in
// scripts/publish_snapshot_contract.py (tests/test_web_publication_snapshot_5530.py). Every date is the
// stored one or null: the original grading is a DAY, `corrected_at` the recorded instant, `published_on`
// null until a publication day is actually recorded. `explanation` is required — reader words, never the
// stored engineering `reason`, which travels beside it as the audit record.
const isoDayOrNull = z.string().regex(ISO_DAY).nullable();
const correction = z
  .object({
    source: z.enum(["corrections", "verdict_correction", "respecified"]),
    kind: z.enum(["regrade", "restate", "withdraw", "respecify", "revert"]),
    rules: z.array(z.object({ id: z.string().min(1), version: z.string().nullable() }).strict()).min(1),
    explanation: z.string().min(1),
    said_on: isoDayOrNull,
    original_status: z.string().nullable(),
    original_outcome_date: isoDayOrNull,
    original_outcome_notes: z.string().nullable(),
    corrected_status: z.string().nullable(),
    corrected_outcome_date: isoDayOrNull,
    corrected_outcome_notes: z.string().nullable(),
    target_before: isoDayOrNull,
    target_after: isoDayOrNull,
    corrected_at: z.string().nullable(),
    published_on: isoDayOrNull,
    reason: z.string().nullable(),
    evaluator_version: z.string().nullable(),
    aggregate_impact: z.string().nullable(),
  })
  .strict();

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
    coach_name: z.string().min(1),
    retired: z.boolean(),
    metric_key: z.string().nullable(),
    claim_withheld: z.enum(["unsourced", "privacy"]).nullable(),
    // Owner rulings 2026-11-03: the stored verdict, disputed pending classification — shown, never counted as verified.
    classification_review: z.boolean(),
    classification_review_reason: z.string().min(1).nullable(),
    corrections: z.array(correction),
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
    quality: z
      .object({ clean: z.number().int(), flagged: z.number().int(), unassessed: z.number().int(), n: z.number().int(), by_flag: z.record(z.number().int()) })
      .nullable(),
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

// One day since the start (#5585): the readings exactly as /api/pulse_history serves them, the trailing
// normals the exporter computed (scripts/publish_snapshot_day.py — never the browser), the week's chapter,
// the neighbours, and whether the three window-bound endpoints still serve the day (M4 fills the detail).
const reading = z.number().nullable();
const normal = z.object({ mean7: z.number().nullable(), n7: z.number().int(), mean30: z.number().nullable(), n30: z.number().int() }).strict();
const READING_KEYS = ["weight_lbs", "recovery_pct", "sleep_hours", "hrv_ms", "rhr_bpm", "strain", "steps", "active_kcal"] as const;

// M4 (#5586): the day's layers 2–3 — mirrored by publish_snapshot_day.check_layers. A block is present
// exactly when its state is "served"; otherwise the page states why in place.
const n = z.number().nullable();
const daySet = z.object({ type: z.string().min(1), reps: n, weight_kg: n, rpe: n }).strict();
const workout = z
  .object({
    title: z.string().min(1),
    duration_min: n,
    volume_kg: n,
    exercises: z.array(z.object({ name: z.string().min(1), sets: z.array(daySet) }).strict()),
  })
  .strict();
const device = z
  .object({ night_of: z.string().regex(ISO_DAY).nullable(), hours: n, deep_hours: n, rem_hours: n, light_hours: n, score: n })
  .strict()
  .nullable();
const night = z
  .object({
    score: n,
    efficiency: n,
    hours: n,
    deep_pct: n,
    rem_pct: n,
    light_pct: n,
    sleep_start: z.string().min(1).nullable(),
    by_device: z.object({ eightsleep: device, whoop: device }).strict(),
  })
  .strict();
const food = z.object({ calories: n, protein_g: n, carbs_g: n, fat_g: n, logging_gap: z.boolean(), floor_g: n, tdee: n }).strict();
const engine = z
  .object({
    level: z.number(),
    composite: n,
    delta: n,
    pillars: z.array(z.object({ name: z.string().min(1), score: n, not_instrumented: z.boolean() }).strict()),
    // owner ruling 2026-11-05: which method computed the score (character_privacy.PUBLIC_METHOD_LABELS), or null
    method: z.string().min(1).nullable(),
  })
  .strict();
// One correction beside a quotation — the same served shape as the coach APIs' summary_corrections / grade_corrections
// (lambdas/coach/authoritative_grades.CORRECTION_NOTE_FIELDS; owner review of #5644, 2026-11-03).
const gradeCorrection = z
  .object({
    prediction_id: z.string().min(1).nullable(),
    coach_id: z.string().min(1).nullable(),
    original_status: z.string().min(1).nullable(),
    corrected_status: z.string().min(1).nullable(),
    corrected_at: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}Z)?$/)
      .nullable(),
    explanation: z.string().min(1).nullable(),
  })
  .strict();
const coachLine = z
  .object({
    coach: z.string().min(1),
    coach_id: z.string().regex(ID),
    move: z.string().min(1),
    move_label: z.string().min(1).nullable(),
    text: z.string().min(1),
    corrections: z.array(z.string().min(1)),
    grade_corrections: z.array(gradeCorrection),
  })
  .strict();
const callSettled = z.object({ prediction_id: z.string().regex(ID), coach_name: z.string().min(1), verdict: z.string().min(1), claim_short: z.string().min(1) }).strict();
const callOpen = z.object({ prediction_id: z.string().regex(ID), coach_name: z.string().min(1), due_date: z.string().regex(ISO_DAY), text: z.string().min(1) }).strict();
const UNSERVED = ["older than the served window", "not served"] as const;

const days = defineCollection({
  loader: snapshot("days"),
  schema: envelope("day", {
    date: z.string().regex(ISO_DAY),
    day_number: z.number().int().min(1),
    weekday: z.string().min(1),
    readings: z.object(Object.fromEntries(READING_KEYS.map((k) => [k, reading])) as Record<(typeof READING_KEYS)[number], typeof reading>).strict(),
    normals: z.object(Object.fromEntries(READING_KEYS.map((k) => [k, normal])) as Record<(typeof READING_KEYS)[number], typeof normal>).strict(),
    chapter_id: z.string().regex(ID).nullable(),
    prev_id: z.string().regex(ID).nullable(),
    next_id: z.string().regex(ID).nullable(),
    has_weighin: z.boolean(),
    in_window: z.object({ workouts: z.boolean(), sleep: z.boolean(), nutrition: z.boolean() }).strict(),
    sleep_target_h: z.number(),
    workout: workout.nullable(),
    workout_state: z.enum(["served", "none logged", ...UNSERVED]),
    night: night.nullable(),
    night_state: z.enum(["served", "none recorded", ...UNSERVED]),
    food: food.nullable(),
    food_state: z.enum(["served", "not logged", ...UNSERVED]),
    engine: engine.nullable(),
    coach_lines: z.array(coachLine),
    calls_settled: z.array(callSettled),
    calls_open: z.array(callOpen),
    calls_open_count: z.number().int().min(0),
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
  days,
};
