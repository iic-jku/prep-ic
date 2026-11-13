<p align="center">
  <img src="https://raw.githubusercontent.com/iic-jku/prep-ic/main/src/prep_ic/gui/assets/prep_ic_logo.svg" alt="PREP-IC logo" width="140">
</p>

# PREP-IC: Pinout, Ring and Early floorplan Planner for ICs

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/iic-jku/prep-ic/blob/main/LICENSE)
[![License Check](https://github.com/iic-jku/prep-ic/actions/workflows/license-check.yml/badge.svg)](https://github.com/iic-jku/prep-ic/actions/workflows/license-check.yml)
[![Tests](https://github.com/iic-jku/prep-ic/actions/workflows/tests.yml/badge.svg)](https://github.com/iic-jku/prep-ic/actions/workflows/tests.yml)
![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)
![GUI: PySide6-Essentials](https://img.shields.io/badge/GUI-PySide6--Essentials-41CD52.svg?logo=qt&logoColor=white)
[![PyPI](https://img.shields.io/pypi/v/prep-ic.svg)](https://pypi.org/project/prep-ic/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23963620.svg)](https://doi.org/10.5281/zenodo.23963620)

(c) 2026 Maximilian Golser and Simon Dorrer

Institute for Integrated Circuits and Quantum Computing (IICQC), Johannes Kepler University (JKU), Linz, Austria

> [!IMPORTANT]
> PREP-IC (GUI, CLI and Python API) runs anywhere with **Python ≥ 3.10** and **PySide6-Essentials**, see [Install](https://github.com/iic-jku/prep-ic#install) below. The CLI export and the Python API do not load Qt at all.
> *Using* the exported files needs a **LibreLane** chip flow and one of the supported PDKs (**IHP SG13G2**, **IHP SG13CMOS5L**, **sky130A** or **gf180mcuD**). The easiest way to get both is the [IIC-OSIC-TOOLS](https://github.com/iic-jku/IIC-OSIC-TOOLS) container.



## Description

**PREP-IC** is a PySide6 GUI and Python API that plans the pad ring and the pinout of an IC before its layout starts. You type the pads of each side, one line per pad, and the die grows with them (pad-limited), so pad count, pitch and die size never disagree. It is made for analog, mixed-signal and RF designers doing early floorplanning.

It works in three layers, each optional on top of the one before:

- **Pad ring.** Plain-text side editors with tags for the pad type, IO function, drive strength, bond pad size and pitch, RF ground-signal-ground groups (`[gsg]`, and `[gsgsg]` for a differential pair), spacers, and power splits that cut the IO ring into domains.
- **PDK and package.** With a supported PDK chosen, the ring shows the real IO cells, corner cells, bondpads and seal ring spacing, and every pad gets its IO cell. A package from the EUROPRACTICE library gives every pad its package pin. See [Supported PDKs and Packages](https://github.com/iic-jku/prep-ic#supported-pdks-and-packages).
- **Chip view.** Macros from LibreLane run directories (size and pins from their LEF) are placed in the core, with a flyline from every off-chip macro pin to its pad. Checks flag crossing flylines, split differential pairs, sensitive pads next to noisy ones, macros too close to each other and macros without a supply pad within reach. Pads and macros are dragged in the same picture, and *Optimize Pad Order*, *Add Missing Pads* and *Suggest Supply Pads* do the routine edits. See [Chip view](https://github.com/iic-jku/prep-ic#chip-view).

The plan goes straight into the chip flow: the pad ring part of the LibreLane `config.yaml`, a `pad_cfg.tcl` that places the IO cells exactly as planned, a `chip_top.sv` with the IO cell instances, the matching core template, `macros.yaml` and the bondplan `PINOUT`. A pin list (CSV) and the drawing (SVG, PNG) document it.

The code is split into a pure-Python, Qt-free model and exporters (`prep_ic.model`, `prep_ic.formats`) behind a scripting API, and a thin `prep_ic.gui` on PySide6-Essentials. The CLI exports without the GUI. How it is built and the rules it follows are in [`doc/architecture.md`](https://github.com/iic-jku/prep-ic/blob/main/doc/architecture.md).

<p align="center">
  <a href="https://raw.githubusercontent.com/iic-jku/prep-ic/main/doc/fig/prep_ic_chip_view.png"><img src="https://raw.githubusercontent.com/iic-jku/prep-ic/main/doc/fig/prep_ic_chip_view.png" alt="PREP-IC chip view with macros and flylines" width="85%"></a><br>
  <em>The chip view of <code>examples/chip_demo.json</code>: an IHP SG13G2 IO ring with the power domains ANA and DIG, four macros with their flylines, one crossing (orange) and one checked pin without a pad.</em>
</p>

<p align="center">
  <a href="https://raw.githubusercontent.com/iic-jku/prep-ic/main/doc/fig/prep_ic_io_ring.png"><img src="https://raw.githubusercontent.com/iic-jku/prep-ic/main/doc/fig/prep_ic_io_ring.png" alt="PREP-IC IO ring with two power domains" width="85%"></a><br>
  <em>The IO ring of <code>examples/ihp_sg13g2_domains.json</code>: 26 IHP SG13G2 IO cells on a fixed 1.6 × 1.6 mm die, split into the power domains MAIN and ANA.</em>
</p>

<p align="center">
  <a href="https://raw.githubusercontent.com/iic-jku/prep-ic/main/doc/fig/prep_ic_librelane.png"><img src="https://raw.githubusercontent.com/iic-jku/prep-ic/main/doc/fig/prep_ic_librelane.png" alt="PREP-IC LibreLane output" width="85%"></a><br>
  <em>The LibreLane tab: the pad ring part of <code>config.yaml</code>, <code>pad_cfg.tcl</code>, <code>chip_top.sv</code>, the core template and the bondplan pinout, ready to copy or export.</em>
</p>


## Directory Structure

```text
📁 prep-ic/
├─ 📁 doc/
│  ├─ 📁 fig/                    README screenshots and logos
│  └─ architecture.md            layers, conventions and the design rules of the chip view
├─ 📁 examples/
│  ├─ 📁 macros/                 abstract LEFs of four demo macros (ADC, PLL, LNA, digital core)
│  ├─ chip_demo.json             chip view demo: IHP SG13G2, two domains, four macros, an RF input
│  ├─ gf180mcud_demo.json        gf180mcuD ring
│  ├─ sky130a_demo.json          sky130A ring
│  ├─ wafer_space_slot_*.json    one project per wafer.space gf180mcuD slot
│  ├─ ihp_sg13g2_domains.json    IHP SG13G2 ring on a fixed die, two domains, QFN32 package
│  ├─ padring.json               pad ring without a PDK
│  └─ script_example.py          build, check and export a pad ring in code
├─ 📁 src/prep_ic/               the package (pip-installable)
│  ├─ 📁 data/                   PDK profiles (pdks/*.json) and the package library (packages.json)
│  ├─ 📁 formats/                project files and exports, no Qt
│  │  ├─ lef.py                  minimal LEF reader: macro size and pins
│  │  ├─ librelane.py            pad ring config, pad_cfg.tcl, chip_top.sv, macros.yaml, bondplan PINOUT
│  │  ├─ pinlist.py              pin list as CSV or tab-separated text
│  │  ├─ project_file.py         project files (JSON)
│  │  └─ svg.py                  SVG drawing of the pad ring
│  ├─ 📁 gui/                    PySide6-Essentials, uses only the model and formats API
│  │  ├─ 📁 assets/              the logo
│  │  ├─ about_dialog.py         Help → About: version, authors, license and links
│  │  ├─ app.py                  the GUI launcher
│  │  ├─ chip_view.py            IO ring, core, draggable macros, flylines and markers
│  │  ├─ macro_panel.py          the macro list
│  │  ├─ main_window.py          side editors, tabs, settings and LibreLane output
│  │  ├─ qt.py                   Qt binding: PySide6, PyQt6 as fallback
│  │  ├─ scene.py                draws layout primitives into a QGraphicsScene
│  │  └─ widgets.py              side editor with pin number gutter, zoomable ring view
│  ├─ 📁 model/                  pure Python, no Qt
│  │  ├─ chip.py                 pads and macros together: flylines, crossings, analog and power checks
│  │  ├─ constants.py            constants shared by the model, the exporters and the GUI
│  │  ├─ floorplan.py            hard macros placed in the core
│  │  ├─ layout.py               pin numbering, die size, geometry and drawing primitives
│  │  ├─ parse.py                editor lines to pad entries
│  │  ├─ pdk.py                  PDK and package profiles
│  │  └─ project.py              ring settings and the entry lines of each side
│  ├─ __init__.py                scripting API and version
│  ├─ __main__.py                python -m prep_ic
│  ├─ cli.py                     command line: GUI, export or check
│  └─ style.py                   color palettes shared by the GUI and the SVG export
├─ 📁 tests/                     unittest suite, the GUI tests run offscreen
│  ├─ 📁 data/                   layout baseline and a test macro
│  ├─ test_chip.py               chip view model: analysis and edits of pads and macros
│  ├─ test_floorplan.py          LEF reading, macro placement and pad generation
│  ├─ test_formats.py            project files, CSV, SVG, the CLI, no Qt in the core
│  ├─ test_gui.py                GUI smoke tests
│  ├─ test_model.py              entry parser, settings, die and core sizing
│  ├─ test_pdk.py                PDK profiles, IO cells, LibreLane and bondplan exports
│  ├─ test_pdk_lef.py            every profile against the LEF of its IO library, needs PDK_ROOT
│  └─ test_qt_essentials.py      guards the PySide6-Essentials-only dependency
├─ 📁 LICENSES/                  license texts the REUSE check resolves against
│  └─ Apache-2.0.txt
├─ 📁 .github/workflows/         CI
│  ├─ license-check.yml          reuse lint: every file carries copyright and license
│  └─ tests.yml                  the unittest suite on Linux, Windows and macOS, Python 3.10 and 3.15
├─ CITATION.cff
├─ LICENSE                       Apache-2.0
├─ MANIFEST.in                   sdist manifest (adds the REUSE files)
├─ pyproject.toml                packaging, dependency and the prep-ic entry point
├─ README.md
├─ REUSE.toml                    licensing of files that cannot carry an SPDX header
└─ ToDo.md                       open defects, release follow-ups, sky130A and gf180mcuD
```


## How to Use

### Install

From PyPI:

```bash
pip install prep-ic
# or, for an isolated install with its own command on PATH:
pipx install prep-ic
```

The development version from GitHub:

```bash
pip install git+https://github.com/iic-jku/prep-ic.git
```

From source (for development), an editable install:

```bash
git clone https://github.com/iic-jku/prep-ic.git
cd prep-ic

python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate

pip install -e .
```

The only dependency is PySide6-Essentials, which pip installs with it. On Linux with Python 3.10 or 3.11 it stays below 6.12, since a reference count bug in the 6.12.0 Linux wheels crashes these Python versions (see [PYSIDE-3474](https://qt-project.atlassian.net/browse/PYSIDE-3474), fixed for 6.12.1).

### Run the GUI

```bash
prep-ic              # after installing
prep-ic chip.json    # the same, opened on that project
```

Without a file the GUI opens the project of the last session, or the built-in example on the first start. *File → Load Example* loads that example again, and more projects live in [`examples/`](https://github.com/iic-jku/prep-ic/tree/main/examples).

From a source checkout without installing, put `src` on the Python path and start the package as a module:

```bash
PYTHONPATH=src python -m prep_ic                   # macOS / Linux
$env:PYTHONPATH = "src"; python -m prep_ic         # Windows PowerShell
```

### Typical workflow

1. **Type the pads** of each side in the *Pads* tab, one line per pad (see [Entry syntax](https://github.com/iic-jku/prep-ic#entry-syntax)). The die grows with them, and the gutter shows each pad's pin number.
2. **Choose the technology** in *Settings → Technology*: a PDK and optionally a package. The ring then shows the real IO cells, and the *Pin List* shows each pad's IO cell, power domain and package pin.
3. **Split the power domains** with `=== NAME` lines where the IO ring is cut.
4. **Add the macros** in the *Macros* tab from their LibreLane run directories, place them in the *Chip* view and check the pins that go off-chip.
5. **Fix the pinout** with *Optimize Pad Order*, *Add Missing Pads* and *Suggest Supply Pads*, until the stat tiles and the warning line are clean.
6. **Export** the LibreLane files (*File → Export LibreLane Files…*), the pin list (*File → Export Pin List as CSV…*) or the drawing (*File → Export Padframe as SVG…* or *as PNG…*), and save the project as JSON.

### Entry syntax

One line per entry. Each side lists its pads as seen on the die: top and bottom from left to right, left and right from top to bottom. Empty lines, also at the end of a side, are spacers.

| Entry | Meaning |
|---|---|
| `VDDA` | pad, type guessed from the name |
| *(empty line)* | spacer slot of one standard pitch |
| `NC` | pad without connection |
| `NAME [p\|g\|a\|rf\|d\|c\|nc]` | force type: power, ground, analog, RF, digital, clock, NC |
| `NAME {80x60}` | custom bond pad size W × H in µm (W along the edge) |
| `NAME @120` | custom pitch in µm |
| `RFIN [gsg]`, `[gs]`, `[sg]` | RF group, e.g. GND, RFIN, GND |
| `LO [gsgsg]` | differential: GND, LO_P, GND, LO_N, GND |
| `NAME [in\|out\|tri\|io\|analog\|vdd\|vss\|iovdd\|iovss\|none]` | IO function, selects the IO cell (default guessed from name and type) |
| `NAME [16mA]` | drive strength of output, tristate and bidirectional cells |
| `NAME [schmitt]`, `NAME [noesd]` | another IO cell of the same function, where the PDK has one: a Schmitt trigger input, an analog pad without ESD clamp |
| `NAME [lock]` | locked pad: it can no longer be dragged and *Optimize Pad Order* leaves it in place |
| `=== NAME` | power split: cuts the IO ring here and starts power domain `NAME` |

Options combine: `RFOUT [gsg] {70x70} @125`, `DOUT[3] [out] [4mA]`. An unknown tag or a malformed option stays in the pad name together with the options left of it, so `A [in] [foo]` is a pad named `A [in] [foo]` and `A {60x}` a pad named `A {60x}`. A size or pitch below 1 µm and `[0mA]` count as malformed. The warning line and `prep-ic check` report it.

### PDK, package and LibreLane

In *Settings → Technology* choose a PDK (IHP SG13G2 or SG13CMOS5L) and optionally a package from the EUROPRACTICE library.

- **With a PDK** the preview shows the real ring: the seal ring spacing, the IO cells, the corner cells and the bondpads (sizes in [Supported PDKs and Packages](https://github.com/iic-jku/prep-ic#supported-pdks-and-packages)). Function and drive of each pad are set in the *Pin List* or with tags in the editor. The rows of the *Pin List* also show the IO cell, the power domain and the package pin.
- **Power splits**: an `=== NAME` line leaves a 10 µm gap in the IO ring. Every ring segment gets its own rails (`VDD_NAME`, `VSS_NAME`, `IOVDD_NAME`, `IOVSS_NAME`), and without splits they are `VDD`, `VSS`, `IOVDD` and `IOVSS`. PREP-IC warns when a domain has no supply pad of a kind.
- **The LibreLane tab and *File → Export LibreLane Files…*** write:
  - `padring_config.yaml`: `DIE_AREA`, `CORE_AREA`, `PAD_CFG` and the `PAD_SOUTH/EAST/NORTH/WEST` lists, to copy into the LibreLane `config.yaml` (flow `Chip`),
  - `pad_cfg.tcl`: places the IO cells exactly as planned (LibreLane's default script spreads them evenly) and keeps the split gaps free,
  - `chip_top.sv`: the IO cell instances with the same names, the top-level `*_PAD` ports and the `chip_core` instance,
  - `chip_core_template.sv`: the matching core ports, and with macros the instances to create in the core,
  - `macros.yaml` (with macros): `MACROS` with LEF and GDS, the `vh`, `nl`, `pnl`, `lib` and `spef` views found in LibreLane's layout below `final/`, and the instance locations (`i_chip_core.<instance>`),
  - `bondplan_pinout.yaml` (with a package): `PACKAGE_NAME` and `PINOUT` for the bondplan config.
- An IHP design must still provide the bondpad cell (`PAD_BONDPAD_NAME`, e.g. `sg13g2_ip__bondpad_70x70` with `EXTRA_LEFS` and `EXTRA_GDS`). The IO cells of sky130A and gf180mcuD carry their own bond pad.
- On sky130A and gf180mcuD, `padring_config.yaml` ends with a comment naming the IO cells LibreLane's disconnected pin check has to skip (gf180mcuD output pads leave `Y` open, the sky130A connect cells and analog pads mark no pin as a power pin). Add them to `IGNORE_DISCONNECTED_MODULES` in your `config.yaml`. The export writes no key there, since it would replace your own list.

See [`examples/ihp_sg13g2_domains.json`](https://github.com/iic-jku/prep-ic/blob/main/examples/ihp_sg13g2_domains.json). From the command line:

```bash
prep-ic export examples/ihp_sg13g2_domains.json --librelane flow/padring
```

### Chip view

The *Chip* tab shows the whole chip: the IO ring with the pads, the core area inside it, the macros and a flyline from every checked macro pin to the pad with the same name. The left panel has two tabs, *Pads* (the side editors) and *Macros* (the macro list).

**Macros**

- *Add Macro…* (in the *Macros* tab or the *File* menu) takes a LibreLane run directory, e.g. `macros/adc_sar/`. Size and pins come from `final/lef/adc_sar_top.lef`, or from the only `*.lef` in `final/lef/`. The project stores the path, and the LEF is read again when the project opens and with *File → Reload Macros* (F5). One macro can be placed several times (`adc_sar0`, `adc_sar1`, …). *Add Placeholder…* adds a box without a LEF.
- Drag a macro to move it. It snaps to the grid (default 10 µm) and to the edges of other macros, and a dashed guide shows the edge it snapped to. Double-click or *Rotate* turns it by 90°, and *Auto-rotate* picks the rotation with the shortest flylines. Shift-click selects macros for *Align Left* and *Align Top*.
- Per macro: the pins that go off-chip, the class (`normal`, `sensitive` for analog and RF, `noisy` for digital or clocks), the power domain and the halo.

**Pads**

- Drag a pad (or a `=== NAME` split marker) along the ring to move it, also to another side, and the side editors follow. Dropped on another pad it is sorted in. Dropped on an empty part of a side (or on a spacer) it stays exactly there and no other pad moves, because empty lines fill the distance.
- Alt-click locks a pad (tag `[lock]`).
- *Add Missing Pads* adds a pad for every checked pin without one, where its dashed line points. *Suggest Supply Pads* adds VDD and VSS pads (named after the macro's LEF power pins) next to the macros that have none of their domain within reach.
- *Optimize Pad Order* sorts the connected pads of each side by the positions of their macro pins, so the flylines no longer cross. Differential pairs (`VIN_P` and `VIN_N`) stay together.

**Checks** (thresholds in *Settings → Checks*)

- Crossing flylines (orange, counted in the stat tiles) and the longest analog or RF flyline.
- Differential pairs that are not adjacent.
- A sensitive pad next to a noisy one. A connected pad takes the class of its macro, the others their type.
- Overlapping macros, macros outside the core, overlapping halos, and sensitive and noisy macros closer than the minimum distance.
- A macro without a VDD and a VSS pad of its domain within the distance. IO supplies don't count.

*Layers* hides the grid, pads, macros, halos, flylines, power domains or pad names, and *Measure* shows distances. *Edit → Undo* and *Redo* (Ctrl+Z, Ctrl+Shift+Z) cover all chip view and macro list actions. Typing in a side editor keeps its own undo while the editor has the focus.

In the *Fixed core size (minimum)* mode, which is set when the first macro is added, the die follows the core size: it is at least the core plus the IO ring (plus the PDK core margin) and still grows with the pads.

**Demo**: [`examples/chip_demo.json`](https://github.com/iic-jku/prep-ic/blob/main/examples/chip_demo.json) uses the demo macros in [`examples/macros/`](https://github.com/iic-jku/prep-ic/tree/main/examples/macros), abstract LEFs of an ADC, a PLL, an LNA and a digital core in the LibreLane run layout `final/lef/<name>_top.lef`. It starts with one crossing and one missing pad, so try *Optimize Pad Order* and *Add Missing Pads*. *Export MACROS…* shows the `macros.yaml` it exports.

### Scripting

The package works without Qt:

```python
import prep_ic as prep

project = prep.load("chip.json")
project.sides["L"].append("VDDA [p]")
project.settings.std.pitch = 90
layout = project.layout()
print(layout.die_width, layout.die_height, layout.warnings)
for pin in layout.pins:
    print(pin.no, pin.name, pin.x, pin.y)
prep.export_csv(project, "pins.csv")
prep.export_svg(project, "ring.svg")
prep.save(project, "chip.json")

macro = prep.Macro.from_dir("macros/adc_sar", "adc0")  # reads final/lef/adc_sar_top.lef
macro.io = ["VIN_P", "VIN_N"]
project.floorplan.macros.append(macro)
prep.add_missing_pads(project)                         # adds VIN_P/VIN_N pads, fixed core mode
print(prep.analyse(project).warnings)                  # crossings, tags, pairs, analog and power checks
print(prep.findings(project))                          # the same plus layout and macro LEF warnings

project.settings.pdk = "ihp-sg13g2"                    # see prep.pdk_names()
project.settings.package = "OP_QFN32_A4_FIT"           # see prep.package_names()
prep.export_librelane(project, "flow/padring")         # padring_config.yaml, pad_cfg.tcl, chip_top.sv, ...
```

`project.sides` holds each side in numbering order. `project.physical_lines(side)` and `project.set_physical_lines(side, lines)` use the order as seen on the die, like the GUI.

See [`examples/script_example.py`](https://github.com/iic-jku/prep-ic/blob/main/examples/script_example.py).

### Run the tests

```bash
python -m unittest discover -s tests -t .    # from the repo root
```

The GUI tests run offscreen and are skipped when Qt is not installed.


## CLI Overview

| Command | Does |
|---|---|
| `prep-ic` | start the GUI on the last project |
| `prep-ic chip.json` | start the GUI on `chip.json` |
| `prep-ic --version` | print the version |
| `prep-ic export chip.json --csv pins.csv` | write the pin list as CSV |
| `prep-ic export chip.json --svg ring.svg` | write the drawing as SVG |
| `prep-ic export chip.json --librelane DIR` | write the LibreLane files into `DIR` (needs a PDK in the project) |
| `prep-ic check chip.json` | list the findings of the project |

The `export` options combine, e.g. `prep-ic export chip.json --csv pins.csv --svg ring.svg`. Each written LibreLane file is printed, and all findings go to stderr. Exit code 0 from `export` says only that the files were written, so gate a script on `check`: it prints one finding per line or `no findings`, and exits 0 when clean, 1 with findings and 2 when the check did not run. A finding is a layout warning, an entry of the project file that could not be read, a macro LEF that is gone, a marked pin no longer in the LEF, or what `prep.analyse` reports: unknown tags and options, bad power domain names, crossings, long analog flylines, pins without a pad, split differential pairs, sensitive pads next to noisy ones, macro and supply checks. Both commands run without Qt. From a source checkout without installing, use `python -m prep_ic` with `src` on the Python path in place of `prep-ic`.


## Supported PDKs and Packages

The PDK profiles are taken from the IO cell LEF and the LibreLane IO config of each PDK (`libs.ref/<io_library>/lef/` and `libs.tech/librelane/<io_library>/config.tcl`).

| | IHP SG13G2 | IHP SG13CMOS5L | sky130A | gf180mcuD |
|---|---|---|---|---|
| Profile name | `ihp-sg13g2` | `ihp-sg13cmos5l` | `sky130A` | `gf180mcuD` |
| IO library | `sg13g2_io` | `sg13cmos5l_io` | `sky130_ef_io` | `gf180mcu_fd_io` |
| IO cell (width × depth) | 80 × 180 µm | 80 × 180 µm | 80 × 198 µm GPIO, 75 × 198 µm supply, 75 × 200 µm analog | 75 × 350 µm |
| Corner cell | 180 × 180 µm | 180 × 180 µm | 200 × 204 µm | 355 × 355 µm |
| Bond pad | 70 × 70 µm, a separate cell | 70 × 70 µm, a separate cell | in the IO cell, 62.6 × 62.45 µm GPIO | in the IO cell, 60 × 60 µm |
| Seal ring spacing | 140 µm | 140 µm | 0 (added after the ring) | 26 µm |
| Minimum pad pitch (IO cell width) | 80 µm | 80 µm | 80 µm | 75 µm |
| Core margin (core power ring) | 45 µm | 45 µm | 100 µm | 61 µm |
| Power split gap and filler | 10 µm, `sg13g2_Filler2000` | 10 µm, `sg13cmos5l_Filler2000` | none, a split gets a warning | none, a split gets a warning |

A new project starts standard pads at the minimum pitch and RF pads at 100 µm. Selecting a PDK in the GUI raises a pitch below the minimum to 100 µm.

The IO function of a pad selects its cell (`<lib>` is `sg13g2` or `sg13cmos5l`, the sky130A cells start with `sky130_ef_io__`, the gf180mcuD ones with `gf180mcu_fd_io__`):

| Function | IHP | sky130A | gf180mcuD |
|---|---|---|---|
| `[in]` | `<lib>_IOPadIn` | `gpiov2_pad` | `in_c`, with `[schmitt]` `in_s` |
| `[out]` | `<lib>_IOPadOut<drive>mA` | `gpiov2_pad` | `bi_24t` |
| `[tri]` | `<lib>_IOPadTriOut<drive>mA` | `gpiov2_pad` | `bi_24t` |
| `[io]` | `<lib>_IOPadInOut<drive>mA` | `gpiov2_pad` | `bi_24t` |
| `[analog]` | `<lib>_IOPadAnalog` | `analog_esd_pad`, with `[noesd]` `analog_noesd_pad` | `asig_5p0` |
| `[vdd]`, `[vss]` | `<lib>_IOPadVdd`, `<lib>_IOPadVss` | `vccd_lvc_clamped_pad`, `vssd_lvc_clamped_pad` | `dvdd`, `dvss` |
| `[iovdd]`, `[iovss]` | `<lib>_IOPadIOVdd`, `<lib>_IOPadIOVss` | `vddio_hvc_clamped_pad`, `vssio_hvc_clamped_pad` | `dvdd`, `dvss` |
| `[none]` | no IO cell | no IO cell | no IO cell |
| Drive | 4, 16 or 30 mA, default 30 mA | none, a drive tag gets a warning | 24 mA, another drive gets a warning |

The control pins of the sky130A and gf180mcuD cells are tied per function in `chip_top.sv`, so the core ports are the same as for IHP.

On sky130A, PREP-IC adds two 20 µm connect cells in front of the first IO supply pad. They tie `VCCHIB` to `VCCD`, `VSWITCH` and `VDDA` to `VDDIO`, and `VSSA` to `VSSIO`, and that side grows by 40 µm. On gf180mcuD, the `dvdd` and `dvss` pads short their two supply rings, so the IO supply and the core supply are one net (`VDD`, `VSS`).

[`examples/`](https://github.com/iic-jku/prep-ic/tree/main/examples) has one project per wafer.space gf180mcuD slot (`wafer_space_slot_*.json`) with the die of the slot, its pad order and the supply pads locked. Name your signals and save it under a new name.

The 25 packages are named after the cells of the EUROPRACTICE package library (`EP_PACKAGES_08022018.gds`). Their pins are numbered counter-clockwise, seen from the top.

| Family | Pins | Pin 1 |
|---|---|---|
| QFN | 16, 24, 32, 40, 48, 56, 64, 80, 88, 100 | top of the left side |
| JLCC | 44, 68, 84 | centre of the top side |
| CLCC | 44, 68, 84 | centre of the top side |
| SOIC | 16, 20, 24, 28 | top of the left side |
| DIL | 16, 24, 28, 40, 48 | top of the left side |

A further PDK is one more JSON file in `src/prep_ic/data/pdks/`, with the fields of `model/pdk.py`, a further package one more entry in `src/prep_ic/data/packages.json`.


## Cite This Work

```
@misc{2026_prep_ic,
  author = {Golser, Maximilian and Dorrer, Simon},
  month = nov,
  year = {2026},
  title = {{GitHub Repository of PREP-IC: Pinout, Ring and Early floorplan Planner for ICs}},
  url = {https://github.com/iic-jku/prep-ic},
  doi = {10.5281/zenodo.23963620}
}
```


## Acknowledgements

- The IO cell profiles and the LibreLane pad ring files follow the IO libraries and the LibreLane integration of the [IHP Open PDK](https://github.com/IHP-GmbH/IHP-Open-PDK), sky130A and gf180mcuD, and the ring wiring of the public chip templates [sky130A-ams-chip-template](https://github.com/iic-jku/sky130A-ams-chip-template) and [gf180mcuD-ams-chip-template](https://github.com/iic-jku/gf180mcuD-ams-chip-template).
- The exports are made for the `Chip` flow of [LibreLane](https://github.com/librelane/librelane).
- The package names and pin counts come from the [EUROPRACTICE](https://europractice-ic.com) package library.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/iic-jku/prep-ic/main/doc/fig/jku_white.svg">
    <img src="https://raw.githubusercontent.com/iic-jku/prep-ic/main/doc/fig/jku.svg" alt="Johannes Kepler University Linz" height="174">
  </picture>
</p>


## License

Licensed under the **Apache License 2.0**, see [`LICENSE`](https://github.com/iic-jku/prep-ic/blob/main/LICENSE).
