import numpy as np
import pandas as pd

from projektionswolf import data, nowcast


def test_parse_ameco_txt():
    txt = "CODE;COUNTRY;SUB-CHAPTER;TITLE;UNIT;2020;2021;\nDEU.1.1.0.0.OVGD;Germany;x;GDP;Mrd;3450.7;NA;\nFRA.1.1.0.0.OVGD;France;x;GDP;Mrd;1;2;\n"
    df = data.parse_ameco_txt(txt)
    assert list(df["var"]) == ["OVGD"]
    assert df["value"].iloc[0] == 3450.7


def test_parse_jsonstat():
    payload = {"id": ["geo", "time"], "size": [1, 3],
               "dimension": {"time": {"category": {"index": {"2024-Q1": 0, "2024-Q2": 1, "2024-Q3": 2}}}},
               "value": {"0": 0.2, "2": 0.1}}
    s = data.parse_jsonstat(payload)
    assert s.to_dict() == {"2024-Q1": 0.2, "2024-Q3": 0.1}
    assert data.eurostat_period("2024-Q3") == pd.Timestamp(2024, 7, 1)


def test_annual_growth_and_carry_over():
    idx = pd.period_range("2024Q1", "2025Q4", freq="Q")
    q = pd.Series([0, 0, 0, 1.0, 0, 0, 0, 0], index=idx)
    a = nowcast.annual_growth(q)
    # Niveau 2024: 1,1,1,1.01; 2025: 1.01 durchgehend
    assert np.isclose(a[2025], 100 * (1.01 / 1.0025 - 1))
    assert np.isclose(nowcast.carry_over(q, 2025), a[2025])


def test_site_clean_handles_missing():
    from projektionswolf import site

    assert site._clean(pd.NaT) is None
    assert site._clean(float("nan")) is None
    assert site._clean(pd.Timestamp("2026-10-08")) == "2026-10-08"
    assert site._clean({"a": np.float64(1.23456)}) == {"a": 1.2346}


def test_prognosen_table_is_clean():
    from projektionswolf import prognosen

    d = pd.read_csv(prognosen.PROGNOSEN)
    assert list(d.columns) == prognosen.COLUMNS
    for c in ["zieljahr", "bip", "bip_kalenderbereinigt", "inflation", "potenzialwachstum", "produktionsluecke"]:
        bad = d[c].notna() & pd.to_numeric(d[c], errors="coerce").isna()
        assert not bad.any(), f"Nicht-Zahl in {c}: Zeilen {list(d.index[bad])}"
    assert pd.to_datetime(d["veroeffentlicht"], format="mixed", errors="coerce").notna().all()
    assert d["quelle"].str.startswith("http").all()
