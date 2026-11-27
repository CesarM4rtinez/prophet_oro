### Prueba en simulacion — Fibonacci 1m con confirmacion (sin ordenes)

- Datos de Capital.com: 3,105 velas 1m, 25/11 05:29 → 27/11 13:44 (hora El Salvador), 3 dias de mercado, 1 huecos de datos.
- Spread real: mediana $0.50, percentil 90 $0.75, 13 % del tiempo mayor a $0,50.

| Variante | Ops | Ops/dia | Acierto | $/oz por op (IC 95 %) | En R | PF | $10 al 5 % (1:200) | $10 al 5 % (1:20) |
|---|---|---|---|---|---|---|---|---|
| Sin filtro de spread | 9 | 3.0 | 44 % | +2.14 (-1.09 a +5.89) | +0.86R | 2.54 | $13.75 (caida 14 %) | $10.94 |
| Solo si spread ≤ $0,50 | 9 | 3.0 | 44 % | +2.14 (-1.09 a +5.89) | +0.86R | 2.54 | $13.75 (caida 14 %) | $10.94 |

**Veredicto:** faltan datos (9 de 100 operaciones). Backtest de referencia: ~3.5 ops/dia, acierto ~31 %, ~+0.5R por operacion.

Ultimas operaciones simuladas (hora El Salvador):

| Entrada | Lado | Precio | Salida | Motivo | $/oz | Spread |
|---|---|---|---|---|---|---|
| 27/11 05:17 | COMPRA | 3,676.61 | 3,674.11 | stop | -2.50 | 0.50 |
| 27/11 00:42 | COMPRA | 3,648.29 | 3,659.40 | objetivo | +11.11 | 0.50 |
| 26/11 23:40 | COMPRA | 3,649.59 | 3,647.09 | stop | -2.50 | 0.50 |
| 26/11 23:01 | COMPRA | 3,635.15 | 3,639.77 | objetivo | +4.62 | 0.50 |
| 26/11 22:03 | COMPRA | 3,629.09 | 3,635.00 | objetivo | +5.91 | 0.50 |
| 26/11 09:03 | VENTA | 3,578.36 | 3,568.21 | objetivo | +10.15 | 0.50 |
| 26/11 07:55 | VENTA | 3,568.14 | 3,570.64 | stop | -2.50 | 0.50 |
| 26/11 06:48 | VENTA | 3,568.07 | 3,570.57 | stop | -2.50 | 0.50 |
