# Supertrend 10/3 1h con tamaño adaptable — backtest 2 años

Capital inicial $10,000. Riesgo total 1.5 % repartido entre N posiciones; N por capital: ((0, 1), (2000, 2), (10000, 3), (50000, 4)). Costo $0.3/oz.

## GC=F (13,761 velas 1h, 07/07/2024 → 26/11/2026)

| Variante | Capital final | Retorno | Caida max | Operaciones | Acierto | PF | Peor mes | Meses positivos | Sharpe | P(perder un mes) MC |
|---|---|---|---|---|---|---|---|---|---|---|
| A. Actual: 0,1 oz fijo, siempre en mercado | $10,132 | +1 % | 1 % | 337 | 36 % | 1.17 | -0.5 % | 68 % | 0.60 | 49 % |
| B. Riesgo fijo por operacion (1 posicion) | $13,041 | +30 % | 14 % | 337 | 36 % | 1.14 | -6.8 % | 54 % | 0.69 | 49 % |
| C. B + piramidacion segun capital | $13,855 | +39 % | 12 % | 712 | 39 % | 1.26 | -5.3 % | 61 % | 1.04 | 37 % |
| D. C + solo en el cambio de color | $14,679 | +47 % | 11 % | 672 | 40 % | 1.34 | -4.7 % | 61 % | 1.26 | 33 % |
| E. D + frenos (perdida diaria / caida max) | $14,679 | +47 % | 11 % | 672 | 40 % | 1.34 | -4.7 % | 61 % | 1.26 | 33 % |

## PAXG-USD (12,388 velas 1h, 27/11/2024 → 26/11/2026)

| Variante | Capital final | Retorno | Caida max | Operaciones | Acierto | PF | Peor mes | Meses positivos | Sharpe | P(perder un mes) MC |
|---|---|---|---|---|---|---|---|---|---|---|
| A. Actual: 0,1 oz fijo, siempre en mercado | $10,414 | +4 % | 1 % | 405 | 38 % | 1.65 | -0.3 % | 67 % | 2.15 | 30 % |
| B. Riesgo fijo por operacion (1 posicion) | $29,021 | +190 % | 14 % | 405 | 38 % | 1.55 | -5.5 % | 67 % | 2.36 | 34 % |
| C. B + piramidacion segun capital | $22,494 | +125 % | 13 % | 862 | 39 % | 1.54 | -5.4 % | 71 % | 2.26 | 22 % |
| D. C + solo en el cambio de color | $21,617 | +116 % | 13 % | 850 | 39 % | 1.53 | -5.4 % | 67 % | 2.19 | 22 % |
| E. D + frenos (perdida diaria / caida max) | $21,617 | +116 % | 13 % | 850 | 39 % | 1.53 | -5.4 % | 67 % | 2.19 | 22 % |
