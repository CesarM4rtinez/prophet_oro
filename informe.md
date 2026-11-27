### Prueba en simulacion — Fibonacci 1m con confirmacion (sin ordenes)

- Datos de Capital.com: 2,580 velas 1m, 25/11 05:29 → 27/11 04:59 (hora El Salvador), 3 dias de mercado, 1 huecos de datos.
- Spread real: mediana $0.50, percentil 90 $0.75, 16 % del tiempo mayor a $0,50.

| Variante | Ops | Ops/dia | Acierto | $/oz por op (IC 95 %) | En R | PF | $10 al 5 % (1:200) | $10 al 5 % (1:20) |
|---|---|---|---|---|---|---|---|---|
| Sin filtro de spread | 8 | 2.7 | 50 % | +2.72 (-0.92 a +6.78) | +1.09R | 3.18 | $14.45 (caida 14 %) | $11.09 |
| Solo si spread ≤ $0,50 | 8 | 2.7 | 50 % | +2.72 (-0.92 a +6.78) | +1.09R | 3.18 | $14.45 (caida 14 %) | $11.09 |

**Veredicto:** faltan datos (8 de 100 operaciones). Backtest de referencia: ~3.5 ops/dia, acierto ~31 %, ~+0.5R por operacion.

Ultimas operaciones simuladas (hora El Salvador):

| Entrada | Lado | Precio | Salida | Motivo | $/oz | Spread |
|---|---|---|---|---|---|---|
| 27/11 00:42 | COMPRA | 3,648.29 | 3,659.40 | objetivo | +11.11 | 0.50 |
| 26/11 23:40 | COMPRA | 3,649.59 | 3,647.09 | stop | -2.50 | 0.50 |
| 26/11 23:01 | COMPRA | 3,635.15 | 3,639.77 | objetivo | +4.62 | 0.50 |
| 26/11 22:03 | COMPRA | 3,629.09 | 3,635.00 | objetivo | +5.91 | 0.50 |
| 26/11 09:03 | VENTA | 3,578.36 | 3,568.21 | objetivo | +10.15 | 0.50 |
| 26/11 07:55 | VENTA | 3,568.14 | 3,570.64 | stop | -2.50 | 0.50 |
| 26/11 06:48 | VENTA | 3,568.07 | 3,570.57 | stop | -2.50 | 0.50 |
| 26/11 05:25 | VENTA | 3,564.35 | 3,566.85 | stop | -2.50 | 0.50 |
