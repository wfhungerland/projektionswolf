"""Verwendungskomponenten und Arbeitsmarkt aus den Prognosetabellen von GD, Bundesbank und Instituten.

Die Texte legt ``tools/tabellen_laden.py`` unter ``data/raw/tabellen`` ab. Gelesen werden nur
Jahrestabellen: ein Kopf mit aufeinanderfolgenden Jahren, darunter Zeilen mit Beschriftung und
genau so vielen Zahlen. Ein Tabellenblock gilt nur dann als belastbar, wenn seine BIP-Zeile mit
dem an der Quelle geprüften BIP-Wert derselben Runde (``data/manuell/prognosen.csv``) übereinstimmt.
Werte aus anderen Blöcken werden nicht übernommen. Beitragstabellen (Prozentpunkte) und
nominale Abschnitte werden übersprungen.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw/tabellen")
OUT = Path("data/manuell/komponenten.csv")
PROGNOSEN = Path("data/manuell/prognosen.csv")

NUM = r"[-−–\xad]?\s?\d{1,2},\d"
SYN = {
    "BIP real": r"(?:reales |Reales )?(Bruttoinlandsprodukt|BIP)(?:\s*\(?(?:preisbereinigt|real)\)?)?(?!\s*(?:nominal|je|in jew|\(nominal))",
    "Privater Konsum": r"(Private Konsumausgaben|Konsumausgaben (der )?private[rn]?( Haushalte)?|Privater Konsum|Private Haushalte( und priv\.? Organisationen ohne Erwerbszweck)?)",
    "Staatskonsum": r"(Konsumausgaben des Staates|Staatliche Konsumausgaben|Öffentlicher Konsum|Staatskonsum(?! und)|Staat(?![a-zäöü]))",
    "Ausrüstungsinvestitionen": r"(Ausrüstungsinvestitionen|Ausrüstungen|Ausrüstungsgüter)",
    "Bauinvestitionen": r"(Bauinvestitionen|Bauten)",
    "Exporte": r"(Exporte|Ausfuhren?)",
    "Importe": r"(Importe|Einfuhren?)",
    "Erwerbstätige": r"(Erwerbstätige( \(?(im )?Inland\)?)?|Erwerbstätige Inland)",
    "Arbeitslosenquote BA (%)": r"(Arbeitslosenquote( BA)?( \(?in %\)?)?( \(?Abgrenzung der BA\)?)?)",
    "Verbraucherpreise": r"(Verbraucherpreise|Verbraucherpreisindex|Konsumentenpreise|Harmonisierter Verbraucherpreisindex|HVPI)",
}
SYN_RE = {k: re.compile(r"^" + v + r"\s*[a-z0-9]?\)?$", re.I) for k, v in SYN.items()}
SKIP_BLOCK = re.compile(r"(Prozentpunkt|Wachstumsbeitr|Beiträge|Beitrag zur|Quartal|Vorquartal|saisonbereinigt)", re.I)
NOMINAL = re.compile(r"(jeweiligen Preisen|nominal|Deflator|Preisentwicklung)", re.I)
REAL = re.compile(r"(preisbereinigt|real|Vorjahrespreis|Kettenindex)", re.I)


def _num(s: str) -> float:
    return float(s.replace("\xad", "-").replace("−", "-").replace("–", "-").replace(" ", "").replace(",", "."))


def _label(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"(\D)\d\)?$", r"\1", s)  # Fußnote am Ende
    return s.strip(" :.")


SYN_ANY = {k: re.compile(r"(?<![A-Za-zäöüß])" + v + r"\s*(?:\d(?:,\d)*\)?|[a-z]\)?)?\s*(?:\((?:in %|%)\))?\s+((?:" + NUM + r"\s+)*" + NUM + r")", re.I)
           for k, v in SYN.items()}


def _years(line: str) -> list[int]:
    """Erste Folge aufeinanderfolgender Jahre in einer Zeile (2 bis 7 Jahre)."""
    yrs = [int(y) for y in re.findall(r"(?<!\d)(20[12]\d)[p*]?(?!\d)", line)]
    run = []
    for y in yrs:
        if run and y != run[-1] + 1:
            break
        run.append(y)
    return run if 2 <= len(run) <= 7 else []


def blocks(text: str) -> list[dict]:
    """Kandidaten-Blöcke: Jahresspalten im Kopf und erkannte Zeilen (auch mitten im Fließtext)."""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        yrs = _years(line)
        if not yrs:
            continue
        head = " ".join(lines[max(0, i - 4): i + 2])
        if SKIP_BLOCK.search(head):
            continue
        n = len(yrs)
        rows, section = {}, "real"
        for line2 in lines[i + 1: i + 60]:
            if _years(line2) and len(_years(line2)) >= 3 and not re.search(NUM, line2):
                break
            if re.search(r"in Prozentpunkten|Wachstumsbeitr", line2):
                break
            if re.search(r"(jeweiligen Preisen|\bnominal\b|Deflator)", line2) and not re.search(NUM, line2):
                section = "nominal"
            elif re.search(r"(preisbereinigt|Vorjahrespreisbasis|Kettenindex)", line2) and not re.search(NUM, line2):
                section = "real"
            for var, rx in SYN_ANY.items():
                if var in rows:
                    continue
                m = rx.search(line2)
                if not m:
                    continue
                vals = [_num(v) for v in re.findall(NUM, m.group(m.lastindex))]
                if len(vals) < n:
                    continue
                if var in ("Privater Konsum", "Staatskonsum", "Ausrüstungsinvestitionen", "Bauinvestitionen",
                           "Exporte", "Importe", "BIP real") and section == "nominal":
                    continue
                rows[var] = dict(zip(yrs, vals[:n]))
        if len(rows) >= 2:
            out.append({"zeile": i, "jahre": yrs, "rows": rows})
    return out


def _season_key(runde: str) -> str:
    m = re.search(r"(Frühjahr|Fruehjahr|Sommer|Frühsommer|Herbst|Winter|Juni|Dezember)\D*(20\d\d)", str(runde))
    return f"{m.group(1).replace('Fruehjahr', 'Frühjahr')} {m.group(2)}" if m else str(runde)


def build(raw: Path = RAW, out: Path = OUT) -> pd.DataFrame:
    prog = pd.read_csv(PROGNOSEN)
    prog["key"] = prog["runde"].map(_season_key)
    bip = prog.set_index(["institution", "key", "zieljahr"])["bip"].dropna()
    meta = prog.drop_duplicates(["institution", "key"]).set_index(["institution", "key"])["veroeffentlicht"]
    log = pd.read_csv(raw / "log.csv")
    urlmap = dict(zip(log["datei"], log["url"]))
    rows = []
    for f in sorted(raw.glob("*.txt")):
        inst, rest = f.stem.split("_", 1)
        key = _season_key(rest.rsplit("_", 1)[0].replace("-", " "))
        for b in blocks(f.read_text(encoding="utf-8", errors="replace")):
            br = b["rows"].get("BIP real")
            if not br:
                continue
            checks = [(y, v) for y, v in br.items() if (inst, key, y) in bip.index]
            if not checks or any(abs(bip[(inst, key, y)] - v) > 0.051 for y, v in checks):
                continue
            for var, vals in b["rows"].items():
                for y, v in vals.items():
                    rows.append({"institution": inst, "runde": key, "veroeffentlicht": meta.get((inst, key)),
                                 "variable": var, "jahr": y, "wert": v, "quelle": urlmap.get(f.stem, ""),
                                 "block": f"{f.stem}:{b['zeile']}", "bip_abgeglichen": len(checks)})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # je Runde, Variable, Jahr: Wert aus dem Block mit den meisten erkannten Größen
    size = df.groupby("block")["variable"].nunique()
    df["blockgroesse"] = df["block"].map(size)
    df = df.sort_values("blockgroesse", ascending=False).drop_duplicates(["institution", "runde", "variable", "jahr"])
    df = df.sort_values(["institution", "veroeffentlicht", "variable", "jahr"]).drop(columns="blockgroesse")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df


def coverage(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(["institution", "variable"])["runde"].nunique().unstack(fill_value=0)
