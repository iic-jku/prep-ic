# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""PDK and package profiles (data files in ``prep_ic/data``).

A PDK profile describes the IO ring of a LibreLane PDK: IO cells per function, cell and
corner size, seal ring spacing, bondpad and how a power split is made. A package profile
describes the leads per side in pin number order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DATA = Path(__file__).resolve().parent.parent / "data"

# Package sides are walked counter-clockwise (seen from the top):
# left top → bottom, bottom left → right, right bottom → top, top right → left.
CCW_ORDER = ("L", "B", "R", "T")


@dataclass(frozen=True)
class Pdk:
    name: str
    label: str
    io_library: str
    site: float                # placement grid along the edge in µm
    cell_width: float          # widest IO cell along the edge, a cell may name its own "width"
    cell_depth: float
    corner: float              # corner cell size (square)
    edge_spacing: float        # die edge to IO cells (PAD_EDGE_SPACING, seal ring)
    bondpad_w: float           # bondpad between seal ring and IO cell
    bondpad_h: float
    default_pitch: float
    core_margin: float         # IO ring to core area (core power ring)
    split_gap: float           # gap in the IO ring at a power split
    split_filler: str          # filler master with the width of split_gap
    power_pins: Dict[str, str]
    cells: Dict[str, dict]

    @property
    def ring_depth(self):
        """Die edge to the inner edge of the IO cells."""
        return self.edge_spacing + self.cell_depth

    def width_of(self, function):
        """Size along the edge of the IO cell of a function, ``cell_width`` unless the cell has its own."""
        return self.cells.get(function, {}).get("width", self.cell_width)

    def drives(self, function):
        return list(self.cells.get(function, {}).get("drives", []))

    def cell(self, function, drive=None) -> Optional[Tuple[str, Dict[str, str]]]:
        """``(master, pins)`` of the IO cell for a function, or ``None`` (no cell).

        ``pins`` maps roles (pad, in, out, oe, analog) to the pin names of the master.
        An unknown drive falls back to the default drive.
        """
        c = self.cells.get(function)
        if c is None:
            return None
        master = c["master"]
        if "{drive}" in master:
            if drive not in c["drives"]:
                drive = c["default_drive"]
            master = master.format(drive=drive)
        return master, dict(c["pins"])


@dataclass(frozen=True)
class Package:
    name: str
    label: str
    pins: int
    segments: Tuple[Tuple[str, int], ...]  # (side, leads) in pin number order, counter-clockwise
    pin1: str

    def leads(self):
        """Pin numbers per side in counter-clockwise order along that side."""
        runs = {s: [] for s in CCW_ORDER}
        no = 0
        for side, n in self.segments:
            runs[side].append(list(range(no + 1, no + n + 1)))
            no += n
        # A side with two segments (pin 1 in the middle of the top side): the numbering wraps
        # around, so the later segment comes first along the side.
        return {s: [p for run in reversed(r) for p in run] for s, r in runs.items()}


@lru_cache(maxsize=None)
def _pdks():
    out = {}
    for path in sorted((DATA / "pdks").glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        out[d["name"]] = Pdk(
            name=d["name"], label=d["label"], io_library=d["io_library"], site=d["site"],
            cell_width=d["cell_width"], cell_depth=d["cell_depth"], corner=d["corner"],
            edge_spacing=d["edge_spacing"], bondpad_w=d["bondpad"]["w"], bondpad_h=d["bondpad"]["h"],
            default_pitch=d["default_pitch"], core_margin=d["core_margin"], split_gap=d["split_gap"],
            split_filler=d["split_filler"], power_pins=d["power_pins"], cells=d["cells"])
    return out


@lru_cache(maxsize=None)
def _packages():
    d = json.loads((DATA / "packages.json").read_text(encoding="utf-8"))
    return {p["name"]: Package(p["name"], p["label"], p["pins"],
                               tuple((s, n) for s, n in p["segments"]), p["pin1"]) for p in d["packages"]}


def pdk_names() -> List[str]:
    return list(_pdks())


def get_pdk(name) -> Optional[Pdk]:
    return _pdks().get(name) if name else None


def package_names() -> List[str]:
    return list(_packages())


def get_package(name) -> Optional[Package]:
    return _packages().get(name) if name else None
