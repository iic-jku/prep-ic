# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Layout computation: pin numbering, die size, geometry and drawing primitives.

All geometry is in µm, y points down, origin at the top-left of the die.
Pin list coordinates (:attr:`Pin.x`, :attr:`Pin.y`) are the bond pad centre with the
origin at the lower-left of the die.

Without a PDK the ring is an abstract IO ring of ``cell_height``. With a PDK profile the
geometry follows the LibreLane pad ring: seal ring spacing, IO cells, corner cells and
bondpads between seal ring and IO cells; pads snap to the placement grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .constants import ORDER, POWER_FUNCTIONS, RAILS, REV, SIDE_NAMES, SIDES, TYPES
from .parse import expand, parse_line
from .pdk import CCW_ORDER, get_package, get_pdk

SPLIT_GAP = 10.0  # µm, gap of a power split without PDK


@dataclass
class Pin:
    no: int
    name: str
    type: str
    side: str
    line: int          # line index in the side's entry list
    w: float           # bond pad width along the edge
    h: float           # bond pad depth
    pitch: float
    grouped: bool      # part of an RF group
    a: float           # slot start along the side
    b: float           # slot end along the side
    cx: float          # bond pad centre, top-left origin
    cy: float
    x: float           # bond pad centre, lower-left origin (pin list)
    y: float
    function: str = "none"   # IO function, see constants.FUNCTIONS
    drive: Optional[int] = None
    cell: str = ""           # IO cell master (with a PDK)
    domain: str = ""         # power domain ("" = single domain)
    package_pin: Optional[int] = None

    @property
    def tag(self):
        """Identifies the editor line: ``"<side>:<line>"``."""
        return f"{self.side}:{self.line}"


@dataclass
class Split:
    side: str
    line: int
    domain: str        # domain that starts after the split (in numbering order)
    a: float           # gap along the side
    b: float


@dataclass
class Layout:
    pins: List[Pin]
    die_width: float
    die_height: float
    core_width: float
    core_height: float
    side_length: Dict[str, float]      # occupied length per side
    pins_per_side: Dict[str, int]
    counts: Dict[str, int]             # pins per type
    warnings: List[str]
    gutter: Dict[str, List[str]]       # pin number label per editor line
    margin: float                      # room for the pin names around the die
    prims: List[dict]                  # drawing primitives, see build_layout
    fixed_die: bool = False            # die size given by the settings, not by the pads
    core_limited: bool = False         # fixed core size mode: the core size is the minimum
    core_margin: float = 0.0           # IO ring to core area (core power ring), from the PDK
    side_space: Optional[Dict[str, float]] = None  # length available for pads per side
    ring_depth: float = 0.0            # die edge to the inner edge of the IO ring
    pdk: str = ""
    package: str = ""
    domains: List[str] = field(default_factory=list)   # power domains in numbering order
    splits: List[Split] = field(default_factory=list)
    unbonded_leads: List[int] = field(default_factory=list)

    @property
    def area_mm2(self):
        return self.die_width * self.die_height / 1e6

    def pins_on(self, side):
        return [p for p in self.pins if p.side == side]

    def rail(self, function, domain):
        """Net name of a power rail (``vdd``…) in a domain."""
        return RAILS[function] + (f"_{domain}" if domain else "")


def _snap(v, grid):
    return math.floor(v / grid + 1e-9) * grid


def _same_size(a, b):
    return all(math.isclose(x, y, abs_tol=1e-9) for x, y in zip(a, b))


