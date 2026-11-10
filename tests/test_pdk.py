# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
import dataclasses
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import ROOT  # noqa: F401  (sets the import path)

import prep_ic as prep
from prep_ic.model import pdk as pdk_model
from prep_ic.formats.librelane import (bondplan_yaml, chip_core_template_sv, chip_top_sv, config_yaml, librelane_files,
                                               pad_cfg_tcl)
from prep_ic.model.parse import format_entry, infer_function, parse_line


def with_cell(function, **fields):
    """While active, ``ihp-sg13g2`` reads with these fields added to one of its IO cells."""
    base = pdk_model.get_pdk("ihp-sg13g2")
    cells = {**base.cells, function: {**base.cells[function], **fields}}
    return mock.patch.object(pdk_model, "_pdks", lambda: {"ihp-sg13g2": dataclasses.replace(base, cells=cells)})


def with_profile(**fields):
    """While active, ``ihp-sg13g2`` reads with these profile fields changed."""
    base = pdk_model.get_pdk("ihp-sg13g2")
    return mock.patch.object(pdk_model, "_pdks", lambda: {"ihp-sg13g2": dataclasses.replace(base, **fields)})


def compac_like(split=False, package=""):
    """8 pads per side on a 1600 µm IHP die, as in a real tapeout (checked with LibreLane)."""
    p = prep.Project()
    st = p.settings
    st.pdk, st.package = "ihp-sg13g2", package
    st.fixed_die, st.die_width, st.die_height, st.std.pitch = True, 1600, 1600, 115
    p.sides["L"] = ["clk [in]", "rst_n [in]", "enable", "IOVDD", "IOVSS", "VDD", "VSS", "out[8] [out]"]
    p.sides["B"] = [f"out[{i}] [out]" for i in range(8)]
    p.sides["R"] = ["ain[0] [analog]", "", "ain[1] [analog]", "IOVDD", "IOVSS", "VDD", "VSS"]
    if split:
        p.sides["R"] = ["=== ANA", "ain[0] [analog]", "ain[1] [analog]", "AVDD [vdd]", "AVSS [vss]",
                        "AIOVDD [iovdd]", "AIOVSS [iovss]", "=== MAIN"]
    p.sides["T"] = [f"bidir[{i}] [io] [4mA]" for i in range(4)]
    return p


class Syntax(unittest.TestCase):
    def test_function_drive_split(self):
        e = parse_line("DOUT[3] [out] [16mA] @120")
        self.assertEqual((e["name"], e["function"], e["drive"], e["pitch"]), ("DOUT[3]", "out", 16, 120.0))
        self.assertEqual(parse_line("=== ANA"), {"split": True, "domain": "ANA"})
        self.assertEqual(parse_line("---")["name"], "---")  # old NC notation still a pad

    def test_format_round_trip(self):
        for line in ("DOUT [out] [16mA]", "RF [gsg] [analog] {60x60} @110", "X [d] [io]", "=== ANA"):
            self.assertEqual(format_entry(parse_line(line)), line)

    def test_infer_function(self):
        cases = {("VDDIO", "pwr"): "iovdd", ("VSSD", "gnd"): "vss", ("CLK_IN", "clk"): "in",
                 ("SDO", "dig"): "out", ("RST_N", "dig"): "in", ("GPIO3", "dig"): "inout",
                 ("VREF", "ana"): "analog", ("NC", "nc"): "none"}
        for (name, typ), fn in cases.items():
            self.assertEqual(infer_function(name, typ), fn, name)

    def test_function_sets_type(self):
        lay = prep.Project(sides={"L": ["AVDD [vdd]", "VDD_SENSE [analog]", "X [none]"],
                                 "T": [], "R": [], "B": []}).layout()
        self.assertEqual([p.type for p in lay.pins], ["pwr", "ana", "nc"])


