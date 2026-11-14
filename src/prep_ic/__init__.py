# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""PREP-IC (Pinout, Ring and Early floorplan Planner for ICs): plan IC pad ring pinouts.

Scripting API (no Qt needed)::

    import prep_ic as prep

    project = prep.load("chip.json")
    project.sides["L"].append("VDDA [p]")
    project.settings.std.pitch = 90
    layout = project.layout()
    print(layout.die_width, layout.die_height, layout.warnings)
    print(prep.findings(project))                # everything to report, as in prep-ic check
    prep.export_csv(project, "pins.csv")
    prep.export_svg(project, "ring.svg")
    prep.save(project, "chip.json")

    project.settings.pdk = "ihp-sg13g2"          # see prep.pdk_names()
    project.settings.package = "OP_QFN32_A4_FIT"  # see prep.package_names()
    prep.export_librelane(project, "flow/padring")   # config part, pad_cfg.tcl, chip_top.sv, …
"""

# defined before the imports: submodules import them
__version__ = "0.2.1"
APP_NAME = "PREP-IC"

from .formats.lef import read_lef
from .formats.librelane import export_librelane, librelane_files
from .formats.pinlist import export_csv
from .formats.project_file import load, save
from .formats.svg import export_svg, to_svg
from .model import (SIDE_NAMES, SIDES, TYPE_NAMES, TYPES, Floorplan, Layout, Macro, PadSettings, Pin,
                    Project, Settings, build_layout)
from .model.chip import (add_missing_pads, align_macros, analyse, auto_rotate, findings, move_line, optimize_pad_order,
                         place_line, suggest_supply_pads, toggle_lock)
from .model.chip import add_missing_pads as generate_pads
from .model.pdk import get_package, get_pdk, package_names, pdk_names

__all__ = ["APP_NAME", "add_missing_pads", "align_macros", "analyse", "auto_rotate", "findings", "move_line",
           "optimize_pad_order", "place_line", "suggest_supply_pads", "toggle_lock", "SIDES", "SIDE_NAMES", "TYPES", "TYPE_NAMES", "Floorplan", "Layout", "Macro", "PadSettings",
           "Pin", "Project", "Settings", "build_layout", "export_csv", "export_librelane", "export_svg",
           "generate_pads", "get_package", "get_pdk", "librelane_files", "load", "package_names", "pdk_names",
           "read_lef", "save", "to_svg"]