def build_layout(project, selected=None):
    """Compute pins, geometry and drawing primitives for a :class:`Project`.

    ``selected`` is a pin tag (``"L:3"``) to highlight. Primitives are dicts with
    ``k`` in rect/line/circle/text; renderers map their ``style`` via
    :func:`prep_ic.style.shape_style`.
    """
    cfg = project.settings.sanitized()
    mode, align, square = cfg.mode, cfg.align, cfg.square
    warnings = []
    pdk = get_pdk(cfg.pdk)
    if cfg.pdk and pdk is None:
        warnings.append(f"Unknown PDK '{cfg.pdk}', planning without IO cells")
    if pdk:
        # the IO ring geometry comes from the PDK; pitches snap to the placement grid
        cfg.cell_height = pdk.ring_depth
        for pads in (cfg.std, cfg.rf):
            pads.w, pads.h = pdk.bondpad_w, pdk.bondpad_h
            pads.pitch = max(pdk.site, round(pads.pitch / pdk.site) * pdk.site)
    P, H = cfg.std.pitch, cfg.cell_height
    d0 = pdk.edge_spacing if pdk else 0.0       # outer edge of the IO cells
    split_gap = pdk.split_gap if pdk else SPLIT_GAP

    sides = {}
    sized = []
    for s in SIDES:
        entries = []
        for i, line in enumerate(project.sides.get(s, [])):
            e = parse_line(line)
            if e is None:
                entries.append({"line": i, "blank": True, "pads": [], "width": P, "group": None})
                continue
            if e["split"]:
                entries.append({"line": i, "blank": True, "split": e["domain"], "pads": [],
                                "width": split_gap, "group": None})
                continue
            if pdk and e["size"]:
                sized.append(e["name"])
                e["size"] = None
            if pdk and e["pitch"]:
                e["pitch"] = max(pdk.site, round(e["pitch"] / pdk.site) * pdk.site)
            pads = expand(e, cfg)
            for p in pads:
                p.update(side=s, line=i, grouped=bool(e["group"]))
            entries.append({"line": i, "blank": False, "pads": pads, "group": e["group"],
                            "width": sum(p["pitch"] for p in pads)})
        sides[s] = entries
    if sized:
        warnings.append("Custom pad size ignored with a PDK (bondpad of the PDK used) for " + ", ".join(sized))

    S = {s: sum(e["width"] for e in sides[s]) for s in SIDES}
    if cfg.fixed_die:
        dw, dh = cfg.die_width, cfg.die_height
        if pdk:
            dw, dh = _snap(dw, pdk.site), _snap(dh, pdk.site)
        # fixed die incl. IO ring; keep room for at least one pitch between the corners
        e_tb = max(P, dw - 2 * H)
        e_lr = max(P, dh - 2 * H)
        used = (e_tb + 2 * H, e_lr + 2 * H)
        if not _same_size(used, (cfg.die_width, cfg.die_height)):
            warnings.append(f"Fixed die size too small for the IO ring, using {used[0]:g} × {used[1]:g} µm"
                            if not _same_size(used, (dw, dh)) else
                            f"Fixed die size snapped to the {pdk.site:g} µm grid: {dw:g} × {dh:g} µm")
    else:
        e_tb = max(P, S["T"], S["B"])
        e_lr = max(P, S["L"], S["R"])
        if cfg.fixed_core:
            # the core (incl. the core margin of the PDK) is the minimum, the pads may need more
            m = H + (pdk.core_margin if pdk else 0.0)
            min_w, min_h = cfg.core_width + 2 * m, cfg.core_height + 2 * m
            if pdk:
                min_w, min_h = (math.ceil(v / pdk.site - 1e-9) * pdk.site for v in (min_w, min_h))
            e_tb, e_lr = max(e_tb, min_w - 2 * H), max(e_lr, min_h - 2 * H)
        if square:
            e_tb = e_lr = max(e_tb, e_lr)
    W, Hh = e_tb + 2 * H, e_lr + 2 * H
    space = {s: e_tb if s in "TB" else e_lr for s in SIDES}

    # Numbering and positions along the sides; ring_seq walks the ring in numbering order
    pins, no, ring_seq, splits = [], 0, [], []
    for s in ORDER[mode]:
        E = e_tb if s in "TB" else e_lr
        cur = (E - S[s]) / 2 if align == "center" else 0.0
        if pdk:
            cur = _snap(cur, pdk.site)
        for e in sides[s]:
            for p in e["pads"]:
                a, b = cur, cur + p["pitch"]
                if REV[mode][s]:
                    a, b = E - b, E - a
                p["a"], p["b"] = a, b
                if pdk:  # IO cell on the grid, as centred in the slot as the grid allows
                    cw = pdk.width_of(p["function"])
                    p["c"] = a + _snap((b - a - cw) / 2, pdk.site) + cw / 2
                else:
                    p["c"] = (a + b) / 2
                cur += p["pitch"]
                no += 1
                p["no"] = no
                pins.append(p)
                ring_seq.append(p)
            if e["blank"]:
                if "split" in e:
                    a, b = cur, cur + e["width"]
                    if REV[mode][s]:
                        a, b = E - b, E - a
                    sp = Split(s, e["line"], e["split"], a, b)
                    splits.append(sp)
                    ring_seq.append(sp)
                cur += e["width"]

    # Power domains: a split starts the domain named in its line; the ring is closed, so the
    # pads before the first split belong to the domain of the last split.
    domains = []
    if splits:
        for k, sp in enumerate(splits):
            if not sp.domain:
                sp.domain = f"D{k + 1}"
            if sp.domain not in domains:
                domains.append(sp.domain)
        current = splits[-1].domain
        for item in ring_seq:
            if isinstance(item, Split):
                current = item.domain
            else:
                item["domain"] = current
    else:
        domains = [""]
        for p in pins:
            p["domain"] = ""

    # IO cells
    for p in pins:
        p["cell"] = ""
        if pdk:
            c = pdk.cell(p["function"], p["drive"])
            if c:
                p["cell"] = c[0]
                if p["drive"] and not pdk.drives(p["function"]):
                    warnings.append(f"Drive strength ignored for pin {p['no']} {p['name']} ({p['function']})")
                elif p["drive"] and p["drive"] not in pdk.drives(p["function"]):
                    warnings.append(f"No {p['drive']} mA cell for pin {p['no']} {p['name']}, using {c[0]}")

    def cell_rect(s, a, b, depth0=0.0):
        if s == "T":
            return H + a, depth0, b - a, H - depth0
        if s == "B":
            return H + a, Hh - H, b - a, H - depth0
        if s == "L":
            return depth0, H + a, H - depth0, b - a
        return W - H, H + a, H - depth0, b - a

    ins = (pdk.edge_spacing - pdk.bondpad_h) if pdk else H * 0.05

    def pad_rect(p):
        c = p["c"]
        w, h, s = p["w"], p["h"], p["side"]
        if s == "T":
            return H + c - w / 2, ins, w, h
        if s == "B":
            return H + c - w / 2, Hh - ins - h, w, h
        if s == "L":
            return ins, H + c - w / 2, h, w
        return W - ins - h, H + c - w / 2, h, w

    fs = min(P * 0.5, H * 0.36)
    max_len = max([len(p["name"]) for p in pins] + [4])
    margin = max_len * fs * 0.62 + fs * 1.4
    gap = fs * 0.45

    prims = []
    add = prims.append
    add(dict(k="rect", x=0, y=0, w=W, h=Hh, style="die"))
    add(dict(k="rect", x=H, y=H, w=W - 2 * H, h=Hh - 2 * H, style="core"))
    for x, y in ((0, 0), (W - H, 0), (0, Hh - H), (W - H, Hh - H)):
        if pdk:  # corner cell inside the seal ring spacing
            x, y = (x + d0 if x == 0 else x), (y + d0 if y == 0 else y)
            add(dict(k="rect", x=x, y=y, w=H - d0, h=H - d0, style="corner"))
            add(dict(k="line", x1=x, y1=y, x2=x + H - d0, y2=y + H - d0, style="cornerline"))
        else:
            add(dict(k="rect", x=x, y=y, w=H, h=H, style="corner"))
            add(dict(k="line", x1=x, y1=y, x2=x + H, y2=y + H, style="cornerline"))
    add(dict(k="circle", cx=d0 + (H - d0) * 0.32, cy=d0 + (H - d0) * 0.32, r=(H - d0) * 0.1, style="pin1"))

    core_w, core_h = W - 2 * H, Hh - 2 * H
    cfs = max(fs, min(core_w, core_h) / 9)
    add(dict(k="text", x=W / 2, y=Hh / 2 - cfs * 0.25, text="Core", size=cfs, angle=0,
             anchor="center", color="muted", bold=True))
    add(dict(k="text", x=W / 2, y=Hh / 2 + cfs * 0.75, text=f"{core_w:g} × {core_h:g} µm",
             size=cfs * 0.5, angle=0, anchor="center", color="muted", bold=False))

    # IO cells (slots) and free sections (fillers)
    for s in SIDES:
        E = e_tb if s in "TB" else e_lr
        occ = sorted((p["a"], p["b"]) for e in sides[s] for p in e["pads"])
        for a, b in occ:
            add(dict(k="rect", **dict(zip("xywh", cell_rect(s, a, b, d0))), style="cell"))
        free, pos = [], 0.0
        for a, b in occ:
            if a - pos > 0.5:
                free.append((pos, a))
            pos = max(pos, b)
        if E - pos > 0.5:
            free.append((pos, E))
        fi = min(P, H - d0) * 0.08
        for a, b in free:
            x, y, w, h = cell_rect(s, a, b, d0)
            if w > 2 * fi and h > 2 * fi:
                add(dict(k="rect", x=x + fi, y=y + fi, w=w - 2 * fi, h=h - 2 * fi, style="free"))
    if pdk:  # the IO cells themselves inside their slots
        for p in pins:
            if p["cell"]:
                c = p["c"]
                cw = pdk.width_of(p["function"])
                x, y, w, h = cell_rect(p["side"], c - cw / 2, c + cw / 2, d0)
                add(dict(k="rect", x=x, y=y, w=w, h=h, style="iocell", tag=f"{p['side']}:{p['line']}"))

    # Power splits: gap in the IO ring and the name of the domain that follows
    for sp in splits:
        x, y, w, h = cell_rect(sp.side, sp.a, sp.b, d0)
        add(dict(k="rect", x=x, y=y, w=w, h=h, style="split", tag=f"{sp.side}:{sp.line}"))

    # Frame RF groups
    for s in SIDES:
        for e in sides[s]:
            if e["group"] and e["pads"]:
                a = min(p["a"] for p in e["pads"])
                b = max(p["b"] for p in e["pads"])
                x, y, w, h = cell_rect(s, a, b, d0)
                gi = H * 0.02
                add(dict(k="rect", x=x + gi, y=y + gi, w=w - 2 * gi, h=h - 2 * gi, style="group",
                         tag=f"{s}:{e['line']}"))

    # Bond pads, numbers, names
    for p in pins:
        s = p["side"]
        tag = f"{s}:{p['line']}"
        sel = selected == tag
        x, y, w, h = pad_rect(p)
        p["cx"], p["cy"] = x + w / 2, y + h / 2
        add(dict(k="rect", x=x, y=y, w=w, h=h, style="pad", type=p["type"], sel=sel, tag=tag))
        digits = len(str(p["no"]))
        nsize = min(fs * 0.72, w / (0.62 * digits + 0.3), h * 0.6)
        add(dict(k="text", x=p["cx"], y=p["cy"], text=str(p["no"]), size=nsize, angle=0,
                 anchor="center", color="muted", bold=False, tag=tag))
        if pdk:
            a, b = p["c"] - 0.5, p["c"] + 0.5
        else:
            a, b = p["a"], p["b"]
        x0, y0, w0, h0 = cell_rect(s, a, b)
        if s == "T":
            lx, ly, ang, anc = x0 + w0 / 2, -gap, 90, "w"
        elif s == "B":
            lx, ly, ang, anc = x0 + w0 / 2, Hh + gap, 90, "e"
        elif s == "L":
            lx, ly, ang, anc = -gap, y0 + h0 / 2, 0, "e"
        else:
            lx, ly, ang, anc = W + gap, y0 + h0 / 2, 0, "w"
        color = "accent" if sel else ("muted" if p["type"] == "nc" else "fg")
        add(dict(k="text", x=lx, y=ly, text=p["name"], size=fs, angle=ang, anchor=anc,
                 color=color, bold=True, tag=tag))

    # Domain names next to the splits, inside the core edge
    for sp in splits:
        x, y, w, h = cell_rect(sp.side, sp.a, sp.b)
        cx, cy = x + w / 2, y + h / 2
        off = H + fs * 0.6
        if sp.side == "T":
            cy, anc, ang = off, "w", 90
        elif sp.side == "B":
            cy, anc, ang = Hh - off, "e", 90
        elif sp.side == "L":
            cx, anc, ang = off, "w", 0
        else:
            cx, anc, ang = W - off, "e", 0
        add(dict(k="text", x=cx, y=cy, text=f"[{sp.domain}]", size=fs * 0.8, angle=ang, anchor=anc,
                 color="warn", bold=True, tag=f"{sp.side}:{sp.line}"))

    # Checks
    counts = {t: 0 for t in TYPES}
    for p in pins:
        counts[p["type"]] += 1
    for s in SIDES:
        if S[s] > space[s] + 1e-9:
            warnings.append(f"Pads do not fit on the {SIDE_NAMES[s].lower()} side: "
                            f"{S[s]:g} µm needed, {space[s]:g} µm available")
    seen, dup = set(), []
    for p in pins:
        if p["type"] in ("pwr", "gnd", "nc"):
            continue
        k = p["name"].upper()
        if k in seen and p["name"] not in dup:
            dup.append(p["name"])
        seen.add(k)
    if dup:
        warnings.append("Signal assigned more than once: " + ", ".join(dup))
    wide = [str(p["no"]) for p in pins if p["w"] > p["pitch"] + 1e-9]
    if wide:
        warnings.append("Pad wider than pitch (overlaps) at pin " + ", ".join(wide))
    deep = [str(p["no"]) for p in pins if p["h"] + ins > H + 1e-9]
    if deep:
        warnings.append("Pad deeper than IO cell at pin " + ", ".join(deep))
    if pdk:
        narrow = {}
        for p in pins:
            if p["cell"] and p["pitch"] < pdk.width_of(p["function"]) - 1e-9:
                narrow.setdefault(pdk.width_of(p["function"]), []).append(str(p["no"]))
        for width, nos in narrow.items():
            warnings.append(f"Pitch smaller than the IO cell ({width:g} µm) at pin " + ", ".join(nos))
        for dom in domains:
            have = {p["function"] for p in pins if p["domain"] == dom}
            missing = [RAILS[f] for f in POWER_FUNCTIONS if f not in have]
            if missing:
                where = f"Power domain {dom}" if dom else "The IO ring"
                warnings.append(f"{where} has no {'/'.join(missing)} pad")
    if len(splits) == 1:
        warnings.append("Only one power split: the IO ring is cut once and stays one domain")
    if len(set(sp.domain for sp in splits)) < len(splits):
        warnings.append("Several power splits start the same domain: the ring segments are separate "
                        "but share net names")

    # Package bonding: pads (with a bondpad) to leads, side by side in counter-clockwise order
    unbonded = []
    pkg = get_package(cfg.package)
    if cfg.package and pkg is None:
        warnings.append(f"Unknown package '{cfg.package}'")
    if pkg:
        leads = pkg.leads()
        for s in CCW_ORDER:
            pads = [p for p in pins if p["side"] == s and p["function"] != "none"]
            key = {"L": lambda p: p["cy"], "B": lambda p: p["cx"],
                   "R": lambda p: -p["cy"], "T": lambda p: -p["cx"]}[s]
            pads.sort(key=key)
            ls = leads[s]
            if len(pads) > len(ls):
                warnings.append(f"{len(pads)} pads on the {SIDE_NAMES[s].lower()} side, "
                                f"but {pkg.name} has {len(ls)} leads there")
            off = max(0, (len(ls) - len(pads)) // 2)
            used = set()
            for i, p in enumerate(pads[:len(ls)]):
                p["package_pin"] = ls[off + i]
                used.add(ls[off + i])
            unbonded += [n for n in ls if n not in used]
        unbonded.sort()

    gutter = {}
    for s in SIDES:
        lab = []
        for e in sides[s]:
            if e["blank"] or not e["pads"]:
                lab.append("===" if "split" in e else "")
            elif len(e["pads"]) == 1:
                lab.append(str(e["pads"][0]["no"]))
            else:
                nos = [p["no"] for p in e["pads"]]
                lab.append(f"{min(nos)}–{max(nos)}")
        gutter[s] = lab

    pin_objs = [Pin(no=p["no"], name=p["name"], type=p["type"], side=p["side"], line=p["line"],
                    w=p["w"], h=p["h"], pitch=p["pitch"], grouped=p["grouped"], a=p["a"], b=p["b"],
                    cx=p["cx"], cy=p["cy"], x=p["cx"], y=Hh - p["cy"], function=p["function"],
                    drive=p["drive"], cell=p["cell"], domain=p["domain"],
                    package_pin=p.get("package_pin")) for p in pins]
    per_side = {s: sum(len(e["pads"]) for e in sides[s]) for s in SIDES}
    return Layout(pins=pin_objs, die_width=W, die_height=Hh, core_width=core_w, core_height=core_h,
                  side_length=S, pins_per_side=per_side, counts=counts, warnings=warnings,
                  gutter=gutter, margin=margin, prims=prims, fixed_die=cfg.fixed_die, side_space=space,
                  core_limited=cfg.fixed_core and not cfg.fixed_die,
                  core_margin=pdk.core_margin if pdk else 0.0,
                  ring_depth=H, pdk=pdk.name if pdk else "", package=pkg.name if pkg else "",
                  domains=domains, splits=splits, unbonded_leads=unbonded)
