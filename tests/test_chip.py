# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Chip view model: analysis and edits of pads and macros together."""

import itertools
import unittest

from tests import ROOT

import prep_ic as prep
from prep_ic.formats.lef import read_lef
from prep_ic.model.chip import (add_missing_pads, align_macros, analyse, auto_rotate, diff_partner, drop_index,
                                     move_line, optimize_pad_order, place_line, suggest_supply_pads,
                                     toggle_lock)
from prep_ic.model.floorplan import Macro, MacroDef

MACRO_DIR = ROOT / "tests" / "data" / "macros" / "adc_sar"
FIXTURE = MACRO_DIR / "final" / "lef" / "adc_sar_top.lef"


def adc(name="a0", x=400.0, y=0.0, rot=0, io=("VIN_P", "VIN_N"), cls="normal"):
    (m,) = read_lef(FIXTURE)
    return Macro(name, m.name, str(MACRO_DIR), x, y, rot, list(io), m, cls)


def box(name, x, y, w=100.0, h=100.0, cls="normal"):
    return Macro(name, cache=MacroDef(name, w, h), x=x, y=y, cls=cls)


def chip(sides=None, macros=()):
    """No PDK, fixed core 1500 × 1200: die 1740 × 1440, core area from (120, 120)."""
    p = prep.Project(sides={s: list((sides or {}).get(s, [])) for s in "TRBL"})
    p.settings.fixed_core, p.settings.square = True, False
    p.floorplan.macros = list(macros)
    return p


def set_lines(p, side, lines):
    p.set_physical_lines(side, list(lines))
    return p


