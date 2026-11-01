"""BIP-Nowcast für Deutschland aus Monatsindikatoren.

Hauptmodell ist ein dynamisches Faktormodell mit gemischten Frequenzen
(statsmodels ``DynamicFactorMQ``, Mariano-Murasawa-Aggregation): ein gemeinsamer
Faktor aus Produktion, Bau, Einzelhandel, Umfragen und Arbeitslosigkeit erklärt
das Quartalswachstum des BIP. Als Gegenprobe dient eine Bridge-Gleichung
(Quartals-OLS auf Produktion und Wirtschaftsklima, fehlende Monate per AR(2)).

Alle Wachstumsraten sind preis-, saison- und kalenderbereinigt (Eurostat SCA).
Jahresraten daraus weichen von den unbereinigten Ursprungswerten der
Bundesregierung um den Kalendereffekt ab.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

# Transformation je Monatsreihe: "dlog" = Veränderung gg. Vormonat in %, "level", "diff"
MONTHLY = {
    "ip": "dlog",
    "ip_manuf": "dlog",
    "construction": "dlog",
    "retail": "dlog",
    "esi": "level",
    "conf_industry": "level",
    "conf_services": "level",
    "conf_consumer": "level",
    "conf_retail": "level",
    "conf_construction": "level",
    "unemp": "diff",
}
HARD = ["ip", "ip_manuf", "construction", "retail", "unemp"]  # Veröffentlichung mit ~6 Wochen Verzug
SOFT = [k for k in MONTHLY if k not in HARD]  # Umfragen: Ende des Berichtsmonats
START = "1999-01"
COVID_MONTHS = ("2020-03", "2021-03")  # in der Schätzung als fehlend behandelt
SOFT_TRANSFORM = "diff12"  # Umfragen: "level" oder "diff12" (Veränderung gg. Vorjahresmonat)


def monthly_panel(raw: pd.DataFrame, soft: str | None = None, mask_covid: bool = True) -> pd.DataFrame:
    """Rohdaten (Index Monatserster) -> stationäre Monatsreihen mit PeriodIndex."""
    soft = soft or SOFT_TRANSFORM
    out = {}
    for k, how in MONTHLY.items():
        if k not in raw:
            continue
        s = raw[k].dropna()
        s.index = pd.PeriodIndex(s.index, freq="M")
        if how == "dlog":
            s = 100 * np.log(s).diff()
        elif how == "diff":
            s = s.diff()
        elif how == "level" and soft == "diff12":
            s = s.diff(12)
        out[k] = s
    df = pd.DataFrame(out)
    df = df.loc[START:]
    if mask_covid:
        df.loc[COVID_MONTHS[0]:COVID_MONTHS[1]] = np.nan
    full = pd.period_range(df.index.min(), df.index.max(), freq="M")
    return df.reindex(full)


def quarterly_gdp(raw: pd.DataFrame, mask_covid: bool = False) -> pd.Series:
    s = raw["gdp_qoq"].dropna()
    s.index = pd.PeriodIndex(s.index, freq="Q")
    s = s.loc[pd.Period(START, "M").asfreq("Q"):]
    if mask_covid:
        a, b = (pd.Period(x, "M").asfreq("Q") for x in COVID_MONTHS)
        s = s[(s.index < a) | (s.index > b + 1)]  # +1: Wachstumsrate des Folgequartals ist ebenfalls verzerrt
    return s


@dataclass
class Nowcast:
    quarterly: pd.Series  # BIP-Wachstum gg. Vorquartal in %, Ist und Schätzung
    estimated: list  # Quartale, die geschätzt sind
    as_of: pd.Period  # letzter Monat mit Daten
    model: str


def _extend_index(m: pd.DataFrame, until: pd.Period) -> pd.DataFrame:
    full = pd.period_range(m.index.min(), until, freq="M")
    return m.reindex(full)


def dfm_nowcast(raw: pd.DataFrame, horizon_quarters: int = 1, as_of: pd.Period | None = None,
                maxiter: int = 300, factor_orders: int = 2, factors: int = 1, soft: str | None = None,
                mask_covid: bool = True) -> Nowcast:
    """Schätzt das Faktormodell und gibt BIP-Wachstum bis ``horizon_quarters`` nach dem laufenden Quartal."""
    m = monthly_panel(raw, soft=soft, mask_covid=mask_covid)
    q_all = quarterly_gdp(raw)
    q = quarterly_gdp(raw, mask_covid=mask_covid)
    if as_of is not None:
        m = m.loc[:as_of]
        q = q.loc[: as_of.asfreq("Q") - 1] if as_of.month % 3 != 0 else q.loc[: as_of.asfreq("Q")]
    as_of = m.dropna(how="all").index.max()
    target_q = as_of.asfreq("Q") + horizon_quarters
    m = _extend_index(m, target_q.asfreq("M", how="end"))
    m = m.loc[:, m.notna().sum() > 60]
    qdf = q.to_frame("gdp_qoq")
    qdf.index = qdf.index.asfreq("M", how="end")
    qdf = qdf.reindex(m.index)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mod = DynamicFactorMQ(m, endog_quarterly=_q_endog(q, m), factors=factors, factor_orders=factor_orders,
                              idiosyncratic_ar1=True, standardize=True)
        res = mod.fit(disp=False, maxiter=maxiter)
    # geglättetes Signal der BIP-Gleichung (nutzt alle Monatsdaten des Quartals), zurückskaliert
    sf = res.smoother_results.smoothed_forecasts[-1]
    mean = np.asarray(mod._endog_mean)[-1] if mod.standardize is not False else 0.0
    std = np.asarray(mod._endog_std)[-1] if mod.standardize is not False else 1.0
    g = pd.Series(sf * std + mean, index=m.index)
    gq = g[g.index.month % 3 == 0]
    gq.index = gq.index.asfreq("Q")
    q_all = q_all.loc[: q.index.max()]
    out = q_all.reindex(pd.period_range(q_all.index.min(), target_q, freq="Q"))
    est = [p for p in out.index if pd.isna(out[p])]
    for p in est:
        out[p] = gq.get(p, np.nan)
    return Nowcast(quarterly=out, estimated=est, as_of=as_of, model="DFM")


def _q_endog(q: pd.Series, m: pd.DataFrame) -> pd.DataFrame:
    """Quartalsreihe für DynamicFactorMQ: Quartals-PeriodIndex über denselben Zeitraum wie die Monate."""
    qi = pd.period_range(m.index.min().asfreq("Q"), m.index.max().asfreq("Q"), freq="Q")
    return q.reindex(qi).to_frame("gdp_qoq")


def bridge_nowcast(raw: pd.DataFrame, horizon_quarters: int = 0, as_of: pd.Period | None = None) -> Nowcast:
    """Bridge-Gleichung: BIP q/q auf Produktion q/q und Wirtschaftsklima (Veränderung)."""
    import statsmodels.api as sm

    lv = raw[["ip", "esi"]].copy()
    lv.index = pd.PeriodIndex(lv.index, freq="M")
    q = quarterly_gdp(raw)
    if as_of is not None:
        lv = lv.loc[:as_of]
        q = q.loc[: as_of.asfreq("Q") - (0 if as_of.month % 3 == 0 else 1)]
    as_of = lv.dropna(how="all").index.max()
    target_q = as_of.asfreq("Q") + horizon_quarters
    lv = lv.reindex(pd.period_range(lv.index.min(), target_q.asfreq("M", how="end"), freq="M"))
    # fehlende Monate: AR(2) auf Monatsveränderung bzw. Niveau
    for c in lv:
        s = lv[c]
        last = s.last_valid_index()
        hist = (np.log(s) if c == "ip" else s).loc[:last].dropna()
        x = hist.diff().dropna() if c == "ip" else hist
        y = x.values[2:]
        X = np.column_stack([np.ones(len(y)), x.values[1:-1], x.values[:-2]])
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        vals = list(x.values[-2:])
        lvl = hist.iloc[-1]
        for p in lv.index[lv.index > last]:
            nxt = b @ [1, vals[-1], vals[-2]]
            vals.append(nxt)
            lvl = lvl + nxt if c == "ip" else nxt
            lv.loc[p, c] = np.exp(lvl) if c == "ip" else lvl
    qa = lv.groupby(lv.index.asfreq("Q")).mean()
    X = pd.DataFrame({"ip": 100 * np.log(qa["ip"]).diff(), "desi": qa["esi"].diff()})
    df = pd.concat([q.rename("gdp"), X], axis=1)
    covid = [pd.Period(p, "Q") for p in ("2020Q1", "2020Q2", "2020Q3", "2020Q4", "2021Q1")]
    fit = df.dropna().drop(index=[c for c in covid if c in df.dropna().index])
    res = sm.OLS(fit["gdp"], sm.add_constant(fit[["ip", "desi"]])).fit()
    out = q.reindex(pd.period_range(q.index.min(), target_q, freq="Q"))
    est = [p for p in out.index if pd.isna(out[p])]
    for p in est:
        out[p] = float(res.params @ [1, X.loc[p, "ip"], X.loc[p, "desi"]])
    return Nowcast(quarterly=out, estimated=est, as_of=as_of, model="Bridge")


def annual_growth(qoq: pd.Series) -> pd.Series:
    """Jahreswachstum in % aus Quartalsraten (Niveau als Kette, Jahresdurchschnitt)."""
    lvl = (1 + qoq.fillna(0) / 100).cumprod()
    lvl[qoq.isna()] = np.nan
    yr = lvl.groupby(lvl.index.year).agg(["mean", "count"])
    a = yr["mean"].where(yr["count"] == 4)
    return 100 * a.pct_change()


def carry_over(qoq: pd.Series, year: int) -> float:
    """Statistischer Überhang: Jahreswachstum ``year``, wenn das BIP auf dem Niveau des Q4 des Vorjahres bliebe."""
    lvl = (1 + qoq.fillna(0) / 100).cumprod()
    prev = lvl[lvl.index.year == year - 1]
    return 100 * (prev.iloc[-1] / prev.mean() - 1)


# ---------------------------------------------------------------- Backtest
def pseudo_realtime_backtest(raw: pd.DataFrame, start: str = "2012Q1", end: str | None = None,
                             model: str = "dfm", maxiter: int = 100, **kw) -> pd.DataFrame:
    """Nowcast je Quartal zum Ende seines dritten Monats.

    Informationsstand: Umfragen bis Monat 3, harte Daten bis Monat 1, BIP bis Vorquartal.
    Genutzt wird der heutige Datenstand (keine Echtzeit-Vintages); Revisionen bleiben außen vor.
    """
    q = quarterly_gdp(raw)
    end = end or str(q.index.max())
    rows = []
    for p in pd.period_range(start, end, freq="Q"):
        m3 = p.asfreq("M", how="end")
        cut = raw.copy()
        cut.index = pd.PeriodIndex(cut.index, freq="M")
        for c in HARD:
            if c in cut:
                cut.loc[cut.index > m3 - 2, c] = np.nan
        for c in SOFT:
            if c in cut:
                cut.loc[cut.index > m3, c] = np.nan
        cut.loc[cut.index > (p - 1).asfreq("M", how="end"), "gdp_qoq"] = np.nan
        cut = cut.loc[:m3]
        cut.index = cut.index.to_timestamp()
        try:
            if model == "dfm":
                nc = dfm_nowcast(cut, horizon_quarters=0, maxiter=maxiter, **kw)
            else:
                nc = bridge_nowcast(cut, horizon_quarters=0)
            val = float(nc.quarterly.get(p, np.nan))
        except Exception:
            val = np.nan
        prev = q.loc[: p - 1]
        rows.append({"quartal": str(p), "ist": q.get(p, np.nan), "nowcast": val,
                     "ar1": _ar1_forecast(prev), "mittelwert": float(prev.loc[str(p - 40):].mean())})
    return pd.DataFrame(rows).set_index("quartal")


def _ar1_forecast(y: pd.Series) -> float:
    covid = (y.index >= pd.Period("2020Q1", "Q")) & (y.index <= pd.Period("2021Q1", "Q"))
    z = y[~covid]
    x, t = z.values[:-1], z.values[1:]
    b = np.linalg.lstsq(np.column_stack([np.ones(len(x)), x]), t, rcond=None)[0]
    return float(b[0] + b[1] * y.iloc[-1])


def backtest_stats(bt: pd.DataFrame, exclude_covid: bool = True) -> pd.DataFrame:
    d = bt.dropna(subset=["ist"])
    if exclude_covid:
        d = d[~d.index.isin(["2020Q1", "2020Q2", "2020Q3", "2020Q4", "2021Q1"])]
    out = {}
    for c in ("nowcast", "ar1", "mittelwert"):
        e = (d[c] - d["ist"]).dropna()
        out[c] = {"RMSE": float(np.sqrt((e**2).mean())), "MAE": float(e.abs().mean()), "n": int(len(e))}
    df = pd.DataFrame(out).T
    df["RMSE relativ zu AR(1)"] = df["RMSE"] / df.loc["ar1", "RMSE"]
    return df
