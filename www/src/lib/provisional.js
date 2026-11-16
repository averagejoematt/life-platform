// A still-recording night, carried to the data room (#5953 acceptance item 3). The vendor's own "this record is not
// final" flag (Eight Sleep's `incomplete`, stored as `vendor_incomplete`) is served per night by /api/sleep_detail and
// rides into the snapshot on each Day object as `night.by_device.<device>.provisional` (scripts/publish_snapshot_day.py,
// #6001). The daily series (/api/series) carries no such flag, so the data room reads it from the Day objects of the
// SAME snapshot — nothing is inferred here: a night is provisional only where the snapshot says `true`.
//
// The series and the Day objects share one date convention: both are keyed by the WAKE morning (the stored DATE#), so
// series day D is Day D's night. Whoop stores a sleep only once it is scored, so its flag is never true today; the rule
// is per device all the same, keyed by the series' own source.
// Pure, no DOM. Proven by tests/provisional.test.mjs.

/** The series that measure a night. A provisional flag on the night says nothing about any other series. */
export const NIGHT_METRICS = new Set(["sleep_duration_hours", "deep_pct", "rem_pct"]);

/** The words a provisional reading carries, wherever it is printed. */
export const PROVISIONAL_WORDS = "still recording when read, provisional";

/** The chart caption's key to the ring svgChart draws on a provisional reading. */
export const PROVISIONAL_RING = "a hollow ring is a night still recording when read, so its reading is provisional";

/**
 * The dates (ISO, ascending) whose night the snapshot marks still recording for this series' device.
 * @param {Array<any>} days the snapshot's Day objects
 * @param {string} metricId the series key
 * @param {string|null|undefined} sourceId the device the series is read from (the series' own source_id)
 */
export function provisionalNights(days, metricId, sourceId) {
  if (!NIGHT_METRICS.has(metricId) || !sourceId) return [];
  return (days || [])
    .filter((d) => d && d.night && d.night.by_device && d.night.by_device[sourceId] && d.night.by_device[sourceId].provisional === true)
    .map((d) => d.date)
    .sort();
}

/** The series' days with `provisional: true` on each listed date (a new array; the input is not changed). */
export function markProvisional(seriesDays, dates) {
  const set = new Set(dates || []);
  if (!set.size) return seriesDays;
  return seriesDays.map((d) => (set.has(d.date) && d.value != null && !d.gap ? { ...d, provisional: true } : d));
}
