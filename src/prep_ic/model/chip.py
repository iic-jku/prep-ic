# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Chip view: pads and macros together. Analysis (flylines, crossings, analog and power checks)
and the edits of the Chip view. Pure Python, no GUI imports.

Positions are die coordinates in µm (origin top-left, y down). Line indices are in physical
order (top/bottom left → right, left/right top → bottom), as in the side editors.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .constants import SIDES
from .floorplan import _function, _overlap, core_area, floorplan_warnings, nearest_side
from .parse import has_unknown_option, parse_line

Point = Tuple[float, float]


@dataclass
class Flyline:
    instance: str
    pin: str
    pad: str
    side: str
    line: int            # physical line index of the pad
    p: Point             # macro pin
    q: Point             # inner edge of the IO ring at the pad
    length: float
    sensitive: bool
    crossing: bool = False


@dataclass
class MissingPin:
    """A checked macro pin without a pad; ``q`` and ``pos`` where it would go."""
    instance: str
    pin: str
    name: str
    side: str
    pos: float           # along the side, die coordinates
    function: Optional[str]
    p: Point
    q: Point


@dataclass
class SupplySuggestion:
    instance: str
    name: str
    function: str        # "vdd" or "vss"
    side: str
    index: int           # insert position, physical line index


@dataclass
class ChipCheck:
    flylines: List[Flyline] = field(default_factory=list)
    missing: List[MissingPin] = field(default_factory=list)
    crossings: int = 0
    longest: Optional[Flyline] = None
    supplies: List[SupplySuggestion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def diff_partner(name: str) -> Optional[str]:
    """Name of the other half of a differential pair (final P ↔ N), or ``None``."""
    if len(name) > 1 and name[-1] in "PN":
        return name[:-1] + ("N" if name[-1] == "P" else "P")
    return None


def _inner_point(layout, side, along) -> Point:
    """Point on the inner edge of the IO ring at ``along`` (die coordinate along the side)."""
    H, W, D = layout.ring_depth, layout.die_width, layout.die_height
    return {"T": (along, H), "B": (along, D - H), "L": (H, along), "R": (W - H, along)}[side]


def _along(pin_or_split, layout) -> float:
    return layout.start(pin_or_split.side) + (pin_or_split.a + pin_or_split.b) / 2


def _pad_pins(project, layout) -> Dict[str, Tuple[str, int, object]]:
    """Pad name → (side, physical line index, layout pin); also the signal pads inside RF groups.

    The first pad of a name in ring order wins (shield grounds of groups repeat ``GND``).
    """
    out = {}
    for pin in layout.pins:
        if pin.name not in out:
            out[pin.name] = (pin.side, project.physical_line_index(pin.side, pin.line), pin)
    return out


def _pad_name_of(project) -> Dict[Tuple[str, str], str]:
    """(instance, pin) → pad name: the pin name, or ``<instance>_<pin>`` if several instances use it."""
    pins = [(m.name, p.name) for m in project.floorplan.macros for p in m.io_pins()]
    count = {}
    for _, n in pins:
        count[n] = count.get(n, 0) + 1
    return {(i, n): n if count[n] == 1 else f"{i}_{n}" for i, n in pins}


def _pins_by_line(project, layout):
    """(side, physical line index) → list of layout pins on that line."""
    out = {}
    for pin in layout.pins:
        i = project.physical_line_index(pin.side, pin.line)
        out.setdefault((pin.side, i), []).append(pin)
    return out


def drop_index(layout, project, side, along) -> int:
    """Physical insert index for a drop at ``along`` (die coordinate along ``side``), by slot centres.

    Spacer lines have no geometry in the layout; their centres are interpolated from the neighbours.
    """
    lines = project.physical_lines(side)
    by_line = _pins_by_line(project, layout)
    centres: List[Optional[float]] = []
    splits = {project.physical_line_index(sp.side, sp.line): sp for sp in layout.splits if sp.side == side}
    for i in range(len(lines)):
        pins = by_line.get((side, i))
        if pins:
            centres.append(sum(_along(p, layout) for p in pins) / len(pins))
        elif i in splits:
            centres.append(_along(splits[i], layout))
        else:
            centres.append(None)
    pitch = project.settings.sanitized().std.pitch
    for i, c in enumerate(centres):  # spacers: half way between known neighbours
        if c is None:
            prev = next((centres[j] for j in range(i - 1, -1, -1) if centres[j] is not None), None)
            nxt = next((centres[j] for j in range(i + 1, len(centres)) if centres[j] is not None), None)
            if prev is not None and nxt is not None:
                centres[i] = (prev + nxt) / 2
            elif prev is not None:
                centres[i] = prev + pitch
            elif nxt is not None:
                centres[i] = nxt - pitch
            else:
                centres[i] = layout.start(side) + pitch * (i + 0.5)
    for i, c in enumerate(centres):
        if along < c:
            return i
    return len(lines)


def _cross(a: Flyline, b: Flyline) -> bool:
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 1e-9) - (v < -1e-9)
    if {a.p, a.q} & {b.p, b.q}:
        return False
    return (orient(a.p, a.q, b.p) * orient(a.p, a.q, b.q) < 0
            and orient(b.p, b.q, a.p) * orient(b.p, b.q, a.q) < 0)


