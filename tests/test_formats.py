# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tests import ROOT

import prep_ic as prep
from prep_ic.formats import pinlist


def child_env():
    # inherit the environment: Windows Python 3.10 and older cannot start without SYSTEMROOT
    return {**os.environ, "PYTHONPATH": str(ROOT / "src")}


class Exports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.project = prep.Project.example()

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_load(self):
        path = self.dir / "sub" / "p.json"
        prep.save(self.project, path)
        self.assertEqual(prep.load(path), self.project)

    def test_load_rejects_other_json(self):
        path = self.dir / "x.json"
        path.write_text("[1, 2]")
        with self.assertRaises(ValueError):
            prep.load(path)

    def test_csv(self):
        path = self.dir / "pins.csv"
        prep.export_csv(self.project, path)
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(tuple(rows[0]), pinlist.HEADER)
        self.assertEqual(len(rows) - 1, len(self.project.layout().pins))
        self.assertEqual(rows[1][:4], ["1", "Left", "VDDIO", "Power"])

    def test_svg(self):
        path = self.dir / "ring.svg"
        prep.export_svg(self.project, path)
        root = ET.parse(path).getroot()
        ns = {"s": "http://www.w3.org/2000/svg"}
        texts = [t.text for t in root.iterfind(".//s:text", ns)]
        self.assertIn("VDDIO", texts)
        self.assertIn("31", texts)


