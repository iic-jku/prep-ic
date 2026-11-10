# PREP-IC Architecture

How PREP-IC is built and the rules it follows, for anyone who changes it. The module map is the README's [Directory Structure](../README.md#directory-structure), the user-facing behavior its [How to Use](../README.md#how-to-use).

## Layers and data flow

`prep_ic` is one package with a pure-Python core and a thin GUI:

- `model/`, `formats/`, `style.py`, `cli.py` and `__init__.py` import no Qt. `tests/test_formats.py` checks it twice, by a source scan and by an export and a check run that must leave PySide6, PyQt6 and shiboken6 unloaded.
- `gui/` imports Qt only through `gui/qt.py` and uses only PySide6-Essentials modules, which `tests/test_qt_essentials.py` enforces together with the `PySide6-Essentials` dependency in `pyproject.toml`. The reason is Essentials-only installs such as the IIC-OSIC-TOOLS image.

A `Project` holds the settings, the entry lines of each side and the `floorplan` (the placed macros). `build_layout(project)` (`model/layout.py`) parses the lines, numbers the pins, sizes the die and returns a `Layout`: pins, power splits and domains, warnings and drawing primitives. The primitives are plain dicts (`k` is `rect`, `line`, `circle` or `text`) that `gui/scene.py` and `formats/svg.py` both render with the styles of `style.py`, so the window and the SVG export show the same picture.

`model/chip.py` analyses a project and its layout (flylines, crossings, checks) and holds every edit of the chip view as a function on a `Project`: `move_line`, `place_line`, `toggle_lock`, `optimize_pad_order`, `add_missing_pads`, `suggest_supply_pads`, `auto_rotate` and `align_macros`. The GUI draws, maps mouse actions onto these functions and keeps the undo stack. Every edit is therefore scriptable and tested without Qt, and the GUI never changes editor text on its own.

## Conventions

- **Units and coordinates.** µm everywhere. The model has its origin at the top-left of the die with y pointing down. LEF files (origin lower-left, y up) are converted when read. The pin list and every LibreLane file use the origin at the lower-left of the die.
- **Two line orders.** `project.sides` holds each side in numbering order (counter-clockwise or clockwise). The side editors and every chip view edit use the physical order, top and bottom from left to right, left and right from top to bottom. `physical_lines`, `set_physical_lines` and `physical_line_index` convert between the two.
- **Grid.** With a PDK the pitches, pad positions and a fixed die snap to the PDK placement site (1 µm for both IHP profiles).
- **Old files stay readable.** New project keys are optional and `from_dict` falls back to the defaults. `tests/data/layout_baseline.json` pins die size, margin and pin geometry of reference projects, so a layout change shows up as a failing test.
- **Data, not code, for technologies.** A PDK profile is one JSON file in `data/pdks/` (read by `model/pdk.py`), a package one entry in `data/packages.json`.

## Die size

There are three modes:

- **Pad-limited** (default): each side is as long as the longer of it and its opposite side needs for its pads, and the die adds the IO ring depth twice.
- **Fixed die**: the die size is given. It is snapped to the site grid and enlarged with a warning when it cannot hold the IO ring.
- **Fixed core size (minimum)**: the die is at least core plus twice the IO ring depth and the PDK core margin, and still grows when the pads need more room. *Add Missing Pads* switches a pad-limited project to this mode, because then the die holds the floorplan.

A fixed die wins when both fixed modes are set. *Square* makes both sides the longer one, except with a fixed die.

## Core area and macros

There is one core in the picture: the LibreLane `CORE_AREA`, the die minus twice the IO ring depth and the PDK core margin (the room of the core power ring, 0 without a PDK). Macro `x`/`y` are the top-left corner of the placed, rotated box relative to the top-left of that area, so the `macros.yaml` export offsets x by that corner and flips y to LibreLane's lower-left origin.

