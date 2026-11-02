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


# ---------------------------------------------------------------- Standard-Anhang "Die wichtigsten Daten der VGR"
VGR_LABELS = {
    "Privater Konsum": r"([Pp]rivate Haushalte|[Pp]rivate Konsumausgaben|Konsumausgaben der privaten Haushalte)",
    "Staatskonsum": r"(Staat(?![a-zäöü])|Konsumausgaben des Staates)",
    "Ausrüstungsinvestitionen": r"(Ausrüstungen|Ausrüstungsinvestitionen)",
    "Bauinvestitionen": r"(Bauten|Bauinvestitionen)",
    "Exporte": r"(Exporte|Ausfuhr)",
    "Importe": r"(Importe|Einfuhr)",
    "BIP real": r"(Bruttoinlandsprodukt)",
}


def _row(line: str, label_rx: str, n: int) -> list[float] | None:
    m = re.search(r"(?<![A-Za-zäöüß])" + label_rx + r"\s*(?:\d\s?\)?)?\s+((?:" + NUM + r"\s+){" + str(n - 1) + ",}" + NUM + r")(?![\d,])", line)
    if not m:
        return None
    return [_num(v) for v in re.findall(NUM, m.group(m.lastindex))]


def vgr_appendix(text: str) -> dict | None:
    """Liest Abschnitt 'Verwendung des Inlandsprodukts, verkettete Volumenangaben', Teil b) Veränderung in %."""
    m = re.search(r"Vorausschätzung für die Jahre (20\d\d) (?:bis|und) (20\d\d)", text)
    if not m:
        return None
    y0, y1 = int(m.group(1)), int(m.group(2))
    years = list(range(y0 - 1, y1 + 1))
    n = len(years)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not re.search(r"Verwendung des Inlandsprodukts,?\s*(verkettete\s*Volumen|preisbereinigt)", line):
            continue
        # Teil b): Veränderung in % gegenüber dem Vorjahr
        j = next((k for k in range(i, min(len(lines), i + 40)) if re.search(r"Veränderung in (%|Prozent) gegenüber (dem )?Vorjahr", lines[k])), None)
        if j is None:
            continue
        raw = {}
        for line2 in lines[j + 1: j + 30]:
            if re.search(r"Preisniveau|Einkommensentstehung", line2):
                break
            for var, rx in VGR_LABELS.items():
                if var in raw:
                    continue
                v = _row(line2, rx, n - 1)
                if v:
                    raw[var] = v
        if "BIP real" in raw and len(raw) >= 4:
            # zwei mögliche Lagen: mit Ist-Spalte (Jahre y0-1 ... y1) oder ohne (y0 ... y1)
            alts = []
            for yrs in (years, years[1:]):
                alts.append({"jahre": yrs, "ist_spalte": len(yrs) == n,
                             "rows": {v: dict(zip(yrs, vals[: len(yrs)])) for v, vals in raw.items() if len(vals) >= len(yrs)}})
            return {"alternativen": alts}
    return None


def build_vgr(raw: Path = RAW) -> pd.DataFrame:
    """Komponenten aus dem Standard-Anhang aller Dateien, mit BIP-Abgleich gegen die geprüfte Tabelle."""
    prog = pd.read_csv(PROGNOSEN)
    prog["key"] = prog["runde"].map(_season_key)
    bip = prog.set_index(["institution", "key", "zieljahr"])["bip"].dropna()
    meta = prog.drop_duplicates(["institution", "key"]).set_index(["institution", "key"])["veroeffentlicht"]
    log = pd.read_csv(raw / "log.csv")
    urlmap = dict(zip(log["datei"], log["url"]))
    out, report = [], []
    for f in sorted(raw.glob("*.txt")):
        inst, rest = f.stem.split("_", 1)
        key = _season_key(rest.rsplit("_", 1)[0].replace("-", " "))
        res = vgr_appendix(f.read_text(encoding="utf-8", errors="replace"))
        if res is None:
            continue
        r, ok, checks, br = None, False, [], {}
        for alt in res["alternativen"]:
            br = alt["rows"].get("BIP real", {})
            checks = [(y, v) for y, v in br.items() if (inst, key, y) in bip.index]
            if len(checks) >= 1 and all(abs(bip[(inst, key, y)] - v) <= 0.051 for y, v in checks):
                r, ok = alt, True
                break
        report.append({"datei": f.stem, "institution": inst, "runde": key, "abgleich": len(checks), "ok": ok,
                       "bip_tabelle": br, "bip_geprueft": {y: bip[(inst, key, y)] for y, _ in checks}})
        if not ok:
            continue
        for var, vals in r["rows"].items():
            for y, v in vals.items():
                out.append({"institution": inst, "runde": key, "veroeffentlicht": meta.get((inst, key)), "variable": var,
                            "jahr": y, "wert": v, "ist": r["ist_spalte"] and y == r["jahre"][0], "quelle": urlmap.get(f.stem, ""), "datei": f.stem})
    df = pd.DataFrame(out).drop_duplicates(["institution", "runde", "variable", "jahr"]) if out else pd.DataFrame()
    return df, pd.DataFrame(report)


# ---------------------------------------------------------------- Bundesbank: "Eckwerte der gesamtwirtschaftlichen Prognose"
BBK_LABELS = {
    "BIP real": r"BIP \(real\)",
    "BIP unbereinigt": r"desgleichen unbereinigt",
    "Privater Konsum": r"Private Konsumausgaben",
    "Staatskonsum": r"Konsumausgaben des Staates",
    "Exporte": r"Exporte",
    "Importe": r"Importe",
    "Erwerbstätige": r"Erwerbstätige",
    "Arbeitslosenquote BA (%)": r"Arbeitslosenquote",
    "Verbraucherpreise": r"Harmonisierter Verbraucherpreisindex",
}
BBK_NUM = r"[-−–]\s?\d{1,2},\d|\d{1,2},\d"


