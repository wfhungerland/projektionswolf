"""Gesamtlauf: Nachbau prüfen, eigene Filter, Nowcast, Backtests. Ergebnisse als Tabellen."""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import bmwe, data, filters, nowcast, potential

log = logging.getLogger(__name__)

NEW_SPEC_MARKER = "part_nfl part_nfl(-1) part_nfl(-2)"  # EViews-Programm seit Frühjahr 2024


@dataclass
class Results:
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def is_new_spec(code: str, root: Path = bmwe.BMWE_DIR) -> bool:
    return NEW_SPEC_MARKER in (root / code / "potenzial.prg").read_text(encoding="latin-1")


def growth(s: pd.Series) -> pd.Series:
    return 100 * s.pct_change()


# ---------------------------------------------------------------- 1. Nachbau
def replicate_all(root: Path = bmwe.BMWE_DIR) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Rechnet jede Runde nach und misst die Abweichung zu den BMWE-Ergebnissen."""
    rows, results = [], {}
    for code in bmwe.list_vintages(root):
        if not is_new_spec(code, root):
            rows.append({"runde": bmwe.vintage_label(code), "kürzel": code, "status": "ältere Programmfassung, nicht nachgerechnet"})
            continue
        v = bmwe.load_vintage(code, root)
        hz = potential.Horizon.from_dict(bmwe.read_horizon(code, root))
        r = potential.estimate(v["input"], hz)
        results[code] = r
        o = v.get("output")
        row = {"runde": bmwe.vintage_label(code), "kürzel": code, "status": "nachgerechnet",
               "kurzfrist_bis": hz.endy_st, "mittelfrist_bis": hz.endy_mt}
        if o is not None:
            for c, name in (("ypot", "max. Abw. Potenzial (Mrd. Euro)"), ("ygap", "max. Abw. Lücke (Pp.)"),
                            ("k", "max. Abw. Kapitalstock (Mrd. Euro)")):
                row[name] = float((r[c] - o[c]).abs().max())
        rows.append(row)
    return pd.DataFrame(rows), results


def vintage_overview(results: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Potenzialwachstum und Lücke je Runde für die Jahre der jeweiligen Projektion (Long-Format)."""
    rows = []
    for code, r in results.items():
        g = potential.growth_table(r, list(range(2015, int(r.index.max()) + 1)))
        for y, row in g.iterrows():
            rows.append({"runde": code, "jahr": y, **row.to_dict()})
    return pd.DataFrame(rows)


def revisions(results: dict[str, pd.DataFrame], var: str) -> pd.DataFrame:
    """Matrix Jahr × Runde für eine Größe (z. B. Lücke oder Potenzialwachstum)."""
    cols = {}
    for code in sorted(results, key=bmwe.vintage_sort_key):
        r = results[code]
        s = r["ygap"] if var == "ygap" else growth(r["ypot"])
        cols[code] = s.loc[2018:]
    return pd.DataFrame(cols).round(3)


