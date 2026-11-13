# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Parsing of editor lines into pad entries.

Entry syntax (one line per entry):
  VDDA                     pad, type is guessed from the name
  <empty line>             spacer slot (one standard pitch)
  NC                       pad without connection
  NAME [p|g|a|rf|d|c|nc]   force type (power, ground, analog, RF, digital, clock, NC)
  NAME {80x60}             custom bond pad size W x H in µm (W = along the edge)
  NAME @120                custom pitch in µm
  RFIN [gsg]               RF group: GND, RFIN, GND
  LO [gsgsg]               differential: GND, LO_P, GND, LO_N, GND
  RFIN [gs] / [sg]         GS or SG
  NAME [in|out|tri|io|analog|vdd|vss|iovdd|iovss|none]
                           IO function (selects the IO cell of the PDK), default guessed
  NAME [16mA]              drive strength of output/tristate/bidirectional cells
  === NAME                 power split: the IO ring is cut here, power domain NAME starts
Options combine, e.g. ``RFOUT [gsg] {70x70} @125`` or ``DOUT [out] [4mA]``.

RF pads and all pads in GSG groups use the RF settings (pitch, pad size).
"""

import math
import re

from .constants import FUNCTION_TAGS, GROUPS, SPLIT_PREFIX, TAGS, VARIANT_TAGS


def num(v, default, minimum=1.0):
    """Parse a number (comma or point as decimal separator); fall back to ``default``."""
    try:
        f = float(str(v).replace(",", "."))
        return f if math.isfinite(f) and f >= minimum else default
    except (TypeError, ValueError):
        return default


def classify(name):
    """Guess the pad type from its name."""
    u = name.upper()
    if re.fullmatch(r"NC|N/C|-+", u):
        return "nc"
    if re.search(r"VSS|GND", u):
        return "gnd"
    if re.search(r"VDD|VCC|VPP|VBAT|SUPPLY", u):
        return "pwr"
    if re.search(r"RF|^LO(_|[PN]$|$)|ANT|LNA|^PA_|PA_?OUT|MIX", u):
        return "rf"
    if re.search(r"CLK|CLOCK|XTAL|XIN|XOUT|OSC", u):
        return "clk"
    if re.search(r"REF|BIAS|VCM|AOUT|AIN|OUTP|OUTN|INP|INN|ANA|^A_", u):
        return "ana"
    return "dig"


_NUM = r"(\d+(?:[.,]\d+)?)"
SIZE_RE = re.compile(r"\s*\{\s*" + _NUM + r"\s*[x×*]\s*" + _NUM + r"\s*\}\s*$", re.I)
PITCH_RE = re.compile(r"\s*@\s*" + _NUM + r"\s*$")
TAG_RE = re.compile(r"\s*\[([A-Za-z0-9]+)\]\s*$")
DRIVE_RE = re.compile(r"(\d+)ma", re.I)
BUS_INDEX_RE = re.compile(r"\[[0-9]+\]")
TYPE_TAGS = {"pwr": "p", "gnd": "g", "ana": "a", "rf": "rf", "dig": "d", "clk": "c", "nc": "nc"}
FUNCTION_TYPES = {"vdd": "pwr", "iovdd": "pwr", "vss": "gnd", "iovss": "gnd", "analog": "ana", "none": "nc"}


def parse_line(line):
    """Parse one editor line. Returns ``None`` for a spacer, else an entry dict.

    A power split line returns ``{"split": True, "domain": name}``.
    """
    t = line.strip()
    if not t:
        return None
    if t.startswith(SPLIT_PREFIX):
        return {"split": True, "domain": t.strip("= \t")}
    typ = size = pitch = group = function = drive = variant = None
    lock = False
    # read from the right: a second tag or option of one kind ends the reading and stays in the name, a finding
    while True:
        m = SIZE_RE.search(t)
        if m and m.start() > 0 and num(m.group(1), 0) and num(m.group(2), 0) and size is None:  # else it stays in the name
            size = (num(m.group(1), 1), num(m.group(2), 1))
            t = t[:m.start()]
            continue
        m = PITCH_RE.search(t)
        if m and m.start() > 0 and num(m.group(1), 0) and pitch is None:
            pitch = num(m.group(1), 1)
            t = t[:m.start()]
            continue
        m = TAG_RE.search(t)
        if m and m.start() > 0:
            k = m.group(1).lower()
            if k in TAGS and typ is None:
                typ = TAGS[k]
            elif k in GROUPS and group is None:
                group = k
            elif k in FUNCTION_TAGS and function is None:
                function = FUNCTION_TAGS[k]
            elif k in VARIANT_TAGS and variant is None:
                variant = k
            elif k == "lock" and not lock:
                lock = True
            elif DRIVE_RE.fullmatch(k) and int(DRIVE_RE.fullmatch(k).group(1)) and drive is None:
                drive = int(DRIVE_RE.fullmatch(k).group(1))
            else:
                break  # e.g. bus name D[3] stays part of the name
            t = t[:m.start()]
            continue
        break
    name = t.strip()
    return {"split": False, "name": name, "type": typ, "auto": typ is None, "size": size,
            "pitch": pitch, "group": group, "function": function, "drive": drive, "lock": lock, "variant": variant}


def has_unknown_option(name):
    """A bracket, brace or ``@`` left in a parsed pad name is a tag or option :func:`parse_line` did not read.

    A numeric index belongs to the name, also inside it as in the LEF pins ``D[1][2]`` and ``x[1].y``.
    """
    return bool(re.search(r"[\[\]{}@]", BUS_INDEX_RE.sub("", name)))


def format_entry(e):
    """Inverse of :func:`parse_line` for pad entries (canonical tag order)."""
    if e.get("split"):
        return f"{SPLIT_PREFIX} {e['domain']}".rstrip()
    parts = [e["name"]]
    if e["type"] and not e.get("auto"):
        parts.append(f"[{TYPE_TAGS[e['type']]}]")
    if e["group"]:
        parts.append(f"[{e['group']}]")
    if e.get("function"):
        parts.append(f"[{'io' if e['function'] == 'inout' else e['function']}]")
    if e.get("drive"):
        parts.append(f"[{e['drive']}mA]")
    if e.get("variant"):
        parts.append(f"[{e['variant']}]")
    if e["size"]:
        parts.append(f"{{{e['size'][0]:g}x{e['size'][1]:g}}}")
    if e["pitch"]:
        parts.append(f"@{e['pitch']:g}")
    if e.get("lock"):
        parts.append("[lock]")
    return " ".join(parts)


def infer_function(name, typ):
    """Default IO function of a pad from its name and type."""
    u = name.upper()
    if typ == "nc":
        return "none"
    if typ in ("pwr", "gnd"):
        io = "IO" in u
        return ("io" if io else "") + ("vdd" if typ == "pwr" else "vss")
    if typ in ("ana", "rf"):
        return "analog"
    if typ == "clk":
        return "in"
    if re.search(r"OUT|SDO|MISO|TXD?$|_O$|_Q$", u):
        return "out"
    if re.search(r"IN|RST|RESET|SCLK|SCK|SDI|MOSI|CS|RXD?$|EN|SEL|_I$", u):
        return "in"
    return "inout"


def pad_type(name, explicit_type, function):
    """Pad type (colour class): explicit tag, else from the function, else from the name."""
    if explicit_type:
        return explicit_type
    if function in FUNCTION_TYPES:
        return FUNCTION_TYPES[function]
    typ = classify(name)
    if function and typ in ("pwr", "gnd", "nc", "ana", "rf"):
        return "dig"  # a signal function overrides a supply-like name
    return typ


def expand(entry, settings):
    """One editor entry → one or more pads (GSG groups). ``settings`` is a :class:`Settings`."""
    def make(name, typ, rf_rules):
        base = settings.rf if (rf_rules or typ == "rf") else settings.std
        w, h = entry["size"] or (base.w, base.h)
        if entry["pitch"]:
            pitch = entry["pitch"]
        elif entry["size"]:
            pitch = max(base.pitch, w + (base.pitch - base.w))
        else:
            pitch = base.pitch
        return {"name": name, "type": typ, "w": w, "h": h, "pitch": pitch}

    def finish(pad, function, shield=False):
        pad["function"] = function or infer_function(pad["name"], pad["type"])
        pad["drive"] = None if shield else entry.get("drive")  # drive and variant tag the signal pad of a group
        pad["variant"] = None if shield else entry.get("variant")
        return pad

    g = entry["group"]
    name = entry["name"]
    fn = entry.get("function")
    if not g:
        typ = pad_type(name, entry["type"], fn)
        return [finish(make(name, typ, False), fn)]
    sig_t = entry["type"] or ("rf" if fn in (None, "analog") else pad_type(name, None, fn))
    if g == "gsgsg":
        seq = [("GND", "gnd"), (name + "_P", sig_t), ("GND", "gnd"), (name + "_N", sig_t), ("GND", "gnd")]
    else:
        seq = [(("GND", "gnd") if c == "g" else (name, sig_t)) for c in g]
    return [finish(make(n, t, True), None if t == "gnd" else fn, shield=t == "gnd") for n, t in seq]


def split_lines(text):
    """Split editor text into lines, dropping trailing empty lines."""
    text = text.replace("\r", "")
    if not text:
        return []
    arr = text.split("\n")
    while arr and not arr[-1].strip():
        arr.pop()
    return arr
