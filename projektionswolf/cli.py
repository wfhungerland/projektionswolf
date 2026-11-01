"""Kommandozeile: ``python -m projektionswolf <befehl>``."""

from __future__ import annotations

import argparse
import logging
import shutil
import tempfile
from pathlib import Path


def cmd_fetch(args) -> int:
    from . import bmwe, data

    data.fetch_all()
    # BMWE-Rohdateien in schlanke CSV umwandeln
    raw = data.RAW / "bmwe"
    for d in sorted(p for p in raw.iterdir() if p.is_dir()):
        try:
            code = bmwe.extract_vintage(d)
            logging.info("BMWE %s -> %s", d.name, code)
        except Exception as e:  # einzelne Runde darf scheitern
            logging.error("BMWE %s: %s", d.name, e)
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="projektionswolf")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="Rohdaten laden (AMECO, Eurostat, BMWE)")
    args = ap.parse_args(argv)
    return {"fetch": cmd_fetch}[args.cmd](args)