# ---------------------------------------------------------------- 2. Eigene Filter
def own_filters(code: str, root: Path = bmwe.BMWE_DIR) -> dict:
    v = bmwe.load_vintage(code, root)
    hz = potential.Horizon.from_dict(bmwe.read_horizon(code, root))
    inp = v["input"].copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        nw = filters.estimate_nawru(v["gap_nawru"])
        tf = filters.estimate_tfp_mcmc(v["gap_tfp"], n_forecast=hz.endy_mt - int(v["gap_tfp"]["DE_TFP08"].last_valid_index()))
    nawru = filters.nawru_medium_term(nw.trend, hz.endy_mt)
    tfp = tf.trend.loc[: hz.endy_mt]
    variants = {}
    for name, n_, t_ in (("Bundesregierung (GAP)", None, None), ("eigene NAWRU", nawru, None),
                         ("eigener TFP-Trend", None, tfp), ("beide eigenen Filter", nawru, tfp)):
        x = inp.copy()
        if n_ is not None:
            x.loc[n_.index.intersection(x.index), "nairu"] = n_
        if t_ is not None:
            x.loc[t_.index.intersection(x.index), "tfp"] = t_
        variants[name] = potential.estimate(x, hz)
    comp_n = filters.compare(nawru, inp["nairu"]).loc[2000:]
    comp_t = filters.compare(100 * tfp.diff(), 100 * inp["tfp"].diff()).loc[2000:]
    comp_t["eigen P5"] = 100 * tf.extra["trend_growth_p05"].reindex(comp_t.index)
    comp_t["eigen P95"] = 100 * tf.extra["trend_growth_p95"].reindex(comp_t.index)
    years = list(range(2018, hz.endy_mt + 1))
    summary = pd.DataFrame({
        **{f"Potenzialwachstum: {k}": growth(r["ypot"]).reindex(years) for k, r in variants.items()},
        **{f"Lücke: {k}": r["ygap"].reindex(years) for k, r in variants.items()},
    })
    summary.index.name = "jahr"
    params = pd.concat([pd.Series(nw.params, name="NAWRU (ML)"), pd.Series(tf.params, name="TFP (Posterior-Mittelwert)"),
                        pd.Series(tf.extra["params_p05"], name="TFP P5"), pd.Series(tf.extra["params_p95"], name="TFP P95")], axis=1)
    params.loc["MCMC Annahmequote", "TFP (Posterior-Mittelwert)"] = tf.extra["acceptance"]
    params.loc["MCMC behaltene Ziehungen", "TFP (Posterior-Mittelwert)"] = tf.extra["kept"]
    return {"summary": summary, "nawru": comp_n, "tfp_growth": comp_t, "params": params, "variants": variants}


# ---------------------------------------------------------------- 3. Nowcast
def run_nowcast(raw: pd.DataFrame) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dfm = nowcast.dfm_nowcast(raw, horizon_quarters=1)
        br = nowcast.bridge_nowcast(raw, horizon_quarters=1)
    q = pd.DataFrame({"BIP q/q Ist": nowcast.quarterly_gdp(raw), "DFM": dfm.quarterly, "Bridge": br.quarterly})
    for c in ("DFM", "Bridge"):
        q.loc[q["BIP q/q Ist"].notna(), c] = np.nan
    q = q.loc["2023Q1":]
    q.index = q.index.astype(str)
    year = dfm.as_of.year
    path = dfm.quarterly
    ann = {
        "Jahr": year,
        "Jahreswachstum aus DFM-Pfad (SCA, %)": float(nowcast.annual_growth(path).get(year, np.nan)),
        "Jahreswachstum aus Bridge-Pfad (SCA, %)": float(nowcast.annual_growth(br.quarterly).get(year, np.nan)),
        f"Überhang für {year + 1} (Pp.)": float(nowcast.carry_over(path, year + 1)) if path.index.max().year > year else np.nan,
        "Datenstand Monate": str(dfm.as_of),
        "geschätzte Quartale": ", ".join(str(p) for p in dfm.estimated),
    }
    return {"quarterly": q, "annual": ann, "dfm": dfm}


# ---------------------------------------------------------------- 4. Backtests
def projection_backtest(root: Path = bmwe.BMWE_DIR) -> pd.DataFrame:
    """BIP-Projektionen der Bundesregierung (aus den Eingangsdaten je Runde) gegen den letzten Datenstand."""
    codes = bmwe.list_vintages(root)
    latest = bmwe.load_vintage(codes[-1], root)["input"]
    last_actual = bmwe.read_horizon(codes[-1], root)["endy_st"] - 2  # T-1 ist Ist
    actual = growth(latest["y"])
    rows = []
    for code in codes:
        inp = bmwe.load_vintage(code, root)["input"]
        y0 = 2000 + int(code[2:])  # Jahr der Veröffentlichung
        g = growth(inp["y"])
        for h, y in (("laufendes Jahr", y0), ("Folgejahr", y0 + 1)):
            rows.append({"runde": code, "horizont": h, "jahr": y, "projektion": g.get(y),
                         "ist (letzter Stand)": actual.get(y) if y <= last_actual else np.nan})
    df = pd.DataFrame(rows)
    df["fehler"] = df["projektion"] - df["ist (letzter Stand)"]
    return df


def projection_backtest_stats(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["fehler"])
    return d.groupby("horizont")["fehler"].agg(
        n="size", mittlerer_fehler="mean", RMSE=lambda e: float(np.sqrt((e**2).mean())), MAE=lambda e: float(e.abs().mean())
    )


