# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Project files (JSON)."""

import json
import os
from pathlib import Path

from ..model.project import Project, load_problems


def load(path):
    """Read a project file. Raises ``OSError`` or ``ValueError``."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "sides" not in data:
            raise ValueError("not a pad ring file")
        project = Project.from_dict(data)
    except (ArithmeticError, AttributeError, RecursionError, TypeError) as e:
        raise ValueError(f"not a pad ring file: {e}") from e
    base = Path(path).resolve().parent
    for m in project.floorplan.macros:  # macro paths are stored relative to the project file
        if m.path and not Path(m.path).is_absolute():
            m.path = os.path.normpath(base / m.path)
    project.load_warnings = load_problems(data) + project.floorplan.reload()
    return project


def save(project, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = project.to_dict()
    base = path.resolve().parent
    for m in data.get("floorplan", {}).get("macros", []):
        if m["path"]:
            try:
                m["path"] = Path(os.path.relpath(Path(m["path"]).resolve(), base)).as_posix()
            except ValueError:  # other drive (Windows): keep it absolute
                pass
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