def _rect(m, grow=0.0):
    w, h = m.size()
    return m.x - grow, m.y - grow, m.x + w + grow, m.y + h + grow


def _gap(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return math.hypot(max(0.0, ax0 - bx1, bx0 - ax1), max(0.0, ay0 - by1, by0 - ay1))


def _type_class(typ):
    return "sensitive" if typ in ("ana", "rf") else "noisy" if typ in ("clk", "dig") else None


def _supply_name(m, function, domain):
    use = "POWER" if function == "vdd" else "GROUND"
    for p in (m.cache.pins if m.cache else []):
        if p.use == use:
            return p.name
    base = "VDD" if function == "vdd" else "VSS"
    return f"{base}_{domain}" if domain else base


def analyse(project, layout=None) -> ChipCheck:
    """Flylines, crossings, missing pads, analog/RF and power checks of a project."""
    layout = layout or project.layout()
    st = project.settings.sanitized()
    x0, y0, _, _ = core_area(layout)
    W, D = layout.die_width, layout.die_height
    out = ChipCheck(warnings=list(floorplan_warnings(project, layout)))
    macros = project.floorplan.macros

    by_line = _pins_by_line(project, layout)
    names = _pad_pins(project, layout)
    pad_of = _pad_name_of(project)
    pad_class = {}  # pad name -> class taken from a connected macro
    for m in macros:
        for p in m.io_pins():
            px, py = m.pin_xy(p)
            pt = (x0 + px, y0 + py)
            name = pad_of[(m.name, p.name)]
            if name in names:
                side, i, pin = names[name]
                q = _inner_point(layout, side, _along(pin, layout))
                cls = m.cls if m.cls != "normal" else _type_class(pin.type)
                if m.cls != "normal":
                    pad_class[name] = m.cls
                out.flylines.append(Flyline(m.name, p.name, name, side, i, pt, q,
                                            math.hypot(pt[0] - q[0], pt[1] - q[1]), cls == "sensitive"))
            else:
                side = nearest_side(pt[0], pt[1], W, D)
                along = pt[0] if side in "TB" else pt[1]
                out.missing.append(MissingPin(m.name, p.name, name, side, along, _function(p), pt,
                                              _inner_point(layout, side, along)))

    fl = out.flylines
    crossed = []
    for i, a in enumerate(fl):
        for b in fl[i + 1:]:
            if _cross(a, b):
                a.crossing = b.crossing = True
                out.crossings += 1
                crossed.append(f"{a.pad}/{b.pad}")
    sens = [f for f in fl if f.sensitive]
    out.longest = max(sens, key=lambda f: f.length) if sens else None

    # differential pairs and sensitive/noisy neighbours, per side in physical order
    for s in SIDES:
        lines = project.physical_lines(s)
        entries = [parse_line(l) for l in lines]
        out.warnings += [f"Unknown tag or option in pad name: {e['name']}" for e in entries
                         if e and not e["split"] and has_unknown_option(e["name"])]
        out.warnings += [f"Power domain name with invalid characters: {e['domain']}" for e in entries
                         if e and e["split"] and not re.fullmatch(r"[A-Za-z0-9_]*", e["domain"])]
        single = {e["name"]: i for i, e in enumerate(entries) if e and not e["split"] and not e["group"]}
        for n, i in single.items():
            q = diff_partner(n)
            if n.endswith("P") and q in single and abs(single[q] - i) != 1:
                out.warnings.append(f"Differential pair {n}/{q} not adjacent")
        for i in range(len(lines) - 1):
            a, b = entries[i], entries[i + 1]
            if not (a and b) or a["split"] or b["split"] or a["group"] or b["group"]:
                continue  # spacers, splits and shielded groups break the adjacency
            pa, pb = by_line.get((s, i)), by_line.get((s, i + 1))
            if not (pa and pb):
                continue
            ca = pad_class.get(a["name"]) or _type_class(pa[0].type)
            cb = pad_class.get(b["name"]) or _type_class(pb[0].type)
            if {ca, cb} == {"sensitive", "noisy"}:
                out.warnings.append(f"Sensitive pad next to noisy pad: {a['name']} – {b['name']}")

    # halos and spacing between sensitive and noisy macros
    for i, a in enumerate(macros):
        for b in macros[i + 1:]:
            ha = st.halo if a.halo is None else a.halo
            hb = st.halo if b.halo is None else b.halo
            gap = _gap(_rect(a), _rect(b))
            if not _overlap(a, b) and gap < ha + hb:  # overlapping macros get their own warning
                out.warnings.append(f"Halos of {a.name} and {b.name} overlap")
            if {a.cls, b.cls} == {"sensitive", "noisy"} and gap < st.spacing:
                s_, n_ = (a, b) if a.cls == "sensitive" else (b, a)
                out.warnings.append(f"{s_.name} (sensitive) closer than {st.spacing:g} µm to {n_.name} (noisy)")
    for f in sens:
        if f.length > st.max_flyline:
            out.warnings.append(f"Flyline {f.pin} {round(f.length)} µm (limit {st.max_flyline:g} µm)")

    # supplies: a VDD and a VSS pad (by function) of the macro's domain within reach
    splits = bool(layout.splits)
    for m in macros:
        w, h = m.size()
        cx, cy = x0 + m.x + w / 2, y0 + m.y + h / 2
        dom_pins = [q for q in layout.pins if not m.domain or not splits or q.domain == m.domain]
        for function, kind in (("vdd", "VDD"), ("vss", "VSS")):
            near = [math.hypot(*(a - b for a, b in zip(_inner_point(layout, q.side, _along(q, layout)), (cx, cy))))
                    for q in dom_pins if q.function == function]
            if near and min(near) <= st.max_supply_dist:
                continue
            dom = m.domain if splits and m.domain else "ring"
            out.warnings.append(f"{m.name}: no {kind} pad of domain {dom} within {st.max_supply_dist:g} µm")
            out.supplies.append(_suggest(project, layout, m, function, dom_pins, (cx, cy), splits))
    if crossed:
        out.warnings.append(f"{len(crossed)} flyline crossing{'s' if len(crossed) > 1 else ''}: " + ", ".join(crossed))
    if out.missing:
        out.warnings.append(f"{len(out.missing)} checked pins without pad: "
                            + ", ".join(x.name for x in out.missing))
    return out


def findings(project) -> List[str]:
    """Everything to report on a project: layout warnings, warnings from reading its files, :func:`analyse`."""
    layout = project.layout()
    return list(dict.fromkeys(layout.warnings + project.load_warnings + analyse(project, layout).warnings))


def _suggest(project, layout, m, function, dom_pins, centre, splits) -> SupplySuggestion:
    """Next to the domain pad closest to the macro, on the macro's side of it."""
    name = _supply_name(m, function, m.domain if splits else "")
    cx, cy = centre
    if dom_pins:
        q = min(dom_pins, key=lambda q: math.hypot(*(a - b for a, b in
                                                     zip(_inner_point(layout, q.side, _along(q, layout)), centre))))
        i = project.physical_line_index(q.side, q.line)
        toward = (cx if q.side in "TB" else cy) > _along(q, layout)
        return SupplySuggestion(m.name, name, function, q.side, i + 1 if toward else i)
    side = nearest_side(cx, cy, layout.die_width, layout.die_height)
    return SupplySuggestion(m.name, name, function, side,
                            drop_index(layout, project, side, cx if side in "TB" else cy))


# ---------- Edits (mutate the project; line indices in physical order) ----------

def _is_locked(line) -> bool:
    e = parse_line(line)
    return bool(e and not e["split"] and e.get("lock"))


def move_line(project, side, index, to_side, to_index) -> None:
    """Move one editor line (pad, group, split or spacer) to ``to_index`` of ``to_side``.

    ``to_index`` counts in the target side as it is before the move (what :func:`drop_index`
    returns). A single pad drags its differential partner from the same side along (P before N).
    Raises ``ValueError`` for a locked line.
    """
    src = project.physical_lines(side)
    line = src[index]
    if _is_locked(line):
        raise ValueError(f"{parse_line(line)['name']} is locked")
    e = parse_line(line)
    partner = None
    if e and not e["split"] and not e["group"]:
        q = diff_partner(e["name"])
        for j, other in enumerate(src):
            o = parse_line(other)
            if q and j != index and o and not o["split"] and not o["group"] and o["name"] == q \
                    and not _is_locked(other):
                partner = (j, other)
                break
    moved = [line]
    remove = sorted([index] + ([partner[0]] if partner else []), reverse=True)
    if partner:
        moved = [line, partner[1]] if e["name"].endswith("P") else [partner[1], line]
    dst = src if to_side == side else project.physical_lines(to_side)
    if to_side == side:
        to_index -= sum(1 for r in remove if r < to_index)
    for r in remove:
        src.pop(r)
    dst[to_index:to_index] = moved
    project.set_physical_lines(side, src)
    if to_side != side:
        project.set_physical_lines(to_side, dst)


def toggle_lock(project, side, index) -> bool:
    """Add or remove the ``[lock]`` tag of a pad line; returns the new state."""
    lines = project.physical_lines(side)
    e = parse_line(lines[index])
    if not e or e["split"]:
        raise ValueError("only pad lines can be locked")
    if e.get("lock"):
        lines[index] = re.sub(r"\s*\[lock\]", "", lines[index], flags=re.I).rstrip()
    else:
        lines[index] = lines[index].rstrip() + " [lock]"
    project.set_physical_lines(side, lines)
    return not e.get("lock")


def optimize_pad_order(project) -> int:
    """Sort the connected, unlocked pads of each side by the position of their macro pins.

    They keep the set of slots they occupy; differential pairs are joined by swapping within
    those slots only. Returns the number of lines that changed.
    """
    check = analyse(project)
    changed = 0
    for s in SIDES:
        lines = project.physical_lines(s)
        keys = {}
        for f in check.flylines:
            if f.side == s and not _is_locked(lines[f.line]) and f.line not in keys:
                keys[f.line] = f.p[0] if s in "TB" else f.p[1]
        slots = sorted(keys)
        order = sorted(slots, key=lambda i: keys[i])
        new = list(lines)
        for slot, i in zip(slots, order):
            new[slot] = lines[i]
        slotset = set(slots)
        for _ in range(len(slots)):  # join pairs by swapping within the slots, P before N
            names = {parse_line(new[i])["name"]: i for i in slots}
            todo = [(names[n], names[diff_partner(n)]) for n in names
                    if n.endswith("P") and diff_partner(n) in names and names[diff_partner(n)] != names[n] + 1]
            todo = [(i, j) for i, j in todo if j == i - 1 or i + 1 in slotset or i - 1 in slotset]
            if not todo:
                break
            i, j = todo[0]
            if j == i - 1:
                new[i], new[j] = new[j], new[i]
            elif i + 1 in slotset:
                new[i + 1], new[j] = new[j], new[i + 1]
            else:
                p_line, n_line, displaced = new[i], new[j], new[i - 1]
                new[i - 1], new[i], new[j] = p_line, n_line, displaced
        changed += sum(1 for a, b in zip(lines, new) if a != b)
        project.set_physical_lines(s, new)
    return changed


def add_missing_pads(project) -> List[str]:
    """Insert a pad line for every checked macro pin without a pad, where its flyline points.

    A pad-limited project switches to the fixed core size mode first (the die then holds the
    floorplan); a fixed die stays. Lines are inserted by position; existing lines are never changed.
    """
    if not project.settings.fixed_die:
        project.settings.fixed_core = True
    layout = project.layout()
    missing = sorted(analyse(project, layout).missing, key=lambda m: m.pos)
    added = []
    for s in SIDES:
        at = {}
        for m in missing:
            if m.side == s:
                fn = m.function
                text = f"{m.name} [{'io' if fn == 'inout' else fn}]" if fn else m.name
                at.setdefault(drop_index(layout, project, s, m.pos), []).append(text)
                added.append(m.name)
        if at:
            lines = project.physical_lines(s)
            for i in sorted(at, reverse=True):
                lines[i:i] = at[i]
            project.set_physical_lines(s, lines)
    order = {m.name: k for k, m in enumerate(missing)}
    return sorted(added, key=order.get)


def suggest_supply_pads(project) -> List[str]:
    """Add VDD/VSS pads for macros that have none of their domain within reach; returns the names.

    One pad at a time (a new pad can serve several macros); a suggestion that stays unsolved
    after its pad was added is not tried again.
    """
    added, tried = [], set()
    for _ in range(50):
        todo = [s for s in analyse(project).supplies if (s.instance, s.function) not in tried]
        if not todo:
            break
        s = todo[0]
        tried.add((s.instance, s.function))
        lines = project.physical_lines(s.side)
        lines.insert(s.index, f"{s.name} [{s.function}]")
        project.set_physical_lines(s.side, lines)
        added.append(s.name)
    return added


def _clamp_into_core(m, layout):
    _, _, cw, ch = core_area(layout)
    w, h = m.size()
    m.x = max(0.0, min(m.x, cw - w))
    m.y = max(0.0, min(m.y, ch - h))


def auto_rotate(project, instance) -> int:
    """Rotate a macro to the rotation with the shortest total flyline length; returns it."""
    m = next(x for x in project.floorplan.macros if x.name == instance)
    layout = project.layout()
    start = (m.rot, m.x, m.y)
    best = None
    for rot in [start[0]] + [r for r in (0, 90, 180, 270) if r != start[0]]:
        m.rot, m.x, m.y = rot, start[1], start[2]
        _clamp_into_core(m, layout)
        total = sum(f.length for f in analyse(project, layout).flylines if f.instance == instance)
        if best is None or total < best[0] - 1e-6:
            best = (total, rot, m.x, m.y)
    _, m.rot, m.x, m.y = best
    return m.rot


def align_macros(project, names, edge) -> None:
    """Align the named macros to the leftmost left edge or the topmost top edge."""
    ms = [m for m in project.floorplan.macros if m.name in names]
    if edge == "left":
        x = min(m.x for m in ms)
        for m in ms:
            m.x = x
    elif edge == "top":
        y = min(m.y for m in ms)
        for m in ms:
            m.y = y
    else:
        raise ValueError(f"unknown edge {edge!r}")


def _spacer_width(project) -> float:
    """Width of an empty line (one standard pitch, snapped to the PDK site like the layout does)."""
    from .pdk import get_pdk
    st = project.settings.sanitized()
    pitch, pdk = st.std.pitch, get_pdk(st.pdk)
    return max(pdk.site, round(pitch / pdk.site) * pdk.site) if pdk else pitch


def _line_widths(project, layout, side) -> List[float]:
    """Width along the side of every physical line: pads from the layout, spacers one pitch."""
    by_line = _pins_by_line(project, layout)
    splits = {project.physical_line_index(sp.side, sp.line): sp for sp in layout.splits if sp.side == side}
    P = _spacer_width(project)
    out = []
    for i in range(len(project.physical_lines(side))):
        if (side, i) in by_line:
            out.append(sum(p.b - p.a for p in by_line[(side, i)]))
        elif i in splits:
            out.append(splits[i].b - splits[i].a)
        else:
            out.append(P)
    return out


def place_line(project, side, index, to_side, along, layout=None) -> None:
    """Drop a line at ``along`` (die coordinate along ``to_side``), keeping every other pad in place.

    On an empty part of the side (before the first or after the last line) the line lands where it
    is dropped: spacer lines fill the distance, and on a centred side the same width is added at the
    other end. On a spacer slot it replaces the spacer. The line leaves spacers behind at its old
    place. Dropped onto a pad or split, it is sorted in like :func:`move_line` (nothing left behind).
    Raises ``ValueError`` for a locked line.
    """
    layout = layout or project.layout()
    src = project.physical_lines(side)
    line = src[index]
    if _is_locked(line):
        raise ValueError(f"{parse_line(line)['name']} is locked")
    P = _spacer_width(project)
    w = _line_widths(project, layout, side)[index]
    gap = [""] * max(1, round(w / P))            # what the line leaves behind
    if to_side == side:
        dst, widths = list(src), _line_widths(project, layout, side)
        dst[index:index + 1] = gap
        widths[index:index + 1] = [P] * len(gap)
    else:
        dst, widths = project.physical_lines(to_side), _line_widths(project, layout, to_side)
    E = layout.side_space[to_side]
    S = sum(widths)
    centred = project.settings.sanitized().align == "center"
    o = (E - S) / 2 if centred else (E - S if project.is_reversed(to_side) else 0.0)
    pos = along - layout.start(to_side)
    # spacers that still fit on the side (a centred side needs them twice); more would grow the die
    room = max(0, int((E - S - (2 * w if centred else w)) / ((2 if centred else 1) * P) + 1e-9))
    if o <= pos <= o + S:
        cur = o
        for j, wj in enumerate(widths):
            if cur <= pos < cur + wj:
                break
            cur += wj
        if dst[j].strip() or (to_side == side and index <= j < index + len(gap)):
            if dst[j].strip():   # on a pad or split: sort in as before
                move_line(project, side, index, to_side, drop_index(layout, project, to_side, along))
            return
        dst[j] = line           # on a spacer: take its slot
    elif pos > o + S and round((pos - (o + S) - w / 2) / P) <= 0 or pos < o and round((o - pos - w / 2) / P) <= 0:
        # right next to the first or last line: no room for a spacer, sort in
        move_line(project, side, index, to_side, drop_index(layout, project, to_side, along))
        return
    elif pos > o + S:
        k = min(room, max(0, round((pos - (o + S) - w / 2) / P)))
        dst += [""] * k + [line]
        if centred:
            dst[:0] = [""] * round((k * P + w) / P)
    else:
        k = min(room, max(0, round((o - pos - w / 2) / P)))
        dst[:0] = [line] + [""] * k
        if centred:
            dst += [""] * round((k * P + w) / P)
    if to_side != side:
        src[index:index + 1] = gap
        project.set_physical_lines(side, src)
    project.set_physical_lines(to_side, dst)