def ameco_comparison(raw_dir: Path = data.RAW) -> pd.DataFrame | None:
    p = raw_dir / "ameco_deu.csv"
    if not p.exists():
        return None
    a = data.load_ameco(raw_dir)
    out = pd.DataFrame({
        "Potenzialwachstum EU-Kommission (%)": growth(a["OVGDP"]) if "OVGDP" in a else np.nan,
        "Lücke EU-Kommission (% Potenzial)": a.get("AVGDGP"),
        "NAWRU EU-Kommission (%)": a.get("ZNAWRU"),
    }).loc[2015:]
    out.index.name = "jahr"
    return out


# ---------------------------------------------------------------- Gesamt
def run(backtest_nowcast: bool = True, bt_start: str = "2014Q1") -> Results:
    res = Results()
    rep, results = replicate_all()
    res.tables["Nachbau"] = rep
    codes = [c for c in bmwe.list_vintages() if c in results]
    latest = codes[-1]
    res.meta["latest"] = latest
    res.meta["latest_label"] = bmwe.vintage_label(latest)
    hz = bmwe.read_horizon(latest)
    years = list(range(2018, hz["endy_mt"] + 1))
    res.tables["Potenzial"] = potential.growth_table(results[latest], years).round(3)
    res.tables["Revisionen Lücke"] = revisions(results, "ygap")
    res.tables["Revisionen Wachstum"] = revisions(results, "growth")

    log.info("Eigene Filter für %s", latest)
    of = own_filters(latest)
    res.tables["Eigene Filter"] = of["summary"].round(3)
    res.tables["NAWRU Vergleich"] = of["nawru"].round(3)
    res.tables["TFP Vergleich"] = of["tfp_growth"].round(3)
    res.tables["Filterparameter"] = of["params"]

    raw = data.load_eurostat()
    log.info("Nowcast")
    nc = run_nowcast(raw)
    res.tables["Nowcast"] = nc["quarterly"].round(2)
    res.meta["nowcast"] = nc["annual"]

    # Szenario: BIP des laufenden Jahres aus dem Nowcast in die letzte Runde einsetzen
    yr = nc["annual"]["Jahr"]
    inp = bmwe.load_vintage(latest)["input"].copy()
    g_br = growth(inp["y"]).get(yr)
    g_nc = nc["annual"]["Jahreswachstum aus DFM-Pfad (SCA, %)"]
    if g_br is not None and np.isfinite(g_nc):
        scale = (1 + g_nc / 100) / (1 + g_br / 100)
        x = inp.copy()
        x.loc[yr:, ["y", "yn"]] *= scale  # spätere Jahre behalten ihre Wachstumsraten
        r = potential.estimate(x, potential.Horizon.from_dict(hz))
        res.meta["szenario"] = {"jahr": yr, "BIP-Wachstum Runde": g_br, "BIP-Wachstum Nowcast": g_nc,
                                "Lücke Runde": float(results[latest]["ygap"][yr]), "Lücke mit Nowcast": float(r["ygap"][yr])}

    pb = projection_backtest()
    res.tables["Backtest Projektion"] = pb.round(3)
    res.tables["Backtest Projektion Kennzahlen"] = projection_backtest_stats(pb).round(3)
    if backtest_nowcast:
        log.info("Nowcast-Backtest ab %s", bt_start)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bt = nowcast.pseudo_realtime_backtest(raw, start=bt_start, maxiter=60)
            bb = nowcast.pseudo_realtime_backtest(raw, start=bt_start, model="bridge")
        bt["bridge"] = bb["nowcast"]
        res.tables["Backtest Nowcast"] = bt.round(3)
        st = nowcast.backtest_stats(bt.rename(columns={"nowcast": "nowcast"}))
        stb = nowcast.backtest_stats(bb).loc[["nowcast"]].rename(index={"nowcast": "bridge"})
        st = pd.concat([st.rename(index={"nowcast": "DFM"}), stb])
        st["RMSE relativ zu AR(1)"] = st["RMSE"] / st.loc["ar1", "RMSE"]
        res.tables["Backtest Nowcast Kennzahlen"] = st.round(3)
    am = ameco_comparison()
    if am is not None:
        res.tables["EU-Kommission"] = am.round(3)
    res.meta["eurostat_last"] = {c: str(raw[c].last_valid_index().date()) for c in raw}
    return res
