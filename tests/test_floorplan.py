# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Floorplan: LEF reading, macro placement and padframe generation."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import ROOT

import prep_ic as prep
from prep_ic.formats.lef import parse_lef, pick_macro, read_lef
from prep_ic.model.chip import add_missing_pads as generate_pads
from prep_ic.model.floorplan import (Floorplan, Macro, MacroDef, MacroPin, core_area, core_origin, find_lef,
                                          floorplan_warnings, io_signals, nearest_side,
                                          utilization)

MACRO_DIR = ROOT / "tests" / "data" / "macros" / "adc_sar"
FIXTURE = MACRO_DIR / "final" / "lef" / "adc_sar_top.lef"


class LefTests(unittest.TestCase):
    def test_size_and_pins(self):
        (m,) = read_lef(FIXTURE)
        self.assertEqual((m.name, m.w, m.h), ("adc_sar_top", 420.0, 310.0))
        pins = {p.name: p for p in m.pins}
        self.assertEqual((pins["VIN_P"].x, pins["VIN_P"].y), (1.0, 80.0))  # y flipped: 310 - 230
        self.assertEqual(pins["VIN_P"].use, "ANALOG")
        self.assertEqual(pins["VIN_P"].direction, "INPUT")
        self.assertEqual(pins["CLK"].use, "CLOCK")
        self.assertEqual(pins["EN"].direction, "OUTPUT TRISTATE")
        self.assertEqual(pins["EN"].use, "SIGNAL")
        self.assertEqual((pins["EN"].x, pins["EN"].y), (105.0, 309.0))
        self.assertEqual(pins["VDD"].use, "POWER")
        self.assertEqual((pins["NOGEO"].x, pins["NOGEO"].y), (210.0, 155.0))  # no shape: centre
        self.assertIn("DOUT[0]", pins)
        self.assertEqual(len(m.pins), 7)

    def test_origin_shifts_shapes(self):
        (m,) = parse_lef("MACRO o\n ORIGIN 10 20 ;\n SIZE 100 BY 50 ;\n PIN A\n  PORT\n   LAYER M1 ;\n"
                         "    RECT -10 -20 -8 -10 ;\n  END\n END A\nEND o\n")
        self.assertEqual((m.pins[0].x, m.pins[0].y), (1.0, 45.0))

    def test_picks_top_macro(self):
        text = "MACRO helper\n SIZE 1 BY 1 ;\nEND helper\n" + FIXTURE.read_text()
        self.assertEqual(pick_macro(parse_lef(text), "adc_sar").name, "adc_sar_top")
        self.assertEqual(pick_macro(parse_lef("MACRO x\n SIZE 1 BY 2 ;\nEND x\n"), "adc_sar").name, "x")

    def test_property_definitions_block_skipped(self):
        text = ("PROPERTYDEFINITIONS\n  MACRO CatenaDesignType STRING ;\n  PIN pinprop STRING ;\n"
                "END PROPERTYDEFINITIONS\n" + FIXTURE.read_text())
        (m,) = parse_lef(text)
        self.assertEqual((m.name, len(m.pins)), ("adc_sar_top", 7))

    def test_rect_mask_ignored(self):
        (m,) = parse_lef("MACRO o\n SIZE 100 BY 50 ;\n PIN A\n  PORT\n   LAYER M1 ;\n"
                         "    RECT MASK 2 10 10 20 20 ;\n  END\n END A\nEND o\n")
        self.assertEqual((m.pins[0].x, m.pins[0].y), (15.0, 35.0))

    def test_no_macro_raises(self):
        with self.assertRaises(ValueError):
            parse_lef("VERSION 5.8 ;\n")


def adc(name="adc_sar0", x=0.0, y=0.0, rot=0, io=()):
    (m,) = read_lef(FIXTURE)
    return Macro(name, m.name, str(MACRO_DIR), x, y, rot, list(io), m)


