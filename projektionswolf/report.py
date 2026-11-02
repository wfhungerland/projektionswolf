"""Ausgabe: auditierbares Workbook und Kurzbericht in Markdown."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .pipeline import Results

OUT = Path("output")

SOURCES = [
    ("BMWE/BMF: Ergänzende Unterlagen zur Bestimmung des Produktionspotenzials (je Runde)",
     "https://www.bundeswirtschaftsministerium.de/Redaktion/DE/Downloads/G/ergaenzende-unterlagen-zu-den-berechnungsgrundlagen-fuer-die-bestimmung-des-gesamtwirtschaftlichen-produktionspotenzials-fruehjahr-2026.zip?__blob=publicationFile&v=1"),
    ("Havik et al. (2014): The Production Function Methodology for Calculating Potential Growth Rates & Output Gaps, European Economy Economic Papers 535",
     "https://ec.europa.eu/economy_finance/publications/economic_paper/2014/pdf/ecp535_en.pdf"),
    ("Eurostat Dissemination API (namq_10_gdp, sts_inpr_m, sts_copr_m, sts_trtu_m, ei_bssi_m_r2, une_rt_m)",
     "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"),
    ("AMECO (EU-Kommission), Gesamtdatei", "https://ec.europa.eu/economy_finance/db_indicators/ameco/documents/ameco0.zip"),
    ("BMWE-Pressemitteilung zur Herbstprojektion 2026 (Eckwerte)",
     "https://www.bundeswirtschaftsministerium.de/Redaktion/DE/Pressemitteilungen/2026/10/20261008-reiche-stellt-herbstprojektion-vor.html"),
]

SHEET_NOTES = {
    "Nachbau": "Python-Nachbau des EViews-Programms je Runde; Abweichung zu Output_EViews (Maximum über alle Jahre).",
    "Potenzial": "Letzte Runde: Potenzialwachstum (%) und Beiträge (Pp.), Lücke in % des Potenzials, BIP real unbereinigt (%).",
    "Revisionen Lücke": "Produktionslücke (% des Potenzials) je Jahr und Projektionsrunde.",
    "Revisionen Wachstum": "Potenzialwachstum (%) je Jahr und Projektionsrunde.",
    "Eigene Filter": "Potenzial mit eigener NAWRU (ML) und/oder eigenem TFP-Trend (Posterior-Mittelwert per MCMC, EU-Prioren) statt der GAP-Werte.",
    "NAWRU Vergleich": "NAWRU in %: eigene Schätzung gegen Wert der Bundesregierung; ab T+2 Ankerregel.",
    "TFP Vergleich": "Wachstum des TFP-Trends in %: eigene Schätzung (mit 90-%-Band) gegen Wert der Bundesregierung.",
    "Filterparameter": "Geschätzte Parameter der Kalman-Filter.",
    "Nowcast": "BIP q/q in %, preis-, saison- und kalenderbereinigt; Ist (Eurostat) und Schätzung.",
    "Backtest Projektion": "BIP-Projektion (unbereinigt, %) je Runde gegen Ist laut letzter Runde.",
    "Backtest Projektion Kennzahlen": "Fehler = Projektion minus Ist, in Pp.",
    "Backtest Nowcast": "Pseudo-Echtzeit-Nowcast zum Ende des Quartals (heutiger Datenstand, ohne Revisionen).",
    "Backtest Nowcast Kennzahlen": "Ohne 2020Q1 bis 2021Q1. RMSE relativ zu AR(1) < 1 heißt besser als AR(1).",
    "EU-Kommission": "AMECO: Potenzialwachstum, Lücke und NAWRU der EU-Kommission.",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def write_excel(res: Results, path: Path = OUT / "projektionswolf.xlsx") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        wb = xw.book
        bold = wb.add_format({"bold": True})
        wrap = wb.add_format({"text_wrap": True, "valign": "top"})
        link = wb.add_format({"font_color": "blue", "underline": 1})
        info = xw.book.add_worksheet("Info")
        info.set_column(0, 0, 34)
        info.set_column(1, 1, 110)
        rows = [
            ("Inhalt", "Nachbau der Potenzialschätzung der Bundesregierung, eigene Filter, BIP-Nowcast und Backtests"),
            ("Erstellt", _stamp()),
            ("Letzte BMWE-Runde", f"{res.meta.get('latest_label')} ({res.meta.get('latest')})"),
        ]
        for k, v in (res.meta.get("nowcast") or {}).items():
            rows.append((f"Nowcast: {k}", v if not isinstance(v, float) else round(v, 3)))
        for k, v in (res.meta.get("szenario") or {}).items():
            rows.append((f"Szenario: {k}", v if not isinstance(v, (float, np.floating)) else round(float(v), 3)))
        for k, v in (res.meta.get("eurostat_last") or {}).items():
            rows.append((f"Eurostat letzter Wert: {k}", v))
        for i, (k, v) in enumerate(rows):
            info.write(i, 0, k, bold)
            info.write(i, 1, v, wrap)
        r0 = len(rows) + 1
        info.write(r0, 0, "Blätter", bold)
        for j, (name, note) in enumerate(SHEET_NOTES.items(), start=1):
            info.write(r0 + j, 0, name)
            info.write(r0 + j, 1, note, wrap)
        q = xw.book.add_worksheet("Quellen")
        q.set_column(0, 0, 90)
        q.set_column(1, 1, 120)
        for i, (name, url) in enumerate(SOURCES):
            q.write(i, 0, name, wrap)
            q.write_url(i, 1, url, link, string=url[:250])
        for name, df in res.tables.items():
            sheet = name[:31]
            df.to_excel(xw, sheet_name=sheet, startrow=1)
            ws = xw.sheets[sheet]
            ws.write(0, 0, SHEET_NOTES.get(name, ""), bold)
            ws.set_column(0, 0, 14)
            ws.set_column(1, max(1, df.shape[1]), 16)
            ws.freeze_panes(2, 1)
    return path


def _md_table(df: pd.DataFrame, digits: int = 2) -> str:
    d = df.copy()
    d = d.map(lambda x: f"{x:.{digits}f}" if isinstance(x, (float, np.floating)) and np.isfinite(x) else ("" if isinstance(x, float) else x))
    d.index = d.index.astype(str)
    cols = [str(d.index.name or "")] + [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for i, row in d.iterrows():
        lines.append("| " + " | ".join([i] + [str(x) for x in row.values]) + " |")
    return "\n".join(lines)


def write_markdown(res: Results, path: Path = OUT / "bericht.md") -> Path:
    t, m = res.tables, res.meta
    nc = m.get("nowcast", {})
    sz = m.get("szenario", {})
    rep = t["Nachbau"]
    done = rep[rep["status"] == "nachgerechnet"]
    parts = [
        "# projektionswolf: Lauf vom " + _stamp(),
        "",
        "## Nachbau der Potenzialschätzung",
        f"Nachgerechnet: {len(done)} Runden ({', '.join(done['kürzel'])}). "
        f"Größte Abweichung der Produktionslücke: {done['max. Abw. Lücke (Pp.)'].max():.1e} Prozentpunkte.",
        "",
        f"### Letzte Runde: {m.get('latest_label')}",
        _md_table(t["Potenzial"]),
        "",
        "### Eigene Filter statt GAP (letzte Runde)",
        _md_table(t["Eigene Filter"][[c for c in t["Eigene Filter"].columns if "Bundesregierung" in c or "beide" in c]]),
        "",
        "## Nowcast",
        _md_table(t["Nowcast"].loc[t["Nowcast"].index >= "2025Q1"]),
        "",
        f"Jahreswachstum {nc.get('Jahr')} (kalenderbereinigt) aus dem Faktormodell: {nc.get('Jahreswachstum aus DFM-Pfad (SCA, %)', float('nan')):.2f} %. "
        f"Datenstand Monatsindikatoren: {nc.get('Datenstand Monate')}.",
    ]
    if sz:
        parts.append(
            f"Setzt man dieses Wachstum in die {m.get('latest_label')} ein ({sz['BIP-Wachstum Runde']:.2f} % dort), "
            f"ändert sich die Lücke {sz['jahr']} von {sz['Lücke Runde']:.2f} auf {sz['Lücke mit Nowcast']:.2f} % des Potenzials."
        )
    if "Backtest Nowcast Kennzahlen" in t:
        parts += ["", "### Backtest Nowcast (ohne Corona-Quartale)", _md_table(t["Backtest Nowcast Kennzahlen"], 3)]
    parts += ["", "## Backtest BIP-Projektionen der Bundesregierung", _md_table(t["Backtest Projektion Kennzahlen"], 2), ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
