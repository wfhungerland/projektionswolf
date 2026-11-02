"""Produktionspotenzial nach dem EViews-Programm von BMWE und BMF (Stand seit Frühjahr 2024).

Die Funktion :func:`estimate` bildet ``eviews_potenzial_<K>.prg`` Schritt für Schritt
nach. NAWRU (``nairu``) und TFP-Trend (``tfp``) sind Eingangsgrößen; sie kommen bei der
Bundesregierung aus dem EU-Programm GAP (siehe :mod:`projektionswolf.filters`).

Ablauf (Jahreswerte, Cobb-Douglas mit Arbeitselastizität 0,65):

1. Partizipationsrate ohne Geflüchtete: AR(2) ohne Konstante, 1995 bis Ende Kurzfrist,
   dynamische Fortschreibung bis ``endy``, HP-Filter (λ=100) ab 1965.
   Geflüchtete gehen ab 2014 mit ihrer unterstellten Rate ungefiltert ein.
2. Arbeitszeit je Erwerbstätigen: 2020 durch den Mittelwert der Nachbarjahre ersetzt,
   AR(1) mit Konstante, Fortschreibung, HP-Filter (λ=100).
3. Potenzielles Arbeitsvolumen = Trend-Partizipation × Erwerbsbevölkerung × (1−NAWRU) × Trend-Arbeitszeit.
4. Potenzial = Arbeitsvolumen^0,65 × Kapitalstock^0,35 × exp(TFP-Trend).
5. Mittelfrist: Investitionsquote am Potenzial per AR(2) fortgeschrieben, Abgangsrate
   konstant, Kapitalstock und Potenzial simultan gelöst; danach Investitionen auf einen
   geometrischen Pfad geglättet und Kapitalstock neu kumuliert.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.filters.hp_filter import hpfilter

ELAST_L = 0.65
ELAST_K = 1 - ELAST_L
REFUGEE_START = 2014  # erstes Jahr mit eigener Partizipationsrate der Geflüchteten


@dataclass
class Horizon:
    endy_st: int  # Ende der Kurzfristprojektion (T+1)
    endy_mt: int  # Ende der Mittelfristprojektion
    endy: int  # Ende der technischen Verlängerung für die Filter
    start: int = 1960

    @classmethod
    def from_dict(cls, d: dict) -> "Horizon":
        return cls(d["endy_st"], d["endy_mt"], d["endy"])


# ---------------------------------------------------------------- Bausteine
def ols_ar(y: pd.Series, start: int, end: int, lags: int, const: bool) -> np.ndarray:
    """OLS von y auf Konstante und eigene Lags im Stützzeitraum [start, end]."""
    idx = range(start, end + 1)
    Y = np.array([y[t] for t in idx])
    cols = [np.ones(len(Y))] if const else []
    cols += [np.array([y[t - k] for t in idx]) for k in range(1, lags + 1)]
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    return beta


def ar_forecast(y: pd.Series, beta: np.ndarray, start: int, end: int, lags: int, const: bool) -> pd.Series:
    """Dynamische Prognose über [start, end]; außerhalb bleiben die Ist-Werte (EViews ``f=actual``)."""
    out = y.copy()
    for t in range(start, end + 1):
        x = ([1.0] if const else []) + [out[t - k] for k in range(1, lags + 1)]
        out[t] = float(np.dot(beta, x))
    return out


def hp(y: pd.Series, start: int, end: int, lam: float = 100) -> pd.Series:
    seg = y.loc[start:end]
    if seg.isna().any():
        raise ValueError(f"HP-Filter: Lücken in {seg[seg.isna()].index.tolist()}")
    _, trend = hpfilter(seg.values, lamb=lam)
    return pd.Series(trend, index=seg.index).reindex(y.index)


# ---------------------------------------------------------------- Schätzung
def estimate(inp: pd.DataFrame, hz: Horizon, return_steps: bool = False) -> pd.DataFrame:
    """Rechnet das Produktionspotenzial aus den Eingangsdaten einer Projektionsrunde.

    ``inp`` hat den Jahresindex und die EViews-Namen als Spalten:
    y, iq, k, l, hpere, lur, popw, nairu, pop, yn, tfp, popw_fl, part_fl, popw_nfl.
    ``lur`` und ``nairu`` in Prozent, ``part_fl`` als Anteil.
    """
    years = pd.Index(range(hz.start, hz.endy + 1), name="year")
    d = inp.reindex(years).astype(float).copy()
    s = {c: d[c].copy() for c in d.columns}
    ST, MT, E = hz.endy_st, hz.endy_mt, hz.endy
    mt0 = ST + 1

    lur = s["lur"] / 100
    nairu = s["nairu"] / 100
    lf = s["l"] / (1 - lur)
    has_fl = "popw_fl" in s and s["popw_fl"].notna().any()
    if has_fl:
        lf_fl = s["part_fl"] * s["popw_fl"]
        lf_nfl = lf.copy()
        lf_nfl.loc[REFUGEE_START:MT] = (lf - lf_fl).loc[REFUGEE_START:MT]
        popw_nfl = s["popw_nfl"]
    else:
        lf_nfl, popw_nfl = lf, s["popw"]
    part_nfl = 100 * lf_nfl / popw_nfl
    totalh = s["l"] * s["hpere"]

    # 1. Partizipationsrate
    b_part = ols_ar(part_nfl, 1995, ST, lags=2, const=False)
    part_f_nfl = ar_forecast(part_nfl, b_part, mt0, E, lags=2, const=False)
    parts_nfl = hp(part_f_nfl, 1965, E)
    if has_fl:
        w_nfl = popw_nfl / (popw_nfl + s["popw_fl"])
        w_fl = s["popw_fl"] / (popw_nfl + s["popw_fl"])
        parts = pd.Series(np.nan, index=years)
        part = pd.Series(np.nan, index=years)
        sl = slice(REFUGEE_START, MT)
        parts.loc[sl] = (w_nfl * parts_nfl + w_fl * s["part_fl"] * 100).loc[sl]
        part.loc[sl] = (w_nfl * part_f_nfl + w_fl * s["part_fl"] * 100).loc[sl]
        parts.loc[: REFUGEE_START - 1] = parts_nfl.loc[: REFUGEE_START - 1]
        part.loc[: REFUGEE_START - 1] = part_f_nfl.loc[: REFUGEE_START - 1]
    else:
        parts, part = parts_nfl, part_f_nfl

    # 2. Arbeitszeit je Erwerbstätigen
    hpere = s["hpere"]
    hpere_mod = hpere.copy()
    hpere_mod[2020] = (hpere[2019] + hpere[2021]) / 2
    b_h = ols_ar(hpere_mod, 1976, ST, lags=1, const=True)
    hpere_mod_f = ar_forecast(hpere_mod, b_h, mt0, E, lags=1, const=True)
    hperehp = hp(hpere_mod_f, 1965, E)
    b_h2 = ols_ar(hpere, 1976, ST, lags=1, const=True)
    hpere_out = ar_forecast(hpere, b_h2, mt0, E, lags=1, const=True)

    # 3./4. Potenzielles Arbeitsvolumen und Potenzial
    totalhs = parts / 100 * s["popw"] * (1 - nairu) * hperehp
    tfp = s["tfp"]
    k = s["k"].copy()
    iq = s["iq"].copy()
    ypot = totalhs**ELAST_L * k**ELAST_K * np.exp(tfp)

    # 5. Mittelfrist: Investitionsquote und Kapitalstock
    iypot = 100 * iq / ypot
    b_i = ols_ar(iypot, 1995, ST, lags=2, const=True)
    iypot = ar_forecast(iypot, b_i, mt0, E, lags=2, const=True)
    dep = (iq - (k - k.shift(1))) / k.shift(1)
    for t in range(mt0, E + 1):
        dep[t] = dep[t - 1]

    k0, iq0 = k.copy(), iq.copy()
    for t in range(mt0, MT + 1):
        a = totalhs[t] ** ELAST_L * np.exp(tfp[t])
        kt = k0[t - 1]
        for _ in range(200):  # Fixpunkt: k = iy/100 * a * k^0,35 + (1-dep) k(-1)
            new = iypot[t] / 100 * a * kt**ELAST_K + (1 - dep[t]) * k0[t - 1]
            if abs(new - kt) < 1e-12 * max(1.0, abs(kt)):
                kt = new
                break
            kt = new
        k0[t] = kt
        iq0[t] = iypot[t] / 100 * a * kt**ELAST_K
    iq, k = iq0, k0

    g = (iq[MT] / iq[MT - 3]) ** (1 / 3)
    for t in range(mt0, MT):
        iq[t] = iq[t - 1] * g
    for t in range(mt0, MT + 1):
        k[t] = iq[t] + (1 - dep[t]) * k[t - 1]
    sr = np.log(s["y"] / (totalh**ELAST_L * k**ELAST_K))
    ypot = totalhs**ELAST_L * k**ELAST_K * np.exp(tfp)

    res = pd.DataFrame(
        {
            "dep": 100 * dep,
            "hpere": hpere_out,
            "hperehp": hperehp,
            "iq": iq,
            "k": k,
            "l": s["l"],
            "lur": 100 * lur,
            "nairu": 100 * nairu,
            "part": part,
            "parts": parts,
            "pop": s["pop"],
            "popw": s["popw"],
            "sr": sr,
            "tfp": tfp,
            "y": s["y"],
            "ygap": (s["y"] / ypot - 1) * 100,
            "yn": s["yn"],
            "ypot": ypot,
            "ypotn": ypot * s["yn"] / s["y"],
            "totalhs": totalhs,
        },
        index=years,
    ).loc[:MT]
    if has_fl:
        res["popw_fl"] = s["popw_fl"]
        res["popw_nfl"] = s["popw_nfl"]
    if return_steps:
        res.attrs["coef"] = {"part_nfl_ar2": b_part, "hpere_ar1": b_h, "iypot_ar2": b_i}
    return res


def growth_table(res: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Wachstumsraten und Wachstumsbeiträge des Potenzials (in % bzw. Prozentpunkten)."""
    lg = np.log(res[["ypot", "totalhs", "k"]])
    tfp = res["tfp"]
    out = pd.DataFrame(index=years)
    out["Potenzialwachstum"] = 100 * (np.exp(lg["ypot"].diff()) - 1).reindex(years)
    out["Beitrag Arbeit"] = 100 * ELAST_L * lg["totalhs"].diff().reindex(years)
    out["Beitrag Kapital"] = 100 * ELAST_K * lg["k"].diff().reindex(years)
    out["Beitrag TFP"] = 100 * tfp.diff().reindex(years)
    out["Produktionslücke"] = res["ygap"].reindex(years)
    out["BIP-Wachstum"] = 100 * res["y"].pct_change().reindex(years)
    out.index.name = "year"
    return out
