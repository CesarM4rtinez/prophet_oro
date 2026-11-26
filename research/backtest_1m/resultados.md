# Backtesting 1 minuto — oro

## PAXG-USD  (40,288 velas 1m, 29/10 → 26/11/2026, ATR 1m mediano $0.78, 55 configuraciones probadas)

Segmentos: train 29/10 07:22–14/11 21:32, val 14/11 21:33–20/11 11:57, test 20/11 11:58–26/11 02:20

| Familia (mejor en entrenamiento) | Parametros | Trades ent/val/PRUEBA | Acierto PRUEBA | PF PRUEBA | $/trade PRUEBA (IC 95 %) | Neto PRUEBA $/oz | Caida max PRUEBA | Dias verdes PRUEBA | $/trade con costo 0 / 0.30 / 0.60 |
|---|---|---|---|---|---|---|---|---|---|
| Supertrend flip 1m | 20/5 | 577/210/188 | 32 % | 0.82 | -0.72 (-2.25 a +1.12) | -135.67 | 256.35 | 20 % | -0.42 / -0.72 / -1.02 |
| Supertrend 1m + filtro 15m/1h | 20/5 | 184/69/51 | 29 % | 0.70 | -1.45 (-4.41 a +2.09) | -73.85 | 119.26 | 20 % | -1.15 / -1.45 / -1.75 |
| Reversion z-score | n20 z3 tp2 sl1.5 | 117/52/45 | 47 % | 0.67 | -0.60 (-1.65 a +0.42) | -26.95 | 40.35 | 40 % | -0.30 / -0.60 / -0.90 |
| Ruptura Donchian + 15m | n120 tp4 sl1 | 327/132/94 | 20 % | 0.91 | -0.17 (-1.16 a +0.97) | -16.25 | 51.33 | 40 % | +0.13 / -0.17 / -0.47 |
| Alto acierto (TP chico / SL grande) | tp0.5 sl4 | 697/294/220 | 75 % | 0.30 | -1.20 (-1.79 a -0.72) | -265.05 | 263.25 | 0 % | -0.90 / -1.20 / -1.50 |
| Regresion logistica (walk-forward) | h30 p>0.55 | 247/168/171 | 33 % | 1.17 | +0.48 (-0.79 a +1.93) | +81.87 | 145.72 | 60 % | +0.78 / +0.48 / +0.18 |

Entrenamiento vs prueba ($/trade con costo 0.30):

- Supertrend flip 1m: entrenamiento -0.71 · validacion +0.06 · prueba -0.72 · Monte Carlo 20 dias (val+prueba): P(perder) 81 %, caida 95 % 671.82
- Supertrend 1m + filtro 15m/1h: entrenamiento +0.40 · validacion +1.30 · prueba -1.45 · Monte Carlo 20 dias (val+prueba): P(perder) 44 %, caida 95 % 307.73
- Reversion z-score: entrenamiento -0.33 · validacion -0.52 · prueba -0.60 · Monte Carlo 20 dias (val+prueba): P(perder) 99 %, caida 95 % 174.11
- Ruptura Donchian + 15m: entrenamiento -0.15 · validacion +0.04 · prueba -0.17 · Monte Carlo 20 dias (val+prueba): P(perder) 60 %, caida 95 % 178.07
- Alto acierto (TP chico / SL grande): entrenamiento -0.78 · validacion -0.70 · prueba -1.20 · Monte Carlo 20 dias (val+prueba): P(perder) 100 %, caida 95 % 1091.26
- Regresion logistica (walk-forward): entrenamiento +0.51 · validacion -0.23 · prueba +0.48 · Monte Carlo 20 dias (val+prueba): P(perder) 35 %, caida 95 % 351.57

## GC=F  (27,128 velas 1m, 29/10 → 26/11/2026, ATR 1m mediano $1.92, 55 configuraciones probadas)

Segmentos: train 29/10 11:23–16/11 04:14, val 16/11 04:15–20/11 03:07, test 20/11 03:08–26/11 02:11

| Familia (mejor en entrenamiento) | Parametros | Trades ent/val/PRUEBA | Acierto PRUEBA | PF PRUEBA | $/trade PRUEBA (IC 95 %) | Neto PRUEBA $/oz | Caida max PRUEBA | Dias verdes PRUEBA | $/trade con costo 0 / 0.30 / 0.60 |
|---|---|---|---|---|---|---|---|---|---|
| Supertrend flip 1m | 10/5 | 212/79/85 | 28 % | 0.75 | -1.80 (-5.29 a +2.33) | -152.60 | 200.60 | 50 % | -1.50 / -1.80 / -2.10 |
| Supertrend 1m + filtro 15m/1h | 20/5 | 59/27/24 | 25 % | 0.61 | -3.01 (-8.64 a +3.61) | -72.20 | 82.50 | 20 % | -2.71 / -3.01 / -3.31 |
| Reversion z-score | n20 z3 tp2 sl3 | 70/27/22 | 68 % | 1.00 | +0.01 (-3.59 a +3.48) | +0.33 | 42.41 | 40 % | +0.31 / +0.01 / -0.29 |
| Ruptura Donchian + 15m | n60 tp4 sl2 | 222/78/77 | 30 % | 0.87 | -0.56 (-2.56 a +1.69) | -43.12 | 76.54 | 33 % | -0.26 / -0.56 / -0.86 |
| Alto acierto (TP chico / SL grande) | tp0.5 sl4 | 753/288/246 | 88 % | 0.62 | -0.68 (-1.48 a -0.01) | -168.13 | 181.92 | 33 % | -0.38 / -0.68 / -0.98 |
| Regresion logistica (walk-forward) | h30 p>0.60 | 157/65/61 | 34 % | 0.69 | -1.90 (-5.08 a +1.39) | -116.02 | 136.13 | 20 % | -1.60 / -1.90 / -2.20 |

Entrenamiento vs prueba ($/trade con costo 0.30):

- Supertrend flip 1m: entrenamiento +0.49 · validacion -0.32 · prueba -1.80 · Monte Carlo 20 dias (val+prueba): P(perder) 85 %, caida 95 % 961.19
- Supertrend 1m + filtro 15m/1h: entrenamiento +3.09 · validacion +3.18 · prueba -3.01 · Monte Carlo 20 dias (val+prueba): P(perder) 46 %, caida 95 % 313.80
- Reversion z-score: entrenamiento +0.75 · validacion +0.54 · prueba +0.01 · Monte Carlo 20 dias (val+prueba): P(perder) 35 %, caida 95 % 145.42
- Ruptura Donchian + 15m: entrenamiento +0.45 · validacion -0.09 · prueba -0.56 · Monte Carlo 20 dias (val+prueba): P(perder) 78 %, caida 95 % 334.37
- Alto acierto (TP chico / SL grande): entrenamiento -0.31 · validacion -0.14 · prueba -0.68 · Monte Carlo 20 dias (val+prueba): P(perder) 100 %, caida 95 % 602.70
- Regresion logistica (walk-forward): entrenamiento +0.46 · validacion -0.22 · prueba -1.90 · Monte Carlo 20 dias (val+prueba): P(perder) 98 %, caida 95 % 545.08
