# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Chip view: IO ring with pads, the core with draggable macros, flylines and markers."""

import math
from dataclasses import dataclass, field
from typing import List

from ..model.chip import _inner_point
from ..model.floorplan import core_area, overlapping
from ..model.parse import classify
from .qt import (QBrush, QColor, QFont, QGraphicsItem, QGraphicsRectItem, QGraphicsSimpleTextItem, QPen,
                 QPointF, QRectF, Qt, QTimer, QTransform)
from .scene import fill_scene, make_pen, mono_family
from .widgets import RingView

MAX_GRID_LINES = 60   # per axis; a denser grid is drawn with every n-th line only
EDGE_SNAP = 15.0      # µm: a macro edge this close to another macro's edge snaps to it
LAYERS = (("grid", "Grid"), ("pads", "Pads"), ("macros", "Macros"), ("halos", "Halos"),
          ("flylines", "Flylines"), ("domains", "Power domains"), ("labels", "Pad names"))
DOMAIN_TYPES = ("gnd", "ana", "rf", "clk", "pwr")  # palette types whose outline colours the domains


def domain_colors(layout, pal):
    """Colour of each power domain (outline colours of the palette types, in ring order)."""
    return {d: pal["types"][DOMAIN_TYPES[i % len(DOMAIN_TYPES)]][1] for i, d in enumerate(layout.domains)}


def _domain_bands(scene, layout, pal, fs):
    """Wide bands inside the IO ring, one per domain section of a side, with the domain name in
    them; the power splits are drawn as cuts through ring and band."""
    colors = domain_colors(layout, pal)
    H, W, D = layout.ring_depth, layout.die_width, layout.die_height
    bh = fs * 1.15
    for s in "TRBL":
        pins = sorted((p for p in layout.pins if p.side == s), key=lambda p: p.a)
        sections = []
        for p in pins:
            if sections and sections[-1][0] == p.domain and not any(
                    sp.side == s and sections[-1][2] <= sp.a < p.a for sp in layout.splits):
                sections[-1][2] = p.b
            else:
                sections.append([p.domain, p.a, p.b])
        for dom, a, b in sections:
            if dom not in colors:
                continue
            a, b = layout.start(s) + a, layout.start(s) + b
            rect = {"T": (a, H, b - a, bh), "B": (a, D - H - bh, b - a, bh),
                    "L": (H, a, bh, b - a), "R": (W - H - bh, a, bh, b - a)}[s]
            band = scene.addRect(QRectF(*rect), make_pen(None), QBrush(QColor(colors[dom])))
            band.setOpacity(0.85)
            band.setZValue(1)
            label = text_item(scene, dom, fs * 0.8, pal["bg"], bold=True)
            k = fs * 0.8 / 100
            tw, th = label.boundingRect().width() * k, label.boundingRect().height() * k
            if tw * 1.2 > b - a:
                label.setVisible(False)  # section too short for its name
            cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
            if s in "LR":  # reads bottom to top
                label.setRotation(-90)
                label.setPos(cx - th / 2, cy + tw / 2)
            else:
                label.setPos(cx - tw / 2, cy - th / 2)
            label.setZValue(1.1)
    for sp in layout.splits:  # the cut: across the ring and the band
        a, b = layout.start(sp.side) + sp.a, layout.start(sp.side) + sp.b
        w = max(b - a, fs * 0.35)
        c = (a + b) / 2
        rect = {"T": (c - w / 2, 0, w, H + bh), "B": (c - w / 2, D - H - bh, w, H + bh),
                "L": (0, c - w / 2, H + bh, w), "R": (W - H - bh, c - w / 2, H + bh, w)}[sp.side]
        scene.addRect(QRectF(*rect), make_pen(None), QBrush(QColor(pal["warn"]))).setZValue(1.2)


def pin_type(pin):
    """Palette type of a macro pin, for its marker and flyline."""
    if pin.use == "ANALOG":
        return "ana"
    if pin.use == "CLOCK":
        return "clk"
    t = classify(pin.name)
    return t if t in ("ana", "rf", "clk") else "dig"


