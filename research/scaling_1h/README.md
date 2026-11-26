# Backtest de tamaño adaptable (Supertrend 10/3, 1h, 2 años)

`python research/scaling_1h/backtest_scaling.py` → `resultados.md`.
Usa el mismo `robot_supertrend/risk.py` que el robot. Variantes A–E descritas en el script.
Sensibilidad probada: riesgo total 1 % / 1,5 % / 2 % (caida maxima ~8–9 %, ~11–13 %, ~15–17 %);
se eligio 1,5 %. Un freno de caida maxima del 15 % detenia el robot de forma permanente en
PAXG (la estrategia tiene caidas normales de ~13–17 %), por eso el freno quedo en 25 %.
