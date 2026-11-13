# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Write a set of output files together: all of them or none."""

import errno
import os
from pathlib import Path


def text_bytes(text):
    """The bytes a text-mode write gives, with the platform's line ends."""
    return text.replace("\n", os.linesep).encode("utf-8")


def _remove(path):
    try:
        path.unlink()
    except OSError:
        pass


def write_all(files, make_dirs=()):
    """Write ``{path: bytes}``, creating the folders in ``make_dirs`` first.

    Every file is written to a temporary name beside its target, the old targets are moved aside, the new files
    renamed into place, and only then the old ones deleted. A failure at any step puts the old files back and
    removes the folders this call created, so the outputs are either all new or all as they were.
    Returns the paths. Raises ``OSError`` for the first file or folder that could not be written.
    """
    created, staged, moved, placed = [], [], [], []
    try:
        for d in map(Path, make_dirs):
            if not d.exists():
                d.mkdir(parents=True)
                created.append(d)
        for path, data in files.items():
            path = Path(path)
            if path.is_dir():
                raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))
            tmp = path.with_name(path.name + ".prep-ic-tmp")
            staged.append((tmp, path))
            tmp.write_bytes(data)
        for _, path in staged:
            if path.exists():
                old = path.with_name(path.name + ".prep-ic-old")
                os.replace(path, old)
                moved.append((old, path))
        for tmp, path in staged:
            os.replace(tmp, path)
            placed.append(path)
    except OSError:
        had_old = {path for _, path in moved}
        for path in placed:
            if path not in had_old:
                _remove(path)
        for old, path in moved:
            try:
                os.replace(old, path)
            except OSError:
                pass
        for tmp, _ in staged:
            _remove(tmp)
        for d in reversed(created):
            try:
                d.rmdir()
            except OSError:
                pass
        raise
    for old, _ in moved:
        _remove(old)
    return [path for _, path in staged]