class PdkGeometry(unittest.TestCase):
    def test_ring_and_cells(self):
        lay = compac_like().layout()
        self.assertEqual((lay.die_width, lay.ring_depth, lay.warnings), (1600, 320, []))
        out0 = next(p for p in lay.pins if p.name == "out[0]")
        self.assertEqual((out0.x - 40, out0.y), (357, 105))  # IO cell edge and bondpad centre
        self.assertEqual(out0.cell, "sg13g2_IOPadOut30mA")
        bidir = next(p for p in lay.pins if p.name == "bidir[0]")
        self.assertEqual(bidir.cell, "sg13g2_IOPadInOut4mA")
        for p in lay.pins:
            self.assertEqual((p.x - 40) % 1 if p.side in "TB" else (p.y - 40) % 1, 0, p.name)

    def test_pitch_too_small(self):
        p = compac_like()
        p.settings.std.pitch = 70
        self.assertTrue(any(w.startswith("Pitch smaller than the IO cell") for w in p.layout().warnings))

    def test_cell_width_per_function(self):
        with with_cell("vdd", width=75.0):
            lay = compac_like().layout()
            vdd = next(q for q in lay.pins if q.name == "VDD" and q.side == "L")
            low = vdd.y - 37.5
            self.assertEqual(low % 1, 0)  # the narrower cell stays on the site grid
            self.assertIn(f"{{IO_WEST pad_VDD_0 {low:g}}}", pad_cfg_tcl(lay))

    def test_pitch_warning_uses_the_width_of_each_cell(self):
        with with_cell("vdd", width=75.0), with_cell("vss", width=75.0):
            p = compac_like()
            p.settings.std.pitch = 78
            warnings = [w for w in p.layout().warnings if w.startswith("Pitch smaller")]
            self.assertEqual(len(warnings), 1)
            self.assertIn("(80 µm)", warnings[0])
            supply = [str(q.no) for q in p.layout().pins if q.function in ("vdd", "vss")]
            self.assertFalse(set(supply) & set(warnings[0].split(" at pin ")[1].split(", ")))

    def test_bondpad_inside_the_cell(self):
        with with_profile(bondpad_inset=2.0, bondpad_w=60.0, bondpad_h=60.0):
            lay = compac_like().layout()
            out0 = next(p for p in lay.pins if p.name == "out[0]")  # bottom side, 140 um seal ring spacing
            self.assertEqual((out0.w, out0.h, out0.y), (60.0, 60.0, 140 + 2 + 30))
            self.assertEqual(lay.warnings, [])
            self.assertNotIn("place_bondpad", pad_cfg_tcl(lay))

    def test_bondpad_of_one_cell(self):
        with with_profile(bondpad_inset=2.0, bondpad_w=60.0, bondpad_h=60.0):
            with with_cell("vdd", bondpad={"w": 54.0, "h": 67.0, "inset": 31.0}):
                lay = compac_like().layout()
                vdd = next(p for p in lay.pins if p.name == "VDD" and p.side == "L")
                self.assertEqual((vdd.w, vdd.h, vdd.x), (54.0, 67.0, 140 + 31 + 33.5))
                out = next(p for p in lay.pins if p.name == "out[8]")
                self.assertEqual((out.w, out.h), (60.0, 60.0))

    def test_separate_bondpad_stays_between_seal_ring_and_cell(self):
        lay = compac_like().layout()
        self.assertEqual(next(p for p in lay.pins if p.name == "out[0]").y, 105)
        self.assertIn("place_bondpad", pad_cfg_tcl(lay))

    def test_missing_supply(self):
        p = compac_like()
        p.sides["R"] = ["ain[0] [analog]"]
        p.sides["L"] = ["clk [in]", "VDD", "VSS"]
        self.assertIn("The IO ring has no IOVDD/IOVSS pad", p.layout().warnings)