class CommandLine(unittest.TestCase):
    def run_cli(self, *args, **env):
        # the timeout ends a GUI that a broken subcommand dispatch would start
        return subprocess.run([sys.executable, "-m", "prep_ic", *args], capture_output=True, text=True,
                              cwd=ROOT, env={**child_env(), **env}, timeout=120)

    def test_export(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("export", "examples/padring.json", "--csv", f"{d}/p.csv", "--svg", f"{d}/p.svg")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(Path(d, "p.csv").exists() and Path(d, "p.svg").exists())

    def test_export_missing_file(self):
        r = self.run_cli("export", "does-not-exist.json", "--csv", "x.csv")
        self.assertEqual(r.returncode, 1)
        self.assertIn("error:", r.stderr)

    def test_export_prints_findings_and_exits_0(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("export", "examples/chip_demo.json", "--csv", f"{d}/p.csv")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(Path(d, "p.csv").exists())
        self.assertIn("warning: 1 flyline crossing: VIN_P/VIN_N", r.stderr)
        self.assertIn("warning: 1 checked pins without pad: CLK", r.stderr)

    def test_check_clean(self):
        for project in ("examples/padring.json", "examples/ihp_sg13g2_domains.json"):
            r = self.run_cli("check", project)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "no findings"), r.stderr)

    def test_check_findings(self):
        r = self.run_cli("check", "examples/chip_demo.json")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["1 flyline crossing: VIN_P/VIN_N", "1 checked pins without pad: CLK"])

    def test_check_reports_a_lost_lef(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(ROOT / "examples" / "chip_demo.json", d)  # its macro paths no longer resolve
            r = self.run_cli("check", str(Path(d, "chip_demo.json")))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("No LEF found for adc_sar0", r.stdout)

    def test_check_that_did_not_run_is_no_finding(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (("text.json", "not json"), ("list.json", "[]"), ("sides.json", '{"sides": 3}')):
                Path(d, name).write_text(text, encoding="utf-8")
                r = self.run_cli("check", str(Path(d, name)))
                self.assertEqual(r.returncode, 2, name)
                self.assertIn("error:", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.run_cli("check", "does-not-exist.json").returncode, 2)
        self.assertEqual(self.run_cli("check").returncode, 2)  # no project given

    def test_check_output_failure_is_no_finding(self):
        broken = "class S(io.StringIO):\n    def write(self, text):\n        raise OSError('closed')\nsys.stdout = S()\n"
        for setup in (broken, "sys.stdout = None\n"):
            code = ("import io, sys\nimport prep_ic.cli as cli\n" + setup
                    + "sys.exit(cli.main(['check', 'examples/padring.json']))\n")
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                               env=child_env(), timeout=120)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("error:", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_check_output_to_a_closed_pipe_exits_2(self):
        read, write = os.pipe()
        os.close(read)
        try:
            r = subprocess.run([sys.executable, "-m", "prep_ic", "check", "examples/padring.json"], stdout=write,
                               stderr=subprocess.PIPE, text=True, cwd=ROOT, env=child_env(), timeout=120)
        finally:
            os.close(write)
        self.assertEqual(r.returncode, 2, r.stderr)  # not 1 for findings, not 120 from the flush at exit
        self.assertIn("error:", r.stderr)

    def test_export_output_to_a_closed_pipe_still_exits_0(self):
        read, write = os.pipe()
        os.close(read)
        with tempfile.TemporaryDirectory() as d:
            try:
                r = subprocess.run([sys.executable, "-m", "prep_ic", "export", "examples/ihp_sg13g2_domains.json",
                                    "--librelane", d], stdout=write, stderr=subprocess.PIPE, text=True, cwd=ROOT,
                                   env=child_env(), timeout=120)
            finally:
                os.close(write)
            self.assertEqual(r.returncode, 0, r.stderr)  # the files are written, the "wrote" lines only inform
            self.assertNotIn("Exception ignored", r.stderr)
            self.assertTrue(Path(d, "pad_cfg.tcl").is_file())

    def test_export_writes_all_files_or_none(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # an output that cannot be written: the CSV before it stays unwritten
            r = self.run_cli("export", "examples/padring.json", "--csv", str(d / "p.csv"), "--svg", str(d / "no" / "p.svg"))
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertFalse((d / "p.csv").exists())
            # LibreLane files without a PDK: nothing at all, not even the folder
            r = self.run_cli("export", "examples/padring.json", "--csv", str(d / "q.csv"), "--librelane", str(d / "ll"))
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertFalse((d / "q.csv").exists() or (d / "ll").exists())
            # one LibreLane file that cannot be written: the others keep what they held before
            ll = d / "ll2"
            (ll / "chip_top.sv").mkdir(parents=True)
            (ll / "pad_cfg.tcl").write_text("old", encoding="utf-8")
            r = self.run_cli("export", "examples/ihp_sg13g2_domains.json", "--librelane", str(ll))
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertEqual(sorted(p.name for p in ll.iterdir()), ["chip_top.sv", "pad_cfg.tcl"])
            self.assertEqual((ll / "pad_cfg.tcl").read_text(encoding="utf-8"), "old")

    def test_a_rename_that_fails_midway_puts_the_old_files_back(self):
        from unittest import mock
        from prep_ic.formats import files
        with tempfile.TemporaryDirectory() as d:
            a, b, c = (Path(d, n) for n in ("a.txt", "b.txt", "c.txt"))
            a.write_text("old a", encoding="utf-8")
            b.write_text("old b", encoding="utf-8")
            real = os.replace

            def flaky(src, dst):
                if str(src).endswith("b.txt.prep-ic-tmp"):  # the second new file cannot go into place
                    raise PermissionError("locked")
                return real(src, dst)
            with mock.patch.object(files.os, "replace", flaky), self.assertRaises(PermissionError):
                files.write_all({a: b"new a", b: b"new b", c: b"new c"})
            self.assertEqual((a.read_text(encoding="utf-8"), b.read_text(encoding="utf-8"), c.exists()),
                             ("old a", "old b", False))
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["a.txt", "b.txt"])

    def test_export_without_a_stdout_succeeds(self):
        code = ("import sys\nimport prep_ic.cli as cli\nsys.stdout = None\n"
                "sys.exit(cli.main(['export', 'examples/ihp_sg13g2_domains.json', '--librelane', sys.argv[1]]))\n")
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-c", code, d], capture_output=True, text=True, cwd=ROOT,
                               env=child_env(), timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(Path(d, "chip_top.sv").exists())

    def test_check_without_a_stdout_encoding(self):
        code = ("import io, sys\nimport prep_ic.cli as cli\nsys.stdout = out = io.StringIO()\n"
                "rc = cli.main(['check', 'examples/padring.json'])\nsys.stderr.write(f'{rc} {out.getvalue()}')\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env=child_env(), timeout=120)
        self.assertEqual(r.stderr.strip(), "0 no findings")

    def test_export_path_outside_the_output_encoding(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("export", "examples/ihp_sg13g2_domains.json", "--librelane", str(Path(d, "Ω")),
                             PYTHONIOENCODING="ascii")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("wrote "), 5)
        self.assertIn("\\u03a9", r.stdout)

    def test_export_malformed_project_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (("attribute.json", '{"sides": 3}'), ("type.json", '{"sides": {}, "std": 3}'),
                               ("nesting.json", "[" * 200000)):
                path = Path(d, name)
                path.write_text(text, encoding="utf-8")
                self.assertRaises(ValueError, prep.load, path)
                r = self.run_cli("export", str(path), "--csv", str(Path(d, "p.csv")))
                self.assertEqual(r.returncode, 1, name)
                self.assertIn("error:", r.stderr)
                self.assertNotIn("Traceback", r.stderr)

    def test_check_name_outside_the_output_encoding(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "chip.json")
            prep.save(prep.Project(sides={"L": ["Ä [foo]"], "T": [], "R": [], "B": []}), path)
            r = self.run_cli("check", str(path), PYTHONIOENCODING="ascii")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("Unknown tag or option in pad name: \\xc4 [foo]", r.stdout)

    def test_check_reports_a_macro_the_loader_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "chip.json")
            path.write_text('{"sides": {"L": "A"}, "floorplan": {"macros": [{"name": "adc0", "io": null}]}}', encoding="utf-8")
            r = self.run_cli("check", str(path))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("Macro entry 1 (adc0) could not be read and was dropped", r.stdout)


class LoadProblems(unittest.TestCase):
    """What the loader leaves out of a hand-edited file has to show up as a finding."""

    MACRO = {"name": "a", "cache": {"name": "a", "w": 100, "h": 100}}

    def warnings(self, data):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "chip.json")
            path.write_text(json.dumps(data), encoding="utf-8")
            return prep.load(path)

    def test_dropped_macro_entries(self):
        cases = {"io null": ([{**self.MACRO, "io": None}], "Macro entry 1 (a) could not be read and was dropped"),
                 "no name": ([{"cache": self.MACRO["cache"]}], "Macro entry 1 could not be read and was dropped"),
                 "not an object": ([3], "Macro entry 1 could not be read and was dropped"),
                 "second of two": ([self.MACRO, {**self.MACRO, "name": "b", "io": 3}],
                                   "Macro entry 2 (b) could not be read and was dropped")}
        for label, (macros, expected) in cases.items():
            p = self.warnings({"sides": {"L": "A"}, "floorplan": {"macros": macros}})
            self.assertEqual(p.load_warnings, [expected], label)
        self.assertEqual([m.name for m in p.floorplan.macros], ["a"])  # the good one stays

    def test_a_reload_keeps_what_the_file_dropped(self):
        p = self.warnings({"sides": {"L": "A"}, "cellh": "tall", "floorplan": {"macros": [{**self.MACRO, "io": None}]}})
        dropped = ["Macro entry 1 (a) could not be read and was dropped", "Setting cellh is no valid number ('tall'), using the default"]
        self.assertEqual(p.load_warnings, dropped)
        self.assertEqual(p.reload_macros(), dropped)  # the content stays dropped, so the finding stays
        self.assertTrue(set(dropped) <= set(prep.findings(p)))

    def test_choices_that_load_as_defaults(self):
        p = self.warnings({"sides": {"L": "A"}, "mode": "zigzag", "align": ["xyz"]})
        self.assertEqual(p.load_warnings, ["Setting mode is no valid choice ('zigzag'), using ccw",
                                           "Setting align is no valid choice (['xyz']), using center"])
        self.assertEqual((p.settings.mode, p.settings.align), ("ccw", "center"))

    def test_sides_that_are_no_text(self):
        p = self.warnings({"format": 2, "sides": {"L": ["A", "B [in]", ""], "T": 5, "R": None}})
        self.assertEqual(p.sides["L"], ["A", "B [in]", ""])  # a list of lines is read as lines
        self.assertEqual(p.load_warnings, ["Side T is no text (5), read as one line"])

    def test_macros_that_are_no_list(self):
        for macros in (None, 3, "ab"):
            p = self.warnings({"sides": {"L": "A"}, "floorplan": {"macros": macros}})
            self.assertEqual(p.load_warnings, ["The floorplan could not be read, its macros were dropped"], macros)

    def test_macro_name_that_is_no_text(self):
        p = self.warnings({"sides": {"L": "A"}, "floorplan": {"macros": [{**self.MACRO, "name": None}]}})
        self.assertEqual(p.load_warnings, ["Macro None: name not valid in the project file"])

    def test_floorplan_that_is_no_object(self):
        self.assertEqual(self.warnings({"sides": {"L": "A"}, "floorplan": 3}).load_warnings,
                         ["The floorplan could not be read, its macros were dropped"])

    def test_unknown_side_key(self):
        p = self.warnings({"sides": {"l": "A", "L": "B"}})
        self.assertEqual(p.load_warnings, ['Unknown side "l" ignored, expected T, R, B or L'])
        self.assertEqual(p.sides["L"], ["B"])

    def test_invalid_numbers_are_findings_and_use_the_default(self):
        p = self.warnings({"sides": {"L": "A"}, "std": {"pitch": 1e999}, "cellh": "tall", "halo": 0})
        self.assertEqual(p.load_warnings, ["Setting cellh is no valid number ('tall'), using the default",
                                           "Setting std.pitch is no valid number (inf), using the default"])
        self.assertEqual((p.settings.std.pitch, p.settings.cell_height, p.settings.halo), (80.0, 120.0, 0.0))
        p = self.warnings({"sides": {"L": "A"}, "pitch": 1e999})  # the flat key of old files
        self.assertEqual(p.load_warnings, ["Setting pitch is no valid number (inf), using the default"])
        self.assertEqual(p.settings.std.pitch, 80.0)

    def test_an_infinite_pitch_no_longer_stops_the_export(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "chip.json")
            path.write_text('{"sides": {"L": "A"}, "pdk": "ihp-sg13g2", "std": {"pitch": 1e999}}', encoding="utf-8")
            prep.export_librelane(prep.load(path), d)  # raised OverflowError
            self.assertTrue(Path(d, "chip_top.sv").exists())

    def test_macro_position_that_is_no_finite_number_is_zero(self):
        macro = {**self.MACRO, "x": 1e999, "y": float("nan"), "rot": 1e999}
        p = self.warnings({"sides": {"L": "A"}, "floorplan": {"macros": [macro]}})
        m = p.floorplan.macros[0]
        self.assertEqual((m.x, m.y, m.rot), (0.0, 0.0, 0))
        self.assertEqual(p.load_warnings, ["Macro a: x, y, rot not valid in the project file"])

    def test_macro_fields_that_load_as_defaults_are_findings(self):
        bad = {"name": "a", "x": "far", "halo": "big", "rot": 45, "class": "loud",
               "cache": {"name": "a", "w": "wide", "h": -5, "pins": [{"name": "p", "x": "left", "y": 1}]}}
        p = self.warnings({"sides": {"L": "A"}, "floorplan": {"macros": [bad]}})
        self.assertEqual(p.load_warnings, ["Macro a: x, rot, halo, class, cache w, cache h, cache pins not valid in the project file"])
        self.assertIn(p.load_warnings[0], prep.findings(p))
        negative = {"name": "b", "cache": {"name": "b", "w": -50, "h": -50}}
        self.assertEqual(self.warnings({"sides": {"L": "A"}, "floorplan": {"macros": [negative]}}).load_warnings,
                         ["Macro b: cache w, cache h not valid in the project file"])

    def test_clean_files_have_no_load_problems(self):
        for data in ({"sides": {"L": "A"}}, {"sides": {"L": "A"}, "floorplan": None}, {"sides": {}, "floorplan": {}},
                     {"sides": {"L": "A"}, "floorplan": {"macros": [self.MACRO]}},
                     prep.Project.example().to_dict()):  # every setting a saved file carries
            self.assertEqual(self.warnings(data).load_warnings, [], data)


class NoQtOutsideGui(unittest.TestCase):
    """Model, formats, API and CLI export must work without loading Qt."""

    def test_no_qt_loaded(self):
        code = (
            "import sys, tempfile, os\n"
            "import prep_ic as prep, prep_ic.cli as cli\n"
            "import prep_ic.model, prep_ic.formats.svg, prep_ic.formats.pinlist\n"
            "d = tempfile.mkdtemp()\n"
            "assert cli.main(['export', 'examples/padring.json', '--csv', os.path.join(d, 'a.csv'),"
            " '--svg', os.path.join(d, 'a.svg')]) == 0\n"
            "assert cli.main(['check', 'examples/padring.json']) == 0\n"
            "bad = [m for m in sys.modules if m.split('.')[0] in ('PySide6', 'PyQt6', 'shiboken6')"
            " or m.startswith('prep_ic.gui.')]\n"
            "assert not bad, bad\n"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_gui_start_without_qt_is_a_clean_error(self):
        code = (
            "import sys\n"
            "sys.modules.update({'PySide6': None, 'PyQt6': None})\n"  # blocks them where Qt is installed
            "import prep_ic.cli as cli\n"
            "sys.exit(cli.main([]))\n"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env=child_env())
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("error: Qt is missing", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_gui_start_with_a_broken_qt_names_the_cause(self):
        code = (
            "import sys\n"
            "class Broken:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.startswith('PySide6'):\n"
            "            raise ImportError('libEGL.so.1: cannot open shared object file')\n"
            "sys.meta_path.insert(0, Broken())\n"
            "sys.modules['PyQt6'] = None\n"
            "import prep_ic.cli as cli\n"
            "sys.exit(cli.main([]))\n"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env=child_env())
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("error: PySide6 cannot be loaded: libEGL.so.1", r.stderr)
        self.assertNotIn("Qt is missing", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_no_qt_import_in_source(self):
        src = ROOT / "src" / "prep_ic"
        for path in src.rglob("*.py"):
            if "gui" in path.relative_to(src).parts:
                continue
            text = path.read_text(encoding="utf-8")
            for qt in ("PySide6", "PyQt6", ".gui."):
                self.assertNotIn(qt, text.replace("from .gui import run", ""), f"{path} mentions {qt}")


if __name__ == "__main__":
    unittest.main()
