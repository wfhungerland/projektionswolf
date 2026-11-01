"""Einmaliger Erkundungslauf: lädt Rohquellen und schreibt ein Inventar."""
import io, json, sys, zipfile, re, pathlib, traceback
import requests

OUT = pathlib.Path("probe/out"); OUT.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 projektionswolf-probe"}
log = {}

def get(url, **kw):
    r = requests.get(url, headers=H, timeout=120, **kw)
    return r

BMWE = "https://www.bundeswirtschaftsministerium.de"
pages = [
 "/Redaktion/DE/Artikel/Wirtschaft/Projektionen-der-Bundesregierung/projektionen-der-bundesregierung-herbst-2026.html",
 "/Redaktion/DE/Artikel/Wirtschaft/Projektionen-der-Bundesregierung/projektionen-der-bundesregierung-fruehjahrsprojektion-2026.html",
 "/Redaktion/DE/Artikel/Wirtschaft/Projektionen-der-Bundesregierung/projektionen-der-bundesregierung.html",
 "/Redaktion/DE/Downloads/G/ergaenzende-unterlagen-zu-den-berechnungsgrundlagen-fuer-die-bestimmung-des-gesamtwirtschaftlichen-produktionspotenzials-herbst-2023.html",
]
links = set()
for p in pages:
    try:
        r = get(BMWE + p)
        log[p] = r.status_code
        (OUT / (p.rsplit("/", 1)[-1] + ".txt")).write_text(r.text[:400000])
        for m in re.findall(r'href="([^"]+)"', r.text):
            if any(k in m.lower() for k in ("produktionspotenzial", "eckwert", "projektion", ".zip", ".xlsx", ".pdf")):
                links.add(m if m.startswith("http") else BMWE + m)
    except Exception as e:
        log[p] = repr(e)
(OUT / "links.txt").write_text("\n".join(sorted(links)))

# Kandidaten-ZIPs der Rechengrundlagen
cands = [l for l in links if "produktionspotenzial" in l.lower()]
guess = [f"{BMWE}/Redaktion/DE/Downloads/G/ergaenzende-unterlagen-zu-den-berechnungsgrundlagen-fuer-die-bestimmung-des-gesamtwirtschaftlichen-produktionspotenzials-{s}.zip"
         for s in ("herbst-2026", "herbstprojektion-2026", "fruehjahr-2026", "fruehjahrsprojektion-2026", "jahresprojektion-2026", "herbst-2025", "2024", "fruehjahr-2024")]
for url in sorted(set(cands + guess)):
    try:
        r = get(url, allow_redirects=True)
        ent = {"status": r.status_code, "ctype": r.headers.get("content-type"), "bytes": len(r.content)}
        if r.ok and r.content[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(r.content))
            ent["files"] = [(i.filename, i.file_size) for i in z.infolist()]
            d = OUT / ("zip_" + url.rsplit("/", 1)[-1].replace(".zip", "").replace(".html", ""))
            d.mkdir(exist_ok=True)
            for i in z.infolist():
                if i.file_size < 3_000_000 and not i.is_dir():
                    (d / pathlib.Path(i.filename).name).write_bytes(z.read(i))
        elif r.ok and "html" in (r.headers.get("content-type") or ""):
            for m in re.findall(r'href="([^"]+\.zip[^"]*)"', r.text):
                ent.setdefault("ziplinks", []).append(m)
        log[url] = ent
    except Exception as e:
        log[url] = repr(e)

# Eurostat und AMECO
tests = {
 "eurostat_gdp": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp?geo=DE&unit=CLV_PCH_PRE&s_adj=SCA&na_item=B1GQ&sinceTimePeriod=2024-Q1",
 "ameco_zip": "https://ec.europa.eu/economy_finance/db_indicators/ameco/documents/ameco0.zip",
}
for k, url in tests.items():
    try:
        r = get(url)
        ent = {"status": r.status_code, "bytes": len(r.content), "head": r.content[:300].decode("latin-1")}
        if k == "ameco_zip" and r.ok and r.content[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(r.content))
            ent["files"] = [(i.filename, i.file_size) for i in z.infolist()]
            for i in z.infolist():
                txt = z.read(i).decode("latin-1")
                lines = [l for l in txt.splitlines() if l.startswith("DEU.") or l.startswith("CODE")]
                (OUT / ("ameco_" + i.filename + ".deu.txt")).write_text("\n".join(lines))
        log[k] = ent
    except Exception as e:
        log[k] = repr(e)
(OUT / "log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False))
print(json.dumps(log, indent=1, ensure_ascii=False)[:20000])
