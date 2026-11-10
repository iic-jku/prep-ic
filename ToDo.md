# ToDo

Planned work on PREP-IC. Each item names the files it touches. Remove an item in the commit that finishes it.


## Found in the review of 0.1.2

Each of these needs a choice or more than a small fix, so they wait for a later release.

- [ ] **One macro name from two paths in `macros.yaml` (`formats/librelane.py`, `macros_yaml`).** Instances group by name and path while `MACROS` is keyed by name, so two run directories of one module, or one directory spelled two ways in a hand-edited file, write a duplicate key that LibreLane's loader rejects. Group by resolved path and report a real conflict.
- [ ] **Hand-made `final/` layouts in `macros.yaml` (`formats/librelane.py`, `_macro_views`).** Only LibreLane's layout is read. Of 64 macro directories in the group's chip repos, 30 have a flat `final/lib/<name>.lib`, which names no corner for a key, and 6 have `final/vh/<name>.v`. The chip templates list such a lib by hand as `lib: {"*": [...]}` for some macros and leave it out for others. Decide whether to export them or to name them in a comment.
- [ ] **`lef:` in `macros.yaml` names `<macro>.lef`, not the file that was read (`formats/librelane.py`, `model/floorplan.py`).** `find_lef` accepts the only `*.lef` of `final/lef/`, so a LEF named otherwise than its macro exports a path that does not exist. None of the 64 directories has this.
- [ ] **A marked pin that became `USE POWER` in the LEF loses its flyline without a finding (`model/floorplan.py`).**
- [ ] **`findings()` keeps load warnings after a reload (`model/chip.py`).** A script that calls `project.floorplan.reload()` has to set `project.load_warnings` itself, as the GUI does, or stale `No LEF found` lines stay.
- [ ] **"Qt is missing" hides the real import error (`gui/qt.py`).** A PySide6 that is installed but cannot load, for lack of `libEGL.so.1` for example, gets the advice to install it, and the cause is lost.


## Other repos

- [ ] **snp2le has the same PySide6 dependency (`pyproject.toml`).** It declares `PySide6-Essentials>=6.6` and Python 3.10 with no limit for Linux. Four of its GUI test files (25 tests) pass on Linux with Python 3.10 and PySide6 6.12.0, and it calls neither of the two `QFont` setters measured here, but other calls and a long session were not measured.
- [ ] **snp2le's `CITATION.cff` fails validation.** `date-released: 2026` is no full date, so `cffconvert --validate` rejects it.


## New PDKs: sky130A and gf180mcuD

Neither PDK fits the current profile format, which follows the IHP IO libraries: one cell width, a separate bondpad cell, one pin per supply rail and IO cells without control pins. So one more JSON file in `src/prep_ic/data/pdks/` is not enough. The profile format grows first, then the two profiles follow.

