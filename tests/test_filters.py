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


def test_tfp_trend_growth_close_to_bmwe_in_history():
    code = bmwe.list_vintages()[-1]
    v = bmwe.load_vintage(code)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = filters.estimate_tfp_bayes(v["gap_tfp"], n_starts=1)
    diff = filters.compare(100 * t.trend.diff(), 100 * v["input"]["tfp"].diff()).loc[2005:2024]["differenz"]
    assert diff.abs().max() < 0.2