class AnalyseTests(unittest.TestCase):
    def test_flylines(self):
        p = set_lines(chip(macros=[adc()]), "L", ["VIN_P", "VIN_N"])
        lay = p.layout()
        c = analyse(p, lay)
        fl = {f.pin: f for f in c.flylines}
        self.assertEqual(set(fl), {"VIN_P", "VIN_N"})
        vin_p = next(q for q in lay.pins if q.name == "VIN_P")
        self.assertEqual(fl["VIN_P"].p, (521.0, 200.0))
        self.assertEqual(fl["VIN_P"].q, (120.0, 120.0 + (vin_p.a + vin_p.b) / 2))
        self.assertAlmostEqual(fl["VIN_P"].length, ((521 - 120) ** 2 + (fl["VIN_P"].q[1] - 200) ** 2) ** 0.5)
        self.assertEqual((fl["VIN_P"].side, fl["VIN_P"].pad), ("L", "VIN_P"))
        self.assertEqual(c.missing, [])

    def test_flyline_to_group_signal_pad(self):
        p = chip(sides={"L": ["RFIN [gsg]"]}, macros=[box("lna", 0.0, 0.0)])
        p.floorplan.macros[0].cache.pins.append(prep.model.floorplan.MacroPin("RFIN", "INPUT", "SIGNAL", 0.0, 50.0))
        p.floorplan.macros[0].io = ["RFIN"]
        lay = p.layout()
        (f,) = analyse(p, lay).flylines
        rfin = next(q for q in lay.pins if q.name == "RFIN")
        self.assertEqual((f.pad, f.side, f.line, f.q), ("RFIN", "L", 0, (120.0, 120.0 + (rfin.a + rfin.b) / 2)))

    def test_crossings(self):
        p = set_lines(chip(macros=[adc()]), "L", ["VIN_N", "VIN_P"])
        c = analyse(p)
        self.assertEqual(c.crossings, 1)
        self.assertTrue(all(f.crossing for f in c.flylines))
        self.assertIn("1 flyline crossing: VIN_P/VIN_N", c.warnings)
        set_lines(p, "L", ["VIN_P", "VIN_N"])
        self.assertEqual(analyse(p).crossings, 0)
        self.assertFalse(any("crossing" in w for w in analyse(p).warnings))

    def test_several_crossings_are_listed(self):
        p = set_lines(chip(macros=[adc(io=("VIN_P", "VIN_N", "CLK"))]), "L", ["CLK", "VIN_N", "VIN_P"])
        c = analyse(p)
        self.assertEqual(c.crossings, 3)
        self.assertIn("3 flyline crossings: VIN_P/VIN_N, VIN_P/CLK, VIN_N/CLK", c.warnings)

    def test_unknown_tags_and_options(self):
        for line in ("A [foo]", "A [in] [foo]", "D [foo-bar]", "A [in", "A]", "A[3] [foo]", "A[]", "A[x]", "A[１]",
                     "A {60x}", "A {60x", "A 60x60}", "{60x60}", "A @x", "@120",
                     "A {0x0}", "A {0x10}", "A @0", "A [0mA]"):  # numbers that cannot be meant
            self.assertIn(f"Unknown tag or option in pad name: {line}",
                          analyse(set_lines(chip(), "L", [line])).warnings)

    def test_valid_lines_are_not_flagged(self):
        for line in ("A", "A[3]", "A [3]", "DOUT[3] [out] [4mA]", "RFOUT [gsg] {70x70} @125", "B [lock]", "---", "NC",
                     "=== ANA", "", "A {60x60}", "A{60x60}", "A @120", "A@120",
                     "A[12]", "D[1][2]", "x[1].y", "A[3]_B"):  # numeric indices, as a LEF pin can have
            warnings = analyse(set_lines(chip(), "L", [line])).warnings
            self.assertFalse(any("Unknown tag" in w for w in warnings), line)

    def test_split_line_needs_a_domain_name_for_rails(self):
        for line in ("=== A B [p]", "=== D2 @120", "=== A-B", "=== [foo]", "=== Ä"):
            self.assertIn(f"Power domain name with invalid characters: {line[4:]}",
                          analyse(set_lines(chip(), "L", ["X", line, "Y"])).warnings)
        for line in ("=== ANA", "=== ana", "=== 1V8", "=== A_B", "==="):
            warnings = analyse(set_lines(chip(), "L", ["X", line, "Y"])).warnings
            self.assertFalse(any("domain name" in w for w in warnings), line)

    def test_findings_join_all_sources_once(self):
        p = set_lines(chip(macros=[adc()]), "L", ["VIN_N", "VIN_P"])
        p.settings.package = "NO_SUCH_PACKAGE"
        p.load_warnings = ["No LEF found for a0", "1 flyline crossing: VIN_P/VIN_N"]
        found = prep.findings(p)
        self.assertIn("Unknown package 'NO_SUCH_PACKAGE'", found)  # layout
        self.assertIn("No LEF found for a0", found)  # reading the file
        self.assertEqual(found.count("1 flyline crossing: VIN_P/VIN_N"), 1)  # analyse, also among the above
        self.assertEqual(prep.findings(set_lines(chip(), "L", ["A"])), [])

    def test_missing_pin(self):
        p = set_lines(chip(macros=[adc(x=0.0)]), "L", ["VIN_P"])
        c = analyse(p)
        (m,) = c.missing
        self.assertEqual((m.instance, m.pin, m.name, m.side, m.function), ("a0", "VIN_N", "VIN_N", "L", "analog"))
        self.assertEqual(m.q, (120.0, 320.0))
        self.assertIn("1 checked pins without pad: VIN_N", c.warnings)

    def test_diff_partner(self):
        self.assertEqual(diff_partner("VIN_P"), "VIN_N")
        self.assertEqual(diff_partner("INN"), "INP")
        self.assertIsNone(diff_partner("CLK"))

    def test_diff_pair_warning(self):
        p = set_lines(chip(), "L", ["VIN_N", "X", "VIN_P"])
        self.assertIn("Differential pair VIN_P/VIN_N not adjacent", analyse(p).warnings)
        set_lines(p, "L", ["VIN_N", "VIN_P", "X"])
        self.assertFalse(any("Differential" in w for w in analyse(p).warnings))

    def test_sensitive_next_to_noisy(self):
        p = set_lines(chip(), "L", ["VREF", "TEST_CLK"])
        self.assertIn("Sensitive pad next to noisy pad: VREF – TEST_CLK", analyse(p).warnings)
        # a connected pad takes the class of its macro: RFIN [in] would be digital by type
        p = set_lines(chip(macros=[adc(io=["VIN_P"], cls="sensitive")]), "L", ["VIN_P [in]", "TEST_CLK"])
        self.assertIn("Sensitive pad next to noisy pad: VIN_P – TEST_CLK", analyse(p).warnings)
        p.floorplan.macros[0].cls = "normal"  # falls through to the type: digital next to clock
        self.assertFalse(any("Sensitive pad" in w for w in analyse(p).warnings))

    def test_spacer_breaks_adjacency(self):
        p = set_lines(chip(), "L", ["VREF", "", "TEST_CLK"])
        self.assertFalse(any("Sensitive pad" in w for w in analyse(p).warnings))
        set_lines(p, "L", ["VREF", "RFIN [gsg]", "TEST_CLK"])  # a shielded group breaks it too
        self.assertFalse(any("VREF – " in w for w in analyse(p).warnings))

    def test_halo_and_spacing(self):
        p = chip(macros=[box("a", 0.0, 0.0, cls="sensitive"), box("b", 130.0, 0.0, cls="noisy")])
        w = analyse(p).warnings
        self.assertIn("Halos of a and b overlap", w)
        self.assertIn("a (sensitive) closer than 100 µm to b (noisy)", w)
        p.floorplan.macros[1].x = 300.0
        w = analyse(p).warnings
        self.assertFalse(any("Halos" in x or "closer" in x for x in w))
        p.floorplan.macros[0].halo = 200.0  # per-macro halo overrides the default
        self.assertIn("Halos of a and b overlap", analyse(p).warnings)

    def test_flyline_too_long(self):
        p = set_lines(chip(macros=[adc(cls="sensitive")]), "L", ["VIN_P", "VIN_N"])
        p.settings.max_flyline = 100.0
        c = analyse(p)
        n = round(next(f.length for f in c.flylines if f.pin == "VIN_P"))
        self.assertIn(f"Flyline VIN_P {n} µm (limit 100 µm)", c.warnings)
        self.assertIn(c.longest.pin, ("VIN_P", "VIN_N"))
        p.floorplan.macros[0].cls = "normal"  # VIN_P is digital by type: no length limit
        self.assertFalse(any(w.startswith("Flyline") for w in analyse(p).warnings))

    def test_supply_by_function_and_domain(self):
        p = chip(sides={"L": ["VDDIO", "VSSIO"]}, macros=[adc(x=0.0, io=())])
        w = analyse(p).warnings
        self.assertIn("a0: no VDD pad of domain ring within 1000 µm", w)  # IO supplies do not count
        self.assertIn("a0: no VSS pad of domain ring within 1000 µm", w)
        set_lines(p, "L", ["VDDIO", "VDD", "VSS", "VSSIO"])
        self.assertFalse(any("pad of domain" in x for x in analyse(p).warnings))

    def test_supply_domains(self):
        p = chip(sides={"L": ["=== ANA", "VDD", "VSS"], "R": ["=== DIG", "VDD", "VSS"]}, macros=[adc(x=0.0, io=())])
        lay = p.layout()
        left = next(q for q in lay.pins if q.side == "L" and q.name == "VDD").domain
        right = next(q for q in lay.pins if q.side == "R" and q.name == "VDD").domain
        self.assertNotEqual(left, right)
        p.floorplan.macros[0].domain = left
        self.assertFalse(any("pad of domain" in x for x in analyse(p).warnings))
        p.floorplan.macros[0].domain = right  # its supplies are far away on the right
        self.assertIn(f"a0: no VDD pad of domain {right} within 1000 µm", analyse(p).warnings)

    def test_supply_without_splits(self):
        p = chip(sides={"T": ["VDD", "VSS"]}, macros=[box("d", 0.0, 0.0)])
        self.assertFalse(any("pad of domain" in x for x in analyse(p).warnings))

    def test_supply_suggestions(self):
        p = chip(sides={"R": ["VDDIO"]}, macros=[adc(x=0.0, io=())])
        s = analyse(p).supplies
        self.assertEqual([(x.name, x.function) for x in s], [("VDD", "vdd"), ("VSS", "vss")])  # LEF: VDD only
        p = chip(sides={"L": ["=== ANA", "X"], "R": ["=== DIG", "Y"]}, macros=[box("d", 0.0, 0.0)])
        dom = next(q for q in p.layout().pins if q.name == "X").domain
        p.floorplan.macros[0].domain = dom
        s = analyse(p).supplies
        self.assertEqual([x.name for x in s], [f"VDD_{dom}", f"VSS_{dom}"])
        self.assertEqual({x.side for x in s}, {"L"})  # next to the domain's pad X

    def test_no_macros(self):
        c = analyse(prep.Project.example())
        self.assertEqual((c.flylines, c.missing, c.crossings, c.longest, c.supplies), ([], [], 0, None, []))

    def test_drop_index(self):
        p = set_lines(chip(), "L", ["A", "", "B"])
        lay = p.layout()
        a = next(q for q in lay.pins if q.name == "A")
        b = next(q for q in lay.pins if q.name == "B")
        self.assertEqual(drop_index(lay, p, "L", 0.0), 0)
        self.assertEqual(drop_index(lay, p, "L", 120 + (a.a + a.b) / 2 + 1), 1)
        self.assertEqual(drop_index(lay, p, "L", 120 + (b.a + b.b) / 2 + 1), 3)
        self.assertEqual(drop_index(lay, p, "T", 500.0), 0)