The references are the IO libraries of each PDK (`libs.ref/<io_library>/lef/` and the LibreLane PDK config) and the public chip templates [sky130A-ams-chip-template](https://github.com/iic-jku/sky130A-ams-chip-template) and [gf180mcuD-ams-chip-template](https://github.com/iic-jku/gf180mcuD-ams-chip-template), whose `rtl/chip_top.sv` and `flow/librelane/` hold a working pad ring of each PDK. Every number in a profile comes from the LEF, as for the IHP profiles.

### Profile format (`model/pdk.py`, `model/layout.py`, `formats/librelane.py`, `gui/main_window.py`)

- [ ] **Cell width per function.** `Pdk.cell_width` is one number for all IO cells. It centers the cell in its slot and sets the pitch warning in `model/layout.py` and the positions in `pad_cfg_tcl`. The sky130 ring mixes 80 µm GPIO pads with 75 µm supply and analog pads.
- [ ] **Bond pad inside the IO cell.** The sky130 and gf180mcu IO cells carry their own bond pad. The profile needs a way to say so. Then the layout draws no separate bondpad between seal ring and cell, the GUI takes the pad size from the cell, and `pad_cfg.tcl` and the README no longer ask for `PAD_BONDPAD_NAME`.
- [ ] **Several supply pins per rail.** `power_pins` maps each rail kind to one pin. The sky130 GPIO pad has ten supply pins (`VCCD`, `VCCHIB`, `VSSD`, `VDDIO`, `VDDIO_Q`, `VDDA`, `VSWITCH`, `VSSIO`, `VSSIO_Q`, `VSSA`), several of them on the same rail. Supply pads have other pin sets than the GPIO pad, so the map belongs to each cell, with the PDK-wide one as default.
- [ ] **Tied control pins.** The `pins` map of a cell knows only the roles `pad`, `in`, `out`, `oe` and `analog`. The sky130 GPIO pad needs its mode pins (`DM`, `INP_DIS`, `IB_MODE_SEL`, `VTRIP_SEL`, `SLOW`, `HLD_*`, `ENABLE_*`, `ANALOG_*`) tied per function, partly to the pad's own `TIE_HI_ESD` and `TIE_LO_ESD`. The gf180mcu bidirectional pad has `CS`, `SL`, `IE`, `PU` and `PD` next to `A`, `OE`, `Y` and `PAD`. A `ties` map per function (pin to constant or tie net) covers both. Decide which of them become core ports instead: the gf180mcuD template drives all five from the core.
- [ ] **Active-low output enable.** The sky130 `OE_N` is active low, so the `oe` role needs a polarity in the profile, and `chip_top.sv` an inversion or a core port of the right sense.
- [ ] **Ring cells that are not pads.** The sky130 ring needs the 20 µm connect slices `sky130_ef_io__connect_vcchib_vccd_and_vswitch_vddio_slice_20um` and `sky130_ef_io__connect_vdda_vddio_and_vssa_vssio_slice_20um`. The model knows pads, spacers and the split filler only. Such cells take room on a side, so they belong in the layout and the die size, in the `PAD_*` lists and in `chip_top.sv`.
- [ ] **Power splits per PDK.** A split is an IHP gap of `split_gap`, kept free by a temporary `split_filler` during the IO fill. The sky130 ring buses run through the pads by abutment, so a domain cut needs a cell of the library that breaks them. Candidates to check are `sky130_ef_io__disconnect_vccd_slice_5um` and `sky130_ef_io__disconnect_vdda_slice_5um` in sky130, and `__brk2` and `__brk5` in the gf180mcu IO libraries. Make the split mechanism an entry of the profile, and refuse splits for a PDK without one.
- [ ] **Rail and function names per PDK.** gf180mcu calls the IO rails `DVDD` and `DVSS`, and the wafer.space slot files reference them by name. `gf180mcu_fd_io` has no separate core supply pad: the gf180mcuD template uses its `dvdd` and `dvss` cells for the core supply as well, where `gf180mcu_ocd_io` has `vdd` and `vss` cells. The profile has to allow two functions on one master.
- [ ] **Drive strength per PDK.** The tags `[4mA]`, `[16mA]` and `[30mA]` select IHP masters. The sky130 GPIO pad has no drive variants (it has `SLOW` and the `DM` modes). gf180mcu has the fixed 24 mA cell `__bi_24t` that the template uses, and `__bi_t` with the drive select pins `PDRV0` and `PDRV1`, to check against the LEF. A tag the PDK cannot honor gets a warning.

### sky130A (`data/pdks/sky130a.json`)

- [ ] Profile from `libs.ref/sky130_fd_io/lef/` and the sky130A LibreLane config: `[in]`, `[out]`, `[tri]` and `[io]` on `sky130_ef_io__gpiov2_pad` with their ties, `[analog]` on `sky130_ef_io__analog_esd_pad` (and `sky130_ef_io__analog_noesd_pad` for a bare pad, as a tag), the supplies on `sky130_ef_io__vccd_lvc_clamped_pad`, `sky130_ef_io__vssd_lvc_clamped_pad`, `sky130_ef_io__vddio_hvc_clamped_pad` and `sky130_ef_io__vssio_hvc_clamped_pad`.
- [ ] Geometry from the LEF. The template's `config.yaml` states 80 µm GPIO pads, 75 µm supply and analog pads, 198 µm deep pads, 200 µm corners and a 1 µm site. Confirm them there and read the seal ring spacing from the PDK config.
- [ ] `chip_top.sv` style. The template wraps each GPIO role in a `chip_pad_*` module, so its `PAD_*` lists name `<wrapper>.pad_cell`. Flat instances with the ties inline keep the planner's `pad_<name>` names and need no extra modules. Pick one.
- [ ] Example project (`examples/sky130a_*.json`), an entry in `tests/data/layout_baseline.json`, and export tests next to the IHP ones in `tests/test_pdk.py`.

### gf180mcuD (`data/pdks/gf180mcud.json`)

- [ ] Profile from `libs.ref/gf180mcu_fd_io/lef/` and `libs.ref/gf180mcu_ocd_io/lef/` (one profile each, or a library choice in one profile) and the gf180mcuD LibreLane config: `[in]` on `__in_c` (or the Schmitt trigger `__in_s`, as a tag), `[out]`, `[tri]` and `[io]` on a bidirectional cell with ties, `[analog]` on `__asig_5p0`, the supplies on `__dvdd` and `__dvss`, plus `__vdd` and `__vss` in `gf180mcu_ocd_io`.
- [ ] Geometry from the LEF: cell width, depth, corner and site. The template flow adds the seal ring with `KLayout.SealRing`, and its die includes 26 µm of seal ring per side, so `edge_spacing` needs a look.
- [ ] **wafer.space slots.** A chip for a wafer.space gf180mcu run goes into one of four fixed slots, each with a fixed die, pad count and pad order (`flow/librelane/slots/slot_*.yaml` in the template, e.g. `DIE_AREA: [0, 0, 3932, 5122]` for `slot_1x1`). A slot preset (fixed die, locked supply pads, open signal slots) lets the planner assign the signals to a slot instead of growing the die.
- [ ] Example project, baseline entry and tests as for sky130A.

### After both

- [ ] README: the PDK table and the IO cell table in *Supported PDKs and Packages* (the latter assumes `<lib>_IOPad*` names), the *IMPORTANT* box that names only the IHP Open PDK, the `PAD_BONDPAD_NAME` line, and the closing sentence on adding a PDK. `doc/architecture.md`: the grid note (1 µm for both IHP profiles) and *Data, not code, for technologies*.
- [ ] A test that compares every profile with its LEF when the PDK is installed (`$PDK_ROOT`) and is skipped otherwise, so a PDK update that changes a cell shows up.
