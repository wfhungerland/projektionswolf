import warnings

from projektionswolf import bmwe, filters


def test_nawru_close_to_bmwe():
    code = bmwe.list_vintages()[-1]
    v = bmwe.load_vintage(code)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        n = filters.estimate_nawru(v["gap_nawru"], n_starts=2)
    diff = filters.compare(n.trend, v["input"]["nairu"]).loc[2005:]["differenz"]
    assert diff.abs().max() < 0.3


def test_tfp_trend_growth_close_to_bmwe():
    """Posterior-Mittelwert (kurze Kette) trifft das GAP-Ergebnis inkl. Mittelfrist auf 0,1 Pp."""
    code = bmwe.list_vintages()[-1]
    v = bmwe.load_vintage(code)
    hz = bmwe.read_horizon(code)
    nf = hz["endy_mt"] - int(v["gap_tfp"]["DE_TFP08"].last_valid_index())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = filters.estimate_tfp_mcmc(v["gap_tfp"], n_forecast=nf, draws=4000, burn=2000)
    diff = filters.compare(100 * t.trend.diff(), 100 * v["input"]["tfp"].diff()).loc[2005:]["differenz"]
    assert diff.index.max() == hz["endy_mt"]
    assert diff.abs().max() < 0.1


def test_tfp_priors_file_matches_constants():
    import numpy as np

    pr = filters.load_tfp_priors(bmwe.BMWE_DIR / bmwe.list_vintages()[-1] / "priors.mat")
    for k, v in filters.TFP_PRIORS_DE.items():
        assert pr[k][0] == v[0]
        assert np.allclose(pr[k][1:], v[1:], rtol=1e-5)
