"""Kommandozeile: ``python -m projektionswolf <befehl>``."""

from __future__ import annotations

import argparse
import logging
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


def cmd_run(args) -> int:
    from . import pipeline, report

    res = pipeline.run(backtest_nowcast=not args.quick)
    x = report.write_excel(res)
    md = report.write_markdown(res)
    from . import site

    html = site.write_site(res)
    logging.info("geschrieben: %s, %s, %s", x, md, html)
    return 0


def cmd_check(args) -> int:
    """Nachbau gegen BMWE-Ergebnisse prüfen; Exit-Code 1 bei Abweichung."""
    from . import pipeline

    rep, _ = pipeline.replicate_all()
    done = rep[rep["status"] == "nachgerechnet"]
    print(done[["kürzel", "max. Abw. Lücke (Pp.)", "max. Abw. Potenzial (Mrd. Euro)"]].to_string(index=False))
    return int(bool((done["max. Abw. Lücke (Pp.)"] > 1e-4).any()))


def cmd_verify(args) -> int:
    """Prognosetabelle an den Quellen gegenprüfen (braucht Netz)."""
    from . import verify

    res = verify.verify()
    print(res["pruefung"].value_counts().to_string())
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="projektionswolf")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="Rohdaten laden (AMECO, Eurostat, BMWE)")
    r = sub.add_parser("run", help="Schätzen und Excel/Bericht schreiben")
    r.add_argument("--quick", action="store_true", help="ohne Nowcast-Backtest")
    sub.add_parser("check", help="Nachbau gegen BMWE-Ergebnisse prüfen")
    sub.add_parser("verify", help="Prognosetabelle an den Quellen gegenprüfen")
    args = ap.parse_args(argv)
    return {"fetch": cmd_fetch, "run": cmd_run, "check": cmd_check, "verify": cmd_verify}[args.cmd](args)