class FloorplanTests(unittest.TestCase):
    def test_rotation(self):
        m = adc(rot=90)
        self.assertEqual(m.size(), (310.0, 420.0))
        vin_p = next(p for p in m.cache.pins if p.name == "VIN_P")
        self.assertEqual(m.pin_xy(vin_p), (230.0, 1.0))
        m.rot = 180
        self.assertEqual(m.size(), (420.0, 310.0))
        self.assertEqual(m.pin_xy(vin_p), (419.0, 230.0))
        m.rot, m.x, m.y = 270, 100.0, 50.0
        self.assertEqual(m.pin_xy(vin_p), (100.0 + 80.0, 50.0 + 419.0))

    def test_io_pins_only_marked_signals(self):
        m = adc(io=["VIN_P", "VDD", "GONE"])
        self.assertEqual([p.name for p in m.io_pins()], ["VIN_P"])

    def test_placeholder(self):
        m = Macro("digital", cache=MacroDef("digital", 600.0, 400.0))
        self.assertTrue(m.placeholder)
        self.assertEqual(m.size(), (600.0, 400.0))
        self.assertEqual(m.io_pins(), [])

    def test_nearest_side(self):
        self.assertEqual(nearest_side(10, 500, 2000, 1000), "L")
        self.assertEqual(nearest_side(1990, 500, 2000, 1000), "R")
        self.assertEqual(nearest_side(1000, 990, 2000, 1000), "B")
        self.assertEqual(nearest_side(1000, 5, 2000, 1000), "T")
        self.assertEqual(nearest_side(500, 500, 1000, 1000), "T")  # tie: T, R, B, L

    def test_core_area(self):
        p = prep.Project(sides={"L": ["A"]})
        p.settings.fixed_core, p.settings.square = True, False
        lay = p.layout()
        self.assertEqual(core_area(lay), (120.0, 120.0, 1500.0, 1200.0))
        self.assertEqual(core_origin(lay, p.settings), (120.0, 120.0))
        p.settings.pdk = "ihp-sg13g2"
        lay = p.layout()
        m = lay.ring_depth + lay.core_margin
        self.assertEqual(core_area(lay), (m, m, lay.die_width - 2 * m, lay.die_height - 2 * m))
        self.assertGreater(lay.core_margin, 0)

    def test_overlap_and_outside_core_warning(self):
        p = prep.Project()
        p.settings.fixed_core = True  # the core fits the die, only the macro warnings remain
        p.settings.core_width, p.settings.core_height = 300.0, 300.0
        p.floorplan.macros = [adc("a0"), adc("a1", x=100.0)]
        w = floorplan_warnings(p)
        self.assertIn("Macros a0 and a1 overlap", w)
        self.assertIn("Macro a0 outside the core", w)
        p.settings.core_width, p.settings.core_height = 2000.0, 2000.0
        p.floorplan.macros[1].x = 500.0
        self.assertEqual(floorplan_warnings(p), [])

    def test_utilization(self):
        p = prep.Project()
        p.settings.fixed_core = True
        p.settings.core_width, p.settings.core_height = 1000.0, 1000.0
        p.floorplan.macros = [adc(), Macro("d", cache=MacroDef("d", 100.0, 100.0))]
        self.assertAlmostEqual(utilization(p), (420 * 310 + 100 * 100) / 1e6)

    def test_instance_names(self):
        fp = Floorplan([adc("adc_sar0")])
        self.assertEqual(fp.instance_name("adc_sar"), "adc_sar1")
        self.assertEqual(Floorplan().instance_name("pll"), "pll0")

    def test_macro_fields_round_trip(self):
        p = prep.Project()
        m = adc("a0")
        m.cls, m.halo, m.domain = "sensitive", 35.0, "ANA"
        p.floorplan.macros = [m, adc("a1")]
        d = p.to_dict()["floorplan"]["macros"]
        self.assertEqual((d[0]["class"], d[0]["halo"], d[0]["domain"]), ("sensitive", 35.0, "ANA"))
        self.assertNotIn("halo", d[1])
        self.assertEqual(prep.Project.from_dict(p.to_dict()), p)
        old = Macro.from_dict({"name": "x"})
        self.assertEqual((old.cls, old.halo, old.domain), ("normal", None, ""))
        self.assertEqual(Macro.from_dict({"name": "x", "class": "loud"}).cls, "normal")

    def test_json_round_trip(self):
        p = prep.Project.example()
        p.floorplan.macros = [adc("adc0", 10.0, 20.0, 90, ["VIN_P"]), adc("adc1", 500.0, 20.0),
                              Macro("digital", cache=MacroDef("digital", 600.0, 400.0))]
        d = p.to_dict()
        self.assertEqual(d["floorplan"]["macros"][0]["io"], ["VIN_P"])
        self.assertEqual(prep.Project.from_dict(d), p)
        self.assertNotIn("floorplan", prep.Project.example().to_dict())
        self.assertEqual(prep.Project.from_dict({"sides": {}}).floorplan, Floorplan())
        self.assertEqual(prep.Project.from_dict({"sides": {}, "floorplan": {"macros": [{"bad": 1}, 3]}}).floorplan,
                         Floorplan())


class ReloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dir = self.tmp / "macros" / "adc_sar"
        shutil.copytree(MACRO_DIR, self.dir)
        self.lef = self.dir / "final" / "lef" / "adc_sar_top.lef"

    def test_find_lef(self):
        self.assertEqual(find_lef(self.dir), self.lef)
        self.lef.rename(self.lef.with_name("other.lef"))
        self.assertEqual(find_lef(self.dir), self.lef.with_name("other.lef"))
        (self.lef.parent / "second.lef").write_text("")
        self.assertIsNone(find_lef(self.dir))
        self.assertIsNone(find_lef(self.tmp / "nothing"))

    def test_from_dir(self):
        m = Macro.from_dir(str(self.dir), "adc_sar0")
        self.assertEqual((m.name, m.macro, m.size()), ("adc_sar0", "adc_sar_top", (420.0, 310.0)))
        self.assertEqual(m.path, str(self.dir))
        with self.assertRaises(ValueError):
            Macro.from_dir(str(self.tmp), "x")

    def test_reload_drops_missing_pin(self):
        fp = Floorplan([Macro.from_dir(str(self.dir), "a0"), Macro.from_dir(str(self.dir), "a1")])
        fp.macros[0].io = ["VIN_P", "VIN_N"]
        text = self.lef.read_text()
        self.lef.write_text(text.replace("PIN VIN_N", "PIN VIN_X").replace("END VIN_N", "END VIN_X")
                            .replace("SIZE 420.000", "SIZE 500.000"))
        warnings = fp.reload()
        self.assertEqual(warnings, ["Pin VIN_N of a0 no longer in the LEF"])
        self.assertEqual(fp.macros[0].io, ["VIN_P", "VIN_N"])
        self.assertEqual([p.name for p in fp.macros[0].io_pins()], ["VIN_P"])
        self.assertEqual(fp.macros[1].size(), (500.0, 310.0))
        self.assertIs(fp.macros[0].cache, fp.macros[1].cache)  # one read per directory

    def test_reload_reports_a_marked_pin_that_became_power(self):
        fp = Floorplan([Macro.from_dir(str(self.dir), "a0")])
        fp.macros[0].io = ["VIN_P", "VIN_N"]
        before = "PIN VIN_N\n    DIRECTION INPUT ;\n    USE ANALOG ;"
        text = self.lef.read_text()
        self.assertIn(before, text)
        self.lef.write_text(text.replace(before, before.replace("USE ANALOG", "USE POWER")))
        self.assertEqual(fp.reload(), ["Pin VIN_N of a0 is a power pin in the LEF, it gets no flyline"])
        self.assertEqual(fp.macros[0].io, ["VIN_P", "VIN_N"])
        self.assertEqual([p.name for p in fp.macros[0].io_pins()], ["VIN_P"])

    def test_reload_macros_keeps_the_findings_current(self):
        p = prep.Project(sides={"L": ["A"], "T": [], "R": [], "B": []})
        p.floorplan.macros = [Macro.from_dir(str(self.dir), "a0")]
        p.load_warnings = ["No LEF found for a0, stale"]
        self.assertEqual(p.reload_macros(), [])
        self.assertFalse(any("No LEF" in f for f in prep.findings(p)))
        self.lef.unlink()
        self.assertEqual(p.reload_macros(), [f"No LEF found for a0 ({self.dir}), using last known values"])
        self.assertIn(f"No LEF found for a0 ({self.dir}), using last known values", prep.findings(p))

    def test_reload_missing_dir_keeps_cache(self):
        m = Macro.from_dir(str(self.dir), "a0")
        shutil.rmtree(self.dir)
        fp = Floorplan([m, Macro("d", cache=MacroDef("d", 1.0, 1.0))])
        self.assertEqual(fp.reload(), [f"No LEF found for a0 ({self.dir}), using last known values"])
        self.assertEqual(m.size(), (420.0, 310.0))

    def test_paths_relative_to_project_file(self):
        p = prep.Project()
        p.floorplan.macros = [Macro.from_dir(str(self.dir), "a0")]
        for target in (self.tmp / "a" / "p.json", self.tmp / "b" / "sub" / "p.json"):
            prep.save(p, target)
            stored = json.loads(target.read_text())["floorplan"]["macros"][0]["path"]
            self.assertFalse(Path(stored).is_absolute())
            q = prep.load(target)
            # load() resolves the project folder, which expands 8.3 names such as RUNNER~1 in TEMP
            self.assertEqual(Path(q.floorplan.macros[0].path), self.dir.resolve())
            self.assertEqual(q.load_warnings, [])
        self.assertEqual(p.floorplan.macros[0].path, str(self.dir))  # saving does not change the project

    def test_load_reads_lef_again(self):
        p = prep.Project()
        p.floorplan.macros = [Macro.from_dir(str(self.dir), "a0")]
        target = self.tmp / "p.json"
        prep.save(p, target)
        self.lef.write_text(self.lef.read_text().replace("SIZE 420.000", "SIZE 430.000"))
        self.assertEqual(prep.load(target).floorplan.macros[0].size(), (430.0, 310.0))

    def test_api(self):
        self.assertIs(prep.Macro, Macro)
        self.assertIs(prep.Floorplan, Floorplan)
        self.assertEqual(prep.read_lef(self.lef)[0].name, "adc_sar_top")


