### Prueba en simulacion — Fibonacci 1m con confirmacion (sin ordenes)

- Datos de Capital.com: 2,029 velas 1m, 25/11 05:29 → 26/11 19:48 (hora El Salvador), 2 dias de mercado, 1 huecos de datos.
- Spread real: mediana $0.50, percentil 90 $0.75, 17 % del tiempo mayor a $0,50.

| Variante | Ops | Ops/dia | Acierto | $/oz por op (IC 95 %) | En R | PF | $10 al 5 % (1:200) | $10 al 5 % (1:20) |
|---|---|---|---|---|---|---|---|---|
| Sin filtro de spread | 4 | 2.0 | 25 % | +0.66 (-2.50 a +6.99) | +0.27R | 1.35 | $10.30 (caida 14 %) | $10.13 |
| Solo si spread ≤ $0,50 | 4 | 2.0 | 25 % | +0.66 (-2.50 a +6.99) | +0.27R | 1.35 | $10.30 (caida 14 %) | $10.13 |

**Veredicto:** faltan datos (4 de 100 operaciones). Backtest de referencia: ~3.5 ops/dia, acierto ~31 %, ~+0.5R por operacion.

Ultimas operaciones simuladas (hora El Salvador):

| Entrada | Lado | Precio | Salida | Motivo | $/oz | Spread |
|---|---|---|---|---|---|---|
| 26/11 09:03 | VENTA | 3,578.36 | 3,568.21 | objetivo | +10.15 | 0.50 |
| 26/11 07:55 | VENTA | 3,568.14 | 3,570.64 | stop | -2.50 | 0.50 |
| 26/11 06:48 | VENTA | 3,568.07 | 3,570.57 | stop | -2.50 | 0.50 |
| 26/11 05:25 | VENTA | 3,564.35 | 3,566.85 | stop | -2.50 | 0.50 |