def text_item(parent_or_scene, text, size, color, bold=False):
    item = QGraphicsSimpleTextItem(text)
    font = QFont(mono_family())
    font.setPixelSize(100)
    font.setBold(bold)
    item.setFont(font)
    item.setBrush(QBrush(QColor(color)))
    item.setScale(size / 100.0)
    if isinstance(parent_or_scene, QGraphicsItem):
        item.setParentItem(parent_or_scene)
    else:
        parent_or_scene.addItem(item)
    return item


@dataclass
class ChipItems:
    macros: List["MacroItem"] = field(default_factory=list)
    flylines: list = field(default_factory=list)   # (Flyline, line item, length label)


class MacroItem(QGraphicsRectItem):
    """A macro instance; the item position is its top-left corner in die coordinates."""

    def __init__(self, macro, ctx):
        w, h = macro.size()
        super().__init__(0.0, 0.0, w, h)
        self.macro, self.ctx = macro, ctx
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(2)
        x0, y0 = ctx["origin"]
        self.setPos(x0 + macro.x, y0 + macro.y)  # as stored, also outside the core (warning)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

    def _snap_edges(self, x, y, w, h):
        """Snap to the edges of the other macros (after the grid); returns x, y and a guide line."""
        guide = None
        others = [m for m in self.ctx["all"] if m is not self.macro]
        for o in others:
            ow, oh = o.size()
            for mine, theirs in ((x, o.x), (x, o.x + ow), (x + w, o.x), (x + w, o.x + ow)):
                if abs(mine - theirs) < EDGE_SNAP:
                    x += theirs - mine
                    guide = ("v", theirs)
                    break
            else:
                continue
            break
        for o in others:
            ow, oh = o.size()
            for mine, theirs in ((y, o.y), (y, o.y + oh), (y + h, o.y), (y + h, o.y + oh)):
                if abs(mine - theirs) < EDGE_SNAP:
                    y += theirs - mine
                    guide = ("h", theirs)
                    break
            else:
                continue
            break
        return x, y, guide

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            x0, y0 = self.ctx["origin"]
            g, (cw, ch) = self.ctx["grid"], self.ctx["core"]
            w, h = self.macro.size()
            x = round((value.x() - x0) / g) * g
            y = round((value.y() - y0) / g) * g
            x, y, guide = self._snap_edges(x, y, w, h)
            x = min(max(x, 0.0), max(0.0, cw - w))
            y = min(max(y, 0.0), max(0.0, ch - h))
            self.ctx["guide"] = guide
            if self.ctx.get("on_guide"):
                self.ctx["on_guide"](guide)
            return QPointF(x0 + x, y0 + y)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            x0, y0 = self.ctx["origin"]
            self.macro.x, self.macro.y = round(self.pos().x() - x0, 6), round(self.pos().y() - y0, 6)
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self.ctx.get("on_select"):
                self.ctx["on_select"](self.macro)
            e.accept()
            return
        if self.ctx.get("on_press"):
            self.ctx["on_press"](self.macro)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self.ctx.get("on_guide"):
            self.ctx["on_guide"](None)
        if self.ctx.get("on_release"):
            self.ctx["on_release"](self.macro)

    def mouseDoubleClickEvent(self, e):
        if self.ctx.get("on_rotate"):  # later: rotating rebuilds the scene, which deletes this item
            QTimer.singleShot(0, lambda m=self.macro, f=self.ctx["on_rotate"]: f(m))
        e.accept()


def _inner_band(layout, pin, depth):
    H, W, D = layout.ring_depth, layout.die_width, layout.die_height
    a, b = layout.start(pin.side) + pin.a, layout.start(pin.side) + pin.b
    return {"T": (a, H - depth, b - a, depth), "B": (a, D - H, b - a, depth),
            "L": (H - depth, a, depth, b - a), "R": (W - H, a, depth, b - a)}[pin.side]


def _marker(scene, x, y, side, text, color, fs):
    scene.addEllipse(QRectF(x - fs * 0.4, y - fs * 0.4, fs * 0.8, fs * 0.8), make_pen(color, 1.2, [2, 2]),
                     QBrush(QColor("#ffffff"))).setZValue(3)
    label = text_item(scene, text, fs * 0.8, color)
    k = fs * 0.8 / 100
    br = label.boundingRect()
    dx = -br.width() * k - fs * 0.6 if side == "R" else fs * 0.6
    dy = fs * 0.3 if side == "T" else -br.height() * k - fs * 0.3
    label.setPos(x + dx, y + dy)
    label.setZValue(3)