class GenerateTests(unittest.TestCase):
    def project(self, *macros):
        p = prep.Project()
        p.floorplan.macros = list(macros)
        return p

    def test_left_side_sorted_top_to_bottom(self):
        p = self.project(adc(io=["VIN_N", "VIN_P"]))
        self.assertEqual(generate_pads(p), ["VIN_P", "VIN_N"])
        self.assertEqual(p.physical_lines("L"), ["VIN_P [analog]", "VIN_N [analog]"])
        self.assertTrue(p.settings.fixed_core)
        self.assertFalse(p.settings.fixed_die)

    def test_functions_from_lef(self):
        p = self.project(adc(io=["VIN_P", "CLK", "DOUT[0]", "EN", "NOGEO"]))
        sig = {s["name"]: s["function"] for s in io_signals(p)}
        self.assertEqual(sig, {"VIN_P": "analog", "CLK": "in", "DOUT[0]": "out", "EN": "tri", "NOGEO": "in"})
        generate_pads(p)
        lines = [l for s in "TRBL" for l in p.sides[s]]
        self.assertIn("DOUT[0] [out]", lines)
        self.assertIn("EN [tri]", lines)

    def test_sides_follow_rotation(self):
        p = self.project(adc(rot=90, io=["VIN_P"]))  # rotated: the left edge of the macro faces up
        p.settings.fixed_core = True
        self.assertEqual(io_signals(p)[0]["side"], "T")

    def test_name_clash_between_instances(self):
        p = self.project(adc("adc0", io=["CLK"]), adc("adc1", x=800.0, io=["CLK"]))
        self.assertEqual(sorted(generate_pads(p)), ["adc0_CLK", "adc1_CLK"])

    def test_non_empty_side_inserts_by_position(self):
        p = self.project(adc(io=["VIN_N", "VIN_P"]))
        p.sides["L"] = ["VDD", "", "VSS"]
        generate_pads(p)  # the pins sit high up on the left: before the existing lines
        self.assertEqual(p.physical_lines("L"), ["VIN_P [analog]", "VIN_N [analog]", "VDD", "", "VSS"])

    def test_generate_is_idempotent(self):
        p = self.project(adc(io=["VIN_N", "VIN_P"]))
        generate_pads(p)
        before = {s: list(v) for s, v in p.sides.items()}
        self.assertEqual(generate_pads(p), [])
        self.assertEqual(p.sides, before)

    def test_stale_pin_skipped(self):
        p = self.project(adc(io=["VIN_P", "GONE"]))
        self.assertEqual(generate_pads(p), ["VIN_P"])

    def test_api(self):
        self.assertIs(prep.generate_pads, generate_pads)


if __name__ == "__main__":
    unittest.main()
