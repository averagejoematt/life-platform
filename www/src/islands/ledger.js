// The ledger's filter island: coach · status · kind · a word in the claim, over the rows the
// build rendered. It hides and shows; it counts what is shown; it computes no rate. The URL's
// query (?coach=sleep&status=refuted) presets the filter so a coach page can link into it.
export function mount(root = document.querySelector("[data-ledger]")) {
  if (!root) return;
  const rows = [...root.querySelectorAll("[data-row]")];
  const count = root.querySelector("[data-count]");
  const coach = root.querySelector("[data-f-coach]");
  const kind = root.querySelector("[data-f-kind]");
  const text = root.querySelector("[data-f-text]");
  const statusBtns = [...root.querySelectorAll("[data-f-status]")];
  const state = { coach: "", status: "", kind: "", text: "" };
  const q = new URLSearchParams(location.search);
  for (const k of ["coach", "status", "kind"]) if (q.get(k)) state[k] = q.get(k);
  if (coach) coach.value = state.coach;
  if (kind) kind.value = state.kind;
  statusBtns.forEach((b) => b.setAttribute("aria-pressed", String((b.dataset.fStatus || "") === state.status)));

  function apply() {
    let shown = 0;
    const needle = state.text.trim().toLowerCase();
    for (const r of rows) {
      const ok =
        (!state.coach || r.dataset.coach === state.coach) &&
        (!state.status || r.dataset.status === state.status) &&
        (!state.kind || r.dataset.kind === state.kind) &&
        (!needle || (r.dataset.text || "").includes(needle));
      r.hidden = !ok;
      if (ok) shown += 1;
    }
    if (count) count.textContent = shown === rows.length ? `all ${rows.length} records` : `${shown} of ${rows.length} records shown`;
    const params = new URLSearchParams();
    for (const k of ["coach", "status", "kind"]) if (state[k]) params.set(k, state[k]);
    const qs = params.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }
  coach?.addEventListener("change", () => {
    state.coach = coach.value;
    apply();
  });
  kind?.addEventListener("change", () => {
    state.kind = kind.value;
    apply();
  });
  text?.addEventListener("input", () => {
    state.text = text.value;
    apply();
  });
  statusBtns.forEach((b) =>
    b.addEventListener("click", () => {
      state.status = b.dataset.fStatus || "";
      statusBtns.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      apply();
    }),
  );
  root.querySelectorAll("[data-needs-js]").forEach((el) => el.removeAttribute("hidden"));
  root.dataset.mounted = "true";
  apply();
  return { state, apply };
}

mount();
