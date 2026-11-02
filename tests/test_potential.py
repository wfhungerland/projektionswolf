import numpy as np
import pandas as pd
import pytest

from projektionswolf import bmwe, pipeline, potential


def new_spec_vintages():
    return [c for c in bmwe.list_vintages() if pipeline.is_new_spec(c)]


@pytest.mark.parametrize("code", new_spec_vintages())
def test_replicates_bmwe_output(code):
    v = bmwe.load_vintage(code)
    hz = potential.Horizon.from_dict(bmwe.read_horizon(code))
    r = potential.estimate(v["input"], hz)
    o = v["output"]
    assert (r["ygap"] - o["ygap"]).abs().max() < 1e-5
    assert ((r["ypot"] - o["ypot"]).abs() / o["ypot"]).max() < 1e-8
    assert (r["parts"] - o["parts"]).abs().max() < 1e-8


def test_growth_contributions_add_up():
    code = new_spec_vintages()[-1]
    v = bmwe.load_vintage(code)
    r = potential.estimate(v["input"], potential.Horizon.from_dict(bmwe.read_horizon(code)))
    g = potential.growth_table(r, list(range(2015, 2027)))
    log_growth = 100 * np.log(r["ypot"]).diff().reindex(g.index)
    total = g["Beitrag Arbeit"] + g["Beitrag Kapital"] + g["Beitrag TFP"]
    assert np.allclose(total, log_growth, atol=1e-10)


def test_ar_forecast_keeps_actuals():
    y = pd.Series(np.arange(10, dtype=float), index=range(2000, 2010))
    out = potential.ar_forecast(y, np.array([1.0, 1.0]), 2008, 2009, lags=1, const=True)
    assert out[2007] == 7 and out[2008] == 8 and out[2009] == 9
