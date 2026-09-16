# WMA(14) + Filtro RSI(14) — Trading intradia sobre Capital.com

Sistema de trading intradia en Streamlit, conectado a Capital.com (Indices, Forex,
Cripto, Futuros/Materias Primas), que implementa una estrategia de seguimiento de
tendencia con filtro de rango inspirada en el enfoque de Pablo Gil.

## Estrategia

- **WMA (Media Movil Ponderada)**: 14 periodos sobre el precio de cierre.
- **RSI**: 14 periodos.
- **Filtro RSI**: compra habilitada mientras `RSI < 40`, venta habilitada mientras
  `RSI > 60`. Entre 40 y 60 es zona neutra: no se abre ni se cierra nada.
- **Disparo**: con el filtro habilitado (RSI fuera de la zona neutra en esa misma
  vela), la entrada ocurre cuando la WMA quiebra de direccion (minimo/maximo
  local): quiebro al alza con filtro de compra -> LONG; quiebro a la baja con
  filtro de venta -> SHORT.
- **Stop Loss**: minimo (LONG) o maximo (SHORT) pivote previo mas cercano al
  momento de la entrada.
- **Cierre**: por Stop Loss, o por una señal contraria (filtro + quiebro opuesto),
  que cierra la posicion y abre la contraria en la misma vela (reversa). No hay
  Take Profit fijo.
- **Reactivacion**: tras cualquier cierre, hace falta que el RSI vuelva a estar
  fuera de la zona neutra (no basta con que la WMA quiebre otra vez sola).

Toda la logica vive en `core/strategy.py` (`generate_signals`), una funcion PURA de
pandas sin dependencias de Streamlit ni del broker — la usan tanto el motor en vivo
(`pages/1_terminal.py`) como el backtest (`core/backtest.py`), asi que nunca hay dos
implementaciones de las reglas que puedan desalinearse.

## Instalacion

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # o copia tu .env de otro proyecto con las mismas credenciales
# completa CAPITAL_API_KEY / CAPITAL_API_USER / CAPITAL_API_PASSWORD en .env
streamlit run app.py
```

## Paginas

- **Terminal**: conexion (DEMO/LIVE, seleccion de cuenta), busqueda de instrumentos
  por clase de activo, grafico en vivo (velas + WMA + señales arriba, RSI + zonas
  40/60 abajo), tarjeta de estado de la maquina, posiciones abiertas, ticket manual
  y motor semi-automatico (armar/desarmar, nunca persiste entre reinicios).
- **Backtest**: corre `generate_signals` sobre velas historicas reales con
  `backtesting.lib.FractionalBacktest` (soporta tamaños fraccionarios, como opera
  Capital.com via CFDs) — stats, curva de equity y tabla de operaciones.

## ⚠️ Riesgo

Este sistema puede conectarse a una cuenta REAL y enviar ordenes con dinero real.
Arranca siempre en DEMO por defecto; armar el motor en LIVE exige escribir "ARMAR"
explicitamente. Verifica los resultados del backtest y las reglas antes de operar
con dinero real — ninguna estrategia garantiza resultados futuros.
