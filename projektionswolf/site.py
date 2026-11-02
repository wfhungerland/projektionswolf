"""Statische Webseite (GitHub Pages) aus den Ergebnissen eines Laufs."""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

import numpy as np
import pandas as pd

from . import bmwe, eckwerte, komponenten, prognosen
from .pipeline import Results

SITE = Path("site")


def _clean(v):
    if v is None or v is pd.NaT or (not isinstance(v, (str, dict, list, tuple)) and pd.isna(v)):
        return None
    if isinstance(v, (np.floating, float)):
        return None if not math.isfinite(float(v)) else round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def _series(s: pd.Series) -> dict:
    s = s.dropna()
    return {"x": [str(i) for i in s.index], "y": [_clean(v) for v in s.values]}


def build_payload(res: Results) -> dict:
    t, m = res.tables, res.meta
    pot = t["Potenzial"]
    payload = {
        "stand": datetime.now(timezone.utc).strftime("%d.%m.%Y"),
        "latest": m.get("latest_label"),
        "nowcast_meta": m.get("nowcast", {}),
        "szenario": m.get("szenario", {}),
        "potenzial": {"jahre": [int(i) for i in pot.index],
                      **{k: [_clean(v) for v in pot[k]] for k in pot.columns}},
        "revisionen": {c: _series(t["Revisionen Lücke"][c]) for c in t["Revisionen Lücke"].columns},
        "revisionen_labels": {c: bmwe.vintage_label(c) for c in t["Revisionen Lücke"].columns},
    }
    ef = t["Eigene Filter"]
    payload["eigene"] = {
        "jahre": [int(i) for i in ef.index],
        "luecke_breg": [_clean(v) for v in ef["Lücke: Bundesregierung (GAP)"]],
        "luecke_eigen": [_clean(v) for v in ef["Lücke: beide eigenen Filter"]],
    }
    tv = t["TFP Vergleich"]
    payload["tfp"] = {"jahre": [int(i) for i in tv.index], **{k: [_clean(v) for v in tv[k]] for k in tv.columns}}
    nv = t["NAWRU Vergleich"]
    payload["nawru"] = {"jahre": [int(i) for i in nv.index], **{k: [_clean(v) for v in nv[k]] for k in nv.columns}}
    nc = t["Nowcast"]
    payload["nowcast"] = {"q": list(nc.index), **{k: [_clean(v) for v in nc[k]] for k in nc.columns}}
    if "Backtest Nowcast Kennzahlen" in t:
        k = t["Backtest Nowcast Kennzahlen"]
        payload["nowcast_bt"] = [{"modell": i, **{c: _clean(k.loc[i, c]) for c in k.columns}} for i in k.index]

    # Prognosevergleich
    df = prognosen.load_all()
    act = prognosen.actuals()
    payload["prognosen"] = [
        {k: _clean(r[k]) for k in ("institution", "runde", "veroeffentlicht", "zieljahr", "bip", "inflation",
                                    "potenzialwachstum", "produktionsluecke", "quelle", "pruefung")}
        for _, r in df.iterrows()
    ]
    payload["ist"] = {str(int(y)): _clean(v) for y, v in act.dropna().items()}
    payload["ist_inflation"] = {str(int(y)): _clean(v) for y, v in prognosen.actuals_inflation().dropna().items()}
    st = prognosen.error_stats(prognosen.errors(df, act))
    payload["fehler"] = [{k: _clean(r[k]) if k != "institution" else str(r[k]) for k in st.columns} for _, r in st.iterrows()]
    payload["institutionen"] = [i for i in prognosen.ORDER if i in set(df["institution"])] + \
        sorted(set(df["institution"]) - set(prognosen.ORDER))
    # Eckwerte der Bundesregierung (volle VGR)
    if eckwerte.OUT.exists():
        ek = eckwerte.load()
        payload["eckwerte"] = [{k: _clean(r[k]) for k in ("runde", "variable", "jahr", "wert", "ist")} for _, r in ek.iterrows()]
        payload["eckwerte_runden"] = {c: bmwe.vintage_label(c) for c in eckwerte.CODES}
        est = eckwerte.error_stats(eckwerte.errors(ek))
        payload["eckwerte_fehler"] = [{k: _clean(r[k]) for k in est.columns} for _, r in est.iterrows()]
        payload["eckwerte_gruppen"] = eckwerte.GROUPS
    payload["vergleich"], payload["ist_vergleich"] = vergleich(df)
    return payload


