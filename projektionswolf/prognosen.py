"""Vergleich der Projektionen der Bundesregierung mit GD, Bundesbank und Instituten.

Quelle der fremden Prognosen ist die gepflegte Tabelle ``data/manuell/prognosen.csv``
(eine Zeile je Veröffentlichung und Zieljahr, mit Quellenlink). Die Werte der
Bundesregierung kommen aus den BMWE-Rechengrundlagen je Runde und für Runden ohne
Rechengrundlage aus ``data/manuell/eckwerte_projektionen.csv``.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import bmwe

PROGNOSEN = Path("data/manuell/prognosen.csv")
ECKWERTE = Path("data/manuell/eckwerte_projektionen.csv")
PRUEFUNG = Path("data/raw/prognosen_pruefung.csv")
COLUMNS = ["institution", "runde", "veroeffentlicht", "zieljahr", "bip", "bip_kalenderbereinigt", "inflation",
           "inflation_index", "potenzialwachstum", "produktionsluecke", "quelle", "geprueft", "anmerkung"]
MONATE = {m: i for i, m in enumerate(["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
                                      "September", "Oktober", "November", "Dezember"], start=1)}
ORDER = ["Bundesregierung", "GD", "Bundesbank", "ifo", "IfW", "DIW", "RWI", "IWH"]


def vintage_date(code: str, root: Path = bmwe.BMWE_DIR) -> pd.Timestamp | None:
    txt = (root / code / "potenzial.prg").read_text(encoding="latin-1")
    m = re.search(r"vom (\d{1,2})\. ([A-Za-zäÄ\xe4]+) (20\d\d)", txt)
    if not m:
        return None
    month = MONATE.get(m.group(2).replace("\xe4", "ä"))
    return pd.Timestamp(int(m.group(3)), month, int(m.group(1))) if month else None


def bundesregierung(root: Path = bmwe.BMWE_DIR, results: dict | None = None) -> pd.DataFrame:
    """Projektionen der Bundesregierung je Runde: BIP (unbereinigt), Potenzialwachstum, Lücke."""
    rows = []
    for code in bmwe.list_vintages(root):
        inp = bmwe.load_vintage(code, root)
        g = 100 * inp["input"]["y"].pct_change()
        out = inp.get("output")
        y0 = 2000 + int(code[2:])
        last = y0 + (2 if code.startswith("HP") else 1)
        for y in range(y0, last + 1):
            row = {"institution": "Bundesregierung", "runde": bmwe.vintage_label(code),
                   "veroeffentlicht": vintage_date(code, root), "zieljahr": y, "bip": g.get(y),
                   "quelle": "BMWE/BMF, Ergänzende Unterlagen zur Bestimmung des Produktionspotenzials", "geprueft": "ja"}
            if out is not None and y in out.index:
                row["potenzialwachstum"] = 100 * (out["ypot"][y] / out["ypot"][y - 1] - 1)
                row["produktionsluecke"] = out["ygap"][y]
            rows.append(row)
    df = pd.DataFrame(rows)
    if ECKWERTE.exists():  # Runden ohne Rechengrundlage (z. B. Herbst 2026)
        ew = pd.read_csv(ECKWERTE)
        have = set(df["runde"])
        for _, r in ew.iterrows():
            label = bmwe.vintage_label(r["runde"])
            if label in have:
                continue
            df.loc[len(df)] = {"institution": "Bundesregierung", "runde": label,
                               "veroeffentlicht": pd.Timestamp(r["veroeffentlicht"]), "zieljahr": int(r["jahr"]),
                               "bip": r["bip_wachstum"], "quelle": r["quelle"], "geprueft": "ja"}
    return df


def load_all(root: Path = bmwe.BMWE_DIR) -> pd.DataFrame:
    parts = [bundesregierung(root)]
    if PROGNOSEN.exists():
        p = pd.read_csv(PROGNOSEN)
        p["veroeffentlicht"] = pd.to_datetime(p["veroeffentlicht"], format="mixed", errors="coerce")  # "JJJJ-MM" -> Monatserster
        parts.append(p)
    df = pd.concat(parts, ignore_index=True)
    for c in COLUMNS:
        if c not in df:
            df[c] = np.nan
    df["veroeffentlicht"] = pd.to_datetime(df["veroeffentlicht"], format="mixed")
    df["horizont"] = df["zieljahr"] - df["veroeffentlicht"].dt.year
    amtlich = (df["institution"] == "Bundesregierung") & ~df["quelle"].astype(str).str.startswith("http")
    df["pruefung"] = np.where(amtlich, "amtliche Rechengrundlage", "nicht geprüft")
    if PRUEFUNG.exists():
        pr = pd.read_csv(PRUEFUNG)[["institution", "runde", "zieljahr", "pruefung"]].drop_duplicates(["institution", "runde", "zieljahr"])
        m = df.merge(pr, on=["institution", "runde", "zieljahr"], how="left", suffixes=("", "_q"))
        df["pruefung"] = m["pruefung_q"].fillna(m["pruefung"]).values
    return df[COLUMNS + ["horizont", "pruefung"]].sort_values(["veroeffentlicht", "institution", "zieljahr"]).reset_index(drop=True)


def actuals(root: Path = bmwe.BMWE_DIR) -> pd.Series:
    """BIP-Wachstum (unbereinigt) laut letzter Runde für abgeschlossene Jahre."""
    codes = bmwe.list_vintages(root)
    inp = bmwe.load_vintage(codes[-1], root)["input"]
    last = bmwe.read_horizon(codes[-1], root)["endy_st"] - 2
    return (100 * inp["y"].pct_change()).loc[:last]


def errors(df: pd.DataFrame, act: pd.Series) -> pd.DataFrame:
    d = df[df["horizont"].isin([0, 1])].copy()
    d["ist"] = d["zieljahr"].map(act)
    d["fehler"] = d["bip"] - d["ist"]
    return d.dropna(subset=["fehler"])


def error_stats(err: pd.DataFrame) -> pd.DataFrame:
    """Treffsicherheit je Institution und Horizont (0 = laufendes Jahr, 1 = Folgejahr)."""
    g = err.groupby(["institution", "horizont"])["fehler"]
    st = pd.DataFrame({"n": g.size(), "mittlerer Fehler": g.mean(), "MAE": g.apply(lambda e: e.abs().mean()),
                       "RMSE": g.apply(lambda e: float(np.sqrt((e**2).mean())))}).reset_index()
    st["institution"] = pd.Categorical(st["institution"], [o for o in ORDER if o in set(st["institution"])] +
                                       sorted(set(st["institution"]) - set(ORDER)), ordered=True)
    return st.sort_values(["horizont", "institution"]).reset_index(drop=True)


def latest_by_institution(df: pd.DataFrame) -> pd.DataFrame:
    """Jüngste Veröffentlichung je Institution mit BIP für laufendes und nächstes Jahr."""
    rows = []
    for inst, g in df.dropna(subset=["veroeffentlicht"]).groupby("institution"):
        last = g[g["veroeffentlicht"] == g["veroeffentlicht"].max()]
        row = {"institution": inst, "runde": last["runde"].iloc[0], "veroeffentlicht": last["veroeffentlicht"].iloc[0].date()}
        for _, r in last.iterrows():
            row[f"BIP {int(r['zieljahr'])}"] = r["bip"]
            if pd.notna(r.get("potenzialwachstum")):
                row[f"Potenzial {int(r['zieljahr'])}"] = r["potenzialwachstum"]
        row["quelle"] = last["quelle"].iloc[0]
        rows.append(row)
    out = pd.DataFrame(rows)
    out["_o"] = out["institution"].map({k: i for i, k in enumerate(ORDER)}).fillna(99)
    return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)