- **Size and pins are never typed for a macro with a LEF.** A macro is a LibreLane run directory. `find_lef` reads `final/lef/<dirname>_top.lef`, else the only `*.lef` in `final/lef/`. In a LEF with several macros, `pick_macro` takes `<dirname>_top`, else the first.
- **The LEF is read again** when the project opens and on *Reload Macros*. The project keeps the last values as a cache, so a macro whose LEF cannot be read keeps them and a warning names it. A marked pin that is no longer in the LEF, or has become a power pin there, stays marked, is skipped and is reported.
- **Paths** are written relative to the project file and resolved against its directory on load, so *Save As* into another folder keeps them working.
- **Pins.** A pin's position is the center of the bounding box of its first port shape, or the macro center for a pin without shapes. Power pins (`USE POWER`, `USE GROUND`) are no pad candidates. They name the pads that *Suggest Supply Pads* adds.
- **Rotation** is in 90° steps clockwise, without mirroring. `macros.yaml` writes 0, 90, 180 and 270° as `N`, `E`, `S` and `W`.
- **Placeholders** have no directory, a typed size and no pins. They are left out of `macros.yaml` with a comment.
- **Views.** `macros.yaml` always names `gds` and `lef`, which LibreLane requires, and adds `vh`, `nl`, `pnl`, `lib` and `spef` for the files that exist in LibreLane's layout below `final/`. A hand-made `final/vh/<macro>.v` counts as the `vh` view. A flat `final/lib/<macro>.lib` names no corner and may not hold for all of them, so it gets a comment and is not exported, since exporting it would change the chip's timing analysis without anyone having decided that. Lint needs one of `vh`, `pnl` and `nl`, so a macro without any gets a comment that says so. `lib` and `spef` feed the chip's timing analysis, and a macro with neither may be black-boxed there. LibreLane allows one definition per macro name, so the instances of a second run directory with the same name are left out and reported.

## Flylines and missing pads

A flyline runs from a checked macro pin to the inner edge of the IO ring at the center of its pad's slot. The pad is found by name, and the first pad of a name in ring order wins, because the shield grounds of RF groups repeat `GND`. The pad name is the pin name, or `<instance>_<pin>` when several instances mark the same pin.

A checked pin without a pad gets a dashed line to the nearest die edge (ties go top, right, bottom, left) and a `+ NAME` marker. *Add Missing Pads* inserts the pad there, with the function from the LEF: `USE ANALOG` gives `[analog]`, `DIRECTION` `INPUT`, `OUTPUT`, `OUTPUT TRISTATE` and `INOUT` give `[in]`, `[out]`, `[tri]` and `[io]`. It never changes an existing line.

Two flylines cross when their straight segments intersect. Shared end points do not count.

## Moving pads

- **Sorting in** (`move_line`): the drop position is compared with the slot centers of the side (spacers interpolated from their neighbors). An RF group or a split line moves as one line. A single pad takes its differential partner on the same side along, P before N.
- **Dropping** (`place_line`, what the GUI does): dropped onto a pad or a split, the line is sorted in as above. Dropped onto a spacer, it takes that slot. Dropped onto an empty part of the side, it lands exactly there and spacer lines fill the distance, on a centered side at both ends, so no other pad moves. The line leaves spacers at its old place. Only as many spacers are added as fit, so a drop never grows the die.
- **Locked lines** (`[lock]`) raise `ValueError` in both and are left alone by *Optimize Pad Order*. A drop or insert before a locked pad on the same side can still shift it by a slot.

## Optimize Pad Order

Per side, the connected unlocked pads keep the set of slots they occupy and are sorted in it by the position of their macro pin along the side. Differential pairs are then joined by swapping within those slots only, P before N. A pair that would need a fixed line to move stays split and keeps its warning. Supplies, splits, locked and unconnected pads stay where they are.

## Checks

