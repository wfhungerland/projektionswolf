"""Datenabruf: AMECO (EU-Kommission), Eurostat und die Rechengrundlagen des BMWE.

Alle Rohdaten landen als CSV unter ``data/raw``. Die Schätzung liest nur diese
Dateien, damit ein Lauf ohne Netz reproduzierbar bleibt.
"""

from __future__ import annotations

import io
import json
import logging
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

RAW = Path("data/raw")
AMECO_URL = "https://ec.europa.eu/economy_finance/db_indicators/ameco/documents/ameco0.zip"
EUROSTAT_API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
BMWE_PREFIX = (
    "https://www.bundeswirtschaftsministerium.de/Redaktion/DE/Downloads/G/"
    "ergaenzende-unterlagen-zu-den-berechnungsgrundlagen-fuer-die-bestimmung-"
    "des-gesamtwirtschaftlichen-produktionspotenzials-"
)

# Eingangsgrößen der Produktionsfunktion aus AMECO (Deutschland)
AMECO_VARS = {
    "OVGD": "BIP real (Mrd. Euro, Preise 2020)",
    "OVGDP": "Produktionspotenzial EU-Kommission (Mrd. Euro, Preise 2020)",
    "AVGDGP": "Produktionslücke EU-Kommission (% des Potenzials)",
    "OKND": "Nettokapitalstock real (Mrd. Euro)",
    "OIGT": "Bruttoanlageinvestitionen real (Mrd. Euro)",
    "NPAN1": "Bevölkerung 15-74 Jahre (1000)",
    "NETD": "Erwerbstätige Inland (1000)",
    "NUTN": "Erwerbslose (1000)",
    "ZUTN": "Erwerbslosenquote (%)",
    "ZNAWRU": "NAWRU EU-Kommission (%)",
    "NLHA": "Arbeitsstunden je Erwerbstätigen",
    "NLHT": "Arbeitsvolumen (Mio. Stunden)",
    "ZVGDF": "TFP EU-Kommission (2020=100)",
    "HWCDW": "Arbeitnehmerentgelt je Arbeitnehmer (1000 Euro)",
    "PVGD": "BIP-Deflator (2020=100)",
}

# Monatsindikatoren für den Nowcast (Eurostat JSON-stat)
EUROSTAT_SERIES = {
    "gdp_qoq": ("namq_10_gdp", {"geo": "DE", "unit": "CLV_PCH_PRE", "s_adj": "SCA", "na_item": "B1GQ"}),
    "ip": ("sts_inpr_m", {"geo": "DE", "unit": "I21", "s_adj": "SCA", "nace_r2": "B-D", "indic_bt": "PRD"}),
    "ip_manuf": ("sts_inpr_m", {"geo": "DE", "unit": "I21", "s_adj": "SCA", "nace_r2": "C", "indic_bt": "PRD"}),
    "construction": ("sts_copr_m", {"geo": "DE", "unit": "I21", "s_adj": "SCA", "nace_r2": "F", "indic_bt": "PRD"}),
    "retail": ("sts_trtu_m", {"geo": "DE", "unit": "I21", "s_adj": "SCA", "nace_r2": "G47", "indic_bt": "VOL_SLS"}),
    "esi": ("ei_bssi_m_r2", {"geo": "DE", "s_adj": "SA", "indic": "BS-ESI-I"}),
    "conf_industry": ("ei_bssi_m_r2", {"geo": "DE", "s_adj": "SA", "indic": "BS-ICI-BAL"}),
    "conf_services": ("ei_bssi_m_r2", {"geo": "DE", "s_adj": "SA", "indic": "BS-SCI-BAL"}),
    "conf_consumer": ("ei_bssi_m_r2", {"geo": "DE", "s_adj": "SA", "indic": "BS-CSMCI-BAL"}),
    "conf_retail": ("ei_bssi_m_r2", {"geo": "DE", "s_adj": "SA", "indic": "BS-RCI-BAL"}),
    "conf_construction": ("ei_bssi_m_r2", {"geo": "DE", "s_adj": "SA", "indic": "BS-CCI-BAL"}),
    "unemp": ("une_rt_m", {"geo": "DE", "s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"}),
}