class PowerDomains(unittest.TestCase):
    def test_domains_wrap_around(self):
        lay = compac_like(split=True).layout()
        self.assertEqual(lay.domains, ["ANA", "MAIN"])
        dom = {p.name: p.domain for p in lay.pins}
        self.assertEqual((dom["ain[0]"], dom["AVDD"], dom["clk"], dom["out[0]"], dom["bidir[3]"]),
                         ("ANA", "ANA", "MAIN", "MAIN", "MAIN"))
        self.assertEqual(lay.warnings, [])

    def test_domain_without_supply(self):
        p = compac_like(split=True)
        p.sides["R"] = ["=== ANA", "ain[0] [analog]", "=== MAIN"]
        self.assertIn("Power domain ANA has no VDD/VSS/IOVDD/IOVSS pad", p.layout().warnings)

    def test_single_split_warns(self):
        p = compac_like()
        p.sides["R"].append("=== X")
        self.assertTrue(any(w.startswith("Only one power split") for w in p.layout().warnings))


class SplitPerPdk(unittest.TestCase):
    def test_a_pdk_without_a_split_mechanism_refuses_splits(self):
        with with_profile(split_gap=None, split_filler=None):
            lay = compac_like(split=True).layout()
            self.assertEqual((lay.splits, lay.domains), ([], [""]))
            self.assertIn("Power split ANA, MAIN ignored: IHP SG13G2 has no split mechanism in its profile", lay.warnings)
            tcl = pad_cfg_tcl(lay)
            self.assertNotIn("findMaster", tcl)
            self.assertNotIn("None", tcl)
            self.assertIn("connect_by_abutment", tcl)

    def test_refused_split_keeps_the_editor_gutter_aligned(self):
        with with_profile(split_gap=None, split_filler=None):
            lay = compac_like(split=True).layout()
        self.assertEqual(len(lay.gutter["R"]), 8)

    def test_the_ihp_profiles_keep_their_split(self):
        for name in ("ihp-sg13g2", "ihp-sg13cmos5l"):
            pdk = pdk_model.get_pdk(name)
            self.assertEqual(pdk.split_gap, 10.0)
            self.assertTrue(pdk.split_filler.endswith("_Filler2000"))
        self.assertIn("findMaster", pad_cfg_tcl(compac_like(split=True).layout()))


class Packaging(unittest.TestCase):
    def test_qfn_one_to_one(self):
        p = compac_like(package="OP_QFN32_A4_FIT")
        p.sides["R"] = ["IOVDD", "IOVSS", "VDD", "VSS", "a", "b", "c", "d"]
        p.sides["T"] += ["e", "f", "g", "h"]
        lay = p.layout()
        self.assertEqual([x.package_pin for x in lay.pins], [x.no for x in lay.pins])
        self.assertEqual(lay.unbonded_leads, [])

    def test_fewer_pads_are_centred(self):
        lay = compac_like(package="OP_QFN32_A4_FIT").layout()
        top = sorted(lay.pins_on("T"), key=lambda x: -x.x)  # counter-clockwise: right to left
        self.assertEqual([x.package_pin for x in top], [27, 28, 29, 30])
        self.assertIn(25, lay.unbonded_leads)

    def test_lcc_pin1_top_centre(self):
        leads = prep.get_package("JLCC44_A4").leads()
        self.assertEqual(leads["T"], [40, 41, 42, 43, 44, 1, 2, 3, 4, 5, 6])
        self.assertEqual(leads["L"][0], 7)


