// mirror_demo.js — the Mirror's synthetic worked example (#1392).
//
// SYNTHETIC — not real data and not anyone's real export. Exists so the page can
// demonstrate the full pipeline (parse → score → overlay) before a reader drops
// their own file, exactly like grade-your-coach's labelled worked example. Shaped
// like a genuine Whoop physiological_cycles.csv: 45 days so the personal
// HRV-ratio band clears the MIN_N=30 floor-guard and the demo exercises the
// personal-variance path, with two device-off days so honest absence shows too.
//
// Embedded as a module constant rather than fetched: the privacy gate
// (tests/test_mirror_parity.py) pins this page to exactly ONE network request —
// the published distributions file — and a demo fetch would be a second.

const HEADER =
  '"Cycle start time","Cycle end time","Cycle timezone","Recovery score %","Resting heart rate (bpm)",' +
  '"Heart rate variability (ms)","Day Strain","Sleep performance %","Sleep efficiency %",' +
  '"In bed duration (min)","Awake duration (min)","Asleep duration (min)",' +
  '"Light sleep duration (min)","Deep (SWS) duration (min)","REM duration (min)"';

// Deterministic pseudo-variation (fixed seed walk — no Math.random: the demo must
// render identically on every visit, or the page would look nondeterministic).
function rows() {
  const out = [];
  let hrv = 52;
  let rhr = 57;
  for (let i = 0; i < 45; i++) {
    const month = i < 16 ? "06" : "07";
    const day = i < 16 ? 15 + i : i - 15;
    const date = `2026-${month}-${String(day).padStart(2, "0")}`;
    // triangle-wave walks — varied but bounded and seedless
    hrv += ((i * 7) % 5) - 2;
    // (i*5)%3 cycles 0,2,1 → steps of -1,+1,0: bounded around 57, never the
    // degenerate constant −1/day walk render-QA caught ((i*3)%3 is always 0).
    rhr += ((i * 5) % 3) - 1;
    const recovery = 30 + ((i * 13) % 61);
    const strain = (6 + ((i * 11) % 90) / 10).toFixed(1);
    const perf = 60 + ((i * 17) % 41);
    const inBed = 400 + ((i * 23) % 90);
    const awake = 25 + ((i * 5) % 30);
    const light = Math.round((inBed - awake) * 0.55);
    const deep = Math.round((inBed - awake) * 0.2);
    const rem = inBed - awake - light - deep;
    if (i === 20 || i === 33) {
      // device-off nights: sleep recorded, no recovery/HRV — honest absence, not zeros
      out.push(
        `"${date} 06:30:00","","America/Los_Angeles","","","","","${perf}","88.5","${inBed}","${awake}","${inBed - awake}","${light}","${deep}","${rem}"`
      );
      continue;
    }
    out.push(
      `"${date} 06:30:00","","America/Los_Angeles","${recovery}","${rhr}","${hrv}.${(i * 37) % 100}","${strain}","${perf}","${(88 + (i % 9)).toFixed(1)}","${inBed}","${awake}","${inBed - awake}","${light}","${deep}","${rem}"`
    );
  }
  return out;
}

export const DEMO_LABEL = "SYNTHETIC — a labelled worked example, not anyone's real export.";
export const DEMO_CSV = [HEADER, ...rows()].join("\n");
