# Backtesting de oro

Adaptacion del sistema de `04. Backtesting` para trabajar con datos OHLCV del notebook, sin credenciales ni conexion a MetaTrader 5.

El notebook usa `PAXG-USD` como proxy de oro spot. La estrategia incluida es RSI con una sola posicion, stop loss y take profit porcentuales.

## Uso rapido

```python
import yfinance as yf
from backtesting_oro import ejecutar_backtest_oro, optimizar_rsi_oro

historico = yf.download("PAXG-USD", period="2y", interval="1d", auto_adjust=True)
backtest, stats = ejecutar_backtest_oro(
	historico,
	report_dir="informes_backtesting_oro",
	report_label="Backtest base",
	report_symbol="PAXG-USD",
)
stats

mejores_stats, heatmap = optimizar_rsi_oro(historico)
```

`preparar_ohlcv` acepta columnas normales o MultiIndex de `yfinance`. Para resultados comparables, separa entrenamiento y prueba antes de optimizar.

Cada llamada a `ejecutar_backtest_oro` que recibe `report_dir` crea un archivo HTML autocontenido cuyo nombre incluye la etiqueta del escenario, por ejemplo `informe_oro_backtest_base_*.html` o `informe_oro_evaluacion_fuera_de_muestra_*.html`, y actualiza `historial_ejecuciones.json`. El informe incluye métricas ejecutivas, curva de capital, operaciones, parámetros y un historial interactivo de ejecuciones. Las ejecuciones repetidas siempre crean una nueva versión; no sobrescriben informes anteriores.

También incorpora un diagnóstico automático: descripción del tipo de prueba, hallazgos clasificados como `CRITICA`, `ALTA` o `MEDIA`, problema observado, causa raíz, mejora propuesta y script/sección afectada. Para que el informe documente correctamente una separación entrenamiento/prueba, el llamador puede enviar contexto explícito:

```python
ejecutar_backtest_oro(
	datos_prueba,
	report_dir="informes_backtesting_oro",
	report_label="Evaluacion fuera de muestra",
	report_description="Parámetros elegidos en entrenamiento y aplicados al tramo de prueba.",
	report_context={"is_in_sample": False, "tipo": "fuera de muestra"},
	**parametros,
)
```

El diagnóstico señala, entre otros riesgos, muestras pequeñas, factor de beneficio inferior a 1, drawdown elevado, resultados dentro de muestra, uso de `PAXG-USD` como proxy y la ausencia de slippage/spread variable. A partir de esos hallazgos también se genera un prompt parametrizado en `informe_oro_*.prompt.txt` y se incluye en el HTML para corregir `proyecciones_oro.ipynb` con las métricas y parámetros reales de la ejecución.

## Pipeline institucional completo (CLI)

`python backtesting_oro.py` ya no corre solo un backtest simple: por defecto ejecuta el mismo
protocolo de `proyecciones_oro.ipynb` — diagnóstico dentro de muestra, separación
entrenamiento/validación/prueba (60/20/20, sin solape) con calentamiento del RSI, walk-forward
de 4 folds, chequeo por régimen, sensibilidad de SL/TP y de costes sobre validación, y una
prueba final fuera de muestra de única lectura — usando `GoldRSIRiskManagedStrategy` (tamaño de
posición por riesgo fijo + freno por drawdown). Genera dos informes HTML:
`informe_oro_backtest_base_diagnostico_dentro_de_muestra_*.html` y
`informe_oro_evaluacion_fuera_de_muestra_test_final_unica_lectura_*.html`.

```bash
python backtesting_oro.py --symbol PAXG-USD --period 2y --interval 1d --n-folds 4
python backtesting_oro.py --simple   # comportamiento anterior: un solo backtest directo
```

Cada paso del pipeline también está disponible por separado para uso programático:
`separar_train_val_test`, `con_calentamiento`, `caminar_hacia_adelante`, `chequear_regimenes`,
`sensibilidad_sl_tp`, `sensibilidad_costes`, y el orquestador `ejecutar_pipeline_completo_oro`.
El notebook mantiene su propia copia narrada celda a celda (con la misma lógica) para explicar
cada paso con markdown; el módulo es ahora la fuente de verdad reusable del mismo protocolo,
ejecutable también fuera de Jupyter.

## Interpretación experta

Cada informe HTML incluye ahora una sección "Interpretación experta": un párrafo por métrica
relevante (factor de beneficio, comparación contra Buy & Hold, tamaño de muestra, drawdown,
si es dentro/fuera de muestra) generado por `generar_interpretacion_experta`, de forma
**determinista y basada en reglas** — mismo backtest, mismo texto siempre, sin llamadas
externas ni costo. No participa en el cálculo del backtest: solo describe resultados ya
calculados.

Opcionalmente, con `--usar-ia-generativa` (o `usar_ia_generativa=True` en las funciones
`ejecutar_backtest_oro`/`ejecutar_pipeline_completo_oro`), el informe intenta además un párrafo
adicional generado por un modelo (`interpretar_con_ia_generativa`). Requiere instalar el
paquete `anthropic` (no incluido en `requirements.txt` por ser opcional) y definir
`ANTHROPIC_API_KEY` en el entorno o `.env`. Si falta el paquete, la key, o falla la llamada, se
omite en silencio y el informe usa solo la interpretación determinista — nunca rompe la
generación del reporte ni altera los números del backtest.
