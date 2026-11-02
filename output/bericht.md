# projektionswolf: Lauf vom 2026-11-02 11:09 UTC

## Nachbau der Potenzialschätzung
Nachgerechnet: 7 Runden (FP24, HP24, JP25, FP25, HP25, JP26, FP26). Größte Abweichung der Produktionslücke: 7.1e-08 Prozentpunkte.

### Letzte Runde: Frühjahrsprojektion 2026
| year | Potenzialwachstum | Beitrag Arbeit | Beitrag Kapital | Beitrag TFP | Produktionslücke | BIP-Wachstum |
|---|---|---|---|---|---|---|
| 2018 | 1.30 | 0.22 | 0.46 | 0.62 | 1.88 | 1.14 |
| 2019 | 1.14 | 0.10 | 0.46 | 0.57 | 1.72 | 0.98 |
| 2020 | 0.81 | -0.07 | 0.43 | 0.44 | -3.27 | -4.13 |
| 2021 | 0.68 | -0.04 | 0.34 | 0.38 | -0.17 | 3.91 |
| 2022 | 0.76 | 0.20 | 0.32 | 0.23 | 0.87 | 1.81 |
| 2023 | 0.78 | 0.35 | 0.32 | 0.10 | -0.78 | -0.87 |
| 2024 | 0.59 | 0.25 | 0.26 | 0.07 | -1.84 | -0.50 |
| 2025 | 0.43 | 0.14 | 0.23 | 0.07 | -2.03 | 0.24 |
| 2026 | 0.31 | 0.00 | 0.24 | 0.07 | -1.84 | 0.51 |
| 2027 | 0.36 | -0.03 | 0.27 | 0.12 | -1.26 | 0.95 |
| 2028 | 0.41 | -0.07 | 0.27 | 0.20 | -0.80 | 0.87 |
| 2029 | 0.45 | -0.09 | 0.28 | 0.26 | -0.38 | 0.87 |
| 2030 | 0.49 | -0.11 | 0.28 | 0.32 | -0.00 | 0.87 |

### Eigene Filter statt GAP (letzte Runde)
| jahr | Potenzialwachstum: Bundesregierung (GAP) | Potenzialwachstum: beide eigenen Filter | Lücke: Bundesregierung (GAP) | Lücke: beide eigenen Filter |
|---|---|---|---|---|
| 2018 | 1.30 | 1.32 | 1.88 | 1.95 |
| 2019 | 1.14 | 1.17 | 1.72 | 1.76 |
| 2020 | 0.81 | 0.81 | -3.27 | -3.23 |
| 2021 | 0.68 | 0.70 | -0.17 | -0.14 |
| 2022 | 0.76 | 0.75 | 0.87 | 0.91 |
| 2023 | 0.78 | 0.74 | -0.78 | -0.70 |
| 2024 | 0.59 | 0.57 | -1.84 | -1.75 |
| 2025 | 0.43 | 0.43 | -2.03 | -1.94 |
| 2026 | 0.31 | 0.30 | -1.84 | -1.74 |
| 2027 | 0.36 | 0.37 | -1.26 | -1.17 |
| 2028 | 0.41 | 0.40 | -0.80 | -0.71 |
| 2029 | 0.45 | 0.46 | -0.38 | -0.30 |
| 2030 | 0.49 | 0.51 | -0.00 | 0.05 |

## Nowcast
|  | BIP q/q Ist | DFM | Bridge |
|---|---|---|---|
| 2025Q1 | 0.10 |  |  |
| 2025Q2 | 0.00 |  |  |
| 2025Q3 | 0.00 |  |  |
| 2025Q4 | 0.30 |  |  |
| 2026Q1 | 0.40 |  |  |
| 2026Q2 | 0.30 |  |  |
| 2026Q3 | 0.20 |  |  |
| 2026Q4 |  | 0.43 | 0.38 |
| 2027Q1 |  | 0.36 | 0.32 |

Jahreswachstum 2026 (kalenderbereinigt) aus dem Faktormodell: 1.06 %. Datenstand Monatsindikatoren: 2026-10.
Setzt man dieses Wachstum in die Frühjahrsprojektion 2026 ein (0.51 % dort), ändert sich die Lücke 2026 von -1.84 auf -1.30 % des Potenzials.

### Backtest Nowcast (ohne Corona-Quartale)
|  | RMSE | MAE | n | RMSE relativ zu AR(1) |
|---|---|---|---|---|
| DFM | 0.453 | 0.323 | 46.000 | 0.813 |
| ar1 | 0.557 | 0.405 | 46.000 | 1.000 |
| mittelwert | 0.537 | 0.386 | 46.000 | 0.964 |
| bridge | 0.544 | 0.367 | 46.000 | 0.976 |

## Backtest BIP-Projektionen der Bundesregierung
| horizont | n | mittlerer_fehler | RMSE | MAE |
|---|---|---|---|---|
| Folgejahr | 6 | 1.42 | 1.56 | 1.42 |
| laufendes Jahr | 9 | 0.48 | 0.68 | 0.54 |
