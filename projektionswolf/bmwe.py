"""Rechengrundlagen des BMWE je Projektionsrunde einlesen.

Je Runde veröffentlichen BMWE und BMF ein ZIP mit
- ``Input_EViews_<K>.xls``: Eingangsdaten der Produktionsfunktion,
- ``Output_EViews_<K>.xlsx``: Ergebnisse (Potenzial, Lücke usw.),
- ``eviews_potenzial_<K>.prg``: EViews-Programm,
- ``GAP50*_NAWRU_<K>.xls`` und ``GAP50_DE_TFP_<K>.xls``: Daten und Spezifikation
  der Kalman-Filter für NAWRU und TFP-Trend (EU-Programm GAP).

Diese Funktionen machen daraus schlanke CSV-Dateien unter ``data/bmwe/<runde>``.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pandas as pd

BMWE_DIR = Path("data/bmwe")

# Kürzel der Runde -> lesbarer Name
LABELS = {
    "JP": "Jahresprojektion",
    "FP": "Frühjahrsprojektion",
    "HP": "Herbstprojektion",
}


def vintage_code(folder: Path) -> str | None:
    """Kürzel wie ``FP26`` aus den Dateinamen eines Runden-Ordners."""
    for f in folder.iterdir():
        m = re.search(r"Input_EViews_([A-Z]{2}\d{2})", f.name)
        if m:
            return m.group(1)
    return None


def vintage_label(code: str) -> str:
    return f"{LABELS.get(code[:2], code[:2])} 20{code[2:]}"


def vintage_sort_key(code: str) -> tuple[int, int]:
    order = {"JP": 0, "FP": 1, "HP": 2}
    return int(code[2:]), order.get(code[:2], 9)


def read_input(path: Path) -> pd.DataFrame:
    """Input_EViews: Zeile 1 Beschreibung, Zeile 2 EViews-Namen, ab Zeile 3 Daten."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = pd.read_excel(path, header=None)
    names = [str(x).strip() for x in raw.iloc[1]]
    desc = [str(x).strip() for x in raw.iloc[0]]
    df = raw.iloc[2:].copy()
    df.columns = names
    df = df.rename(columns={names[0]: "year"})
    df = df[pd.to_numeric(df["year"], errors="coerce").notna()]
    df["year"] = df["year"].astype(int)
    keep = [c for c in df.columns if c != "nan" and c == c]
    df = df[keep].set_index("year").apply(pd.to_numeric, errors="coerce")
    df = df.dropna(axis=1, how="all")
    df.attrs["descriptions"] = {n: d for n, d in zip(names, desc) if n in df.columns}
    return df


def read_output(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, engine="calamine")
    df = df.rename(columns={df.columns[0]: "year"})
    df["year"] = pd.to_datetime(df["year"]).dt.year
    return df.set_index("year").apply(pd.to_numeric, errors="coerce")


def read_gap_data(path: Path) -> pd.DataFrame:
    """Blatt ``Data`` eines GAP-Tools: Zeile 3 Namen, ab Zeile 4 Jahreswerte (Spalte B)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = pd.read_excel(path, sheet_name="Data", header=None)
    names = raw.iloc[2]
    body = raw.iloc[3:]
    years = pd.to_numeric(body.iloc[:, 1], errors="coerce")
    cols = {}
    for j in range(2, raw.shape[1]):
        n = names.iloc[j]
        if isinstance(n, str) and n.strip():
            cols[n.strip()] = pd.to_numeric(body.iloc[:, j], errors="coerce").values
    df = pd.DataFrame(cols, index=years.values)
    df = df[df.index.notna()]
    df.index = df.index.astype(int)
    df.index.name = "year"
    return df.dropna(how="all")


def extract_vintage(src: Path, dst_root: Path = BMWE_DIR) -> str | None:
    """Wandelt einen entpackten Runden-Ordner in CSV-Dateien um. Gibt das Kürzel zurück."""
    code = vintage_code(src)
    if code is None:
        return None
    dst = dst_root / code
    dst.mkdir(parents=True, exist_ok=True)
    files = {f.name: f for f in src.iterdir()}

    def find(pattern: str) -> Path | None:
        for n, f in files.items():
            if re.search(pattern, n, flags=re.I) and not n.startswith("._"):
                return f
        return None

    inp = read_input(find(r"^Input_EViews"))
    inp.to_csv(dst / "input.csv")
    pd.Series(inp.attrs["descriptions"], name="beschreibung").rename_axis("variable").to_csv(dst / "input_beschreibung.csv")
    if (out := find(r"^Output_EViews")) is not None:
        read_output(out).to_csv(dst / "output.csv")
    if (nawru := find(r"^GAP50.*tkp.*\.xls$")) is not None:
        read_gap_data(nawru).to_csv(dst / "gap_nawru.csv")
    if (tfp := find(r"^GAP50.*TFP.*\.xls$")) is not None:
        read_gap_data(tfp).to_csv(dst / "gap_tfp.csv")
    if (mat := find(r"^priors.*\.mat$")) is not None:
        (dst / "priors.mat").write_bytes(mat.read_bytes())
    if (prg := find(r"\.prg$")) is not None:
        (dst / "potenzial.prg").write_bytes(prg.read_bytes())
    return code


def list_vintages(root: Path = BMWE_DIR) -> list[str]:
    codes = [p.name for p in root.iterdir() if p.is_dir() and (p / "input.csv").exists()] if root.exists() else []
    return sorted(codes, key=vintage_sort_key)


def load_vintage(code: str, root: Path = BMWE_DIR) -> dict[str, pd.DataFrame]:
    d = root / code
    out = {"input": pd.read_csv(d / "input.csv", index_col="year")}
    for name in ("output", "gap_nawru", "gap_tfp"):
        if (d / f"{name}.csv").exists():
            out[name] = pd.read_csv(d / f"{name}.csv", index_col="year")
    return out


def read_horizon(code: str, root: Path = BMWE_DIR) -> dict[str, int]:
    """Liest Kurzfrist- und Mittelfristende aus dem EViews-Programm der Runde."""
    txt = (root / code / "potenzial.prg").read_text(encoding="latin-1")
    endy_st = int(re.search(r"!endy_st\s*=\s*(\d{4})", txt).group(1))
    endy_mt = int(re.search(r"!endy_mt\s*=\s*(\d{4})", txt).group(1))
    endy = int(re.search(r"!endy\s*=\s*(\d{4})", txt).group(1))
    # Ab Herbst 2023 gibt es die Aufteilung nach Geflüchteten; ältere Programme haben sie nicht
    refugees = "popw_fl" in txt
    return {"endy_st": endy_st, "endy_mt": endy_mt, "endy": endy, "refugees": refugees}
