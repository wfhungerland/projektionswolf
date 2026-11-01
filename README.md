# projektionswolf

Nachbau der Potenzialschätzung der Bundesregierung in Python, ergänzt um eigene Kalman-Filter für NAWRU und TFP-Trend, einen BIP-Nowcast aus Monatsindikatoren und Backtests. GitHub Actions lädt die Daten wöchentlich neu und schreibt die Ergebnisse nach [`output/`](output).

| Pfad | Inhalt |
|---|---|
| [`output/projektionswolf.xlsx`](output/projektionswolf.xlsx) | Workbook: Info, Quellen, je Auswertung ein Blatt |
| [`output/bericht.md`](output/bericht.md) | Kurzbericht des letzten Laufs |
| `data/bmwe/<Runde>/` | Rechengrundlagen des BMWE je Projektionsrunde als CSV (Eingangsdaten, Ergebnisse, GAP-Daten, EViews-Programm) |
| `data/raw/` | Eurostat-Monatsindikatoren, AMECO-Reihen, Abrufstatus |
| `data/manuell/` | Eckwerte, die noch nicht als Rechengrundlage vorliegen (z. B. Herbstprojektion 2026) |

## Was die Bausteine leisten

1. **Nachbau** (`projektionswolf/potential.py`): Das EViews-Programm von BMWE und BMF Zeile für Zeile in Python. Es trifft die veröffentlichten Ergebnisse aller Runden seit Frühjahr 2024 auf Rundungsgenauigkeit (Abweichung der Produktionslücke unter 10⁻⁷ Prozentpunkten). Die Runden davor nutzen eine ältere Programmfassung und werden nur für den Projektions-Backtest gelesen.
2. **Eigene Filter** (`projektionswolf/filters.py`): Die Bundesregierung übernimmt NAWRU und TFP-Trend aus dem EU-Programm GAP (Bayes-Schätzung). Hier stehen dieselben Modelle als Zustandsraummodelle: NAWRU per Maximum Likelihood in den GAP-Parametergrenzen, TFP per Posterior-Modus mit den EU-Prioren für Deutschland. Das Workbook zeigt, wie sich Potenzial und Lücke damit ändern.
3. **Nowcast** (`projektionswolf/nowcast.py`): dynamisches Faktormodell mit gemischten Frequenzen (Produktion, Bau, Einzelhandel, EU-Umfragen, Arbeitslosigkeit; Quartals-BIP), dazu eine Bridge-Gleichung als Gegenprobe. Corona-Monate gehen als fehlend in die Schätzung ein.
4. **Backtests** (`projektionswolf/pipeline.py`): BIP-Projektionen der Bundesregierung je Runde gegen den letzten Datenstand; Nowcast in Pseudo-Echtzeit seit 2014 gegen AR(1) und Mittelwert.

## Start

```bash
pip install -e ".[dev]"
```

```bash
python -m projektionswolf fetch
```

```bash
python -m projektionswolf run
```

```bash
python -m projektionswolf check
```

`fetch` lädt AMECO, Eurostat und die BMWE-Rechengrundlagen und wandelt sie in CSV um. `run` schätzt alles und schreibt Workbook und Bericht; `--quick` lässt den Nowcast-Backtest weg. `check` vergleicht den Nachbau mit den BMWE-Ergebnissen und endet mit Exit-Code 1 bei Abweichung. Tests: `pytest -q`.

## Grenzen

- Die eigenen Filter treffen GAP nicht exakt: GAP schätzt per MCMC den Posterior-Mittelwert, hier steht der Modus bzw. ML. Die NAWRU liegt historisch rund 0,1 Punkte über dem Wert der Bundesregierung. Beim TFP-Trend landet die Dämpfung am Rand (0,99); deshalb flacht der eigene Trend ab 2028 ab, während GAP wieder anzieht.
- Die NAWRU-Fortschreibung ab T+2 ist eine vereinfachte Ankerregel (lineare Annäherung an 3,6 % über acht Jahre).
- Der Nowcast nutzt kalenderbereinigte Raten; die Projektion der Bundesregierung nennt unbereinigte Jahresraten. Der Backtest arbeitet mit heutigem Datenstand, nicht mit Echtzeit-Vintages.
- Die Variante des Nowcasts (Umfragen als Vorjahresveränderung, Corona maskiert) wurde auf demselben Zeitraum gewählt, auf dem sie getestet wird.
- Die Rechengrundlagen der Herbstprojektion 2026 waren beim Aufbau noch nicht veröffentlicht. `fetch` versucht sie bei jedem Lauf; sobald das ZIP online ist, rechnet der Lauf sie mit.

## Quellen

- BMWE/BMF: Ergänzende Unterlagen zu den Berechnungsgrundlagen für die Bestimmung des gesamtwirtschaftlichen Produktionspotenzials, je Projektionsrunde (Downloads unter `bundeswirtschaftsministerium.de/Redaktion/DE/Downloads/G/`).
- Havik, K. et al. (2014): The Production Function Methodology for Calculating Potential Growth Rates & Output Gaps. European Economy, Economic Papers 535.
- Eurostat Dissemination API; AMECO-Datenbank der EU-Kommission.
