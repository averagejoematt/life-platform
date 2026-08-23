// #3048 — extracted inline module (gear page): sticky "on this page" jump bar.
import { mountSectionToc } from "/assets/js/section_toc.js";
const w = document.querySelector(".gr-wrap");
mountSectionToc(w, { before: w.querySelector(".rd-sec") });