- **Pad classes.** A pad connected to a `sensitive` or `noisy` macro takes the macro's class. Any other pad gets one from its type: analog or RF is sensitive, clock or digital is noisy, supplies and NC are neither. The macro class comes first because `pad_type` makes every pad with a signal function digital, so an LNA's `RFIN [in]` would otherwise count as noisy.
- **Neighbors.** A sensitive pad next to a noisy one on the same side is a warning. A spacer, a split or an RF group between them breaks the adjacency.
- **Differential pairs** are single-pad lines on one side whose names differ only in a final `P`/`N` (`VIN_P`/`VIN_N`, `INP`/`INN`). They must be adjacent.
- **Flyline length.** Flylines of sensitive pads longer than *Max analog/RF flyline* (900 µm) are reported. The stat tile shows the longest.
- **Crossings.** Two flylines that cross are a warning that names their pads, next to the count in the stat tile.
- **Unknown tags and options.** A bracket, a brace or an `@` left in a pad name, other than a numeric index like the two in `D[1][2]`, is a tag or option the parser did not read. The parser stops at it, so the options left of it stay in the name too. A power domain name takes letters, digits and `_` only, since it ends up in net names.
- **Macros.** Overlaps, macros outside the core, halos that overlap (the gap between two macro boxes is smaller than the sum of their halos, 20 µm by default per macro) and sensitive and noisy macros closer than *Spacing* (100 µm).
- **Supplies.** Every macro needs a pad with function `vdd` and one with `vss` of its domain whose inner edge point is within *Max supply distance* (1000 µm) of the macro center. Supplies match by function, not by name, and IO supplies do not count. Without splits every pad is in the one domain.
- **Suggest Supply Pads** adds one pad at a time, next to the pad of the domain that is closest to the macro, on the macro's side of it. The pad is named after the macro's LEF power pin, else `VDD`/`VSS` (`VDD_<DOMAIN>` with splits), and gets an explicit `[vdd]`/`[vss]` tag. It repeats until no macro misses a supply, since one new pad can serve several macros, and tries each macro and kind once.
- **Findings.** `findings(project)` joins the layout warnings, the warnings from reading the project file (a macro entry that does not parse, a side key other than `T`, `R`, `B`, `L`) and the macro LEFs, and `analyse`. A script that reads the LEFs again calls `Project.reload_macros`, which replaces the warnings from reading. `prep-ic export` prints them and still exits 0, since the files were written. `prep-ic check` lists them and exits 0 when clean, 1 with findings and 2 when the check did not run, also on an unexpected exception, because a traceback would exit 1 and read as findings.

## Power domains

An `=== NAME` line starts the domain `NAME` in numbering order. The ring is closed, so the pads before the first split belong to the domain of the last split. Splits without a name are called `D1`, `D2`, and so on. A single split cuts the ring once and leaves one domain, and two splits that start the same name give separate segments, both with a warning. Every domain has its own rails (`VDD_NAME`, `VSS_NAME`, `IOVDD_NAME`, `IOVSS_NAME`), and without splits they are `VDD`, `VSS`, `IOVDD` and `IOVSS`.

With a PDK a split is a gap of the PDK's `split_gap` (10 µm) in the IO ring. `pad_cfg.tcl` places a filler cell of the PDK into each gap as a temporary blocker, so the IO fill leaves the gap free, and removes the blockers after the fill.

## Undo

The window keeps a stack of project snapshots. A step ends after every chip view action and macro panel edit, and when a side editor loses the focus with changed text. Settings changes are no undo steps: a restored snapshot keeps the current settings. While a side editor has the focus, Ctrl+Z is the editor's own undo.

## LibreLane export

`formats/librelane.py` writes the files listed in the README from the same `Layout`, so names match across them (`tests/test_pdk.py` compares them). `pad_cfg.tcl` places each IO cell at its planned position, where LibreLane's default script would spread them evenly. `macros.yaml` lists per macro its GDS, LEF and other views (`dir::` paths relative to the export directory, absolute in the GUI's preview and across drives) and the instances `i_chip_core.<instance>` with their lower-left location and orientation. `chip_core_template.sv` lists the macro instances to create in the core under the same names.