class LibreLaneOutput(unittest.TestCase):
    def test_needs_pdk(self):
        with self.assertRaises(ValueError):
            librelane_files(prep.Project.example())

    def test_names_match_between_files(self):
        lay = compac_like(split=True).layout()
        cfg, sv, tcl = config_yaml(lay), chip_top_sv(lay), pad_cfg_tcl(lay)
        listed = re.findall(r'"(pad_\w+)"', cfg)
        self.assertEqual(len(listed), sum(1 for p in lay.pins if p.cell))
        instances = re.findall(r"^\s+sg13g2_\w+ (pad_\w+) \($", sv, re.M)
        self.assertEqual(sorted(listed), sorted(instances))
        placed = re.findall(r"\{IO_\w+ (pad_\w+) [\d.]+\}", tcl)
        self.assertEqual(sorted(placed), sorted(listed))
        self.assertIn("{IO_EAST", tcl.split("set prp_gaps {")[1].split("}")[0] + "}")

    def test_config_values(self):
        cfg = config_yaml(compac_like().layout())
        self.assertIn("DIE_AREA: [0, 0, 1600, 1600]", cfg)
        self.assertIn("CORE_AREA: [365, 365, 1235, 1235]", cfg)
        self.assertIn("PAD_CFG: dir::pad_cfg.tcl", cfg)
        west = cfg.split("PAD_WEST: [")[1].split("\n]")[0]
        self.assertLess(west.index("pad_out_8"), west.index("pad_clk"))  # bottom to top

    def test_several_supply_pins_per_rail(self):
        pins = {"iovdd": ["VDDIO", "VSWITCH"], "iovss": "VSSIO", "vdd": ["VCCD", "VCCHIB"], "vss": ["VSSD"]}
        with with_profile(power_pins=pins):
            sv = chip_top_sv(compac_like().layout())
        for conn in (".VDDIO(IOVDD)", ".VSWITCH(IOVDD)", ".VSSIO(IOVSS)", ".VCCD(VDD)", ".VCCHIB(VDD)", ".VSSD(VSS)"):
            self.assertIn(conn, sv)
        self.assertNotIn(".iovdd(", sv)

    def test_supply_pins_of_one_cell(self):
        with with_cell("iovdd", power_pins={"iovdd": ["DVDD"], "iovss": ["DVSS"], "vss": ["VSS"]}):
            sv = chip_top_sv(compac_like().layout())
        block = sv[sv.index("sg13g2_IOPadIOVdd"):].split(");")[0]
        self.assertIn(".DVDD(IOVDD)", block)
        self.assertNotIn(".vdd(", block)  # this cell has no pin for the core supply
        self.assertIn(".vdd(VDD)", sv)  # the others keep the PDK-wide map

    def test_tied_control_pins(self):
        ties = {"DM": "3'b110", "IN_H": None, "HLD_H_N": "@TIE_HI_ESD", "TIE_HI_ESD": "@TIE_HI_ESD"}
        with with_cell("inout", ties=ties):
            sv = chip_top_sv(compac_like().layout())
        block = sv[sv.index("sg13g2_IOPadInOut4mA pad_bidir_0 "):].split(");")[0]
        for conn in (".DM(3'b110)", ".IN_H()", ".HLD_H_N(pad_bidir_0_TIE_HI_ESD)", ".TIE_HI_ESD(pad_bidir_0_TIE_HI_ESD)",
                     ".c2p_en(bidir_c2p_en[0])"):
            self.assertIn(conn, block)
        self.assertEqual(sv.count("wire pad_bidir_0_TIE_HI_ESD;"), 1)

    def test_core_ports_do_not_change_with_ties(self):
        base = chip_core_template_sv(compac_like().layout())
        with with_cell("inout", ties={"CS": "1'b0"}):
            self.assertEqual(chip_core_template_sv(compac_like().layout()), base)

    def test_active_low_output_enable(self):
        pins = {"pad": "PAD", "in": "IN", "out": "OUT", "oe": "OE_N"}
        with with_cell("inout", pins=pins, active_low=["oe"]):
            lay = compac_like().layout()
            sv = chip_top_sv(lay)
            core = chip_core_template_sv(lay)
        self.assertIn(".OE_N(~bidir_c2p_en[0])", sv)
        self.assertIn("output logic [3:0] bidir_oe", core)  # the core port stays active high

    def test_rail_names_per_pdk(self):
        rails = {"vdd": "VDD", "vss": "VSS", "iovdd": "DVDD", "iovss": "DVSS"}
        with with_profile(rails=rails):
            lay = compac_like(package="OP_QFN32_A4_FIT").layout()
            sv = chip_top_sv(lay)
            self.assertIn("inout wire DVDD", sv)
            self.assertIn(".iovdd(DVDD)", sv)
            self.assertNotIn(".iovdd(IOVDD)", sv)
            self.assertRegex(bondplan_yaml(lay), r'\n  4:\s+"DVDD"')
            p = compac_like()
            p.sides["R"] = ["ain[0] [analog]"]
            p.sides["L"] = ["clk [in]", "VDD", "VSS"]
            self.assertIn("The IO ring has no DVDD/DVSS pad", p.layout().warnings)

    def test_two_functions_on_one_master(self):
        with with_cell("vdd", master="sg13g2_IOPadIOVdd"):
            lay = compac_like().layout()
        self.assertEqual({q.cell for q in lay.pins if q.function in ("vdd", "iovdd")}, {"sg13g2_IOPadIOVdd"})
        self.assertEqual(lay.warnings, [])

    def test_chip_top_ports(self):
        sv = chip_top_sv(compac_like(split=True).layout())
        for decl in ("inout wire [8:0] out_PAD", "inout wire [1:0] ain_PAD", "inout wire VDD_ANA",
                     ".bidir_oe(bidir_c2p_en)", ".padres(ain_padres[1])"):
            self.assertIn(decl, sv)

    def test_bondplan(self):
        text = bondplan_yaml(compac_like(package="OP_QFN32_A4_FIT").layout())
        self.assertIn("PACKAGE_NAME: OP_QFN32_A4_FIT", text)
        self.assertRegex(text, r'\n  1:\s+"clk_PAD"')
        self.assertRegex(text, r'\n  4:\s+"IOVDD"')
        self.assertRegex(text, r'\n  25:\s+~\s+# not bonded')
        self.assertNotIn('"~"', text)  # the string "~" would be taken for a pad name