# Rechengrundlagen je Projektionsrunde (Namensschema der BMWE-Downloads)
BMWE_VINTAGES = [
    "fruehjahr-2023", "herbst-2023", "2024", "fruehjahr-2024", "herbst-2024",
    "2025", "fruehjahr-2025", "herbst-2025", "2026", "fruehjahr-2026", "herbst-2026",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (projektionswolf; +https://github.com/wfhungerland/projektionswolf)"
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- AMECO
def parse_ameco_txt(text: str, country: str = "DEU") -> pd.DataFrame:
    """Liest eine AMECO-Textdatei (Semikolon, Jahre als Spalten) ins Long-Format."""
    lines = text.splitlines()
    header = lines[0].rstrip(";").split(";")
    years = header[5:]
    rows = []
    for line in lines[1:]:
        if not line.startswith(country + "."):
            continue
        parts = line.rstrip(";").split(";")
        code = parts[0]
        var = code.rsplit(".", 1)[-1]
        for y, v in zip(years, parts[5:]):
            v = v.strip()
            if v in ("", "NA"):
                continue
            try:
                val = float(v)
            except ValueError:
                continue
            rows.append((code, var, parts[3].strip(), parts[4].strip(), int(y), val))
    return pd.DataFrame(rows, columns=["code", "var", "title", "unit", "year", "value"])


def fetch_ameco(session: requests.Session, out: Path = RAW) -> Path:
    r = session.get(AMECO_URL, timeout=180)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    frames = [parse_ameco_txt(z.read(i).decode("latin-1")) for i in z.infolist() if i.filename.upper().endswith(".TXT")]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["var"].isin(AMECO_VARS)]
    path = out / "ameco_deu.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("AMECO: %d Werte", len(df))
    return path


def load_ameco(raw: Path = RAW) -> pd.DataFrame:
    """Jahresreihen als Wide-Frame (Index Jahr, Spalten AMECO-Kürzel).

    Je Variable wird die Einheit in nationaler Währung bzw. die erste Fassung genommen.
    """
    df = pd.read_csv(raw / "ameco_deu.csv")
    # bei Mehrfachcodes (z. B. EUR vs. PPS) gewinnt der Code mit ".0.0." (nationale Währung)
    df["prio"] = (~df["code"].str.contains(r"\.0\.0\.")).astype(int)
    df = df.sort_values(["var", "prio", "code"])
    first = df.groupby("var")["code"].first()
    df = df[df["code"].isin(first.values)]
    wide = df.pivot_table(index="year", columns="var", values="value")
    return wide.sort_index()


# ---------------------------------------------------------------- Eurostat
def parse_jsonstat(payload: dict) -> pd.Series:
    """JSON-stat 2.0 mit genau einer nicht-trivialen Dimension (Zeit) zu Series."""
    dims = payload["id"]
    sizes = payload["size"]
    if any(s > 1 for d, s in zip(dims, sizes) if d != "time"):
        raise ValueError(f"Mehr als eine Ausprägung je Dimension: {dict(zip(dims, sizes))}")
    tidx = payload["dimension"]["time"]["category"]["index"]
    pos2time = {v: k for k, v in tidx.items()}
    vals = {pos2time[int(k)]: v for k, v in payload["value"].items() if v is not None}
    s = pd.Series(vals, dtype=float)
    return s.reindex(sorted(s.index))


def eurostat_period(p: str) -> pd.Timestamp:
    if "-Q" in p:
        y, q = p.split("-Q")
        return pd.Timestamp(int(y), 3 * int(q) - 2, 1)
    if "-" in p:
        y, m = p.split("-")[:2]
        return pd.Timestamp(int(y), int(m), 1)
    return pd.Timestamp(int(p), 1, 1)


def fetch_eurostat(session: requests.Session, out: Path = RAW) -> Path:
    rows, status = [], {}
    for sid, (ds, params) in EUROSTAT_SERIES.items():
        try:
            r = session.get(EUROSTAT_API + ds, params={**params, "format": "JSON", "lang": "en"}, timeout=120)
            r.raise_for_status()
            s = parse_jsonstat(r.json())
            for p, v in s.items():
                rows.append((sid, eurostat_period(p).date().isoformat(), v))
            status[sid] = {"ok": True, "n": len(s), "last": s.index[-1] if len(s) else None}
        except Exception as e:  # eine kaputte Reihe bricht den Lauf nicht ab
            status[sid] = {"ok": False, "error": repr(e)[:300]}
            log.warning("Eurostat %s: %s", sid, e)
        time.sleep(0.3)
    path = out / "eurostat_de.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(rows, columns=["series_id", "date", "value"])
    if path.exists():  # fehlgeschlagene Reihen aus dem letzten Lauf behalten
        old = pd.read_csv(path)
        keep = old[~old["series_id"].isin(new["series_id"].unique())]
        new = pd.concat([keep, new], ignore_index=True)
    new.sort_values(["series_id", "date"]).to_csv(path, index=False)
    (out / "eurostat_status.json").write_text(json.dumps({"retrieved_at": _stamp(), "series": status}, indent=1))
    return path


def load_eurostat(raw: Path = RAW) -> pd.DataFrame:
    df = pd.read_csv(raw / "eurostat_de.csv", parse_dates=["date"])
    return df.pivot_table(index="date", columns="series_id", values="value").sort_index()


# ---------------------------------------------------------------- BMWE
def fetch_bmwe(session: requests.Session, out: Path = RAW / "bmwe") -> dict:
    """Lädt die Rechengrundlagen zum Produktionspotenzial je Projektionsrunde."""
    found = {}
    for v in BMWE_VINTAGES:
        target = out / v
        if target.exists() and any(target.iterdir()):
            found[v] = "vorhanden"
            continue
        url = BMWE_PREFIX + v + ".zip?__blob=publicationFile&v=1"
        try:
            r = session.get(url, timeout=120)
            if not (r.ok and r.content[:2] == b"PK"):
                found[v] = f"kein ZIP ({r.status_code})"
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            target.mkdir(parents=True, exist_ok=True)
            for i in z.infolist():
                if not i.is_dir() and i.file_size < 8_000_000:
                    (target / Path(i.filename).name).write_bytes(z.read(i))
            found[v] = f"{len(z.infolist())} Dateien"
        except Exception as e:
            found[v] = repr(e)[:200]
        time.sleep(0.5)
    out.mkdir(parents=True, exist_ok=True)
    (out / "status.json").write_text(json.dumps({"retrieved_at": _stamp(), "vintages": found}, indent=1, ensure_ascii=False))
    return found


def fetch_all(out: Path = RAW) -> None:
    s = _session()
    for name, fn in (("AMECO", fetch_ameco), ("Eurostat", fetch_eurostat), ("BMWE", fetch_bmwe)):
        try:
            fn(s) if name != "BMWE" else fn(s, out / "bmwe")
        except Exception as e:
            log.error("%s fehlgeschlagen: %s", name, e)
