# Backtesting en 1 minuto — oro (noviembre 2026)

Ejecutar: `python research/backtest_1m/backtest_1m.py` (descarga los ~28 dias de velas 1m que
Yahoo permite y escribe `resultados.md`).

## Conclusiones (corrida del 25/11/2026)

- **Datos:** PAXG-USD en 1m tiene **43 % de velas planas** (sin operaciones) en horario
  operable: no sirve para 1m. Los futuros GC=F (0 % planas) son la referencia valida.
- **64 configuraciones** en 6 familias: Supertrend 1m, Supertrend con filtro 15m/1h, reversion
  z-score, ruptura Donchian, "alto acierto" y regresion logistica walk-forward.
- **Ninguna gano en entrenamiento Y en prueba en ambos mercados.** Solo el 4 % (PAXG) y el
  11 % (GC=F) de las configuraciones ganaron en la prueba ciega.
- **En GC=F, la correlacion entre el resultado en entrenamiento y en prueba es −0,57:** lo
  que mejor funcionaba antes tendio a fallar despues (sobreajuste o cambio de regimen).
- **Entradas al azar** pierden ~$0,31/trade, que es el costo. Las mejores estrategias no se
  distinguen del azar (intervalos de confianza que incluyen el 0).
- **Las configuraciones de alto acierto (71–90 % de operaciones ganadoras) pierden dinero:**
  ganan poco muchas veces y pierden mucho pocas veces.
- **Veredicto:** no hay base estadistica para automatizar 1m en oro con costos de CFD. La
  regla Supertrend 10/3 en 1h (2 años, PF 1,39 en el dashboard) sigue siendo la opcion con
  evidencia.