def fill_chip(scene, project, layout, check, pal, layers, selected=(), callbacks=None):
    """Draw the chip view; returns :class:`ChipItems`. ``project.floorplan`` is edited by drags."""
    cb = callbacks or {}
    split_labels = {f"[{sp.domain}]" for sp in layout.splits}  # replaced by the labelled bands
    if "pads" in layers:
        fill_scene(scene, layout, pal, skip=lambda pr: pr["k"] == "text" and pr.get("text") in split_labels)
    else:
        scene.clear()
        scene.setBackgroundBrush(QBrush(QColor(pal["bg"])))
        m = layout.margin
        scene.setSceneRect(QRectF(-m, -m, layout.die_width + 2 * m, layout.die_height + 2 * m))
        scene.addRect(QRectF(0, 0, layout.die_width, layout.die_height), make_pen(pal["fg"], 1.5))
    if "labels" not in layers:  # pad names are the bold texts outside the die
        for it in scene.items():
            if isinstance(it, QGraphicsSimpleTextItem) and it.font().bold() and it.data(0):
                it.setVisible(False)
    st = project.settings.sanitized()
    x0, y0, cw, ch = core_area(layout)
    fs = min(st.std.pitch * 0.5, layout.ring_depth * 0.36)
    items = ChipItems()

    scene.addRect(QRectF(x0, y0, cw, ch), make_pen(pal["line"], 1.0), QBrush(QColor(pal["surface"]))).setZValue(0.4)
    if "grid" in layers and cw > 0 and ch > 0:
        step = st.grid * max(1, math.ceil(max(cw, ch) / st.grid / MAX_GRID_LINES))
        pen = make_pen(pal["line"], 0.5)
        for i in range(int(cw / step + 1e-9) + 1):
            scene.addLine(x0 + i * step, y0, x0 + i * step, y0 + ch, pen).setZValue(0.5)
        for i in range(int(ch / step + 1e-9) + 1):
            scene.addLine(x0, y0 + i * step, x0 + cw, y0 + i * step, pen).setZValue(0.5)
    core_label = text_item(scene, f"Core {cw:g} × {ch:g} µm", fs * 0.8, pal["muted"])
    core_label.setPos(x0 + fs * 0.3, y0 + fs * 0.2)
    core_label.setZValue(0.6)

    if "domains" in layers and layout.domains:
        _domain_bands(scene, layout, pal, fs)
    if "pads" in layers:  # lock symbols
        for s in "TRBL":
            for i, line in enumerate(project.physical_lines(s)):
                if "[lock]" in line.lower():
                    for pin in layout.pins:
                        if pin.side == s and project.physical_line_index(s, pin.line) == i:
                            lock = text_item(scene, "🔒", fs * 0.7, pal["fg"])
                            lock.setPos(pin.cx - fs * 0.35, pin.cy - fs * 0.4)
                            lock.setZValue(3)

    if "macros" in layers:
        bad = {m.name for pair in overlapping(project.floorplan.macros) for m in pair}
        ctx = {"origin": (x0, y0), "grid": st.grid, "core": (cw, ch), "all": project.floorplan.macros,
               "guide": None, **{k: cb.get(k) for k in ("on_press", "on_release", "on_rotate", "on_select",
                                                         "on_guide")}}
        for m in project.floorplan.macros:
            w, h = m.size()
            if "halos" in layers:
                halo = st.halo if m.halo is None else m.halo
                if halo > 0:
                    scene.addRect(QRectF(x0 + m.x - halo, y0 + m.y - halo, w + 2 * halo, h + 2 * halo),
                                  make_pen(pal["muted"], 0.8, [1, 3])).setZValue(1.5)
            item = MacroItem(m, ctx)
            edge = {"sensitive": pal["types"]["ana"][1], "noisy": pal["types"]["pwr"][1]}.get(m.cls, pal["accent"])
            sel = m.name in selected
            item.setPen(make_pen(pal["warn"] if m.name in bad else edge,
                                 3.0 if sel or m.name in bad else 1.5, [6, 4] if m.placeholder else None))
            item.setBrush(QBrush(QColor(pal["cell"] if not sel else pal["core"])))
            scene.addItem(item)
            mfs = max(fs, min(w, h) / 12)
            k = mfs / 100.0
            name = text_item(item, m.name, mfs, pal["fg"], bold=True)
            name.setPos(w / 2 - name.boundingRect().width() * k / 2, h / 2 - name.boundingRect().height() * k)
            info = f"{w:g} × {h:g} µm · {m.cls}" + (f" · {m.domain}" if m.domain else "")
            sub = text_item(item, info, mfs * 0.6, pal["muted"])
            sub.setPos(w / 2 - sub.boundingRect().width() * k * 0.6 / 2, h / 2)
            r = max(2.0, min(w, h) / 60)
            io = set(m.io)
            for p in m.signal_pins():
                px, py = m.pin_xy(p)
                fill, outline = pal["types"][pin_type(p)]
                marker = QGraphicsRectItem(px - m.x - r, py - m.y - r, 2 * r, 2 * r, item)
                marker.setPen(make_pen(outline, 1.2))
                marker.setBrush(QBrush(QColor(outline if p.name in io else fill)))
                marker.setData(2, p.name)
            items.macros.append(item)

        if "flylines" in layers:
            pins = {(m.name, p.name): p for m in project.floorplan.macros for p in m.signal_pins()}
            for f in check.flylines:
                color = pal["warn"] if f.crossing else pal["types"][pin_type(pins[(f.instance, f.pin)])][1]
                line = scene.addLine(f.p[0], f.p[1], f.q[0], f.q[1], make_pen(color, 2.0 if f.crossing else 1.3))
                line.setZValue(1.8)
                line.setData(2, f.pad)
                label = text_item(scene, f"{f.pad}: {round(f.length)} µm", fs * 0.8, pal["fg"])
                label.setPos((f.p[0] + f.q[0]) / 2 + fs * 0.3, (f.p[1] + f.q[1]) / 2 - fs)
                label.setZValue(4)
                label.setVisible(False)
                items.flylines.append((f, line, label))
            for x in check.missing:
                color = pal["types"][pin_type(pins[(x.instance, x.pin)])][1]
                scene.addLine(x.p[0], x.p[1], x.q[0], x.q[1], make_pen(color, 1.2, [4, 3])).setZValue(1.8)
                _marker(scene, x.q[0], x.q[1], x.side, f"+ {x.name}", color, fs)
    for s in check.supplies:
        m = next(mm for mm in project.floorplan.macros if mm.name == s.instance)
        w, h = m.size()
        along = (x0 + m.x + w / 2) if s.side in "TB" else (y0 + m.y + h / 2)
        q = _inner_point(layout, s.side, along)
        color = pal["types"]["pwr" if s.function == "vdd" else "gnd"][1]
        _marker(scene, q[0], q[1] + (fs * 1.6 if s.function == "vss" and s.side in "LR" else 0),
                s.side, f"+ {s.name}" + (f" ({m.domain})" if m.domain else ""), color, fs)
    return items