class EditTests(unittest.TestCase):
    def test_move_within_side(self):
        p = set_lines(chip(), "L", ["A", "B", "C"])
        move_line(p, "L", 0, "L", 3)  # to_index as before the move (as drop_index gives it)
        self.assertEqual(p.physical_lines("L"), ["B", "C", "A"])
        move_line(p, "L", 2, "L", 0)
        self.assertEqual(p.physical_lines("L"), ["A", "B", "C"])

    def test_move_to_other_side(self):
        p = set_lines(set_lines(chip(), "L", ["A", "B"]), "T", ["X"])
        move_line(p, "L", 1, "T", 1)
        self.assertEqual((p.physical_lines("L"), p.physical_lines("T")), (["A"], ["X", "B"]))

    def test_move_group_line(self):
        p = set_lines(chip(), "L", ["A", "RFIN [gsg]"])
        move_line(p, "L", 1, "L", 0)
        self.assertEqual(p.physical_lines("L"), ["RFIN [gsg]", "A"])

    def test_move_split_line(self):
        p = set_lines(chip(), "L", ["=== ANA", "A"])
        move_line(p, "L", 0, "B", 0)
        self.assertEqual((p.physical_lines("L"), p.physical_lines("B")), (["A"], ["=== ANA"]))

    def test_move_keeps_spacers(self):
        p = set_lines(chip(), "L", ["A", "", "B"])
        move_line(p, "L", 2, "L", 0)
        self.assertEqual(p.physical_lines("L"), ["B", "A", ""])

    def test_move_drags_partner(self):
        p = set_lines(set_lines(chip(), "L", ["VIN_N", "X", "VIN_P"]), "T", ["Y"])
        move_line(p, "L", 0, "T", 1)  # VIN_N to the top; VIN_P follows and goes first
        self.assertEqual((p.physical_lines("L"), p.physical_lines("T")), (["X"], ["Y", "VIN_P", "VIN_N"]))

    def test_move_locked_raises(self):
        p = set_lines(chip(), "L", ["A [lock]", "B"])
        with self.assertRaises(ValueError):
            move_line(p, "L", 0, "L", 2)

    def test_toggle_lock(self):
        p = set_lines(chip(), "L", ["A [out]", "", "=== X"])
        self.assertTrue(toggle_lock(p, "L", 0))
        self.assertEqual(p.physical_lines("L")[0], "A [out] [lock]")
        self.assertFalse(toggle_lock(p, "L", 0))
        self.assertEqual(p.physical_lines("L")[0], "A [out]")
        with self.assertRaises(ValueError):
            toggle_lock(p, "L", 1)

    def test_optimize_removes_crossings(self):
        p = set_lines(chip(macros=[adc()]), "L", ["VIN_N", "VDD", "VIN_P"])
        self.assertEqual(analyse(p).crossings, 1)
        optimize_pad_order(p)
        self.assertEqual(p.physical_lines("L"), ["VIN_P", "VDD", "VIN_N"])  # VDD stays, the pair stays split
        self.assertEqual(analyse(p).crossings, 0)
        set_lines(p, "L", ["VIN_N", "VIN_P", "VDD"])
        self.assertEqual(optimize_pad_order(p), 2)
        self.assertEqual(p.physical_lines("L"), ["VIN_P", "VIN_N", "VDD"])
        set_lines(p, "L", ["VIN_N [lock]", "VIN_P", "VDD"])
        self.assertEqual(optimize_pad_order(p), 0)

    def test_optimize_joins_pairs_by_swapping(self):
        p = chip(macros=[adc(io=["VIN_P", "VIN_N", "CLK"])])
        p.floorplan.macros[0].x = 0.0
        set_lines(p, "L", ["VIN_P", "CLK", "VIN_N"])  # CLK is on the right of the macro: connects to L anyway
        optimize_pad_order(p)
        lines = p.physical_lines("L")
        self.assertEqual(abs(lines.index("VIN_P") - lines.index("VIN_N")), 1)
        self.assertLess(lines.index("VIN_P"), lines.index("VIN_N"))

    def test_add_missing_inserts_by_position(self):
        p = set_lines(chip(macros=[adc(x=0.0)]), "L", ["A", "B", "C", "D", "E", "F"])
        self.assertEqual(add_missing_pads(p), ["VIN_P", "VIN_N"])
        lines = p.physical_lines("L")
        self.assertEqual(lines[:2], ["VIN_P [analog]", "VIN_N [analog]"])  # pins are high up on the left
        self.assertEqual(add_missing_pads(p), [])

    def test_add_missing_keeps_fixed_die(self):
        p = set_lines(chip(macros=[adc(x=0.0)]), "L", ["A"])
        p.settings.fixed_core, p.settings.fixed_die = False, True
        p.settings.die_width = p.settings.die_height = 3000.0
        add_missing_pads(p)
        self.assertEqual((p.settings.fixed_die, p.settings.fixed_core), (True, False))
        p.settings.fixed_die = False  # pad-limited: switches to the core size as minimum
        p.floorplan.macros[0].io.append("CLK")
        add_missing_pads(p)
        self.assertTrue(p.settings.fixed_core)

    def test_generate_pads_alias(self):
        self.assertIs(prep.generate_pads, add_missing_pads)

    def test_suggest_supply_pads(self):
        p = chip(sides={"R": ["X"]}, macros=[adc(x=1000.0, io=()), adc("a1", x=1000.0, y=600.0, io=())])
        added = suggest_supply_pads(p)
        self.assertEqual(added, ["VDD", "VSS"])  # one pair serves both macros
        self.assertIn("VDD [vdd]", p.physical_lines("R"))
        self.assertFalse(analyse(p).supplies)

    def test_suggest_supply_pads_named_from_lef(self):
        m = box("m", 0.0, 0.0)
        m.cache.pins += [prep.model.floorplan.MacroPin("VPWR", "INOUT", "POWER"),
                         prep.model.floorplan.MacroPin("VGND", "INOUT", "GROUND")]
        p = chip(macros=[m])
        self.assertEqual(suggest_supply_pads(p), ["VPWR", "VGND"])
        lines = [l for s in "TRBL" for l in p.sides[s]]
        self.assertEqual(sorted(lines), ["VGND [vss]", "VPWR [vdd]"])
        self.assertEqual(suggest_supply_pads(p), [])

    def test_suggest_supply_pads_stops_when_nothing_helps(self):
        p = chip(sides={"L": ["X"]}, macros=[box("far", 1300.0, 1000.0)])
        p.settings.max_supply_dist = 10.0  # unreachable: one try per supply, no endless loop
        self.assertEqual(len(suggest_supply_pads(p)), 2)

    def test_auto_rotate(self):
        p = set_lines(chip(macros=[adc(x=600.0, y=0.0)]), "T", ["VIN_P", "VIN_N"])
        self.assertEqual(auto_rotate(p, "a0"), 90)  # the pins on the left edge then face up
        self.assertEqual(p.floorplan.macros[0].rot, 90)
        self.assertEqual(auto_rotate(p, "a0"), 90)  # stays

    def test_align(self):
        p = chip(macros=[box("a", 10.0, 50.0), box("b", 40.0, 20.0), box("c", 0.0, 0.0)])
        align_macros(p, ["a", "b"], "left")
        self.assertEqual([m.x for m in p.floorplan.macros], [10.0, 10.0, 0.0])
        align_macros(p, ["a", "b"], "top")
        self.assertEqual([m.y for m in p.floorplan.macros], [20.0, 20.0, 0.0])