VERGLEICH_VARS = ["BIP real", "Verbraucherpreise", "Privater Konsum", "Staatskonsum", "Ausrüstungsinvestitionen",
                  "Bauinvestitionen", "Exporte", "Importe"]


def vergleich(prog: pd.DataFrame) -> tuple[list, dict]:
    """Einheitliche Liste für das Konsensband: BIP und Inflation aus der geprüften Tabelle, Komponenten aus den
    Prognosetabellen; Bundesregierung aus ihren Eckwerten. Ist laut Eckwerten der Bundesregierung."""
    rows = []
    for _, r in prog.iterrows():
        for col, var in (("bip", "BIP real"), ("inflation", "Verbraucherpreise")):
            if pd.notna(r[col]) and pd.notna(r["veroeffentlicht"]):
                rows.append({"institution": r["institution"], "runde": r["runde"], "veroeffentlicht": r["veroeffentlicht"],
                             "variable": var, "jahr": int(r["zieljahr"]), "wert": float(r[col]), "pruefung": r.get("pruefung")})
    if komponenten.OUT.exists():
        k = pd.read_csv(komponenten.OUT)
        k = k[~k["ist"] & k["variable"].isin(VERGLEICH_VARS) & ~k["variable"].isin(["BIP real", "Verbraucherpreise"])]
        for _, r in k.iterrows():
            rows.append({"institution": r["institution"], "runde": r["runde"], "veroeffentlicht": r["veroeffentlicht"],
                         "variable": r["variable"], "jahr": int(r["jahr"]), "wert": float(r["wert"]),
                         "pruefung": "Tabelle, BIP abgeglichen"})
    ist = {}
    if eckwerte.OUT.exists():
        ek = eckwerte.load()
        dates = prog[prog["institution"] == "Bundesregierung"].drop_duplicates("runde").set_index("runde")["veroeffentlicht"]
        e = ek[~ek["ist"] & ek["variable"].isin(VERGLEICH_VARS) & ~ek["variable"].isin(["BIP real", "Verbraucherpreise"])]
        for _, r in e.iterrows():
            label = bmwe.vintage_label(r["runde"])
            if label in dates.index and pd.notna(dates[label]):
                rows.append({"institution": "Bundesregierung", "runde": label, "veroeffentlicht": dates[label],
                             "variable": r["variable"], "jahr": int(r["jahr"]), "wert": float(r["wert"]),
                             "pruefung": "amtliche Eckwerte"})
        a = eckwerte.actuals(ek)
        for var in VERGLEICH_VARS:
            s = a[a["variable"] == var]
            ist[var] = {str(int(y)): _clean(v) for y, v in zip(s["jahr"], s["ist"])}
    return [{k: _clean(v) for k, v in r.items()} for r in rows], ist


def write_site(res: Results, out: Path = SITE) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    payload = build_payload(res)
    tpl = resources.files("projektionswolf").joinpath("templates/index.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    (out / "index.html").write_text(html, encoding="utf-8")
    js = resources.files("projektionswolf").joinpath("static/plotly.min.js")
    (out / "plotly.min.js").write_bytes(js.read_bytes())
    xlsx = Path("output/projektionswolf.xlsx")
    if xlsx.exists():
        shutil.copy(xlsx, out / "projektionswolf.xlsx")
    (out / ".nojekyll").write_text("")
    return out / "index.html"
