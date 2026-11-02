"""Lädt die Prognosetabellen von GD, Bundesbank und Instituten (URLs aus data/manuell/tabellen_urls.csv).

PDF: Seiten mit Verwendungskomponenten als Text; XLSX: alle Blätter als CSV-Text. Bereits geladene
Dateien werden übersprungen. Sperrseiten (Bot-Schutz) gelten als nicht abrufbar.
"""
import io, re, time, hashlib
from pathlib import Path
import pandas as pd, requests, pdfplumber

OUT = Path("data/raw/tabellen"); OUT.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "de,en"}
KEY = re.compile(r"(Konsumausgaben|Ausrüstung|Bauinvestition|Exporte|Importe|Erwerbstätige|private consumption|equipment|exports)", re.I)
urls = pd.read_csv("data/manuell/tabellen_urls.csv")
logp = OUT / "log.csv"
old = pd.read_csv(logp) if logp.exists() else pd.DataFrame(columns=["datei", "url", "status", "art"])
log = []
for _, r in urls.iterrows():
    url = str(r["url"])
    if not url.startswith("http"):
        continue
    slug = re.sub(r"\W+", "-", f"{r['institution']}_{r['runde']}").strip("-")
    name = f"{slug}_{hashlib.sha1(url.encode()).hexdigest()[:6]}"
    if (OUT / f"{name}.txt").exists():
        log.append({"datei": name, "url": url, "status": "vorhanden", "art": ""}); continue
    try:
        resp = requests.get(url, headers=H, timeout=180)
        c = resp.content
        if not resp.ok or len(c) < 1500 or b"Client Challenge" in c[:4000] or b"Radware" in c[:4000]:
            log.append({"datei": name, "url": url, "status": f"nicht abrufbar ({resp.status_code})", "art": ""}); continue
        if c[:4] == b"%PDF":
            pages = []
            with pdfplumber.open(io.BytesIO(c)) as pdf:
                for i, p in enumerate(pdf.pages[:300]):
                    t = p.extract_text() or ""
                    if len(KEY.findall(t)) >= 3:
                        pages.append(f"=== Seite {i+1}\n{t}")
            txt, art = "\n".join(pages), "pdf"
        elif c[:2] == b"PK":
            sheets = pd.read_excel(io.BytesIO(c), sheet_name=None, header=None)
            txt = "\n".join(f"=== Blatt {k}\n" + v.to_csv(index=False, header=False) for k, v in sheets.items())
            art = "xlsx"
        else:
            html = c.decode("utf-8", errors="replace")
            html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
            txt, art = re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", html)), "html"
        (OUT / f"{name}.txt").write_text(txt, encoding="utf-8")
        log.append({"datei": name, "url": url, "status": f"ok ({len(txt)} Zeichen)", "art": art})
    except Exception as e:
        log.append({"datei": name, "url": url, "status": repr(e)[:150], "art": ""})
    time.sleep(1)
pd.DataFrame(log).to_csv(logp, index=False)
print(pd.DataFrame(log)["status"].str.split(" ").str[0].value_counts())