class PlaceTests(unittest.TestCase):
    """Dropping a pad into an empty part of a side: it stays there, no other pad moves."""

    def centres(self, p):
        lay = p.layout()
        return {q.name: (q.side, round(q.cx, 3), round(q.cy, 3)) for q in lay.pins}

    def test_after_the_end(self):
        p = set_lines(set_lines(chip(), "L", ["A", "B"]), "T", ["X", "Y"])
        before = self.centres(p)
        place_line(p, "L", 0, "L", 120 + 1000.0)  # far below B
        after = self.centres(p)
        self.assertEqual(after["B"], before["B"])
        self.assertEqual((after["X"], after["Y"]), (before["X"], before["Y"]))
        self.assertLessEqual(abs(after["A"][2] - 1120.0), 40.0)  # within half a pitch of the drop
        self.assertEqual(p.physical_lines("L")[-1], "A")

    def test_before_the_start(self):
        p = set_lines(chip(), "B", ["A", "B", "C"])
        before = self.centres(p)
        place_line(p, "B", 2, "B", 120 + 100.0)
        after = self.centres(p)
        self.assertEqual((after["A"], after["B"]), (before["A"], before["B"]))
        self.assertLessEqual(abs(after["C"][1] - 220.0), 40.0)
        self.assertEqual(p.physical_lines("B")[0], "C")

    def test_from_another_side(self):
        p = set_lines(set_lines(chip(), "L", ["A", "B", "C"]), "R", ["X"])
        before = self.centres(p)
        place_line(p, "L", 1, "R", 120 + 100.0)
        after = self.centres(p)
        self.assertEqual((after["A"], after["C"], after["X"]), (before["A"], before["C"], before["X"]))
        self.assertEqual(after["B"][0], "R")
        self.assertLessEqual(abs(after["B"][2] - 220.0), 40.0)

    def test_into_a_gap(self):
        p = set_lines(set_lines(chip(), "L", ["A", "", "B"]), "T", ["X"])
        before = self.centres(p)
        lay = p.layout()
        a = next(q for q in lay.pins if q.name == "A")
        place_line(p, "T", 0, "L", 120 + a.b + 40)  # the middle of the spacer slot
        self.assertEqual(p.physical_lines("L"), ["A", "X", "B"])
        after = self.centres(p)
        self.assertEqual((after["A"], after["B"]), (before["A"], before["B"]))

    def test_into_a_gap_past_the_ring_cells(self):
        # sky130A puts two 20 um connect cells in front of the first IO supply pad, which are no lines
        def sky(lines):
            p = prep.Project(sides={"L": lines, "T": [], "R": [], "B": []})
            p.settings.pdk, p.settings.fixed_die, p.settings.die_width, p.settings.die_height = "sky130A", True, 1500, 1500
            return p
        cases = (("IOVSS", ["a", "", "b", "IOVDD", "IOVSS", "c", ""]), ("a", ["a", "c", "b", "IOVDD", "IOVSS", "", ""]))
        for (target, expect), into in itertools.product(cases, (10, 70)):  # near either end of the 80 um spacer after the target
            p = sky(["a", "", "b", "IOVDD", "IOVSS", "", "c"])
            lay = p.layout()
            self.assertEqual(len(lay.ring_cells), 2)
            before = self.centres(p)
            q = next(q for q in lay.pins if q.name == target)
            place_line(p, "L", 6, "L", lay.start("L") + q.b + into, lay)
            self.assertEqual(p.physical_lines("L"), expect, (target, into))
            after = self.centres(p)
            self.assertEqual({k: v for k, v in after.items() if k != "c"}, {k: v for k, v in before.items() if k != "c"})

    def test_into_a_gap_past_a_refused_split(self):
        # gf180mcuD refuses splits: the line stays in the editor but takes no room in the ring
        for into in (10, 70):
            p = prep.Project(sides={"L": ["a", "=== X", "", "b"], "T": [], "R": [], "B": []})
            p.settings.pdk, p.settings.fixed_die, p.settings.die_width, p.settings.die_height = "gf180mcuD", True, 1500, 1500
            lay = p.layout()
            a = next(q for q in lay.pins if q.name == "a")
            place_line(p, "L", 3, "L", lay.start("L") + a.b + into, lay)
            self.assertEqual(p.physical_lines("L"), ["a", "=== X", "b", ""], into)

    def test_inside_the_pads_reorders(self):
        p = set_lines(chip(), "L", ["A", "B", "C"])
        lay = p.layout()
        c = next(q for q in lay.pins if q.name == "C")
        place_line(p, "L", 0, "L", 120 + c.a + 1)  # onto C: as before, sorted in
        self.assertEqual(p.physical_lines("L"), ["B", "A", "C"])

    def test_start_alignment(self):
        p = set_lines(chip(), "B", ["A", "B"])
        p.settings.align = "start"
        before = self.centres(p)
        place_line(p, "B", 0, "B", 120 + 1000.0)
        after = self.centres(p)
        self.assertEqual(after["B"], before["B"])
        self.assertLessEqual(abs(after["A"][1] - 1120.0), 40.0)
        lines = p.physical_lines("B")
        self.assertEqual((lines[:2], len(lines)), (["", "B"], 13))  # nothing added at the anchored corner

    def test_near_the_corner_stays_on_the_side(self):
        p = set_lines(chip(), "L", ["A", "B", "C"])  # side space 1200 µm
        die = p.layout().die_height
        before = self.centres(p)
        place_line(p, "L", 0, "L", die - 125.0)  # just inside the corner
        after = self.centres(p)
        self.assertEqual(p.layout().die_height, die)  # no growth
        self.assertEqual((after["B"], after["C"]), (before["B"], before["C"]))
        self.assertGreater(after["A"][2], before["C"][2])

    def test_right_after_the_last_pad_sorts_in(self):
        p = set_lines(chip(), "L", ["A", "B", "C"])
        lay = p.layout()
        c = next(q for q in lay.pins if q.name == "C")
        place_line(p, "L", 0, "L", 120 + c.b + 1)
        self.assertEqual(p.physical_lines("L"), ["B", "C", "A"])

    def test_locked_raises(self):
        p = set_lines(chip(), "L", ["A [lock]", "B"])
        with self.assertRaises(ValueError):
            place_line(p, "L", 0, "L", 1100.0)

class DemoTests(unittest.TestCase):
    def test_demo_project(self):
        p = prep.load(ROOT / "examples" / "chip_demo.json")
        self.assertEqual(p.load_warnings, [])
        self.assertEqual([m.name for m in p.floorplan.macros], ["adc_sar0", "pll0", "lna0", "digital_core0"])
        c = analyse(p)
        self.assertEqual((c.crossings, [x.name for x in c.missing]), (1, ["CLK"]))  # left for the demo
        optimize_pad_order(p)
        add_missing_pads(p)
        c = analyse(p)
        self.assertEqual((c.crossings, c.missing), (0, []))
        self.assertIn("macros.yaml", prep.librelane_files(p))

if __name__ == "__main__":
    unittest.main()
