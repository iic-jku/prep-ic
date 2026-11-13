# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Every PDK profile against the LEF of its IO library, when the PDK is installed."""

import glob
import os
import re
import unittest
from pathlib import Path

from tests import ROOT  # noqa: F401  (sets the import path)

from prep_ic.model.pdk import get_pdk, pdk_names


def read_macros(path):
    """Macro name → (width, height, pin names), from the plain LEF text."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    out = {}
    for m in re.finditer(r"^\s*MACRO\s+(\S+)(.*?)^\s*END\s+\1\s*$", text, re.S | re.M):
        w, h = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", m.group(2)).groups()
        pins = {re.sub(r"\[\d+\]$", "", p) for p in re.findall(r"^\s*PIN\s+(\S+)", m.group(2), re.M)}
        out[m.group(1)] = (float(w), float(h), pins)
    return out


def masters(cell):
    """Every IO cell master a profile entry can select."""
    variants = [v["master"] for v in cell.get("variants", {}).values()]
    if "{drive}" in cell["master"]:
        return [cell["master"].format(drive=d) for d in cell["drives"]] + variants
    return [cell["master"]] + variants


@unittest.skipUnless(os.environ.get("PDK_ROOT"), "needs PDK_ROOT")
class ProfilesAgainstLef(unittest.TestCase):
    def macros(self, pdk):
        files = glob.glob(os.path.join(os.environ["PDK_ROOT"], pdk.name, "libs.ref", "*", "lef", f"{pdk.io_library}*.lef"))
        macros = {}
        for f in files:
            macros.update(read_macros(f))
        return macros

    def test_every_profile(self):
        checked = 0
        for name in pdk_names():
            pdk = get_pdk(name)
            macros = self.macros(pdk)
            if not macros:  # this PDK is not installed
                continue
            for ring in pdk.ring_cells:
                with self.subTest(pdk=name, ring=ring["name"]):
                    self.assertEqual(macros[ring["master"]][0], ring["width"])
                    supplies = {q for pins in ring.get("power_pins", {}).values() for q in pins}
                    self.assertLessEqual(supplies, macros[ring["master"]][2])
            for function, cell in pdk.cells.items():
                for master in masters(cell):
                    with self.subTest(pdk=name, master=master):
                        self.assertIn(master, macros)
                        w, h, pins = macros[master]
                        self.assertEqual(w, pdk.width_of(function))
                        self.assertLessEqual(h, pdk.cell_depth)
                        for role, pin in cell["pins"].items():
                            self.assertIn(pin, pins, role)
                        supplies = {q for rail in pdk.power_pins_of(function).values() for q in rail}
                        self.assertLessEqual(supplies, pins, "supply pins")
                        checked += 1
        self.assertGreater(checked, 0, "no profile found its LEF below PDK_ROOT")


if __name__ == "__main__":
    unittest.main()
