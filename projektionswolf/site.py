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

from . import bmwe, eckwerte, prognosen
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
    return payload


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
