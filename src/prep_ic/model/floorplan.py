# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Floorplan: hard macros placed in the core. Pure Python, no GUI imports.

Macro coordinates are in µm with the origin at the top-left corner of the macro and y pointing
down, like the rest of the model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class MacroPin:
    """A pin of a macro as read from the LEF. ``x``/``y``: unrotated macro coordinates."""
    name: str
    direction: str = ""     # LEF DIRECTION, e.g. "INPUT", "OUTPUT TRISTATE"
    use: str = "SIGNAL"     # LEF USE: SIGNAL, POWER, GROUND, ANALOG, CLOCK
    x: float = 0.0
    y: float = 0.0


@dataclass
class MacroDef:
    """Size and pins of a macro (LEF ``MACRO``)."""
    name: str
    w: float
    h: float
    pins: List[MacroPin] = field(default_factory=list)


POWER_USES = ("POWER", "GROUND")
MACRO_CLASSES = ("normal", "sensitive", "noisy")


def _f(v, default=0.0):
    try:
        f = float(v)
    except (OverflowError, TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


@dataclass
class Macro:
    """A placed macro instance. ``x``/``y``: top-left of the placed (rotated) box in core coordinates.

    ``path`` is the macro directory (LibreLane run output); ``""`` makes a placeholder whose size is
    typed in. ``cache`` holds the last values read from the LEF. ``io`` lists the pins marked as
    off-chip signals.
    """
    name: str
    macro: str = ""
    path: str = ""
    x: float = 0.0
    y: float = 0.0
    rot: int = 0
    io: List[str] = field(default_factory=list)
    cache: Optional[MacroDef] = None
    cls: str = "normal"             # "normal", "sensitive" (analog/RF) or "noisy" (digital, clocks)
    halo: Optional[float] = None    # keep-out in µm, None = settings default
    domain: str = ""                # power domain (split name), "" = the whole ring

    @classmethod
    def from_dir(cls, path: str, name: str) -> "Macro":
        """New instance of the macro in a LibreLane run directory. Raises ``ValueError``/``OSError``."""
        lef = find_lef(path)
        if lef is None:
            raise ValueError(f"No LEF found in {Path(path) / 'final' / 'lef'}")
        mdef = _read_macro(lef, path)
        return cls(name, mdef.name, str(path), cache=mdef)

    @property
    def placeholder(self):
        return not self.path

    def size(self) -> Tuple[float, float]:
        w, h = (self.cache.w, self.cache.h) if self.cache else (0.0, 0.0)
        return (h, w) if self.rot % 180 else (w, h)

    def pin_xy(self, pin: MacroPin) -> Tuple[float, float]:
        """Core coordinates of a pin, with the rotation (90° steps clockwise) applied."""
        x, y = pin.x, pin.y
        w, h = self.cache.w, self.cache.h
        for _ in range((self.rot // 90) % 4):
            x, y = h - y, x
            w, h = h, w
        return self.x + x, self.y + y

    def signal_pins(self) -> List[MacroPin]:
        return [p for p in (self.cache.pins if self.cache else []) if p.use not in POWER_USES]

    def io_pins(self) -> List[MacroPin]:
        return [p for p in self.signal_pins() if p.name in self.io]

    def to_dict(self):
        d = {"name": self.name, "macro": self.macro, "path": self.path, "x": self.x, "y": self.y,
             "rot": self.rot, "io": list(self.io), "class": self.cls, "domain": self.domain}
        if self.halo is not None:
            d["halo"] = self.halo
        if self.cache:
            d["cache"] = {"name": self.cache.name, "w": self.cache.w, "h": self.cache.h,
                          "pins": [{"name": p.name, "dir": p.direction, "use": p.use, "x": p.x, "y": p.y}
                                   for p in self.cache.pins]}
        return d

    @classmethod
    def from_dict(cls, d):
        """Raises ``KeyError``/``TypeError``/``AttributeError`` for entries that are no macro."""
        c = d.get("cache")
        cache = None
        if isinstance(c, dict):
            pins = [MacroPin(str(p["name"]), str(p.get("dir", "")), str(p.get("use", "SIGNAL")),
                             _f(p.get("x")), _f(p.get("y"))) for p in c.get("pins", []) if isinstance(p, dict)]
            cache = MacroDef(str(c.get("name", "")), _f(c.get("w")), _f(c.get("h")), pins)
        rot = int(_f(d.get("rot"))) % 360
        halo = d.get("halo")
        return cls(str(d["name"]), str(d.get("macro", "")), str(d.get("path", "")), _f(d.get("x")),
                   _f(d.get("y")), rot - rot % 90, [str(n) for n in d.get("io", [])], cache,
                   d.get("class") if d.get("class") in MACRO_CLASSES else "normal",
                   None if halo is None else max(0.0, _f(halo)), str(d.get("domain", "")))



@dataclass
class Floorplan:
    macros: List[Macro] = field(default_factory=list)

    def reload(self) -> List[str]:
        """Read the LEF of every macro again (once per directory); returns warnings.

        A macro whose LEF cannot be read keeps its last known values. Marked pins that are no
        longer in the LEF or became power pins stay marked but are skipped.
        """
        warnings, read = [], {}
        for m in self.macros:
            if m.placeholder:
                continue
            if m.path not in read:
                lef = find_lef(m.path)
                try:
                    read[m.path] = _read_macro(lef, m.path) if lef else None
                except (OSError, ValueError):
                    read[m.path] = None
            mdef = read[m.path]
            if mdef is None:
                warnings.append(f"No LEF found for {m.name} ({m.path}), using last known values")
                continue
            m.cache, m.macro = mdef, mdef.name
            names = {p.name for p in mdef.pins}
            signals = {p.name for p in m.signal_pins()}
            warnings += [f"Pin {n} of {m.name} no longer in the LEF" for n in m.io if n not in names]
            warnings += [f"Pin {n} of {m.name} is a power pin in the LEF, it gets no flyline"
                         for n in m.io if n in names and n not in signals]
        return warnings

    def instance_name(self, macro: str) -> str:
        """First free instance name ``<macro>0``, ``<macro>1``, …"""
        names = {m.name for m in self.macros}
        k = 0
        while f"{macro}{k}" in names:
            k += 1
        return f"{macro}{k}"

    def to_dict(self):
        return {"macros": [m.to_dict() for m in self.macros]}

    @classmethod
    def from_dict(cls, d):
        return cls(_read_macros(d)[0])


def _read_macros(d):
    """The macros of a floorplan dict, and a warning for each part of it that had to be dropped."""
    if d is not None and not isinstance(d, dict):
        return [], ["The floorplan could not be read, its macros were dropped"]
    macros, warnings = [], []
    for i, m in enumerate((d or {}).get("macros", []), 1):
        try:
            macros.append(Macro.from_dict(m))
        except (KeyError, TypeError, AttributeError, ValueError):
            name = m.get("name") if isinstance(m, dict) else None
            warnings.append(f"Macro entry {i}" + (f" ({name})" if name else "") + " could not be read and was dropped")
    return macros, warnings


def dropped_entries(d) -> List[str]:
    """Warnings for what :meth:`Floorplan.from_dict` leaves out of ``d``."""
    return _read_macros(d)[1]


def find_lef(path) -> Optional[Path]:
    """``<path>/final/lef/<dirname>_top.lef``, else the only ``*.lef`` there, else ``None``."""
    d = Path(path) / "final" / "lef"
    top = d / f"{Path(path).name}_top.lef"
    if top.is_file():
        return top
    found = sorted(d.glob("*.lef")) if d.is_dir() else []
    return found[0] if len(found) == 1 else None


def _read_macro(lef, path) -> MacroDef:
    from ..formats.lef import pick_macro, read_lef  # formats imports the model
    return pick_macro(read_lef(lef), Path(path).name)


def core_area(layout) -> Tuple[float, float, float, float]:
    """``(x0, y0, w, h)`` of the core area (LibreLane CORE_AREA): die minus IO ring and core margin."""
    m = layout.ring_depth + layout.core_margin
    return m, m, layout.die_width - 2 * m, layout.die_height - 2 * m


def core_origin(layout, settings=None) -> Tuple[float, float]:
    """Die coordinates of the top-left corner of the core area (macro coordinates start here)."""
    return core_area(layout)[:2]


def nearest_side(x: float, y: float, die_w: float, die_h: float) -> str:
    """Die side closest to a point in die coordinates; ties go T, R, B, L."""
    d = {"T": y, "R": die_w - x, "B": die_h - y, "L": x}
    return min(("T", "R", "B", "L"), key=lambda s: d[s])


def _overlap(a, b):
    (aw, ah), (bw, bh) = a.size(), b.size()
    return a.x < b.x + bw and b.x < a.x + aw and a.y < b.y + bh and b.y < a.y + ah


def overlapping(macros) -> List[Tuple[Macro, Macro]]:
    """Pairs of overlapping macros."""
    return [(a, b) for i, a in enumerate(macros) for b in macros[i + 1:] if _overlap(a, b)]


def floorplan_warnings(project, layout=None) -> List[str]:
    macros = project.floorplan.macros
    if not macros:
        return []
    _, _, cw, ch = core_area(layout or project.layout())
    out = [f"Macros {a.name} and {b.name} overlap" for a, b in overlapping(macros)]
    eps = 1e-6
    for m in macros:
        w, h = m.size()
        if m.x < -eps or m.y < -eps or m.x + w > cw + eps or m.y + h > ch + eps:
            out.append(f"Macro {m.name} outside the core")
    return out


def utilization(project, layout=None) -> float:
    """Macro area / core area."""
    _, _, cw, ch = core_area(layout or project.layout())
    area = sum(w * h for w, h in (m.size() for m in project.floorplan.macros))
    return area / (cw * ch) if cw > 0 and ch > 0 else 0.0


def _function(pin: MacroPin) -> Optional[str]:
    """IO function of a pad for a macro pin, from the LEF USE and DIRECTION."""
    if pin.use == "ANALOG":
        return "analog"
    return {"INPUT": "in", "OUTPUT": "out", "OUTPUT TRISTATE": "tri", "INOUT": "inout"}.get(pin.direction)


def io_signals(project) -> List[dict]:
    """Marked macro pins with the die side they face and their position along it (physical order)."""
    layout = project.layout()
    x0, y0 = core_origin(layout, project.settings)
    pins = [(m, p) for m in project.floorplan.macros for p in m.io_pins()]
    count = {}
    for _, p in pins:
        count[p.name] = count.get(p.name, 0) + 1
    out = []
    for m, p in pins:
        px, py = m.pin_xy(p)
        x, y = x0 + px, y0 + py
        side = nearest_side(x, y, layout.die_width, layout.die_height)
        out.append({"instance": m.name, "pin": p.name,
                    "name": p.name if count[p.name] == 1 else f"{m.name}_{p.name}",
                    "side": side, "pos": x if side in "TB" else y, "function": _function(p)})
    return out
