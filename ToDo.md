# ToDo

Planned work on PREP-IC. Each item names the files it touches. Remove an item in the commit that finishes it.


## Other repos

- [ ] **snp2le has the same PySide6 dependency (`pyproject.toml`).** It declares `PySide6-Essentials>=6.6` and Python 3.10 with no limit for Linux. Four of its GUI test files (25 tests) pass on Linux with Python 3.10 and PySide6 6.12.0, and it calls neither of the two `QFont` setters measured here, but other calls and a long session were not measured.
- [ ] **snp2le's `CITATION.cff` fails validation.** `date-released: 2026` is no full date, so `cffconvert --validate` rejects it.


## New PDKs: sky130A and gf180mcuD

Neither PDK fits the current profile format, which follows the IHP IO libraries: one cell width, a separate bondpad cell, one pin per supply rail and IO cells without control pins. So one more JSON file in `src/prep_ic/data/pdks/` is not enough. The profile format grows first, then the two profiles follow.

The references are the IO libraries of each PDK (`libs.ref/<io_library>/lef/` and the LibreLane PDK config) and the public chip templates [sky130A-ams-chip-template](https://github.com/iic-jku/sky130A-ams-chip-template) and [gf180mcuD-ams-chip-template](https://github.com/iic-jku/gf180mcuD-ams-chip-template), whose `rtl/chip_top.sv` and `flow/librelane/` hold a working pad ring of each PDK. Every number in a profile comes from the LEF, as for the IHP profiles.

### Profile format (`model/pdk.py`, `model/layout.py`, `formats/librelane.py`, `gui/main_window.py`)


### sky130A (`data/pdks/sky130a.json`)


### gf180mcuD (`data/pdks/gf180mcud.json`)

- [ ] **wafer.space slots.** A chip for a wafer.space gf180mcu run goes into one of four fixed slots, each with a fixed die, pad count and pad order (`flow/librelane/slots/slot_*.yaml` in the template, e.g. `DIE_AREA: [0, 0, 3932, 5122]` for `slot_1x1`). A slot preset (fixed die, locked supply pads, open signal slots) lets the planner assign the signals to a slot instead of growing the die.

### After both

- [ ] README: the PDK table and the IO cell table in *Supported PDKs and Packages* (the latter assumes `<lib>_IOPad*` names), the *IMPORTANT* box that names only the IHP Open PDK, the `PAD_BONDPAD_NAME` line, and the closing sentence on adding a PDK. `doc/architecture.md`: the grid note (1 µm for both IHP profiles) and *Data, not code, for technologies*.
