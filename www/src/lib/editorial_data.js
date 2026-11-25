// The editorial release's ONE reader of the snapshot (owner, review 14: "Make sure the live 'What happens next' figures
// use the same current data as the homepage"). The homepage's first screen, its "where the experiment stands" body
// figure, the "What happens next" block on the homepage and the "What happens next" page all call loadEditorial() and
// read the same progress() result — one computation over one snapshot. Built once per build process.
import { latestEdition, loadSeries, loadJourney, loadCalibration, loadOwnWords } from "./snapshot.js";
import { roomPublic } from "./room.js";
import { verifiedLead, denominatorSteps } from "./calibration.js";
import { ownWords } from "./own_words.js";
import { progress, progressInputs, coachesChecked } from "./editorial.js";

let _cache = null;

export async function loadEditorial() {
  if (_cache) return _cache;
  const edition = await latestEdition();
  const series = await loadSeries();
  let journey = null;
  try {
    const j = await loadJourney();
    journey = j && j.state !== "absent" ? j : null;
  } catch {
    journey = null;
  }
  const inputs = progressInputs({ series, journey, edition });
  const p = progress(inputs);
  let checked = null;
  if (roomPublic()) {
    try {
      const f = await loadCalibration();
      checked = f?.state === "ok" ? coachesChecked(f, verifiedLead(f.calibration || {}), denominatorSteps(f.calibration || {})) : null;
    } catch {
      checked = null;
    }
  }
  const served = await loadOwnWords();
  const own = {
    coaches_changed: ownWords(served, "coaches_changed")?.text || null,
    content: ownWords(served, "content")?.text || null,
  };
  _cache = { edition, inputs, p, checked, own };
  return _cache;
}