def bbk_tables(text: str) -> list[dict]:
    """Alle Eckwert-Tabellen der Bundesbank im Text (kalenderbereinigt und, falls vorhanden, unbereinigt)."""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if not re.match(r"^Position\s+20[12]\d", line.strip()):
            continue
        if not any(re.match(r"^BIP \(real\)", l.strip()) for l in lines[i + 1: i + 3]):
            continue
        years = [int(y) for y in re.findall(r"(20[12]\d)", line)]
        if len(years) < 3 or years != list(range(years[0], years[0] + len(years))):
            continue
        n = len(years)
        unbereinigt = any("ohne Kalenderbereinigung" in l for l in lines[max(0, i - 4): i])
        rows, contrib = {}, False
        for line2 in lines[i + 1: i + 60]:
            s = line2.strip()
            if re.match(r"^Position\s+20", s):
                break
            if re.search(r"Beiträge zum", s):
                contrib = True
            if re.match(r"^(Arbeitsmarkt|Löhne|Preise)", s):
                contrib = False
            for var, rx in BBK_LABELS.items():
                if var in rows or (contrib and var in ("Exporte", "Importe")):
                    continue
                m = re.match(r"^" + rx + r"\s*\d?\)?\s+((?:(?:" + BBK_NUM + r")\s+){" + str(n - 1) + r"}(?:" + BBK_NUM + r"))$", s)
                if m:
                    rows[var] = dict(zip(years, [_num(v) for v in re.findall(BBK_NUM, m.group(1))]))
        if "BIP real" in rows and len(rows) >= 4:
            out.append({"jahre": years, "rows": rows, "unbereinigt": unbereinigt})
    return out


def bbk_table(text: str) -> dict | None:
    ts = bbk_tables(text)
    if not ts:
        return None
    un = [t for t in ts if t["unbereinigt"]]
    if not un and len(ts) >= 2 and ts[1]["jahre"] == ts[0]["jahre"]:
        ts[1]["unbereinigt"] = True  # zweite Tabelle gleicher Jahre: Fassung ohne Kalenderbereinigung
        un = [ts[1]]
    return un[0] if un else ts[0]


def build_bbk(raw: Path = RAW) -> tuple[pd.DataFrame, pd.DataFrame]:
    prog = pd.read_csv(PROGNOSEN)
    prog = prog[prog["institution"] == "Bundesbank"].copy()
    prog["key"] = prog["runde"].map(_season_key)
    ref = {}
    for _, r in prog.iterrows():
        for c in ("bip", "bip_kalenderbereinigt"):
            if pd.notna(r[c]):
                ref.setdefault((r["key"], int(r["zieljahr"])), set()).add(round(float(r[c]), 1))
    meta = prog.drop_duplicates("key").set_index("key")["veroeffentlicht"]
    log = pd.read_csv(raw / "log.csv")
    urlmap = dict(zip(log["datei"], log["url"]))
    out, report = [], []
    for f in sorted(raw.glob("Bundesbank_*.txt")):
        key = _season_key(f.stem.split("_", 1)[1].rsplit("_", 1)[0].replace("-", " "))
        t = bbk_table(f.read_text(encoding="utf-8", errors="replace"))
        if t is None:
            continue
        bips = [t["rows"].get("BIP real", {}), t["rows"].get("BIP unbereinigt", {})]
        checks = [(y, v) for b in bips for y, v in b.items() if (key, y) in ref]
        hits = [any(abs(v - x) <= 0.051 for x in ref[(key, y)]) for y, v in checks]
        ok = bool(hits) and sum(hits) >= max(1, len({y for y, _ in checks}))
        report.append({"datei": f.stem, "runde": key, "ok": ok, "abgleich": len(checks)})
        if not ok:
            continue
        for var, vals in t["rows"].items():
            if var == "BIP unbereinigt":
                continue
            for y, v in vals.items():
                out.append({"institution": "Bundesbank", "runde": key, "veroeffentlicht": meta.get(key), "variable": var,
                            "jahr": y, "wert": v, "ist": y == t["jahre"][0], "quelle": urlmap.get(f.stem, ""),
                            "datei": f.stem, "anmerkung": ("unbereinigt" if t["unbereinigt"] else "kalenderbereinigt") + "; Verbraucherpreise = HVPI"})
    df = pd.DataFrame(out).drop_duplicates(["runde", "variable", "jahr"]) if out else pd.DataFrame()
    return df, pd.DataFrame(report)


def build_all(raw: Path = RAW, out: Path = OUT) -> pd.DataFrame:
    """Standard-Anhang (GD, Institute) und Bundesbank zusammen, nur am BIP abgeglichene Tabellen."""
    a, _ = build_vgr(raw)
    b, _ = build_bbk(raw)
    df = pd.concat([x for x in (a, b) if len(x)], ignore_index=True)
    if "anmerkung" not in df:
        df["anmerkung"] = ""
    df["anmerkung"] = df["anmerkung"].fillna("unbereinigt (Standardanhang VGR)")
    df = df[["institution", "runde", "veroeffentlicht", "variable", "jahr", "wert", "ist", "quelle", "anmerkung"]]
    df = df.sort_values(["institution", "veroeffentlicht", "variable", "jahr"])
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df
