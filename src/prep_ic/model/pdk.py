# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""PDK and package profiles (data files in ``prep_ic/data``).

A PDK profile describes the IO ring of a LibreLane PDK: IO cells per function, cell and
corner size, seal ring spacing, bondpad and how a power split is made. A package profile
describes the leads per side in pin number order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .constants import RAILS

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
    corner: Tuple[float, float]  # corner cell extent along x and along y in die coordinates
    edge_spacing: float        # die edge to IO cells (PAD_EDGE_SPACING, seal ring)
    bondpad_w: float           # default bond pad, a cell may name its own "bondpad"
    bondpad_h: float
    default_pitch: float
    core_margin: float         # IO ring to core area (core power ring)
    split_gap: Optional[float]   # gap in the IO ring at a power split, None: this PDK refuses splits
    split_filler: Optional[str]  # filler master with the width of split_gap
    power_pins: Dict[str, object]  # rail kind to a pin or a list of pins, a cell may name its own "power_pins"
    cells: Dict[str, dict]
    bondpad_default_shift: float = 0.0  # the bond pad of a cell may sit off its centre along the row
    ring_cells: tuple = ()     # cells the ring needs that are not pads: name, master, width, power_pins
    rails: Dict[str, str] = field(default_factory=lambda: dict(RAILS))  # net name per supply function
    bondpad_inset: Optional[float] = None  # cell's outer edge to its bond pad, None: a separate cell outside it
    ignore_disconnected: tuple = ()  # IO cells LibreLane's disconnected pin check has to skip (IGNORE_DISCONNECTED_MODULES)

    @property
    def ring_depth(self):
        """Die edge to the inner edge of the IO cells."""
        return self.edge_spacing + self.cell_depth

    def row_start(self, side):
        """Die edge to where the IO cells of a side begin: past the corner cell, which may be taller than wide."""
        return self.edge_spacing + self.corner[0 if side in "TB" else 1]

    def width_of(self, function):
        """Size along the edge of the IO cell of a function, ``cell_width`` unless the cell has its own."""
        return self.cells.get(function, {}).get("width", self.cell_width)

    def power_pins_of(self, function):
        """Rail kind → supply pins of the IO cell of a function, ``power_pins`` unless the cell has its own."""
        pins = self.cells.get(function, {}).get("power_pins", self.power_pins)
        return {rail: [p] if isinstance(p, str) else list(p) for rail, p in pins.items()}

    def bondpad_of(self, function):
        """``(w, h, inset)`` of the bond pad of a function, ``inset`` as in ``bondpad_inset``."""
        own = self.cells.get(function, {}).get("bondpad", {})
        return own.get("w", self.bondpad_w), own.get("h", self.bondpad_h), own.get("inset", self.bondpad_inset)

    def bondpad_shift(self, function):
        """Bond pad centre minus cell centre along the row, in die coordinates (x or y upward)."""
        own = self.cells.get(function, {}).get("bondpad", {})
        return own.get("shift", self.bondpad_default_shift)

    def drives(self, function):
        return list(self.cells.get(function, {}).get("drives", []))

    def cell(self, function, drive=None, variant=None) -> Optional[Tuple[str, Dict[str, str]]]:
        """``(master, pins)`` of the IO cell for a function, or ``None`` (no cell).

        ``pins`` maps roles (pad, in, out, oe, analog) to the pin names of the master.
        An unknown drive falls back to the default drive, an unknown variant to the plain cell.
        """
        c = self.cells.get(function)
        if c is None:
            return None
        master = c.get("variants", {}).get(variant, {}).get("master", c["master"])
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


def _pair(v):
    """A square size given as one number, or ``[x, y]``."""
    return (float(v), float(v)) if isinstance(v, (int, float)) else (float(v[0]), float(v[1]))


@lru_cache(maxsize=None)
def _pdks():
    out = {}
    for path in sorted((DATA / "pdks").glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        out[d["name"]] = Pdk(
            name=d["name"], label=d["label"], io_library=d["io_library"], site=d["site"],
            cell_width=d["cell_width"], cell_depth=d["cell_depth"], corner=_pair(d["corner"]),
            edge_spacing=d["edge_spacing"], bondpad_w=d["bondpad"]["w"], bondpad_h=d["bondpad"]["h"],
            default_pitch=d["default_pitch"], core_margin=d["core_margin"],
            split_gap=(d.get("split") or {}).get("gap"), split_filler=(d.get("split") or {}).get("filler"),
            power_pins=d["power_pins"], cells=d["cells"],
            bondpad_default_shift=d["bondpad"].get("shift", 0.0), ring_cells=tuple(d.get("ring_cells", ())), bondpad_inset=d["bondpad"].get("inset"), rails=d.get("rails", dict(RAILS)),
            ignore_disconnected=tuple(d.get("ignore_disconnected", ())))
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
