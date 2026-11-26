### Prueba en simulacion — Fibonacci 1m con confirmacion (sin ordenes)

- Datos de Capital.com: 999 velas 1m, 25/11 05:29 → 25/11 23:08 (hora El Salvador), 1 dias de mercado.
- Spread real: mediana $0.50, percentil 90 $0.75, 22 % del tiempo mayor a $0,50.

| Variante | Ops | Ops/dia | Acierto | $/oz por op (IC 95 %) | En R | PF | $10 al 5 % (1:200) | $10 al 5 % (1:20) |
|---|---|---|---|---|---|---|---|---|
| Sin filtro de spread | 0 | — | — | — | — | — | — | — |
| Solo si spread ≤ $0,50 | 0 | — | — | — | — | — | — | — |

**Veredicto:** faltan datos (0 de 100 operaciones). Backtest de referencia: ~3.5 ops/dia, acierto ~31 %, ~+0.5R por operacion.