TAPE = "#f2c230"       # tape measure: yellow band with dark marks, readable on both palettes
TAPE_INK = "#3d3000"


def _nice_step(x):
    """Smallest 1/2/5 × 10^n not below ``x``."""
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    return next(m * e for m in (1, 2, 5, 10) if m * e >= x)


class ChipView(RingView):
    """Ring view with pad dragging (along the ring), alt-click lock, hover highlight and a measure tape."""

    def __init__(self, scene, on_click, on_hover, on_drop, on_lock):
        super().__init__(scene, on_click, on_hover)
        self.on_drop, self.on_lock = on_drop, on_lock
        self._drag = None          # (tag, press point) of a pad drag
        self.measuring = False
        self._measure = None       # (start point, items, label text)
        self.hover_key = None

    def set_measuring(self, on):
        self.measuring = on
        self._clear_measure()
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def _clear_measure(self):
        if self._measure:
            for it in self._measure[1]:
                try:
                    if it.scene():
                        self.scene().removeItem(it)
                except RuntimeError:  # already deleted with a redraw
                    pass
        self._measure = None

    def measure_text(self):
        return self._measure[2] if self._measure else ""

    def measure_line(self, a, b):
        """Draw the tape measure from scene point ``a`` to ``b`` (µm)."""
        self._clear_measure()
        sc = self.scene()
        px = 1.0 / max(self.transform().m11(), 1e-6)    # µm per screen pixel
        dx, dy = b.x() - a.x(), b.y() - a.y()
        d = math.hypot(dx, dy)
        items = []

        def add(it, z=20):
            it.setZValue(z)
            items.append(it)
            return it

        def pen(color, width_px, dash=None):
            # widths in µm (not cosmetic): Qt repaints an item inside its bounding rect, which it
            # computes in scene units; a cosmetic 13 px pen leaves traces when zoomed out
            p = QPen(QColor(color))
            p.setWidthF(width_px * px)
            p.setCapStyle(Qt.PenCapStyle.FlatCap)
            if dash:
                p.setDashPattern(dash)
            return p

        legs = pen(TAPE, 1.5, [4, 3])                     # Δx and Δy legs
        if dx and dy:  # only for a slanted tape
            add(sc.addLine(a.x(), a.y(), b.x(), a.y(), legs), 19)
            add(sc.addLine(b.x(), a.y(), b.x(), b.y(), legs), 19)
        add(sc.addLine(a.x(), a.y(), b.x(), b.y(), pen(TAPE_INK, 16)))   # band outline
        add(sc.addLine(a.x(), a.y(), b.x(), b.y(), pen(TAPE, 13)))       # band
        if d > 0:
            ux, uy = dx / d, dy / d                       # along the tape
            nx, ny = -uy, ux                              # across
            step = _nice_step(10 * px)                    # ticks at least 10 px apart
            major = step * (5 if str(step).lstrip("0.")[:1] == "2" else 10)
            ink = pen(TAPE_INK, 1.2)
            k = 0
            while k * step <= d + 1e-9:
                t = k * step
                big = abs(t / major - round(t / major)) < 1e-6
                half = (6 if big else 3) * px
                cx, cy = a.x() + ux * t, a.y() + uy * t
                add(sc.addLine(cx - nx * half, cy - ny * half, cx + nx * half, cy + ny * half, ink), 21)
                k += 1
            end = 11 * px
            for p in (a, b):
                add(sc.addLine(p.x() - nx * end, p.y() - ny * end, p.x() + nx * end, p.y() + ny * end,
                               pen(TAPE_INK, 2.5)), 21)
        text = f"{d:.1f} µm   Δx {abs(dx):.1f}  Δy {abs(dy):.1f}"
        box = QGraphicsRectItem()
        box.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        label = QGraphicsSimpleTextItem(text, box)
        font = QFont(mono_family())
        font.setPixelSize(15)
        font.setBold(True)
        label.setFont(font)
        label.setBrush(QBrush(QColor(TAPE_INK)))
        br = label.boundingRect()
        box.setRect(QRectF(-6, -4, br.width() + 12, br.height() + 8))
        box.setPen(QPen(QColor(TAPE_INK), 1.5))  # ignores transformations: pixels are fine
        box.setBrush(QBrush(QColor(TAPE)))
        box.setPos(b.x() + 14 * px, b.y() + 10 * px)
        sc.addItem(box)
        add(box, 22)
        self._measure = (a, items, text)

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        if e.button() == Qt.MouseButton.LeftButton and self.measuring:
            p = self.mapToScene(pos)
            self.measure_line(p, p)
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            tag = self._tag_at(pos)
            if tag and e.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.on_lock(tag)
                e.accept()
                return
            if tag:
                self._drag = (tag, self.mapToScene(pos))
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self.measuring and self._measure and e.buttons() & Qt.MouseButton.LeftButton:
            self.measure_line(self._measure[0], self.mapToScene(pos))
            e.accept()
            return
        if self._drag:
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
        key = None
        for it in self.items(pos):
            key = it.data(2)
            if key:
                break
        if key != self.hover_key:
            self.hover_key = key
            if key:
                self.on_hover(f"pad:{key}")
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag and e.button() == Qt.MouseButton.LeftButton:
            tag, start = self._drag
            self._drag = None
            end = self.mapToScene(e.position().toPoint())
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            moved = math.hypot(end.x() - start.x(), end.y() - start.y()) * self.transform().m11() > 6
            if moved:
                self.on_drop(tag, end.x(), end.y())
            else:
                self.on_click(tag)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.measuring:
            self.set_measuring(False)
            if hasattr(self, "on_measure_end"):
                self.on_measure_end()
            e.accept()
            return
        super().keyPressEvent(e)