class MacroExport(unittest.TestCase):
    def project(self):
        import os
        from prep_ic.formats.lef import read_lef
        from prep_ic.model.floorplan import Macro, MacroDef
        d = ROOT / "tests" / "data" / "macros" / "adc_sar"
        (m,) = read_lef(d / "final" / "lef" / "adc_sar_top.lef")
        p = compac_like()
        p.floorplan.macros = [Macro("adc0", m.name, str(d), 40.0, 20.0, 90, [], m),
                              Macro("dig", cache=MacroDef("dig", 100.0, 100.0))]
        return p

    def test_macros_yaml(self):
        from prep_ic.formats.librelane import macros_yaml
        from prep_ic.model.floorplan import core_area
        p = self.project()
        lay = p.layout()
        x0, y0, _, _ = core_area(lay)
        text = macros_yaml(p, lay, out_dir=ROOT / "flow")
        self.assertIn("MACROS:\n  adc_sar_top:\n", text)
        self.assertIn('    gds: ["dir::../tests/data/macros/adc_sar/final/gds/adc_sar_top.gds"]\n', text)
        self.assertIn('    lef: ["dir::../tests/data/macros/adc_sar/final/lef/adc_sar_top.lef"]\n', text)
        self.assertIn(f"      i_chip_core.adc0:\n        location: [{x0 + 40:g}, {lay.die_height - (y0 + 20 + 420):g}]\n"
                      "        orientation: E\n", text)
        self.assertIn("# placeholder dig (no LEF) not exported", text)
        for view in ("vh:", "nl:", "pnl:", "lib:", "spef:"):  # the fixture holds a LEF only
            self.assertNotIn(f"    {view}", text)
        self.assertIn("    # no vh, pnl or nl in LibreLane's layout below final/, so lint stops with MODMISSING\n", text)

    def test_macros_yaml_paths_without_out_dir_are_absolute(self):
        from prep_ic.formats.librelane import macros_yaml
        p = self.project()
        d = (ROOT / "tests" / "data" / "macros" / "adc_sar").resolve().as_posix()
        for text in (macros_yaml(p, p.layout()), librelane_files(p)["macros.yaml"]):  # the GUI's preview
            self.assertIn(f'    gds: ["{d}/final/gds/adc_sar_top.gds"]\n', text)
            self.assertNotIn("dir::", text)
        p.floorplan.macros[0].path = "some/relative/dir"  # as a script can set it
        self.assertIn(f'    gds: ["{Path.cwd().resolve().as_posix()}/some/relative/dir/final/gds/adc_sar_top.gds"]\n',
                      macros_yaml(p, p.layout()))

    def test_macros_yaml_paths_on_another_drive_are_absolute(self):
        from unittest import mock
        from prep_ic.formats.librelane import macros_yaml
        p = self.project()
        with mock.patch("prep_ic.formats.librelane.os.path.relpath", side_effect=ValueError("other drive")):
            text = macros_yaml(p, p.layout(), out_dir=ROOT / "flow")
        self.assertIn("/tests/data/macros/adc_sar/final/gds/adc_sar_top.gds", text)
        self.assertNotIn("dir::", text)

    def run_dir_yaml(self, views, directory="m", instances=("m0",)):
        """macros.yaml of a macro ``m`` in a run directory that holds these files below ``final/``, or folders for ``x/``."""
        from prep_ic.formats.librelane import macros_yaml
        from prep_ic.model.floorplan import Macro, MacroDef
        with tempfile.TemporaryDirectory() as d:
            for view in views:
                path = Path(d, directory, "final", view)
                if view.endswith("/"):
                    path.mkdir(parents=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
            p = compac_like()
            p.floorplan.macros = [Macro(i, "m", str(Path(d, directory)), 40.0, 20.0, 0, [], MacroDef("m", 100.0, 100.0))
                                  for i in instances]
            return macros_yaml(p, p.layout(), out_dir=d)

    def test_macros_yaml_quotes_paths(self):
        for directory in ("br[ack]et", "cu{r}ly", "com,ma", "ha #sh", "smile😀"):  # none survive a plain YAML scalar
            text = self.run_dir_yaml(["vh/m.vh", "lib/nom/m__nom.lib"], directory)
            self.assertIn(f'    gds: ["dir::{directory}/final/gds/m.gds"]\n', text)
            self.assertIn(f'    vh: ["dir::{directory}/final/vh/m.vh"]\n', text)
            self.assertIn(f'      nom: ["dir::{directory}/final/lib/nom/m__nom.lib"]\n', text)

    def test_macros_yaml_lists_all_instances_of_a_macro_once(self):
        text = self.run_dir_yaml(["vh/m.vh"], instances=("m0", "m1"))
        self.assertEqual(text.count("  m:\n"), 1)
        self.assertIn("      i_chip_core.m0:\n", text)
        self.assertIn("      i_chip_core.m1:\n", text)

    def test_macros_yaml_exports_the_views_of_a_run_directory(self):
        text = self.run_dir_yaml(["vh/m.vh", "nl/m.nl.v", "pnl/m.pnl.v", "lib/nom_slow/m__nom_slow.lib",
                                  "lib/nom_fast/m__nom_fast.lib", "spef/nom/m.nom.spef", "spef/max/m.max.spef"])
        self.assertIn('    lef: ["dir::m/final/lef/m.lef"]\n'
                      '    vh: ["dir::m/final/vh/m.vh"]\n'
                      '    nl: ["dir::m/final/nl/m.nl.v"]\n'
                      '    pnl: ["dir::m/final/pnl/m.pnl.v"]\n'
                      "    lib:\n"
                      '      nom_fast: ["dir::m/final/lib/nom_fast/m__nom_fast.lib"]\n'
                      '      nom_slow: ["dir::m/final/lib/nom_slow/m__nom_slow.lib"]\n'
                      "    spef:\n"
                      '      max_*: ["dir::m/final/spef/max/m.max.spef"]\n'
                      '      nom_*: ["dir::m/final/spef/nom/m.nom.spef"]\n'
                      "    instances:\n", text)
        self.assertNotIn("MODMISSING", text)

    def test_macros_yaml_lists_only_views_that_exist(self):
        text = self.run_dir_yaml(["pnl/m.pnl.v", "vh/m.vh/", "nl/m.nl.v/", "lib/nom_fast/other.lib",
                                  "lib/nom_x/m__nom_x.lib/", "spef/nom/other.spef"])
        self.assertIn('    pnl: ["dir::m/final/pnl/m.pnl.v"]\n', text)
        for view in ("vh:", "nl:", "lib:", "spef:"):
            self.assertNotIn(f"    {view}", text)
        self.assertNotIn("MODMISSING", text)  # lint takes the pnl

    def test_macros_yaml_names_the_lef_that_was_read(self):
        self.assertIn('    lef: ["dir::m/final/lef/renamed.lef"]\n', self.run_dir_yaml(["lef/renamed.lef"]))
        self.assertIn('    lef: ["dir::m/final/lef/m_top.lef"]\n', self.run_dir_yaml(["lef/m_top.lef", "lef/other.lef"]))
        self.assertIn('    lef: ["dir::m/final/lef/m.lef"]\n', self.run_dir_yaml(["lef/m.lef", "lef/other.lef"]))
        self.assertIn('    lef: ["dir::m/final/lef/m.lef"]\n', self.run_dir_yaml([]))  # none there, the path LibreLane expects

    def test_macros_yaml_hand_made_verilog_view(self):
        self.assertIn('    vh: ["dir::m/final/vh/m.v"]\n', self.run_dir_yaml(["vh/m.v"]))
        self.assertNotIn("MODMISSING", self.run_dir_yaml(["vh/m.v"]))
        text = self.run_dir_yaml(["vh/m.v", "vh/m.vh"])  # LibreLane's own name wins
        self.assertIn('    vh: ["dir::m/final/vh/m.vh"]\n', text)
        self.assertNotIn("m/final/vh/m.v\"", text)

    def test_macros_yaml_names_a_flat_lib_without_exporting_it(self):
        text = self.run_dir_yaml(["vh/m.vh", "lib/m.lib"])
        self.assertIn('    # final/lib/m.lib not exported, it names no corner. If it holds for all of them: lib: {"*": [...]}\n', text)
        self.assertNotIn("    lib:", text)
        self.assertNotIn("not exported, it names", self.run_dir_yaml(["vh/m.vh"]))

    def two_paths(self, first, second):
        from prep_ic.model.floorplan import Macro, MacroDef
        p = compac_like()
        p.floorplan.macros = [Macro(n, "m", path, 40.0, y, 0, [], MacroDef("m", 100.0, 100.0))
                              for n, path, y in (("c0", first, 20.0), ("c1", second, 200.0))]
        return p

    def test_macros_yaml_one_directory_spelled_two_ways(self):
        from prep_ic.formats.librelane import macros_yaml
        with tempfile.TemporaryDirectory() as d:
            p = self.two_paths(str(Path(d, "m")), f"{d}/x/../m/")
            text = macros_yaml(p, p.layout(), out_dir=d)
        self.assertEqual(text.count("  m:\n"), 1)
        self.assertIn("      i_chip_core.c0:\n", text)
        self.assertIn("      i_chip_core.c1:\n", text)
        self.assertFalse(any("directories" in w for w in prep.findings(p)))

    def test_macros_yaml_one_macro_name_from_two_directories(self):
        from prep_ic.formats.librelane import macros_yaml
        with tempfile.TemporaryDirectory() as d:
            p = self.two_paths(str(Path(d, "v1", "m")), str(Path(d, "v2", "m")))
            text = macros_yaml(p, p.layout(), out_dir=d)
        self.assertEqual(text.count("  m:\n"), 1)  # a second key would stop LibreLane's loader
        self.assertIn('dir::v1/m/final/gds/m.gds', text)
        self.assertNotIn("v2/m", text)
        self.assertNotIn("i_chip_core.c1:", text)
        self.assertIn("# c1 not exported: macro m already comes from another directory", text)
        self.assertIn("Macro m comes from 2 directories, not exported: c1", prep.findings(p))

    def test_macros_yaml_keeps_three_decimals(self):
        from prep_ic.formats.librelane import _num
        self.assertEqual((_num(1790.565), _num(160.0), _num(0.1 + 0.2)), ("1790.565", "160", "0.3"))

    def test_macros_yaml_only_with_macros(self):
        self.assertNotIn("macros.yaml", librelane_files(compac_like()))
        files = librelane_files(self.project())
        self.assertIn("macros.yaml", files)
        self.assertIn("//   adc_sar_top i_chip_core.adc0", files["chip_core_template.sv"])
        self.assertNotIn("Macros", librelane_files(compac_like())["chip_core_template.sv"])


if __name__ == "__main__":
    unittest.main()
