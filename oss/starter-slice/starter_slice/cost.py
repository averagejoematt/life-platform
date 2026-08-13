"""What running this costs -- read from `cost_note.json`, never typed here.

`cost_note.json` is GENERATED from the platform's published stack manifest
(https://averagejoematt.com/data/stack.json, the `cost_of_ownership` block). There
is exactly one source of truth for every dollar figure in this template, and it is
not this file. If the manifest's numbers move, the generator moves them here and a
drift test fails until it has been run.
"""

import json
import os

NOTE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cost_note.json")


def load(path: str = NOTE_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _usd_range(pair) -> str:
    return f"${pair[0]:g}-${pair[1]:g}" if isinstance(pair, list) else str(pair)


def lines(note: dict | None = None) -> list[str]:
    """The cost note as plain text, entirely derived from the loaded figures."""
    note = note or load()
    platform, slice_ = note["platform"], note["this_slice"]
    out = [
        "This slice, per month: " + (str(slice_["monthly_usd"]) if slice_["monthly_usd"] is not None else "no figure asserted"),
        "  basis: " + slice_["basis"],
        "  billed services: " + ", ".join(slice_["billed_services"]),
        "",
        "The full platform this slice is cut from, per month:",
        f"  typical run-rate     {platform['monthly_usd_typical']}",
        f"  self-imposed ceiling ${platform['ceiling_usd']:g} (floats to ${platform['surge_ceiling_usd']:g} under reader-traffic surge)",
        f"  non-AI floor         {_usd_range(platform['non_ai_floor_monthly_usd'])}",
        f"  AI, variable         {_usd_range(platform['ai_variable_monthly_usd'])}",
        "  billed actuals       " + ", ".join(f"{a['label']} ${a['usd']:.2f}" for a in platform["actuals"]),
        "",
        "  source: " + note["derived_from"],
    ]
    return out


if __name__ == "__main__":  # pragma: no cover - convenience
    print("\n".join(lines()))
