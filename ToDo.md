# ToDo

Planned work on PREP-IC. Each item names the files it touches. Remove an item in the commit that finishes it.


## Waiting for the PDK

- [ ] **`[padbare]` for IHP analog pads (`data/pdks/ihp-sg13g2.json`, `data/pdks/ihp-sg13cmos5l.json`).** The chip templates' own IO library (`ip/*_io_custom`) gives `IOPadAnalog` a `padbare` pin, the pad without the series resistor of `padres`, and iic-jku/IHP-Open-PDK#37 brings it into the PDK. Once the PDK in IIC-OSIC-TOOLS has it, a `[padbare]` variant can wire the core to `padbare`, and `tests/test_pdk_lef.py` checks the pin.

## New PDKs: what stays open

Both profiles are in and go through `OpenROAD.PadRing` with every pad and bond pad centre as planned. No whole flow has run on either yet.

- [ ] **Power splits on sky130A and gf180mcuD (`data/pdks/`).** Both refuse a split with a warning, since their supply buses run through the pads and need a library cell that breaks them. Candidates to check are `sky130_ef_io__disconnect_vccd_slice_5um` and `sky130_ef_io__disconnect_vdda_slice_5um` in sky130, and `__brk2` and `__brk5` in the gf180mcu IO libraries.
- [ ] **`gf180mcu_ocd_io` (`data/pdks/`).** The image's `libs.ref` holds only `gf180mcu_fd_io`, so the profile covers that library. `gf180mcu_ocd_io` has separate `vdd` and `vss` cells.
- [ ] **gf180mcuD drive select (`data/pdks/gf180mcud.json`).** Only the fixed 24 mA `__bi_24t` is in the profile. `__bi_t` has the drive select pins `PDRV0` and `PDRV1`, but no file of the PDK says which value selects which current.

## Found while planning the chip templates

The plans of the sky130A and gf180mcuD templates (`doc/prep-ic/chip_top.json` there) showed three gaps.

- [ ] **A terminal on every listed pin (`formats/librelane.py`).** The exported `pad_cfg.tcl` places a terminal on the first pin of a master that `PAD_PLACE_IO_TERMINALS` lists, as LibreLane's script does. The sky130A template's own `pad_cfg.tcl` places one on every listed pin, so a supply pad gets a terminal on its bond pad for the packaging and one on its bus pin for the power grid analysis. Check the change through `OpenROAD.PadRing` on sky130A.
- [ ] **Supply reach on gf180mcuD (`model/chip.py`).** The check that a macro has a VDD and a VSS pad in reach counts `[vdd]` and `[vss]` pads only. On gf180mcuD, `[iovdd]` and `[iovss]` are the same `dvdd` and `dvss` cells on the same nets (`rails` in `data/pdks/gf180mcud.json`), so they should count too. The template's plan works around it by tagging three of its four supply pairs `[vdd]` and `[vss]`.
- [ ] **Bonds across a package corner (`model/layout.py`, `model/pdk.py`).** Pads map to the leads of their own side. A wafer.space slot has 17 pads on each long side and the QFN56 of the gf180mcuD template 14 leads per side, so its bondplan bonds three pads of each long side to the leads of the next side. PREP-IC reports those sides as not fitting, so the template's plan leaves the package out, and only then are its pad numbers the QFN56 pins.
