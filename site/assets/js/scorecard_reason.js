/*
  scorecard_reason.js — the reason line under a graded call on /coaching/scorecard/ (#4220).

  `/api/predictions` serves each call's `outcome_notes` as the grader wrote it. For
  directional calls that is a serialized JSON object
  ({"actual_value": null, "reason": "Insufficient data to determine trend for
  'blood_glucose_avg'", "beats_null": false, "bayesian_update": null,
  "algo_version": "1.0", "grading_open": true}), and the page printed that object verbatim
  as the reason line (seen live 2026-09-29). This pure function turns it into reader words:
  the grader's own `reason`, and for a call that came back with no signal,
  "not gradable yet — <reason>". Plain-text notes pass through unchanged. An object with no
  reason renders nothing, never "[object Object]" and never the raw dict.
*/

const NO_SIGNAL = new Set(["inconclusive", "expired"]);

export function callReasonText(status, outcomeNotes) {
  let text = outcomeNotes == null ? "" : outcomeNotes;
  let parsed = null;
  if (typeof text === "object") parsed = text;
  else {
    text = String(text).trim();
    if (text.startsWith("{")) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = null; // not JSON after all — shown as the plain note it is
      }
    }
  }
  if (parsed && typeof parsed === "object") text = typeof parsed.reason === "string" ? parsed.reason.trim() : "";
  if (!text) return "";
  if (NO_SIGNAL.has(String(status || ""))) {
    return `not gradable yet — ${text.charAt(0).toLowerCase()}${text.slice(1)}`;
  }
  return text;
}
