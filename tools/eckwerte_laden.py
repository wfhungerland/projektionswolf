"""Lädt die Eckwert-Tabellen der Bundesregierung (URLs aus data/manuell/eckwerte_urls.csv) und legt den Text ab."""
import io, re, sys, time
from pathlib import Path
import pandas as pd, requests, pdfplumber

OUT = Path("data/raw/eckwerte"); OUT.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "de"}
urls = pd.read_csv("data/manuell/eckwerte_urls.csv")
log = []
for n, r in urls.iterrows():
    if r["art"] == "pressemitteilung" or "/Artikel/" in r["url"]:
        continue
    name = f"{r['kuerzel']}_{n:02d}"
    try:
        resp = requests.get(r["url"], headers=H, timeout=120)
        ok = resp.ok and resp.content[:4] == b"%PDF"
        log.append({"kuerzel": r["kuerzel"], "datei": name, "status": resp.status_code, "pdf": ok, "url": r["url"]})
        if not ok:
            continue
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            pages = []
            for i, p in enumerate(pdf.pages[:400]):
                t = p.extract_text() or ""
                if re.search(r"Eckwert|Bruttoinlandsprodukt|Verwendung des", t):
                    pages.append(f"=== Seite {i+1}\n{t}")
        (OUT / f"{name}.txt").write_text("\n".join(pages), encoding="utf-8")
    except Exception as e:
        log.append({"kuerzel": r["kuerzel"], "datei": name, "status": repr(e)[:200], "pdf": False, "url": r["url"]})
    time.sleep(1)
pd.DataFrame(log).to_csv(OUT / "log.csv", index=False)
print(pd.DataFrame(log).to_string())
