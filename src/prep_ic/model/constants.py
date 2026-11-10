# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Constants shared by the model, the exporters and the GUI."""

SIDES = ("T", "R", "B", "L")
SIDE_NAMES = {"T": "Top", "R": "Right", "B": "Bottom", "L": "Left"}

# Numbering order of the sides per mode. Each side lists its entries in numbering order;
# REV marks the sides whose numbering runs against the geometric direction
# (left → right on top/bottom, top → bottom on left/right).
ORDER = {"ccw": ("L", "B", "R", "T"), "cw": ("T", "R", "B", "L")}
REV = {
    "ccw": {"L": False, "B": False, "R": True, "T": True},
    "cw": {"T": False, "R": False, "B": True, "L": True},
}
MODES = tuple(ORDER)
ALIGNS = ("center", "start")

TYPES = ("pwr", "gnd", "ana", "rf", "clk", "dig", "nc")
TYPE_NAMES = {"pwr": "Power", "gnd": "Ground", "ana": "Analog", "rf": "RF",
              "clk": "Clock", "dig": "Digital", "nc": "NC"}
TAGS = {"p": "pwr", "g": "gnd", "a": "ana", "rf": "rf", "r": "rf", "d": "dig", "c": "clk", "nc": "nc"}
GROUPS = {"gsg": "GSG", "gs": "GS", "sg": "SG", "gsgsg": "GSGSG"}

# IO function of a pad: selects the IO cell of the PDK
FUNCTIONS = ("in", "out", "tri", "inout", "analog", "vdd", "vss", "iovdd", "iovss", "none")
FUNCTION_NAMES = {"in": "Input", "out": "Output", "tri": "Tristate output", "inout": "Bidirectional",
                  "analog": "Analog", "vdd": "Core supply", "vss": "Core ground", "iovdd": "IO supply",
                  "iovss": "IO ground", "none": "No IO cell"}
FUNCTION_TAGS = {"in": "in", "out": "out", "tri": "tri", "io": "inout", "inout": "inout", "analog": "analog",
                 "vdd": "vdd", "vss": "vss", "iovdd": "iovdd", "iovss": "iovss", "none": "none"}
VARIANT_TAGS = ("schmitt", "noesd")  # a tag that picks another IO cell of the same function, if the PDK has one
POWER_FUNCTIONS = ("vdd", "vss", "iovdd", "iovss")
# Rail names of the IO ring; with power domains they get a "_<domain>" suffix
RAILS = {"vdd": "VDD", "vss": "VSS", "iovdd": "IOVDD", "iovss": "IOVSS"}
SPLIT_PREFIX = "==="  # editor line "=== NAME" splits the IO ring and starts power domain NAME

EXAMPLE = {  # in CCW order
    "L": ["VDDIO", "VSSIO", "RST_N", "CS_N", "SCLK", "SDI", "SDO", "VDDD", "VSSD"],
    "B": ["CLK_IN", "VSSD", "", "VDDA", "VSSA", "IBIAS", "VREF", "VSSA"],
    "R": ["VDDA", "RFOUT [gsg]", "VSSA", "", "TEST_EN", "NC"],
    "T": ["VDDIO", "LO [gsgsg]", "VDD_RF", "VSS_RF"],
}
