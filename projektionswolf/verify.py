"""Gegenprüfung der gepflegten Prognosetabelle an den Quellen.

Für jede Zeile mit Quellen-URL wird das Dokument geladen (HTML oder PDF) und geprüft,
ob die eingetragenen Zahlen im Text vorkommen (deutsche und englische Schreibweise).
Ergebnis je Zeile: ``bestätigt`` (alle eingetragenen Werte gefunden), ``teilweise``,
``nicht gefunden`` oder ``nicht abrufbar``. Das ist eine Plausibilitätsprüfung: Ein
gefundener Wert kann zufällig an anderer Stelle stehen; ein fehlender Wert ist ein
Hinweis auf einen Fehler oder auf eine Zahl, die nur in einer Grafik steht.
"""

from __future__ import annotations

import io
import logging
import re
import time
from pathlib import Path

import pandas as pd
import requests

from .prognosen import PROGNOSEN

log = logging.getLogger(__name__)
OUT = Path("data/raw/prognosen_pruefung.csv")
TEXTS = Path("data/raw/quellen_text")  # Volltext nicht bestätigter Quellen, zum Nachprüfen
CHECK_COLS = ["bip", "inflation", "potenzialwachstum", "produktionsluecke"]
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
           "Accept-Language": "de,en;q=0.8"}


def _text(content: bytes, ctype: str) -> str:
    if content[:4] == b"%PDF" or "pdf" in ctype:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:80])
    html = content.decode("utf-8", errors="replace")
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def _variants(v: float) -> list[str]:
    s = f"{v:.1f}"
    out = {s, s.replace(".", ",")}
    if v < 0:
        a = f"{abs(v):.1f}"
        out |= {f"−{a}", f"–{a}", f"−{a}".replace(".", ","), f"–{a}".replace(".", ",")}
    return sorted(out)


def found(text: str, v: float) -> bool:
    lb = r"(?<![\d,.])" if v < 0 else r"(?<![\d,.\-−–])"  # positive Werte nicht als Teil von "−0,2" zählen
    for s in _variants(v):
        if re.search(lb + re.escape(s) + r"(?![\d])", text):
            return True
    return False


def verify(path: Path = PROGNOSEN, out: Path = OUT, pause: float = 0.5) -> pd.DataFrame:
    df = pd.read_csv(path)
    cache: dict[str, str | None] = {}
    s = requests.Session()
    s.headers.update(HEADERS)
    rows = []
    for i, r in df.iterrows():
        url = str(r.get("quelle") or "")
        if not url.startswith("http"):
            rows.append({"zeile": i, "pruefung": "keine URL"})
            continue
        if url not in cache:
            try:
                resp = s.get(url, timeout=60)
                ok = resp.ok and len(resp.content) > 500 and b"Radware" not in resp.content[:3000]
                cache[url] = _text(resp.content, resp.headers.get("content-type", "")) if ok else None
            except Exception as e:  # Netz- oder Parserfehler: Zeile als nicht abrufbar markieren
                log.warning("%s: %s", url, e)
                cache[url] = None
            time.sleep(pause)
        text = cache[url]
        if text is None:
            rows.append({"zeile": i, "pruefung": "nicht abrufbar"})
            continue
        vals = {c: pd.to_numeric(r[c], errors="coerce") for c in CHECK_COLS if c in r}
        vals = {c: v for c, v in vals.items() if pd.notna(v)}
        hits = {c: found(text, float(v)) for c, v in vals.items()}
        n = sum(hits.values())
        status = "bestätigt" if vals and n == len(vals) else ("teilweise" if n else "nicht gefunden")
        rows.append({"zeile": i, "pruefung": status, "fehlend": ", ".join(c for c, h in hits.items() if not h)})
    res = df.join(pd.DataFrame(rows).set_index("zeile"))
    import hashlib

    TEXTS.mkdir(parents=True, exist_ok=True)
    for f in TEXTS.glob("*.txt"):
        f.unlink()
    bad = res[res["pruefung"].isin(["teilweise", "nicht gefunden"])]
    index = []
    for url in bad["quelle"].unique():
        h = hashlib.sha1(url.encode()).hexdigest()[:12]
        (TEXTS / f"{h}.txt").write_text(cache[url] or "", encoding="utf-8")
        index.append({"datei": f"{h}.txt", "quelle": url})
    pd.DataFrame(index, columns=["datei", "quelle"]).to_csv(TEXTS / "index.csv", index=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out, index=False)
    return res
