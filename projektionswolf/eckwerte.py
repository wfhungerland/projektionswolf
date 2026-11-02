"""Eckwerte der Projektionen der Bundesregierung: einlesen, Ist zuordnen, Treffsicherheit.

Quelle sind die Eckwert-Tabellen je Runde (PDF des BMWE, Jahreswirtschaftsbericht oder
Schlaglichter), deren Text ``tools/eckwerte_laden.py`` nach ``data/raw/eckwerte`` legt.
Die erste Jahresspalte jeder Tabelle ist das Ist des Vorjahres (vorläufige Ergebnisse des
Statistischen Bundesamtes zum Stand der Runde), die übrigen Spalten sind Projektion.
Als Ist für den Backtest dient der jüngste Wert, den eine spätere Runde als Ist ausweist;
so stimmen Abgrenzung und Definition mit der Projektion überein.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw/eckwerte")
OUT = Path("data/bmwe_eckwerte.csv")
CODES = ["JP23", "FP23", "HP23", "JP24", "FP24", "HP24", "JP25", "FP25", "HP25", "JP26", "FP26", "HP26"]

NUM = r"[-−–\xad]?\s?\d+,\d"
TITLE = re.compile(r"eckwerte der (jahres|frühjahrs|herbst)projektion\s+20\d\d", re.I)

# (Abschnitt, Zeilenbeginn) -> (Variable, Einheit)
SECTIONS = [
    (re.compile(r"^ENTSTEHUNG", re.I), "entstehung"),
    (re.compile(r"^VERWENDUNG des BIP in jeweiligen Preisen", re.I), "nominal"),
    (re.compile(r"^VERWENDUNG des BIP preisbereinigt", re.I), "real"),
    (re.compile(r"^Preisentwicklung", re.I), "preise"),
    (re.compile(r"^VERTEILUNG", re.I), "verteilung"),
]
ROWS = {
    ("entstehung", "BIP (preisbereinigt)"): "BIP real",
    ("entstehung", "Erwerbstätige (im Inland)"): "Erwerbstätige",
    ("entstehung", "BIP je Erwerbstätigen"): "Produktivität je Erwerbstätigen",
    ("entstehung", "BIP je Erwerbstätigenstunde"): "Produktivität je Stunde",
    ("entstehung", "Erwerbslosenquote in % (ESVG-Konzept)"): "Erwerbslosenquote ESVG (%)",
    ("entstehung", "Arbeitslosenquote in % (Abgrenzung der BA)"): "Arbeitslosenquote BA (%)",
    ("nominal", "Private Haushalte und priv. Organisationen ohne Erwerbszweck"): "Privater Konsum nominal",
    ("nominal", "Staat"): "Staatskonsum nominal",
    ("nominal", "Bruttoanlageinvestitionen"): "Bruttoanlageinvestitionen nominal",
    ("nominal", "Vorratsveränderungen und Nettozugang an Wertsachen (Mrd. EURO)"): "Vorratsveränderung (Mrd. Euro)",
    ("nominal", "Inlandsnachfrage"): "Inlandsnachfrage nominal",
    ("nominal", "Außenbeitrag (Mrd. EURO)"): "Außenbeitrag (Mrd. Euro)",
    ("nominal", "Außenbeitrag (in % des BIP)"): "Außenbeitrag (% BIP)",
    ("nominal", "Saldo der Leistungsbilanz (in % des BIP)"): "Leistungsbilanzsaldo (% BIP)",
    ("nominal", "Bruttoinlandsprodukt (nominal)"): "BIP nominal",
    ("real", "Private Haushalte und priv. Organisationen ohne Erwerbszweck"): "Privater Konsum",
    ("real", "Staat"): "Staatskonsum",
    ("real", "Bruttoanlageinvestitionen"): "Bruttoanlageinvestitionen",
    ("real", "Ausrüstungen"): "Ausrüstungsinvestitionen",
    ("real", "Bauten"): "Bauinvestitionen",
    ("real", "Sonstige Anlagen"): "Sonstige Anlagen",
    ("real", "Vorratsveränderung und Nettozugang an Wertsachen (Impuls)"): "Vorräte (Beitrag, Pp.)",
    ("real", "Inlandsnachfrage"): "Inlandsnachfrage",
    ("real", "Exporte"): "Exporte",
    ("real", "Importe"): "Importe",
    ("real", "Außenbeitrag (Impuls)"): "Außenbeitrag (Beitrag, Pp.)",
    ("preise", "Verbraucherpreisindex"): "Verbraucherpreise",
    ("preise", "Konsumausgaben der privaten Haushalte"): "Deflator privater Konsum",
    ("preise", "Inlandsnachfrage"): "Deflator Inlandsnachfrage",
    ("preise", "Bruttoinlandsprodukt"): "BIP-Deflator",
    ("verteilung", "Arbeitnehmerentgelte"): "Arbeitnehmerentgelte",
    ("verteilung", "Unternehmens- und Vermögenseinkommen"): "Unternehmens- und Vermögenseinkommen",
    ("verteilung", "Volkseinkommen"): "Volkseinkommen",
    ("verteilung", "Bruttonationaleinkommen"): "Bruttonationaleinkommen",
    ("verteilung", "Arbeitnehmer"): "Arbeitnehmer",
    ("verteilung", "Bruttolöhne und -gehälter"): "Bruttolöhne und -gehälter",
    ("verteilung", "Bruttolöhne und -gehälter je Arbeitnehmer"): "Löhne je Arbeitnehmer",
    ("verteilung", "Verfügbares Einkommen der privaten Haushalte"): "Verfügbares Einkommen",
    ("verteilung", "Sparquote in %"): "Sparquote (%)",
}
ROWS_NORM = {(sec, re.sub(r"\s+", " ", lab.replace("in Prozent", "in %")).lower()): v for (sec, lab), v in ROWS.items()}
# Größen in Niveaus oder Quoten: Fehler in Punkten, sonst Prozentpunkte der Rate
GROUPS = {
    "Gesamt": ["BIP real", "BIP nominal", "BIP-Deflator", "Verbraucherpreise"],
    "Verwendung": ["Privater Konsum", "Staatskonsum", "Bruttoanlageinvestitionen", "Ausrüstungsinvestitionen",
                   "Bauinvestitionen", "Sonstige Anlagen", "Inlandsnachfrage", "Exporte", "Importe",
                   "Vorräte (Beitrag, Pp.)", "Außenbeitrag (Beitrag, Pp.)"],
    "Arbeitsmarkt": ["Erwerbstätige", "Arbeitslosenquote BA (%)", "Erwerbslosenquote ESVG (%)",
                     "Produktivität je Erwerbstätigen", "Produktivität je Stunde"],
    "Einkommen": ["Arbeitnehmerentgelte", "Bruttolöhne und -gehälter", "Löhne je Arbeitnehmer",
                  "Unternehmens- und Vermögenseinkommen", "Verfügbares Einkommen", "Sparquote (%)"],
}


def _num(s: str) -> float:
    s = s.replace("\xad", "-").replace("−", "-").replace("–", "-").replace(" ", "").replace(",", ".")
    return float(s)


def _norm(s: str) -> str:
    """Einheitliche Schreibweise der Zeilenbeschriftung (Fußnoten, Abkürzungen, Groß/klein)."""
    s = s.strip()
    s = re.sub(r"\s*\d[a-z.)]*\s*$", "", s)  # Fußnote am Ende: "2", "2)", "2i.", "3b", "5i.."
    s = re.sub(r"(\))\d[a-z.]*$", r"\1", s)  # Fußnote direkt an Klammer: "(Impuls)3"
    s = s.replace("in Prozent", "in %").replace("private Organisationen", "priv. Organisationen")
    s = s.replace("Vorratsveränderungen und Nettozugang an Wertsachen (Impuls)", "Vorratsveränderung und Nettozugang an Wertsachen (Impuls)")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def _clean_label(s: str) -> str:
    return _norm(s)


def parse_text(text: str) -> pd.DataFrame | None:
    """Eckwerttabelle aus Seitentext: Long-Frame (variable, jahr, wert, ist)."""
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if not TITLE.search(line):
            continue
        # Jahre im Kopf (bis "Veränderung gegenüber Vorjahr")
        years, j = [], start
        while j < min(len(lines), start + 10):
            if re.search(r"Veränderung gegenüber Vorjahr", lines[j]):
                break
            years += [int(y) for y in re.findall(r"\b(20\d\d)\b", lines[j]) if j > start]
            j += 1
        years = sorted(set(years))
        if len(years) < 2 or years != list(range(years[0], years[0] + len(years))):
            continue
        n = len(years)
        rows, section = [], None
        for line in lines[j + 1: j + 120]:
            if re.match(r"^\s*1\)?\s+(Bis|Statistisches|Vorläufige|Stand|Quelle)", line) or line.startswith("1)"):
                break
            for pat, name in SECTIONS:
                if pat.search(line):
                    section = name
            m = re.match(rf"^(.*?)\s+((?:{NUM}\s+){{{n - 1}}}{NUM})\s*$", line)
            if not m or section is None:
                continue
            label = _clean_label(m.group(1))
            var = ROWS_NORM.get((section, label))
            if var is None:
                continue
            vals = re.findall(NUM, m.group(2))
            for y, v in zip(years, vals):
                rows.append({"variable": var, "jahr": y, "wert": _num(v), "ist": y == years[0]})
        if len(rows) >= 20:
            return pd.DataFrame(rows).drop_duplicates(["variable", "jahr"])
    return None


def build(raw: Path = RAW, out: Path = OUT) -> pd.DataFrame:
    """Liest je Runde die erste parsbare Datei und schreibt die Long-Tabelle."""
    log = pd.read_csv(raw / "log.csv") if (raw / "log.csv").exists() else pd.DataFrame()
    frames = []
    for code in CODES:
        for f in sorted(raw.glob(f"{code}_*.txt")):
            df = parse_text(f.read_text(encoding="utf-8"))
            if df is None:
                continue
            url = log.loc[log["datei"] == f.stem, "url"]
            df.insert(0, "runde", code)
            df["quelle"] = url.iloc[0] if len(url) else ""
            frames.append(df)
            break
    res = pd.concat(frames, ignore_index=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out, index=False)
    return res


def load(path: Path = OUT) -> pd.DataFrame:
    return pd.read_csv(path)


def round_year(code: str) -> int:
    return 2000 + int(code[2:])


def actuals(df: pd.DataFrame) -> pd.DataFrame:
    """Jüngstes ausgewiesenes Ist je Variable und Jahr."""
    order = {c: i for i, c in enumerate(CODES)}
    ist = df[df["ist"]].copy()
    ist["o"] = ist["runde"].map(order)
    ist = ist.sort_values("o").groupby(["variable", "jahr"]).last().reset_index()
    return ist[["variable", "jahr", "wert", "runde"]].rename(columns={"wert": "ist", "runde": "ist_aus"})


def errors(df: pd.DataFrame) -> pd.DataFrame:
    p = df[~df["ist"]].drop(columns="ist").copy()
    p["horizont"] = p["jahr"] - p["runde"].map(round_year)
    p = p.merge(actuals(df), on=["variable", "jahr"], how="inner")
    p["fehler"] = p["wert"] - p["ist"]
    return p[p["horizont"].isin([0, 1])]


def error_stats(err: pd.DataFrame) -> pd.DataFrame:
    g = err.groupby(["variable", "horizont"])["fehler"]
    st = pd.DataFrame({"n": g.size(), "mittlerer Fehler": g.mean(), "MAE": g.apply(lambda e: e.abs().mean()),
                       "RMSE": g.apply(lambda e: float(np.sqrt((e**2).mean()))),
                       "Anteil zu hoch": g.apply(lambda e: float((e > 0).mean()))}).reset_index()
    order = [v for vs in GROUPS.values() for v in vs]
    st["_o"] = st["variable"].map({v: i for i, v in enumerate(order)}).fillna(99)
    return st.sort_values(["horizont", "_o"]).drop(columns="_o").reset_index(drop=True)
