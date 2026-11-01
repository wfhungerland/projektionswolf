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
PFX = BMWE + "/Redaktion/DE/Downloads/G/ergaenzende-unterlagen-zu-den-berechnungsgrundlagen-fuer-die-bestimmung-des-gesamtwirtschaftlichen-produktionspotenzials-"
vint = ["herbst-2026", "herbstprojektion-2026", "2026", "jahresprojektion-2026", "fruehjahr-2026",
        "herbst-2025", "2025", "jahresprojektion-2025", "fruehjahr-2025",
        "herbst-2024", "2024", "fruehjahr-2024", "herbst-2023", "jahresprojektion-2023", "fruehjahr-2023"]
for v in vint:
    for ext in (".zip", ".html"):
        url = PFX + v + ext
        try:
            r = get(url + "?__blob=publicationFile&v=1", allow_redirects=True)
            ent = {"status": r.status_code, "ctype": r.headers.get("content-type"), "bytes": len(r.content)}
            if r.ok and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                ent["files"] = [(i.filename, i.file_size) for i in z.infolist()]
                d = OUT / ("zip_" + v); d.mkdir(exist_ok=True)
                for i in z.infolist():
                    if i.file_size < 4_000_000 and not i.is_dir():
                        (d / pathlib.Path(i.filename).name).write_bytes(z.read(i))
            elif r.ok:
                ent["blobs"] = sorted(set(re.findall(r'href="([^"]*blob=publicationFile[^"]*)"', r.text)))
            log[url] = ent
        except Exception as e:
            log[url] = repr(e)

# Eurostat und AMECO
tests = {
 "eurostat_gdp": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp?geo=DE&unit=CLV_PCH_PRE&s_adj=SCA&na_item=B1GQ&sinceTimePeriod=2024-Q1",
 
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
