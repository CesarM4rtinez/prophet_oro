# Estrategia Fibonacci 1m con confirmacion — prueba en simulacion

Es el estilo de trading manual del usuario convertido en reglas (ver `strategy.py` y
`research/manual_style`):

- **Contexto:** impulso de 1 minuto a favor de la tendencia Supertrend 10/3 de 15m **y** de 1h.
- **Entrada:** el precio toca el retroceso **0,618** y una vela de 1m **cierra** de vuelta por
  encima de **0,5** (compra; espejo para venta). Compra al ask, vende al bid.
- **Stop:** fijo de **$2,50**. **Objetivo:** extension **1,272**. **Sin stop a cero** (en el
  backtest subia el acierto de 25 % a 45 %, pero dejaba la ganancia en ~$0).
- **Filtro de spread:** solo opera con spread ≤ $0,50 (de noche llega a $1-2).

## Por que primero en simulacion

El backtest de 25 dias (87 operaciones, 31 % de acierto, +$11,00 / −$2,80 por onza, ≈ +0,5R
por operacion) gano en entrenamiento y en prueba, pero la muestra es de un solo mes. Antes de
arriesgar dinero se mide con los precios **reales de Capital.com** (bid/ask, spread incluido)
hasta tener al menos 100 operaciones.

## Como funciona sin PC

El flujo `.github/workflows/fib1m_forward.yml` corre cada 2 horas en GitHub Actions:

1. Descarga las ultimas 1 000 velas de 1 minuto de GOLD (~16 horas) con bid y ask.
2. Las agrega en la rama **`datos-fib1m`** (`GOLD_1m_AAAA-MM-DD.csv`); si GitHub se atrasa
   unas horas no se pierden datos.
3. Simula la estrategia sobre todo lo acumulado y escribe **`informe.md`** en esa rama y en el
   resumen de cada ejecucion (pestaña Actions).

**No envia ninguna orden** ni toca la subcuenta. Usa los mismos Secrets que el robot de 1h.
Para apagarla: variable `FIB1M_FORWARD = false`.

## Veredicto automatico del informe

- *Faltan datos*: menos de 100 operaciones.
- *Confirmada*: el intervalo de confianza del resultado por operacion queda por encima de 0 →
  lista para operar en la subcuenta demo **CFDs** (riesgo 5 %, filtro de spread y de noticias).
- *Positiva pero no concluyente* / *No confirmada*: seguir midiendo o descartarla.

## Para operar de verdad (despues)

Una estrategia de 1 minuto necesita reaccionar en segundos: GitHub Actions no sirve para
ejecutarla (corre cada varios minutos, con atrasos). Si la simulacion la confirma, se ejecuta
con `robot_supertrend/runner.py` (u otro proceso continuo) en una PC o servidor, en la
subcuenta **CFDs**, separada de **dm** (robot de 1h).

## Pruebas

```bash
python -m pytest robot_fib1m/tests -q
```
