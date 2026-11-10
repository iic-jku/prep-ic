# ToDo

Planned work on PREP-IC. Each item names the files it touches. Remove an item in the commit that finishes it.


## Other repos

- [ ] **snp2le has the same PySide6 dependency (`pyproject.toml`).** It declares `PySide6-Essentials>=6.6` and Python 3.10 with no limit for Linux. Four of its GUI test files (25 tests) pass on Linux with Python 3.10 and PySide6 6.12.0, and it calls neither of the two `QFont` setters measured here, but other calls and a long session were not measured.
- [ ] **snp2le's `CITATION.cff` fails validation.** `date-released: 2026` is no full date, so `cffconvert --validate` rejects it.


## New PDKs: what stays open

Both profiles are in and go through `OpenROAD.PadRing` with every pad and bond pad centre as planned. No whole flow has run on either yet.

- [ ] **Power splits on sky130A and gf180mcuD (`data/pdks/`).** Both refuse a split with a warning, since their supply buses run through the pads and need a library cell that breaks them. Candidates to check are `sky130_ef_io__disconnect_vccd_slice_5um` and `sky130_ef_io__disconnect_vdda_slice_5um` in sky130, and `__brk2` and `__brk5` in the gf180mcu IO libraries.
- [ ] **`gf180mcu_ocd_io` (`data/pdks/`).** The image's `libs.ref` holds only `gf180mcu_fd_io`, so the profile covers that library. `gf180mcu_ocd_io` has separate `vdd` and `vss` cells.
- [ ] **gf180mcuD drive select (`data/pdks/gf180mcud.json`).** Only the fixed 24 mA `__bi_24t` is in the profile. `__bi_t` has the drive select pins `PDRV0` and `PDRV1`, but no file of the PDK says which value selects which current.
