"""Eigene Schätzung von NAWRU und TFP-Trend mit Kalman-Filtern nach dem EU-Ansatz.

Die Bundesregierung nutzt dafür das EU-Programm GAP mit Bayes-Schätzung und
Prioren der EU-Kommission. Hier steht dieselbe Modellstruktur, geschätzt per
Maximum Likelihood innerhalb der Parametergrenzen aus den GAP-Spezifikationen.
Ergebnisse weichen deshalb von den GAP-Werten ab; :func:`compare` beziffert das.

NAWRU (traditionelle Phillips-Kurve, "TKP"):
    u_t     = N_t + C_t
    N_t     = N_{t-1} + S_{t-1} + η_t         (Trend: Random Walk 2. Ordnung)
    S_t     = S_{t-1} + ζ_t
    C_t     = φ1 C_{t-1} + φ2 C_{t-2} + κ_t   (Zyklus: AR(2))
    DWS_t   = α + β C_t + γ' X_t + e_t        (Lohn-Phillips-Kurve, X: ddprod, ddtot(-1), ddprod(-1))

TFP-Trend (Solow-Residuum, Kapazitätsauslastung CUBS als Signal):
    sr_t    = P_t + C_t
    P_t     = P_{t-1} + μ_{t-1}
    μ_t     = (1-ω) μ̄ + ω μ_{t-1} + ζ_t     (gedämpfter Trendzuwachs)
    C_t     = φ1 C_{t-1} + φ2 C_{t-2} + κ_t
    CUBS_t  = α + β C_t + e_t
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from statsmodels.tsa.statespace.initialization import Initialization
from statsmodels.tsa.statespace.mlemodel import MLEModel


@dataclass
class Param:
    name: str
    lb: float
    ub: float
    start: float | None = None

    def to_bounded(self, x: float) -> float:
        return self.lb + (self.ub - self.lb) / (1 + np.exp(-x))

    def to_free(self, v: float) -> float:
        p = (v - self.lb) / (self.ub - self.lb)
        p = min(max(p, 1e-6), 1 - 1e-6)
        return float(np.log(p / (1 - p)))


def _ar2_ok(phi1: float, phi2: float) -> bool:
    return phi2 < 1 - 1e-4 + 0 and phi2 + phi1 < 1 - 1e-4 and phi2 - phi1 < 1 - 1e-4 and phi2 > -1 + 1e-4


class _UCModel(MLEModel):
    """Gemeinsame Basis: Trend + AR(2)-Zyklus mit zweiter Signalgleichung."""

    params_spec: list[Param]

    def __init__(self, endog: pd.DataFrame, exog: pd.DataFrame | None, params_spec: list[Param]):
        self.params_spec = params_spec
        self._exog_df = exog
        super().__init__(endog.values, k_states=4, k_posdef=3, initialization=None)
        self["selection"] = np.zeros((4, 3))
        self["selection", 0, 0] = 1
        self["selection", 1, 1] = 1
        self["selection", 2, 2] = 1
        self["transition", 3, 2] = 1
        self["design", 0, 0] = 1
        self["design", 0, 2] = 1
        init = Initialization(4)
        init.set((0, 2), "approximate_diffuse")
        init.set((2, 4), "stationary")
        self.ssm.initialization = init
        self._diffuse_var = 1e6

    @property
    def param_names(self):
        return [p.name for p in self.params_spec]

    @property
    def start_params(self):
        return np.array([p.start if p.start is not None else (p.lb + p.ub) / 2 for p in self.params_spec])

    def transform_params(self, unconstrained):
        return np.array([p.to_bounded(x) for p, x in zip(self.params_spec, unconstrained)])

    def untransform_params(self, constrained):
        return np.array([p.to_free(v) for p, v in zip(self.params_spec, constrained)])


class NawruModel(_UCModel):
    EXOG = ["ddprod", "ddtot-1", "ddprod-1"]

    def __init__(self, df: pd.DataFrame):
        spec = [
            Param("phi1", -1.96, 1.96, 1.2),
            Param("phi2", -0.97, 0.97, -0.5),
            Param("var_trend", 0.002, 0.06, 0.02),
            Param("var_slope", 0.0, 0.15, 0.01),
            Param("var_cycle", 1e-8, 0.5125, 0.1),
            Param("alpha", -1.0, 1.0, 0.0),
            Param("beta", -2.0, 2.0, -0.01),
            Param("g_ddprod", 0.0, 3.0, 0.3),
            Param("g_ddtot1", -3.0, 3.0, 0.0),
            Param("g_ddprod1", 0.0, 1.0, 0.3),
            Param("var_pc", 1e-8, 0.000543, 0.0003),
        ]
        super().__init__(df[["LUR", "DWS"]], df[self.EXOG], spec)
        self["transition", 0, 0] = 1
        self["transition", 0, 1] = 1
        self["transition", 1, 1] = 1
        init = Initialization(4)
        init.set((0, 2), "approximate_diffuse")
        init.set((2, 4), "stationary")
        self.ssm.initialization = init

    def update(self, params, **kwargs):
        params = super().update(params, **kwargs)
        p = dict(zip(self.param_names, params))
        self["transition", 2, 2] = p["phi1"]
        self["transition", 2, 3] = p["phi2"]
        self["state_cov"] = np.diag([p["var_trend"], p["var_slope"], p["var_cycle"]])
        self["design", 1, 2] = p["beta"]
        X = self._exog_df.fillna(0.0).values
        d = np.zeros((2, self.nobs))
        d[1] = p["alpha"] + X @ np.array([p["g_ddprod"], p["g_ddtot1"], p["g_ddprod1"]])
        self["obs_intercept"] = d
        self["obs_cov"] = np.diag([0.0, p["var_pc"]])


class TfpModel(_UCModel):
    def __init__(self, df: pd.DataFrame, slope_mean_ub: float = 0.0402):
        spec = [
            Param("phi1", -1.96, 1.96, 1.0),
            Param("phi2", -0.97, 0.97, -0.3),
            Param("omega", 0.0, 0.99, 0.8),
            Param("slope_mean", 0.0, slope_mean_ub, 0.005),
            Param("var_slope", 1e-10, 9.9e-5, 1e-5),
            Param("var_cycle", 1e-10, 9.9e-5, 5e-5),
            Param("alpha", -0.1, 0.1, 0.0),
            Param("beta", 0.0, 10.0, 2.0),
            Param("var_cubs", 1e-8, 0.00075, 0.0003),
        ]
        super().__init__(df[["sr", "CUBS"]], None, spec)
        self["selection"] = np.zeros((4, 3))
        self["selection", 1, 1] = 1
        self["selection", 2, 2] = 1
        self["transition", 0, 0] = 1
        self["transition", 0, 1] = 1
        init = Initialization(4)
        init.set(0, "approximate_diffuse")
        init.set(1, "approximate_diffuse")
        init.set((2, 4), "stationary")
        self.ssm.initialization = init

    def update(self, params, **kwargs):
        params = super().update(params, **kwargs)
        self._apply(dict(zip(self.param_names, params)))

    def _apply(self, p: dict):
        self["transition", 1, 1] = p["omega"]
        self["state_intercept"] = np.array([0, (1 - p["omega"]) * p["slope_mean"], 0, 0])
        self["transition", 2, 2] = p["phi1"]
        self["transition", 2, 3] = p["phi2"]
        self["state_cov"] = np.diag([0.0, p["var_slope"], p["var_cycle"]])
        self["design", 1, 2] = p["beta"]
        self["obs_intercept"] = np.array([0.0, p["alpha"]])
        self["obs_cov"] = np.diag([0.0, p["var_cubs"]])


@dataclass
class FilterResult:
    trend: pd.Series
    cycle: pd.Series
    params: dict
    loglike: float
    extra: dict = field(default_factory=dict)


def _fit(model: _UCModel, n_starts: int = 6, seed: int = 0):
    """ML-Schätzung mit mehreren Startwerten; AR(2)-Zyklus muss stationär sein."""
    rng = np.random.default_rng(seed)
    best = None

    def negll(x):
        c = model.transform_params(x)
        p = dict(zip(model.param_names, c))
        if not _ar2_ok(p["phi1"], p["phi2"]):
            return 1e10
        try:
            ll = model.loglike(c, transformed=True)
        except Exception:
            return 1e10
        return -ll if np.isfinite(ll) else 1e10

    x0 = model.untransform_params(model.start_params)
    starts = [x0] + [x0 + rng.normal(0, 1.0, len(x0)) for _ in range(n_starts - 1)]
    for s in starts:
        r = minimize(negll, s, method="L-BFGS-B", options={"maxiter": 2000})
        r = minimize(negll, r.x, method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-7, "fatol": 1e-9})
        if best is None or r.fun < best.fun:
            best = r
    params = model.transform_params(best.x)
    res = model.smooth(params, transformed=True)
    return params, res, -best.fun


def estimate_nawru(gap: pd.DataFrame, n_starts: int = 6) -> FilterResult:
    df = gap.dropna(subset=["LUR"]).copy()
    m = NawruModel(df)
    params, res, ll = _fit(m, n_starts)
    st = res.smoothed_state
    return FilterResult(
        trend=pd.Series(st[0], index=df.index, name="nawru"),
        cycle=pd.Series(st[2], index=df.index, name="u_cycle"),
        params=dict(zip(m.param_names, params)),
        loglike=ll,
        extra={"slope_last": float(st[1, -1])},
    )


def estimate_tfp(gap: pd.DataFrame, n_forecast: int = 3, n_starts: int = 6) -> FilterResult:
    """``gap`` enthält ``DE_TFP08`` (log Solow-Residuum) und ``DE_CUBS08``."""
    df = gap.rename(columns={"DE_TFP08": "sr", "DE_CUBS08": "CUBS"})[["sr", "CUBS"]]
    df = df.loc[df["sr"].first_valid_index() : df["sr"].last_valid_index()]
    m = TfpModel(df)
    params, res, ll = _fit(m, n_starts)
    st = res.smoothed_state
    trend = pd.Series(st[0], index=df.index, name="tfp")
    # Fortschreibung des Trends: P_{t+1} = P_t + μ_t, μ konvergiert gedämpft zu μ̄
    p = dict(zip(m.param_names, params))
    P, mu = st[0, -1], st[1, -1]
    fc = {}
    for h in range(1, n_forecast + 1):
        P = P + mu
        mu = (1 - p["omega"]) * p["slope_mean"] + p["omega"] * mu
        fc[df.index[-1] + h] = P
    trend = pd.concat([trend, pd.Series(fc)])
    return FilterResult(trend=trend, cycle=pd.Series(st[2], index=df.index), params=p, loglike=ll)


def nawru_medium_term(nawru: pd.Series, end: int, anchor: float = 3.6, horizon: int = 8) -> pd.Series:
    """Mittelfrist-Fortschreibung der NAWRU: lineare Annäherung an den Anker.

    Vereinfachte Regel; GAP nutzt den Anker innerhalb der Filterprognose.
    """
    out = nawru.copy()
    last = out.index.max()
    step = (anchor - out[last]) / horizon
    for h, t in enumerate(range(last + 1, end + 1), start=1):
        out[t] = out[last] + h * step
    return out


def compare(own: pd.Series, official: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"eigen": own, "bundesregierung": official}).dropna()
    df["differenz"] = df["eigen"] - df["bundesregierung"]
    return df


# ---------------------------------------------------------------- Bayes (Posterior-Modus) für TFP
from scipy import stats  # noqa: E402

# Prioren der EU-Kommission für Deutschland aus priorsDE_<K>.mat (Struktur data.M, je Parameter
# eine 8x2-Matrix). Genutzt wird Zeile 1 (Mittelwert, Std.-Abw.) mit den Grenzen aus Zeile 2/3,
# Spalte 0. Mit dieser Lesart und Normal-Prioren für Amplitude und Dämpfung trifft der
# Posterior-Mittelwert die GAP-Ergebnisse der Bundesregierung (siehe tests/test_filters.py).
# Die Datei ist in allen Runden seit 2023 identisch.
TFP_PRIORS_DE = {
    "amplitude": ("normal", 0.422013, 0.17, 0.0, 1.0),
    "period": ("normal", 7.998562, 3.5, 2.0, 32.0),
    "omega": ("normal", 0.7984656, 0.2381, 0.0, 0.99),
    "slope_mean": ("normal", 0.01499845, 0.01002463, 0.0, 0.03),
    "var_slope": ("invgamma", 2.426325e-06, 2.426325e-06, 2.426325e-09, 2.674973e-02),
    "var_cycle": ("invgamma", 3.015291e-04, 3.023870e-04, 3.015291e-07, 5.349945e-02),
    "alpha": ("normal", 4.0e-04, 3.133616e-02, -0.1, 0.1),
    "beta": ("normal", 1.4, 0.705, 0.0, 5.0),
    "var_cubs": ("invgamma", 3.003773e-03, 3.003773e-03, 4.500238e-07, 8.543948e-02),
}


def load_tfp_priors(path) -> dict:
    """Liest die Prioren aus einer GAP-.mat-Datei (Zeile 1: Mittelwert und Std.-Abw.)."""
    import scipy.io

    M = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)["data"].M
    row = lambda a: (float(a[1, 0]), float(a[1, 1]), float(a[2, 0]), float(a[3, 0]))  # noqa: E731
    keys = {"amplitude": "amplitude", "period": "period", "omega": "damp", "slope_mean": "dampmean",
            "var_slope": "slope", "var_cycle": "cycle", "alpha": "exog2", "beta": "beta", "var_cubs": "inf"}
    out = {}
    for k, f in keys.items():
        m, s, lb, ub = row(getattr(M, f))
        out[k] = (TFP_PRIORS_DE[k][0], m, s, lb, ub)
    return out


def _logprior(kind: str, x: float, m: float, s: float, lb: float, ub: float) -> float:
    if not (lb <= x <= ub):
        return -np.inf
    if kind == "normal":
        return stats.norm.logpdf(x, m, s)
    if kind == "beta":
        z, mz, sz = (x - lb) / (ub - lb), (m - lb) / (ub - lb), s / (ub - lb)
        k = mz * (1 - mz) / sz**2 - 1
        return stats.beta.logpdf(z, mz * k, (1 - mz) * k)
    if kind == "invgamma":
        a = m**2 / s**2 + 2
        b = m * (a - 1)
        return stats.invgamma.logpdf(x, a, scale=b)
    raise ValueError(kind)


class TfpBayesModel(TfpModel):
    """TFP-Modell mit AR(2)-Zyklus in Polarform (Amplitude, Periode) wie in GAP."""

    def __init__(self, df: pd.DataFrame, priors: dict = TFP_PRIORS_DE):
        super().__init__(df)
        self.priors = priors
        self.params_spec = [Param(k, v[3], v[4], v[1]) for k, v in priors.items()]

    def update(self, params, **kwargs):
        params = MLEModel.update(self, params, **kwargs)
        p = dict(zip(self.param_names, params))
        self._apply({**p, "phi1": 2 * p["amplitude"] * np.cos(2 * np.pi / p["period"]), "phi2": -p["amplitude"] ** 2})

    @property
    def param_names(self):
        return list(self.priors)

    def logprior(self, params) -> float:
        return float(sum(_logprior(v[0], x, *v[1:]) for x, v in zip(params, self.priors.values())))


def estimate_tfp_bayes(gap: pd.DataFrame, n_forecast: int = 3, priors: dict = TFP_PRIORS_DE, n_starts: int = 4) -> FilterResult:
    """TFP-Trend per Posterior-Modus mit den EU-Prioren (GAP nutzt den Posterior-Mittelwert per MCMC)."""
    df = gap.rename(columns={"DE_TFP08": "sr", "DE_CUBS08": "CUBS"})[["sr", "CUBS"]]
    df = df.loc[df["sr"].first_valid_index() : df["sr"].last_valid_index()]
    m = TfpBayesModel(df, priors)
    rng = np.random.default_rng(1)

    def neglp(x):
        c = m.transform_params(x)
        lp = m.logprior(c)
        if not np.isfinite(lp):
            return 1e10
        try:
            ll = m.loglike(c, transformed=True)
        except Exception:
            return 1e10
        return -(ll + lp) if np.isfinite(ll) else 1e10

    x0 = m.untransform_params(m.start_params)
    best = None
    for s in [x0] + [x0 + rng.normal(0, 0.7, len(x0)) for _ in range(n_starts - 1)]:
        r = minimize(neglp, s, method="L-BFGS-B", options={"maxiter": 3000})
        r = minimize(neglp, r.x, method="Nelder-Mead", options={"maxiter": 6000, "xatol": 1e-8, "fatol": 1e-10})
        if best is None or r.fun < best.fun:
            best = r
    params = m.transform_params(best.x)
    res = m.smooth(params, transformed=True)
    p = dict(zip(m.param_names, params))
    st = res.smoothed_state
    trend = pd.Series(st[0], index=df.index, name="tfp")
    P, mu, fc = st[0, -1], st[1, -1], {}
    for h in range(1, n_forecast + 1):
        P = P + mu
        mu = (1 - p["omega"]) * p["slope_mean"] + p["omega"] * mu
        fc[df.index[-1] + h] = P
    trend = pd.concat([trend, pd.Series(fc)])
    return FilterResult(trend=trend, cycle=pd.Series(st[2], index=df.index), params=p, loglike=-best.fun)


# ---------------------------------------------------------------- Bayes (Posterior-Mittelwert per MCMC) für TFP
def _trend_path(model: "TfpBayesModel", params: np.ndarray, n_forecast: int) -> np.ndarray:
    """Geglätteter TFP-Trend plus Fortschreibung über ``n_forecast`` Jahre für einen Parametersatz."""
    res = model.smooth(params, transformed=True)
    st = res.smoothed_state
    p = dict(zip(model.param_names, params))
    P, mu, fc = st[0, -1], st[1, -1], []
    for _ in range(n_forecast):
        P = P + mu
        mu = (1 - p["omega"]) * p["slope_mean"] + p["omega"] * mu
        fc.append(P)
    return np.concatenate([st[0], fc])


def estimate_tfp_mcmc(gap: pd.DataFrame, n_forecast: int = 3, priors: dict = TFP_PRIORS_DE,
                      draws: int = 20000, burn: int = 10000, thin: int = 5, seed: int = 0) -> FilterResult:
    """TFP-Trend als Posterior-Mittelwert wie in GAP (dort 20.000 Ziehungen, 10.000 Burn-in).

    Adaptiver Random-Walk-Metropolis im unbeschränkten Raum (Logit-Transformation samt
    Jacobi-Term), Start im Posterior-Modus. Trend und Fortschreibung werden über die
    behaltenen Ziehungen gemittelt.
    """
    df = gap.rename(columns={"DE_TFP08": "sr", "DE_CUBS08": "CUBS"})[["sr", "CUBS"]]
    df = df.loc[df["sr"].first_valid_index() : df["sr"].last_valid_index()]
    m = TfpBayesModel(df, priors)
    spec = m.params_spec
    rng = np.random.default_rng(seed)

    def logpost(x):
        c = m.transform_params(x)
        lp = m.logprior(c)
        if not np.isfinite(lp):
            return -np.inf
        try:
            ll = m.loglike(c, transformed=True)
        except Exception:
            return -np.inf
        if not np.isfinite(ll):
            return -np.inf
        sig = 1 / (1 + np.exp(-x))
        jac = sum(np.log(p.ub - p.lb) + np.log(s) + np.log1p(-s) for p, s in zip(spec, sig))
        return ll + lp + jac

    mode = estimate_tfp_bayes(gap, n_forecast=n_forecast, priors=priors, n_starts=2)
    x = m.untransform_params(np.array([mode.params[k] for k in m.param_names]))
    lp = logpost(x)
    k = len(x)
    cov = np.eye(k) * 0.05
    hist, kept_p, kept_t = [], [], []
    accepted = 0
    for i in range(draws):
        if i >= 1000 and i % 500 == 0:  # Vorschlagsverteilung an bisherige Ziehungen anpassen
            cov = np.cov(np.array(hist[-5000:]).T) * (2.38**2 / k) + 1e-8 * np.eye(k)
        prop = rng.multivariate_normal(x, cov)
        lpp = logpost(prop)
        if np.log(rng.uniform()) < lpp - lp:
            x, lp = prop, lpp
            accepted += 1
        hist.append(x)
        if i >= burn and (i - burn) % thin == 0:
            c = m.transform_params(x)
            kept_p.append(c)
            kept_t.append(_trend_path(m, c, n_forecast))
    P = np.array(kept_p)
    T = np.array(kept_t)
    idx = list(df.index) + [df.index[-1] + h for h in range(1, n_forecast + 1)]
    trend = pd.Series(T.mean(axis=0), index=idx, name="tfp")
    params = dict(zip(m.param_names, P.mean(axis=0)))
    extra = {
        "acceptance": accepted / draws,
        "kept": len(P),
        "params_p05": dict(zip(m.param_names, np.percentile(P, 5, axis=0))),
        "params_p95": dict(zip(m.param_names, np.percentile(P, 95, axis=0))),
        "trend_growth_p05": pd.Series(np.percentile(np.diff(T, axis=1), 5, axis=0), index=idx[1:]),
        "trend_growth_p95": pd.Series(np.percentile(np.diff(T, axis=1), 95, axis=0), index=idx[1:]),
        "mode": mode.params,
    }
    return FilterResult(trend=trend, cycle=pd.Series(dtype=float), params=params, loglike=float(lp), extra=extra)
