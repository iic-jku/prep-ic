# ToDo

Planned work on PREP-IC. Each item names the files it touches. Remove an item in the commit that finishes it.


## Waiting for the PDK

- [ ] **`[padbare]` for IHP analog pads (`data/pdks/ihp-sg13g2.json`, `data/pdks/ihp-sg13cmos5l.json`).** The chip templates' own IO library (`ip/*_io_custom`) gives `IOPadAnalog` a `padbare` pin, the pad without the series resistor of `padres`, and iic-jku/IHP-Open-PDK#37 brings it into the PDK. Once the PDK in IIC-OSIC-TOOLS has it, a `[padbare]` variant can wire the core to `padbare`, and `tests/test_pdk_lef.py` checks the pin.

## New PDKs: what stays open

Both profiles are in and go through `OpenROAD.PadRing` with every pad and bond pad centre as planned. No whole flow has run on either yet.

- [ ] **Power splits on sky130A and gf180mcuD (`data/pdks/`).** Both refuse a split with a warning, since their supply buses run through the pads and need a library cell that breaks them. Candidates to check are `sky130_ef_io__disconnect_vccd_slice_5um` and `sky130_ef_io__disconnect_vdda_slice_5um` in sky130, and `__brk2` and `__brk5` in the gf180mcu IO libraries.
- [ ] **`gf180mcu_ocd_io` (`data/pdks/`).** The image's `libs.ref` holds only `gf180mcu_fd_io`, so the profile covers that library. `gf180mcu_ocd_io` has separate `vdd` and `vss` cells.
- [ ] **gf180mcuD drive select (`data/pdks/gf180mcud.json`).** Only the fixed 24 mA `__bi_24t` is in the profile. `__bi_t` has the drive select pins `PDRV0` and `PDRV1`, but no file of the PDK says which value selects which current.

## Open points of the review before 0.2.0

- [ ] **A second tag of one kind is dropped silently (`model/parse.py`).** In `A [noesd] [schmitt]` or `A @100 @200` the first one wins, nothing reports the second, and a rewrite from the GUI's *Pin List* loses it.
- [ ] **`export` can leave a partial set of files (`cli.py`, `formats/librelane.py`).** When one write fails, the files written before it stay, and with `--csv` the CSV is written before `--librelane` finds that the project has no PDK.
- [ ] **The sky130A connect cells have no label in the chip view (`model/layout.py`).** They show as two plain 20 µm boxes in front of the first IO supply pad.
