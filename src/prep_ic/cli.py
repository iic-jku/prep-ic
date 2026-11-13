# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Command line entry point. Without a subcommand the GUI starts.

    prep-ic [PROJECT]
    prep-ic export PROJECT [--csv FILE] [--svg FILE] [--librelane DIR]
    prep-ic check PROJECT
"""

import argparse
import sys

from . import APP_NAME, __version__, export_csv, export_librelane, export_svg, findings, load


def _print(text):
    """``print`` for text with names or paths, which may not fit the encoding of the output."""
    if sys.stdout is not None:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, "backslashreplace").decode(encoding))


def _inform(text):
    """``_print`` for a line nobody has to read: a closed output ends the lines, not the command."""
    try:
        _print(text)
        if sys.stdout is not None:
            sys.stdout.flush()
    except (OSError, ValueError):
        sys.stdout = None  # the flush at exit would fail too and turn the exit code into 120


def _export(argv):
    ap = argparse.ArgumentParser(prog="prep-ic export", description="Export a project without the GUI.")
    ap.add_argument("project", help="project file (.json)")
    ap.add_argument("--csv", metavar="FILE", help="write the pin list as CSV")
    ap.add_argument("--svg", metavar="FILE", help="write the drawing as SVG")
    ap.add_argument("--librelane", metavar="DIR",
                    help="write the LibreLane pad ring files (needs a PDK in the project)")
    args = ap.parse_args(argv)
    if not (args.csv or args.svg or args.librelane):
        ap.error("nothing to export, give --csv, --svg and/or --librelane")
    try:
        project = load(args.project)
        if args.csv:
            export_csv(project, args.csv)
        if args.svg:
            export_svg(project, args.svg)
        if args.librelane:
            for path in export_librelane(project, args.librelane, source=args.project):
                _inform(f"wrote {path}")
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in findings(project):
        print(f"warning: {w}", file=sys.stderr)
    return 0


def _check(argv):
    ap = argparse.ArgumentParser(prog="prep-ic check", description="List the problems of a project.",
                                 epilog="Exit code: 0 no findings, 1 findings, 2 the check did not run.")
    ap.add_argument("project", help="project file (.json)")
    args = ap.parse_args(argv)
    try:
        found = findings(load(args.project))
    except Exception as e:  # a traceback would exit 1, which means findings
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        for line in found or ["no findings"]:
            _print(line)
        sys.stdout.flush()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.stdout = None  # the flush at exit would fail too and turn the code into 120
        return 2
    return 1 if found else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "export":
        return _export(argv[1:])
    if argv and argv[0] == "check":
        return _check(argv[1:])
    ap = argparse.ArgumentParser(prog="prep-ic", description=f"{APP_NAME}: plan IC pad ring pinouts.",
                                 epilog="Subcommands: 'prep-ic export -h' for exports without the GUI, "
                                        "'prep-ic check -h' to list the problems of a project.")
    ap.add_argument("project", nargs="?", help="project file (.json) to open")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = ap.parse_args(argv)
    try:
        from .gui import qt, run  # gui itself imports lazily, qt raises the install advice
    except ImportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return run(args.project)


if __name__ == "__main__":
    sys.exit(main())
