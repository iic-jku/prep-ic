# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Pin list as rows, tab-separated text or CSV."""

import csv
import io

from .files import write_all

from ..model.constants import FUNCTION_NAMES, SIDE_NAMES, TYPE_NAMES

HEADER = ("Pin", "Side", "Name", "Type", "Function", "IO cell", "Domain", "Package pin",
          "Pad W [µm]", "Pad H [µm]", "Pitch [µm]", "X [µm]", "Y [µm]")


def rows(layout):
    """One tuple per pin, values formatted as in the pin list. X/Y: bond pad centre, origin lower-left."""
    return [(p.no, SIDE_NAMES[p.side], p.name, TYPE_NAMES[p.type], FUNCTION_NAMES[p.function], p.cell,
             p.domain, p.package_pin or "", f"{p.w:g}", f"{p.h:g}", f"{p.pitch:g}", f"{p.x:.1f}",
             f"{p.y:.1f}") for p in layout.pins]


def to_tsv(layout):
    return "\n".join("\t".join(map(str, r)) for r in [HEADER] + rows(layout))


def csv_bytes(layout):
    """The pin list as CSV, UTF-8 with BOM for Excel."""
    f = io.StringIO(newline="")
    w = csv.writer(f)
    w.writerow(HEADER)
    w.writerows(rows(layout))
    return f.getvalue().encode("utf-8-sig")


def export_csv(project, path):
    """Write the pin list of a :class:`Project` as CSV (UTF-8 with BOM for Excel)."""
    write_all({path: csv_bytes(project.layout())})
