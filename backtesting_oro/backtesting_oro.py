"""Backtesting reproducible para oro usando DataFrames OHLCV del notebook.

El modulo no abre conexiones a MetaTrader 5: recibe datos ya descargados
(por ejemplo, desde yfinance con el ticker PAXG-USD).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from html import escape
import argparse
import json
import os
import warnings
from pathlib import Path
import re

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy


_REQUIRED_COLUMNS = ("Open", "High", "Low", "Close")


def preparar_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    """Normaliza datos de yfinance al formato esperado por backtesting.py."""
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data debe ser un pandas.DataFrame")

    frame = data.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    frame.columns = [str(column).strip().lower() for column in frame.columns]
    renombradas = {column: column.capitalize() for column in frame.columns}
    frame = frame.rename(columns=renombradas)

    faltantes = [column for column in _REQUIRED_COLUMNS if column not in frame]
    if faltantes:
        raise ValueError(f"Faltan columnas OHLC: {', '.join(faltantes)}")

    if "Volume" not in frame:
        frame["Volume"] = 0

    frame.index = pd.to_datetime(frame.index)
    frame = frame.sort_index()
    frame = frame.loc[:, ["Open", "High", "Low", "Close", "Volume"]]
    return frame.apply(pd.to_numeric, errors="coerce").dropna()


def _rsi(close: Iterable[float], period: int) -> np.ndarray:
    """RSI de Wilder, devuelto como ndarray para self.I."""
    prices = pd.Series(np.asarray(close, dtype=float))
    delta = prices.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    average_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative_strength))
    result = result.where(average_loss != 0, 100.0)
    return result.to_numpy()


class GoldRSIStrategy(Strategy):
    """Estrategia RSI con una sola posición y SL/TP porcentuales."""

    rsi_period = 14
    upper_level = 70
    lower_level = 30
    sl_pct = 0.01
    tp_pct = 0.02

    def init(self):
        self.rsi = self.I(_rsi, self.data.Close, self.rsi_period, name="RSI")

    def next(self):
        current_rsi = self.rsi[-1]
        current_close = self.data.Close[-1]
        if np.isnan(current_rsi):
            return

        if self.position.is_long and current_rsi >= self.upper_level:
            self.position.close()
        elif self.position.is_short and current_rsi <= self.lower_level:
            self.position.close()

        if self.position:
            return

        if current_rsi <= self.lower_level:
            self.buy(
                sl=current_close * (1 - self.sl_pct),
                tp=current_close * (1 + self.tp_pct),
            )
        elif current_rsi >= self.upper_level:
            self.sell(
                sl=current_close * (1 + self.sl_pct),
                tp=current_close * (1 - self.tp_pct),
            )


class GoldRSIRiskManagedStrategy(GoldRSIStrategy):
    """GoldRSIStrategy + tamaño de posición por riesgo fijo + freno por drawdown.

    Portada desde proyecciones_oro.ipynb (donde vivía como subclase local) para que el
    pipeline institucional completo (ver ``ejecutar_pipeline_completo_oro``) pueda
    ejecutarse también fuera del notebook, p. ej. con ``python backtesting_oro.py``.
    """

    riesgo_pct = 0.005          # riesgo maximo por operacion, como fraccion del equity
    frenar_drawdown_pct = 0.15  # deja de abrir operaciones si el drawdown acumulado supera esto

    def init(self):
        super().init()
        self._equity_maxima = self.equity

    def next(self):
        self._equity_maxima = max(self._equity_maxima, self.equity)
        drawdown_actual = 1 - (self.equity / self._equity_maxima)

        current_rsi = self.rsi[-1]
        current_close = self.data.Close[-1]
        if np.isnan(current_rsi):
            return

        if self.position.is_long and current_rsi >= self.upper_level:
            self.position.close()
        elif self.position.is_short and current_rsi <= self.lower_level:
            self.position.close()

        if self.position:
            return

        if drawdown_actual >= self.frenar_drawdown_pct:
            return

        tamano = max(0.01, min(0.9999, self.riesgo_pct / self.sl_pct))

        if current_rsi <= self.lower_level:
            self.buy(size=tamano, sl=current_close * (1 - self.sl_pct), tp=current_close * (1 + self.tp_pct))
        elif current_rsi >= self.upper_level:
            self.sell(size=tamano, sl=current_close * (1 + self.sl_pct), tp=current_close * (1 - self.tp_pct))


def ejecutar_backtest_oro(
    data: pd.DataFrame,
    *,
    cash: float = 10_000,
    commission: float = 0.0004,
    strategy: type[Strategy] = GoldRSIStrategy,
    report_dir: str | Path | None = None,
    report_label: str = "Backtest de oro",
    report_symbol: str = "PAXG-USD",
    report_description: str | None = None,
    report_context: Mapping[str, object] | None = None,
    usar_ia_generativa: bool = False,
    anthropic_api_key: str | None = None,
    **strategy_parameters,
):
    """Ejecuta un backtest y devuelve ``(backtest, estadisticas)``.

    Si ``report_dir`` tiene valor, también guarda un informe HTML ejecutivo
    y actualiza el historial de ejecuciones de esa carpeta. ``usar_ia_generativa``
    y ``anthropic_api_key`` son opcionales y solo afectan el texto de interpretación
    del informe (ver ``generar_interpretacion_experta``); nunca alteran los cálculos
    del backtest ni sus métricas.
    """
    frame = preparar_ohlcv(data)
    if len(frame) < 30:
        raise ValueError("Se necesitan al menos 30 velas para ejecutar el backtest")

    backtest = Backtest(
        frame,
        strategy,
        cash=cash,
        commission=commission,
        exclusive_orders=True,
        finalize_trades=True,
    )
    stats = backtest.run(**strategy_parameters)
    if report_dir is not None:
        generar_informe_html(
            backtest,
            stats,
            output_dir=report_dir,
            label=report_label,
            symbol=report_symbol,
            strategy_parameters=strategy_parameters,
            description=report_description,
            report_context=report_context,
            usar_ia_generativa=usar_ia_generativa,
            anthropic_api_key=anthropic_api_key,
        )
    return backtest, stats


def optimizar_rsi_oro(
    data: pd.DataFrame,
    *,
    rsi_periods: Iterable[int] = (7, 14, 21),
    upper_levels: Iterable[int] = (65, 70, 75),
    lower_levels: Iterable[int] = (25, 30, 35),
    maximize: str = "Return [%]",
    cash: float = 10_000,
    commission: float = 0.0004,
):
    """Busca parámetros RSI y devuelve ``(mejores_stats, heatmap)``."""
    frame = preparar_ohlcv(data)
    backtest = Backtest(
        frame,
        GoldRSIStrategy,
        cash=cash,
        commission=commission,
        exclusive_orders=True,
        finalize_trades=True,
    )
    return backtest.optimize(
        rsi_period=list(rsi_periods),
        upper_level=list(upper_levels),
        lower_level=list(lower_levels),
        maximize=maximize,
        return_heatmap=True,
    )


def evaluar_periodos(
    periodos: Mapping[str, pd.DataFrame],
    *,
    cash: float = 10_000,
    commission: float = 0.0004,
    **strategy_parameters,
) -> pd.DataFrame:
    """Ejecuta el mismo conjunto de parámetros sobre varios períodos."""
    rows = []
    for nombre, data in periodos.items():
        _, stats = ejecutar_backtest_oro(
            data,
            cash=cash,
            commission=commission,
            **strategy_parameters,
        )
        rows.append(
            {
                "periodo": nombre,
                "retorno_pct": stats["Return [%]"],
                "win_rate_pct": stats["Win Rate [%]"],
                "profit_factor": stats["Profit Factor"],
                "max_drawdown_pct": stats["Max. Drawdown [%]"],
                "trades": stats["# Trades"],
            }
        )
    return pd.DataFrame(rows).set_index("periodo")


# ---------------------------------------------------------------------------
# Pipeline institucional completo: separacion train/val/test con calentamiento
# del indicador, walk-forward, chequeo por regimen, sensibilidad de SL/TP y de
# costes, y prueba final fuera de muestra. Portado desde proyecciones_oro.ipynb
# (donde vivia repartido en varias celdas) para que sea reproducible tambien
# como script independiente via `python backtesting_oro.py`, y no solo dentro
# del notebook. El notebook puede seguir usando su propia copia narrada celda a
# celda; esta version es la fuente de verdad reusable del mismo protocolo.
# ---------------------------------------------------------------------------

REJILLA_RSI_DEFAULT: Mapping[str, list[int]] = {
    "rsi_period": [7, 14, 21],
    "upper_level": [65, 70, 75],
    "lower_level": [25, 30, 35],
}

ESCENARIOS_COSTO_DEFAULT: Mapping[str, float] = {
    "solo_comision_broker_0.04pct": 0.0004,
    "spread_moderado_0.10pct": 0.0010,
    "spread_slippage_adversos_0.25pct": 0.0025,
    "estres_0.50pct": 0.0050,
}


def con_calentamiento(
    datos_completos: pd.DataFrame, ini_oficial_idx: int, fin_oficial_idx: int, barras: int = 30
) -> pd.DataFrame:
    """Extiende ``[ini_oficial_idx, fin_oficial_idx)`` hacia atras con barras que YA
    ocurrieron antes del inicio oficial (nunca datos futuros ni del propio tramo), para
    que un indicador con ventana movil (ej. RSI con ``min_periods=rsi_period``) tenga
    valor valido desde la primera vela oficial del tramo, en vez de perder sus primeras
    velas por el NaN inicial del indicador. No cambia los limites oficiales de fecha.
    """
    ini_extendido = max(0, ini_oficial_idx - barras)
    return datos_completos.iloc[ini_extendido:fin_oficial_idx]


def separar_train_val_test(
    data: pd.DataFrame,
    *,
    frac_train: float = 0.60,
    frac_val: float = 0.80,
    barras_calentamiento: int = 30,
    imprimir: bool = True,
) -> dict:
    """Separa cronologicamente en entrenamiento/validacion/prueba, sin mezclar, y agrega
    copias con calentamiento del indicador (``validacion_bt``/``prueba_bt``) listas para
    pasarle al motor de backtest. Lanza ``AssertionError`` si los tramos se solapan."""
    frame = preparar_ohlcv(data)
    n_barras = len(frame)
    fin_entrenamiento = int(n_barras * frac_train)
    fin_validacion = int(n_barras * frac_val)

    entrenamiento = frame.iloc[:fin_entrenamiento]
    validacion = frame.iloc[fin_entrenamiento:fin_validacion]
    prueba = frame.iloc[fin_validacion:]

    assert entrenamiento.index[-1] < validacion.index[0] < prueba.index[0], (
        "los tramos deben quedar en orden cronologico y sin solape"
    )

    validacion_bt = con_calentamiento(frame, fin_entrenamiento, fin_validacion, barras_calentamiento)
    prueba_bt = con_calentamiento(frame, fin_validacion, n_barras, barras_calentamiento)

    if imprimir:
        for nombre, tramo in [
            ("Entrenamiento", entrenamiento),
            ("Validacion", validacion),
            ("Prueba (fuera de muestra)", prueba),
        ]:
            print(f"{nombre:<28} {len(tramo):>4} velas | {tramo.index[0].date()} -> {tramo.index[-1].date()}")
        print("OK: los 3 tramos son cronologicos y no se solapan.")
        print(
            f"Calentamiento del indicador: hasta {barras_calentamiento} velas previas (ya pasadas) "
            f"antes de validacion y prueba para ejecutar el backtest."
        )

    return {
        "n_barras": n_barras,
        "fin_entrenamiento": fin_entrenamiento,
        "fin_validacion": fin_validacion,
        "entrenamiento": entrenamiento,
        "validacion": validacion,
        "prueba": prueba,
        "validacion_bt": validacion_bt,
        "prueba_bt": prueba_bt,
    }


def optimizar_en_ventana(
    data: pd.DataFrame,
    *,
    strategy: type[Strategy] = GoldRSIRiskManagedStrategy,
    cash: float = 100_000,
    commission: float = 0.0004,
    maximize: str = "SQN",
    **rejilla,
):
    """Grid search dentro de UNA ventana de datos, con la estrategia con gestion de riesgo."""
    frame = preparar_ohlcv(data)
    backtest = Backtest(
        frame, strategy, cash=cash, commission=commission, exclusive_orders=True, finalize_trades=True,
    )
    return backtest.optimize(maximize=maximize, return_heatmap=True, **rejilla)


def caminar_hacia_adelante(
    datos_entrenamiento: pd.DataFrame,
    *,
    n_folds: int = 4,
    rejilla_rsi: Mapping[str, list[int]] | None = None,
    strategy: type[Strategy] = GoldRSIRiskManagedStrategy,
    cash: float = 100_000,
    commission: float = 0.0004,
) -> tuple[pd.DataFrame, dict]:
    """Validacion walk-forward (ventana expansiva) SOLO dentro de entrenamiento: cada fold
    optimiza con su propio pasado y se evalua en el tramo siguiente, nunca antes visto.
    Devuelve ``(tabla_walk_forward, parametros_candidatos)`` — los candidatos vienen del
    ultimo fold (el mas cercano en el tiempo a validacion)."""
    rejilla_rsi = dict(rejilla_rsi or REJILLA_RSI_DEFAULT)
    n_train = len(datos_entrenamiento)
    segmento = n_train // (n_folds + 1)
    limites = [segmento * i for i in range(1, n_folds + 2)]
    limites[-1] = n_train

    filas, parametros_por_fold = [], []
    for fold in range(n_folds):
        fold_train = datos_entrenamiento.iloc[:limites[fold]]
        fold_prueba = datos_entrenamiento.iloc[limites[fold]:limites[fold + 1]]
        if len(fold_train) < 60 or len(fold_prueba) < 10:
            continue
        fold_prueba_bt = con_calentamiento(datos_entrenamiento, limites[fold], limites[fold + 1])
        mejores_stats, _ = optimizar_en_ventana(fold_train, strategy=strategy, cash=cash, commission=commission, **rejilla_rsi)
        parametros_fold = {
            "rsi_period": int(mejores_stats._strategy.rsi_period),
            "upper_level": int(mejores_stats._strategy.upper_level),
            "lower_level": int(mejores_stats._strategy.lower_level),
        }
        parametros_por_fold.append(parametros_fold)
        _, stats_oos = ejecutar_backtest_oro(
            fold_prueba_bt, cash=cash, commission=commission, strategy=strategy, **parametros_fold,
        )
        filas.append({
            "fold": fold + 1,
            "velas_entrenamiento": len(fold_train),
            "velas_prueba_oos": len(fold_prueba),
            **parametros_fold,
            "retorno_pct": stats_oos["Return [%]"],
            "buy_hold_pct": stats_oos["Buy & Hold Return [%]"],
            "win_rate_pct": stats_oos["Win Rate [%]"],
            "profit_factor": stats_oos["Profit Factor"],
            "max_drawdown_pct": stats_oos["Max. Drawdown [%]"],
            "trades": stats_oos["# Trades"],
        })

    tabla = pd.DataFrame(filas)
    parametros_candidatos = parametros_por_fold[-1] if parametros_por_fold else {
        "rsi_period": 14, "upper_level": 70, "lower_level": 30,
    }
    return tabla, parametros_candidatos


def chequear_regimenes(
    data: pd.DataFrame,
    fin_entrenamiento: int,
    *,
    n_bloques: int = 3,
    strategy: type[Strategy] = GoldRSIRiskManagedStrategy,
    cash: float = 100_000,
    commission: float = 0.0004,
    **parametros,
) -> pd.DataFrame:
    """Aplica parametros fijos (sin reoptimizar) a ``n_bloques`` calendario dentro de
    entrenamiento, para chequear que el comportamiento no dependa de un solo sub-periodo."""
    frame = preparar_ohlcv(data)
    n_regimen = fin_entrenamiento // n_bloques
    periodos = {}
    for i in range(n_bloques):
        ini = i * n_regimen
        fin = fin_entrenamiento if i == n_bloques - 1 else (i + 1) * n_regimen
        sufijo = "_mas_antiguo" if i == 0 else "_mas_reciente" if i == n_bloques - 1 else ""
        nombre = f"regimen_{i + 1}{sufijo}"
        # regimen_1 empieza en la posicion 0 del historico: no hay barras previas de donde
        # tomar calentamiento, asi que conserva su perdida natural de arranque.
        periodos[nombre] = frame.iloc[ini:fin] if i == 0 else con_calentamiento(frame, ini, fin)
    return evaluar_periodos(periodos, cash=cash, commission=commission, strategy=strategy, **parametros)


def sensibilidad_sl_tp(
    datos_validacion_bt: pd.DataFrame,
    *,
    strategy: type[Strategy] = GoldRSIRiskManagedStrategy,
    cash: float = 100_000,
    commission: float = 0.0004,
    sl_grid: Iterable[float] = (0.005, 0.01, 0.015, 0.02),
    tp_grid: Iterable[float] = (0.01, 0.02, 0.03),
    min_trades: int = 5,
    **parametros_candidatos,
) -> tuple[pd.DataFrame, dict, pd.Series]:
    """Un solo vistazo a validacion: corre los parametros candidatos tal cual, y hace un
    grid de SL/TP sobre el mismo tramo para fijarlos ANTES de tocar el tramo de prueba.
    Devuelve ``(tabla_sl_tp, parametros_finales, stats_validacion)``."""
    _, stats_validacion = ejecutar_backtest_oro(
        datos_validacion_bt, cash=cash, commission=commission, strategy=strategy, **parametros_candidatos,
    )

    filas = []
    for sl_pct in sl_grid:
        for tp_pct in tp_grid:
            _, stats = ejecutar_backtest_oro(
                datos_validacion_bt, cash=cash, commission=commission, strategy=strategy,
                sl_pct=sl_pct, tp_pct=tp_pct, **parametros_candidatos,
            )
            filas.append({
                "sl_pct": sl_pct, "tp_pct": tp_pct,
                "retorno_pct": stats["Return [%]"], "profit_factor": stats["Profit Factor"],
                "max_drawdown_pct": stats["Max. Drawdown [%]"], "trades": stats["# Trades"],
            })
    tabla = pd.DataFrame(filas)
    candidatos = tabla[tabla["trades"] >= min_trades]
    if candidatos.empty:
        candidatos = tabla
    mejor = candidatos.sort_values(["profit_factor", "max_drawdown_pct"], ascending=[False, True]).iloc[0]
    parametros_finales = {
        **parametros_candidatos, "sl_pct": float(mejor["sl_pct"]), "tp_pct": float(mejor["tp_pct"]),
    }
    return tabla, parametros_finales, stats_validacion


def sensibilidad_costes(
    datos_validacion_bt: pd.DataFrame,
    *,
    strategy: type[Strategy] = GoldRSIRiskManagedStrategy,
    cash: float = 100_000,
    escenarios: Mapping[str, float] | None = None,
    escenario_elegido: str = "spread_moderado_0.10pct",
    **parametros_finales,
) -> tuple[pd.DataFrame, float]:
    """Sensibilidad de coste total (comision+spread+slippage estimados) sobre VALIDACION.
    El escenario final se elige por nombre (a priori), nunca por el que de mejor resultado."""
    escenarios = dict(escenarios or ESCENARIOS_COSTO_DEFAULT)
    filas = []
    for nombre, comision in escenarios.items():
        _, stats = ejecutar_backtest_oro(
            datos_validacion_bt, cash=cash, commission=comision, strategy=strategy, **parametros_finales,
        )
        filas.append({
            "escenario": nombre, "comision_total_pct": comision * 100,
            "retorno_pct": stats["Return [%]"], "profit_factor": stats["Profit Factor"],
            "max_drawdown_pct": stats["Max. Drawdown [%]"], "trades": stats["# Trades"],
        })
    tabla = pd.DataFrame(filas).set_index("escenario")
    comision_final = escenarios[escenario_elegido]
    return tabla, comision_final


def ejecutar_pipeline_completo_oro(
    data: pd.DataFrame,
    *,
    symbol: str = "PAXG-USD",
    report_dir: str | Path = "informes_backtesting_oro",
    cash_diagnostico: float = 10_000,
    cash_pipeline: float = 100_000,
    n_folds: int = 4,
    rejilla_rsi: Mapping[str, list[int]] | None = None,
    escenario_costo: str = "spread_moderado_0.10pct",
    strategy: type[Strategy] = GoldRSIRiskManagedStrategy,
    usar_ia_generativa: bool = False,
    anthropic_api_key: str | None = None,
    imprimir: bool = True,
) -> dict:
    """Corre el protocolo institucional completo — diagnostico dentro de muestra, split
    cronologico con calentamiento del indicador, walk-forward, chequeo por regimen,
    validacion con sensibilidad de SL/TP, sensibilidad de costes y prueba final fuera de
    muestra (unica lectura) — y genera los dos informes HTML principales:
    ``Backtest base (diagnostico dentro de muestra)`` y ``Evaluacion fuera de muestra
    (test final, unica lectura)``. Es el mismo protocolo de ``proyecciones_oro.ipynb``
    empaquetado aqui para poder ejecutarlo tambien fuera del notebook, p. ej. con
    ``python backtesting_oro.py``. No requiere credenciales ni conexion a un broker: solo
    recibe un DataFrame OHLCV ya descargado.
    """
    frame = preparar_ohlcv(data)

    def _log(*args):
        if imprimir:
            print(*args)

    _log(f"Velas disponibles: {len(frame)}")
    _, resultados_diagnostico = ejecutar_backtest_oro(
        frame, cash=cash_diagnostico, commission=0.0004, report_dir=report_dir,
        report_label="Backtest base (diagnostico dentro de muestra)", report_symbol=symbol,
        report_description="Diagnostico dentro de muestra: solo referencia historica, no se usa para elegir parametros.",
        report_context={"is_in_sample": True, "tipo": "dentro de muestra"},
        usar_ia_generativa=usar_ia_generativa, anthropic_api_key=anthropic_api_key,
    )
    _log("\nDiagnostico dentro de muestra (estrategia original, sin gestion de riesgo, todo el historico):")
    _log(resultados_diagnostico[[
        "Return [%]", "Buy & Hold Return [%]", "Win Rate [%]", "Profit Factor", "Max. Drawdown [%]", "# Trades",
    ]])

    tramos = separar_train_val_test(frame, imprimir=imprimir)

    _log("\nWalk-forward (cada fold optimiza solo con su pasado y se evalua en el tramo siguiente):")
    tabla_walk_forward, parametros_candidatos = caminar_hacia_adelante(
        tramos["entrenamiento"], n_folds=n_folds, rejilla_rsi=rejilla_rsi, strategy=strategy, cash=cash_pipeline,
    )
    _log(tabla_walk_forward)
    _log("Parametros candidatos (del ultimo fold):", parametros_candidatos)

    _log("\nChequeo por regimen (parametros candidatos fijos, sin reoptimizar):")
    tabla_regimenes = chequear_regimenes(
        frame, tramos["fin_entrenamiento"], strategy=strategy, cash=cash_pipeline, **parametros_candidatos,
    )
    _log(tabla_regimenes)

    _log("\nValidacion + sensibilidad de SL/TP (un solo vistazo, nunca sobre el tramo de prueba):")
    tabla_sl_tp, parametros_finales, stats_validacion = sensibilidad_sl_tp(
        tramos["validacion_bt"], strategy=strategy, cash=cash_pipeline, **parametros_candidatos,
    )
    _log(tabla_sl_tp)
    _log("Parametros finales (fijados antes de mirar el tramo de prueba):", parametros_finales)

    _log("\nSensibilidad de costes sobre VALIDACION:")
    tabla_costes, comision_final = sensibilidad_costes(
        tramos["validacion_bt"], strategy=strategy, cash=cash_pipeline,
        escenario_elegido=escenario_costo, **parametros_finales,
    )
    _log(tabla_costes)
    _log(f"Comision elegida para la prueba final: {comision_final * 100:.2f}%")

    _log("\nPRUEBA FUERA DE MUESTRA FINAL (unica lectura del tramo de prueba):")
    _, resultados_prueba_final = ejecutar_backtest_oro(
        tramos["prueba_bt"], cash=cash_pipeline, commission=comision_final, strategy=strategy,
        report_dir=report_dir,
        report_label="Evaluacion fuera de muestra (test final, unica lectura)", report_symbol=symbol,
        report_description=(
            "Parametros de RSI (walk-forward), SL/TP y coste (sensibilidad en validacion) fijados "
            "antes de esta lectura; unica evaluacion del tramo de prueba. Incluye calentamiento del "
            "indicador con barras previas a la prueba oficial."
        ),
        report_context={"is_in_sample": False, "tipo": "fuera de muestra"},
        usar_ia_generativa=usar_ia_generativa, anthropic_api_key=anthropic_api_key,
        **parametros_finales,
    )
    _log(resultados_prueba_final[[
        "Return [%]", "Buy & Hold Return [%]", "Win Rate [%]", "Profit Factor", "Max. Drawdown [%]", "# Trades",
    ]])

    tabla_comparativa = pd.DataFrame({
        "Diagnostico dentro de muestra (todo el historico)": {
            "retorno_pct": resultados_diagnostico["Return [%]"],
            "buy_hold_pct": resultados_diagnostico["Buy & Hold Return [%]"],
            "win_rate_pct": resultados_diagnostico["Win Rate [%]"],
            "profit_factor": resultados_diagnostico["Profit Factor"],
            "max_drawdown_pct": resultados_diagnostico["Max. Drawdown [%]"],
            "trades": resultados_diagnostico["# Trades"],
        },
        "Walk-forward (mediana de folds, con gestion de riesgo)": {
            "retorno_pct": tabla_walk_forward["retorno_pct"].median() if not tabla_walk_forward.empty else float("nan"),
            "buy_hold_pct": tabla_walk_forward["buy_hold_pct"].median() if not tabla_walk_forward.empty else float("nan"),
            "win_rate_pct": tabla_walk_forward["win_rate_pct"].median() if not tabla_walk_forward.empty else float("nan"),
            "profit_factor": tabla_walk_forward["profit_factor"].median() if not tabla_walk_forward.empty else float("nan"),
            "max_drawdown_pct": tabla_walk_forward["max_drawdown_pct"].median() if not tabla_walk_forward.empty else float("nan"),
            "trades": tabla_walk_forward["trades"].sum() if not tabla_walk_forward.empty else 0,
        },
        "Validacion (un solo vistazo, con gestion de riesgo)": {
            "retorno_pct": stats_validacion["Return [%]"],
            "buy_hold_pct": stats_validacion["Buy & Hold Return [%]"],
            "win_rate_pct": stats_validacion["Win Rate [%]"],
            "profit_factor": stats_validacion["Profit Factor"],
            "max_drawdown_pct": stats_validacion["Max. Drawdown [%]"],
            "trades": stats_validacion["# Trades"],
        },
        "Prueba fuera de muestra FINAL (unica lectura)": {
            "retorno_pct": resultados_prueba_final["Return [%]"],
            "buy_hold_pct": resultados_prueba_final["Buy & Hold Return [%]"],
            "win_rate_pct": resultados_prueba_final["Win Rate [%]"],
            "profit_factor": resultados_prueba_final["Profit Factor"],
            "max_drawdown_pct": resultados_prueba_final["Max. Drawdown [%]"],
            "trades": resultados_prueba_final["# Trades"],
        },
    }).T
    _log("\nComparativa final (retorno, Buy & Hold, win rate, profit factor, drawdown, operaciones):")
    _log(tabla_comparativa)

    return {
        "resultados_diagnostico": resultados_diagnostico,
        "tramos": tramos,
        "tabla_walk_forward": tabla_walk_forward,
        "parametros_candidatos": parametros_candidatos,
        "tabla_regimenes": tabla_regimenes,
        "tabla_sl_tp": tabla_sl_tp,
        "parametros_finales": parametros_finales,
        "stats_validacion": stats_validacion,
        "tabla_costes": tabla_costes,
        "comision_final": comision_final,
        "resultados_prueba_final": resultados_prueba_final,
        "tabla_comparativa": tabla_comparativa,
    }


def _json_value(value):
    if isinstance(value, (pd.Timestamp, pd.Timedelta, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if pd.isna(value):
        return None
    return value


def _records_from_frame(frame: pd.DataFrame | None, limit: int | None = None):
    if frame is None or frame.empty:
        return []
    selected = frame.tail(limit) if limit else frame
    records = []
    for index, row in selected.iterrows():
        record = {"Fecha": _json_value(index)}
        record.update({str(key): _json_value(value) for key, value in row.items()})
        records.append(record)
    return records


def _metric_payload(stats: pd.Series):
    labels = {
        "Return [%]": "Retorno",
        "Buy & Hold Return [%]": "Comprar y mantener",
        "Win Rate [%]": "Tasa de acierto",
        "Profit Factor": "Factor de beneficio",
        "Sharpe Ratio": "Ratio de Sharpe",
        "Max. Drawdown [%]": "Drawdown máximo",
        "# Trades": "Operaciones",
        "Exposure Time [%]": "Exposición",
    }
    return [
        {"key": key, "label": label, "value": _json_value(stats.get(key))}
        for key, label in labels.items()
        if key in stats
    ]


def _diagnostic_findings(
    stats: pd.Series,
    *,
    label: str,
    symbol: str,
    n_bars: int,
    report_context: Mapping[str, object] | None = None,
):
    """Construye hallazgos accionables y conserva el origen del problema."""
    context = dict(report_context or {})
    findings = []

    def add(severity, title, problem, root_cause, improvement, scripts):
        findings.append({
            "severity": severity,
            "title": title,
            "problem": problem,
            "root_cause": root_cause,
            "improvement": improvement,
            "scripts": scripts,
        })

    trades = stats.get("# Trades")
    return_pct = stats.get("Return [%]")
    profit_factor = stats.get("Profit Factor")
    drawdown = stats.get("Max. Drawdown [%]")

    if not trades or trades < 1:
        add(
            "CRITICA", "Sin operaciones ejecutadas",
            "La muestra no contiene trades; el retorno no permite evaluar la estrategia.",
            "La combinación de RSI, umbrales y periodo no produjo señales operables.",
            "Ampliar la muestra o revisar los umbrales; no usar este resultado para validar la estrategia.",
            "backtesting_oro/backtesting_oro.py · GoldRSIStrategy.next",
        )
    elif trades < 30:
        add(
            "ALTA", "Muestra estadística pequeña",
            f"Solo se ejecutaron {int(trades)} operaciones; la estimación de rendimiento es inestable.",
            "El periodo o la frecuencia evaluada no contiene suficientes eventos independientes.",
            "Usar más histórico y exigir un mínimo de operaciones antes de comparar parámetros.",
            "proyecciones_oro.ipynb · celda 'Backtesting reproducible de oro'",
        )

    if profit_factor is not None and pd.notna(profit_factor) and profit_factor < 1:
        add(
            "CRITICA", "Ventaja estadística negativa",
            f"El factor de beneficio es {float(profit_factor):.2f}, inferior a 1.",
            "Las pérdidas brutas superan a las ganancias brutas en esta muestra.",
            "Revisar reglas RSI, costes y niveles SL/TP; confirmar en una prueba fuera de muestra antes de optimizar.",
            "backtesting_oro/backtesting_oro.py · GoldRSIStrategy.next",
        )

    if drawdown is not None and pd.notna(drawdown) and drawdown <= -20:
        add(
            "ALTA", "Drawdown máximo elevado",
            f"El drawdown máximo alcanza {float(drawdown):.2f}%.",
            "El riesgo fijo por operación y la secuencia de pérdidas permiten una caída de capital relevante.",
            "Añadir position sizing por riesgo, límite de pérdida diaria y validación de sensibilidad del SL.",
            "backtesting_oro/backtesting_oro.py · ejecutar_backtest_oro",
        )

    if context.get("is_in_sample"):
        add(
            "ALTA", "Resultado dentro de muestra",
            "Este informe usa datos que también se emplean para seleccionar o revisar parámetros.",
            "El backtest base se ejecuta sobre todo el histórico antes de separar entrenamiento y prueba.",
            "Reservar el tramo de prueba antes de mirar resultados y reportar el fuera de muestra como referencia principal.",
            "proyecciones_oro.ipynb · celda 'Backtesting reproducible de oro'",
        )

    add(
        "MEDIA", "Proxy de oro",
        f"El símbolo evaluado es {symbol}, un proxy tokenizado y no una cotización directa XAU/USD.",
        "El notebook usa PAXG-USD porque es el ticker disponible en yfinance para esta fuente.",
        "Comparar con una fuente spot/futuros del instrumento operativo e incorporar spread, slippage y horarios reales.",
        "proyecciones_oro.ipynb · ORO_TICKER; backtesting_oro/backtesting_oro.py · report_symbol",
    )

    add(
        "MEDIA", "Modelo de ejecución simplificado",
        "El resultado se calcula con velas OHLC y comisión, pero no modela explícitamente slippage ni spread.",
        "La estrategia GoldRSIStrategy usa entradas y SL/TP porcentuales sin una fuente de costes de ejecución variable.",
        "Añadir slippage por operación, spread, latencia y pruebas de sensibilidad para evitar una rentabilidad optimista.",
        "backtesting_oro/backtesting_oro.py · GoldRSIStrategy.next",
    )

    if n_bars < 200:
        add(
            "MEDIA", "Histórico limitado",
            f"La ejecución solo contiene {n_bars} velas.",
            "La ventana histórica es corta para evaluar distintos regímenes de tendencia y volatilidad.",
            "Usar un histórico más largo y separar por regímenes o realizar validación walk-forward.",
            "proyecciones_oro.ipynb · yf.download(period='2y', interval='1d')",
        )

    return findings


def generar_interpretacion_experta(
    stats: pd.Series,
    findings: list[dict[str, object]],
    *,
    is_in_sample: bool,
) -> list[str]:
    """Capa de razonamiento experto: convierte metricas + hallazgos en una interpretacion
    en lenguaje natural, correlacionando varias metricas a la vez (no solo listandolas).

    Es deliberadamente determinista y basada en reglas (sin llamadas externas ni
    aleatoriedad): dado el mismo backtest, siempre produce el mismo texto. Esto es a
    proposito — un informe de backtesting debe ser reproducible y auditable, y esta capa
    solo DESCRIBE resultados ya calculados; nunca participa en el calculo ni los altera.
    Para un enriquecimiento adicional (opcional) con un modelo generativo real, ver
    ``interpretar_con_ia_generativa``.
    """
    retorno = stats.get("Return [%]")
    buy_hold = stats.get("Buy & Hold Return [%]")
    profit_factor = stats.get("Profit Factor")
    drawdown = stats.get("Max. Drawdown [%]")
    trades = stats.get("# Trades")

    severidad_max = "OK"
    orden = {"OK": 0, "MEDIA": 1, "ALTA": 2, "CRITICA": 3}
    for hallazgo in findings:
        if orden.get(hallazgo["severity"], 0) > orden[severidad_max]:
            severidad_max = hallazgo["severity"]

    veredictos = {
        "CRITICA": "No apta para operar en real: hay al menos un hallazgo crítico sin resolver en esta ejecución.",
        "ALTA": "Requiere más validación antes de considerarla operable: quedan hallazgos de severidad alta.",
        "MEDIA": "Metodológicamente razonable, con limitaciones conocidas y ya documentadas.",
        "OK": "Sin hallazgos automáticos relevantes en esta ejecución.",
    }
    parrafos = [f"Veredicto automático: {veredictos[severidad_max]}"]

    if profit_factor is not None and pd.notna(profit_factor):
        if profit_factor < 1:
            parrafos.append(
                f"El factor de beneficio es {float(profit_factor):.2f}, por debajo del punto de "
                "equilibrio (1.0): en esta muestra, las pérdidas brutas superan a las ganancias "
                "brutas, incluso antes de comparar contra Buy & Hold."
            )
        else:
            parrafos.append(
                f"El factor de beneficio de {float(profit_factor):.2f} indica que las ganancias "
                "superan a las pérdidas en esta muestra — condición necesaria, aunque no "
                "suficiente por sí sola, para considerar la estrategia viable."
            )

    if retorno is not None and buy_hold is not None and pd.notna(retorno) and pd.notna(buy_hold):
        if retorno < buy_hold:
            parrafos.append(
                f"El retorno de la estrategia ({float(retorno):.2f}%) queda por debajo de Buy & "
                f"Hold ({float(buy_hold):.2f}%) en el mismo período: simplemente sostener el activo "
                "habría rendido más que operarlo con estas reglas."
            )
        else:
            parrafos.append(
                f"El retorno de la estrategia ({float(retorno):.2f}%) supera a Buy & Hold "
                f"({float(buy_hold):.2f}%) en el mismo período — favorable, aunque una sola ventana "
                "histórica no basta para atribuirlo a la estrategia y descartar el azar."
            )

    if trades is not None and pd.notna(trades):
        if trades < 30:
            parrafos.append(
                f"Con {int(trades)} operaciones, la muestra es pequeña: cualquier métrica (win rate, "
                "factor de beneficio, drawdown) puede moverse mucho con solo 2-3 operaciones de "
                "diferencia. Conviene leer estos números como una tendencia, no como una estimación "
                "precisa."
            )
        else:
            parrafos.append(
                f"Con {int(trades)} operaciones, la muestra ya permite leer las métricas con algo más "
                "de confianza, aunque sigue siendo corta para estándares institucionales (>100 "
                "operaciones)."
            )

    if drawdown is not None and pd.notna(drawdown):
        if drawdown <= -20:
            parrafos.append(
                f"El drawdown máximo ({float(drawdown):.2f}%) es elevado: una cuenta real habría "
                "visto caer su capital en esa proporción en algún punto de la muestra, antes de "
                "recuperarse (si llegó a recuperarse)."
            )
        else:
            parrafos.append(
                f"El drawdown máximo ({float(drawdown):.2f}%) se mantiene en un rango moderado para "
                "los parámetros de riesgo configurados en esta ejecución."
            )

    if is_in_sample:
        parrafos.append(
            "Esta lectura es DENTRO de muestra: los mismos datos pudieron influir en la elección de "
            "parámetros, por lo que tiende a ser optimista respecto al desempeño con dinero real. No "
            "debe usarse para decidir si operar la estrategia."
        )
    else:
        parrafos.append(
            "Esta lectura es FUERA de muestra: los parámetros se fijaron antes de ver estos datos, "
            "por lo que es la referencia más confiable de las disponibles en este sistema — aunque "
            "sigue siendo una sola muestra histórica, no una garantía de desempeño futuro."
        )

    return parrafos


def interpretar_con_ia_generativa(
    contexto: str,
    *,
    api_key: str | None = None,
    modelo: str = "claude-sonnet-5",
    max_tokens: int = 400,
) -> str | None:
    """Enriquecimiento OPCIONAL de la interpretación con un modelo generativo real.

    Apagado por defecto (nadie lo llama a menos que ``usar_ia_generativa=True`` en
    ``ejecutar_backtest_oro``/``ejecutar_pipeline_completo_oro``). Nunca participa en el
    cálculo de resultados: solo redacta un párrafo adicional a partir de métricas ya
    calculadas. Si falta la librería ``anthropic``, la API key, hay un error de red o de
    cuota, devuelve ``None`` en silencio y el informe usa solo la interpretación
    determinista de ``generar_interpretacion_experta`` — nunca rompe la generación del
    reporte por esta causa.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # dependencia opcional, no listada en requirements.txt
    except ImportError:
        return None
    try:
        cliente = anthropic.Anthropic(api_key=api_key)
        respuesta = cliente.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": contexto}],
        )
        return respuesta.content[0].text.strip()
    except Exception:
        return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "backtest"


def _build_correction_prompt(
    stats: pd.Series,
    *,
    label: str,
    symbol: str,
    n_bars: int,
    parameters: Mapping[str, object],
    findings: list[dict[str, object]],
):
    metrics = {
        "retorno_pct": _json_value(stats.get("Return [%]")),
        "win_rate_pct": _json_value(stats.get("Win Rate [%]")),
        "profit_factor": _json_value(stats.get("Profit Factor")),
        "drawdown_max_pct": _json_value(stats.get("Max. Drawdown [%]")),
        "operaciones": _json_value(stats.get("# Trades")),
    }
    hallazgos = "\n".join(
        f"- [{item['severity']}] {item['title']}: {item['problem']} "
        f"Causa raíz: {item['root_cause']} Mejora: {item['improvement']} "
        f"Área: {item['scripts']}"
        for item in findings
    )
    return f"""Actúa como ingeniero cuantitativo y modifica exclusivamente el notebook
`proyecciones_oro.ipynb` para corregir los problemas detectados en este backtest de oro.

CONTEXTO PARAMÉTRICO
- Informe: {label}
- Símbolo: {symbol}
- Velas analizadas: {n_bars}
    - Parámetros de estrategia: {json.dumps({str(key): _json_value(value) for key, value in parameters.items()}, ensure_ascii=False, sort_keys=True)}
- Métricas observadas: {json.dumps(metrics, ensure_ascii=False, sort_keys=True)}

HALLAZGOS PRIORIZADOS
{hallazgos or '- No se detectaron fallas automáticas.'}

REQUISITOS DE CORRECCIÓN
1. Inspecciona las celdas existentes antes de editar y conserva el objetivo del notebook.
2. Separa estrictamente entrenamiento, validación y prueba fuera de muestra antes de
   optimizar parámetros; evita reutilizar datos de prueba para decidir reglas.
3. Añade validación walk-forward o por regímenes cuando exista suficiente histórico.
4. Modela explícitamente comisión, spread y slippage, y ejecuta un análisis de sensibilidad.
5. Revisa la lógica de entrada, RSI, stop loss, take profit y el tamaño de posición; no
   ocultes operaciones ni elimines periodos perdedores para mejorar métricas.
6. Conserva una comparación clara contra Buy & Hold y reporta retorno, win rate, factor
   de beneficio, drawdown, número de operaciones y rentabilidad fuera de muestra.
7. Si `PAXG-USD` es solo un proxy, deja visible esa limitación y permite configurar la
   fuente/símbolo sin romper el flujo actual.
8. Genera un resumen final de cambios, celdas afectadas, causa raíz corregida y pruebas
   ejecutadas. No inventes resultados: si hace falta descargar datos o ejecutar celdas,
   indícalo explícitamente.

ENTREGA
Devuelve el notebook corregido y una tabla breve que relacione cada hallazgo con la
modificación concreta y la evidencia usada para verificarla."""


def generar_informe_html(
    backtest: Backtest,
    stats: pd.Series,
    *,
    output_dir: str | Path = "informes_backtesting_oro",
    label: str = "Backtest de oro",
    symbol: str = "PAXG-USD",
    strategy_parameters: Mapping[str, object] | None = None,
    description: str | None = None,
    report_context: Mapping[str, object] | None = None,
    usar_ia_generativa: bool = False,
    anthropic_api_key: str | None = None,
):
    """Genera un informe HTML interactivo y conserva el historial de ejecuciones."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d_%H%M%S_%f")
    trades = _records_from_frame(stats.get("_trades"), limit=250)
    equity_curve = stats.get("_equity_curve")
    equity = _records_from_frame(equity_curve, limit=1500)
    parameters = dict(strategy_parameters or {})
    if hasattr(stats, "_strategy"):
        strategy_instance = stats._strategy
        for name in ("rsi_period", "upper_level", "lower_level", "sl_pct", "tp_pct"):
            if hasattr(strategy_instance, name):
                parameters.setdefault(name, getattr(strategy_instance, name))

    context = dict(report_context or {})
    is_in_sample = context.get("is_in_sample", "base" in label.lower())
    label_lower = label.lower()
    report_description = description or (
        "Backtest dentro de muestra: ejecución exploratoria sobre el histórico completo."
        if is_in_sample
        else "Evaluación fuera de muestra: parámetros fijados previamente y aplicados al tramo de prueba."
        if "fuera" in label_lower or "prueba" in label_lower
        else "Backtest histórico de la estrategia RSI con SL/TP porcentuales."
    )
    findings = _diagnostic_findings(
        stats,
        label=label,
        symbol=symbol,
        n_bars=len(equity_curve) if equity_curve is not None else 0,
        report_context={**context, "is_in_sample": is_in_sample},
    )
    correction_prompt = _build_correction_prompt(
        stats,
        label=label,
        symbol=symbol,
        n_bars=len(equity_curve) if equity_curve is not None else 0,
        parameters=parameters,
        findings=findings,
    )
    interpretacion = generar_interpretacion_experta(stats, findings, is_in_sample=is_in_sample)
    interpretacion_ia = None
    if usar_ia_generativa:
        contexto_ia = (
            "Eres un analista cuantitativo. En maximo 3 frases y sin inventar cifras nuevas, "
            f"interpreta este backtest de {symbol} ({label}): retorno {_json_value(stats.get('Return [%]'))}%, "
            f"buy & hold {_json_value(stats.get('Buy & Hold Return [%]'))}%, "
            f"factor de beneficio {_json_value(stats.get('Profit Factor'))}, "
            f"drawdown maximo {_json_value(stats.get('Max. Drawdown [%]'))}%, "
            f"{_json_value(stats.get('# Trades'))} operaciones."
        )
        interpretacion_ia = interpretar_con_ia_generativa(contexto_ia, api_key=anthropic_api_key)

    history_path = directory / "historial_ejecuciones.json"
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    summary = {
        "id": run_id,
        "fecha": now.isoformat(),
        "label": label,
        "symbol": symbol,
        "description": report_description,
        "bars": len(equity_curve) if equity_curve is not None else 0,
        "start": _json_value(stats.get("Start")),
        "end": _json_value(stats.get("End")),
        "return_pct": _json_value(stats.get("Return [%]")),
        "win_rate_pct": _json_value(stats.get("Win Rate [%]")),
        "profit_factor": _json_value(stats.get("Profit Factor")),
        "max_drawdown_pct": _json_value(stats.get("Max. Drawdown [%]")),
        "trades": _json_value(stats.get("# Trades")),
    }
    history.append(summary)
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = {
        "run": summary,
        "metrics": _metric_payload(stats),
        "parameters": {str(key): _json_value(value) for key, value in parameters.items()},
        "trades": trades,
        "equity": equity,
        "history": history,
        "findings": findings,
        "interpretation": interpretacion,
        "interpretation_ia": interpretacion_ia,
        "correction_prompt": correction_prompt,
    }
    payload_json = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    report_path = directory / f"informe_oro_{_slugify(label)}_{run_id}.html"
    report_path.write_text(_render_report(payload_json), encoding="utf-8")
    report_path.with_suffix(".prompt.txt").write_text(correction_prompt, encoding="utf-8")
    return report_path


def _render_report(payload_json: str):
    template = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Informe ejecutivo | Oro</title>
<style>
:root { --bg:#09070f; --panel:rgba(24,18,39,.78); --line:rgba(224,205,255,.14); --text:#f8f4ff; --muted:#aaa0bd; --purple:#a66cff; --violet:#6e3bd5; --green:#65e6b0; --red:#ff7b9e; }
* { box-sizing:border-box; } body { margin:0; color:var(--text); background:radial-gradient(circle at 12% 0%,#44206e 0,transparent 34%),radial-gradient(circle at 90% 12%,#17204d 0,transparent 30%),linear-gradient(135deg,#08070d,#151020 55%,#08070d); font:15px/1.5 Inter,Segoe UI,sans-serif; min-height:100vh; }
.wrap { max-width:1280px; margin:auto; padding:34px 24px 70px; } .hero { display:flex; justify-content:space-between; gap:24px; align-items:flex-end; margin-bottom:28px; } .eyebrow { color:#c9a9ff; text-transform:uppercase; letter-spacing:.16em; font-size:11px; font-weight:700; } h1 { font-size:clamp(30px,5vw,58px); line-height:1.02; margin:8px 0; letter-spacing:-.02em; } h2 { margin:0 0 16px; font-size:20px; } .sub { color:var(--muted); max-width:700px; } .stamp { color:var(--muted); text-align:right; white-space:nowrap; }
.grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:20px 0; } .card,.panel { background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:0 18px 50px #0005; backdrop-filter:blur(16px); } .card { padding:18px; min-height:122px; } .card .icon { color:var(--purple); font-size:24px; } .metric-label { color:var(--muted); font-size:12px; margin-top:8px; } .metric-value { font-size:25px; font-weight:750; margin-top:3px; } .positive { color:var(--green); } .negative { color:var(--red); }
.columns { display:grid; grid-template-columns:1.6fr 1fr; gap:18px; } .panel { padding:22px; margin-bottom:18px; } .chart { width:100%; height:285px; } .axis { stroke:#ffffff1c; stroke-width:1; } .line { fill:none; stroke:var(--purple); stroke-width:3; filter:drop-shadow(0 0 7px #a66cff99); } .dot { fill:var(--purple); } .legend { color:var(--muted); font-size:12px; }
.chips { display:flex; flex-wrap:wrap; gap:8px; } .chip { border:1px solid #b88aff55; background:#a66cff13; border-radius:999px; padding:7px 10px; color:#e9ddff; font-size:12px; } .finding { border-left:4px solid var(--muted); background:#ffffff08; padding:14px 16px; margin:10px 0; } .finding h3 { margin:0 0 7px; font-size:15px; } .finding p { margin:5px 0; color:#d7cfdf; } .finding b { color:#f2eaff; } .severity-CRITICA { border-left-color:#ff4d6d; } .severity-ALTA { border-left-color:#ffae57; } .severity-MEDIA { border-left-color:#f1d264; } table { width:100%; border-collapse:collapse; font-size:12px; } th,td { padding:10px 8px; text-align:left; border-bottom:1px solid var(--line); } th { color:#d5c6e9; font-size:11px; text-transform:uppercase; } td { color:#cbc1d8; } .table-scroll { overflow:auto; max-height:400px; } button { color:var(--text); background:#a66cff18; border:1px solid #b88aff55; border-radius:8px; padding:8px 11px; cursor:pointer; } button:hover { background:#a66cff35; } .empty { color:var(--muted); padding:18px 0; } .footer { color:var(--muted); font-size:12px; text-align:center; padding-top:18px; }
.prompt { width:100%; min-height:300px; resize:vertical; color:#e9ddff; background:#0d0a16; border:1px solid var(--line); border-radius:8px; padding:12px; font:12px/1.5 Consolas,monospace; }
.interpretation p { margin:8px 0; color:#e4d9ff; line-height:1.6; } .interpretation p:first-child { color:#f8f4ff; font-weight:700; } .ia-tag { border-top:1px dashed var(--line); margin-top:14px !important; padding-top:12px; color:#c9a9ff !important; font-weight:400 !important; }
@media (max-width:850px) { .hero,.columns { display:block; } .stamp { text-align:left; margin-top:14px; } .grid { grid-template-columns:repeat(2,minmax(0,1fr)); } } @media (max-width:480px) { .wrap { padding:24px 14px 50px; } .grid { grid-template-columns:1fr; } .card { min-height:96px; } }
</style>
</head>
<body><main class="wrap">
<header class="hero"><div><div class="eyebrow">Atlas Quant · Informe ejecutivo</div><h1>Lectura del backtest<br><span style="color:#b889ff">__SYMBOL__</span></h1><div class="sub" id="description"></div></div><div class="stamp"><b>__LABEL__</b><br>Generado: __DATE__</div></header>
<section id="metrics" class="grid"></section>
<section class="panel"><h2>Interpretación experta</h2><p class="legend">Lectura automática, determinista y reproducible de las métricas de esta ejecución (no participa en el cálculo del backtest).</p><div id="interpretation" class="interpretation"></div></section>
<section class="panel"><h2>Diagnóstico y plan de mejora</h2><div id="findings"></div></section>
<section class="panel"><h2>Prompt paramétrico de corrección</h2><p class="legend">Generado con las métricas, parámetros y fallas de esta ejecución para corregir <b>proyecciones_oro.ipynb</b>.</p><textarea id="correction-prompt" class="prompt" readonly></textarea><br><button id="copy-prompt">Copiar prompt</button></section>
<div class="columns"><div><section class="panel"><h2>Curva de capital</h2><div id="equity-chart" class="chart"></div><div class="legend">Evolución del equity al avanzar el histórico evaluado.</div></section><section class="panel"><h2>Operaciones recientes</h2><div class="table-scroll"><table><thead><tr><th>Entrada</th><th>Salida</th><th>Dirección</th><th>Resultado</th><th>Retorno</th></tr></thead><tbody id="trades"></tbody></table></div></section></div><div><section class="panel"><h2>Configuración evaluada</h2><div id="parameters" class="chips"></div></section><section class="panel"><h2>Historial de ejecuciones</h2><button id="sort-history">Ordenar por retorno</button><div class="table-scroll"><table><thead><tr><th>Fecha</th><th>Tipo</th><th>Retorno</th><th>Acierto</th></tr></thead><tbody id="history"></tbody></table></div></section></div></div>
<div class="footer">Informe generado automáticamente. Los resultados históricos no garantizan resultados futuros.</div></main>
<script>const REPORT=__PAYLOAD__;
const fmt=(v,suffix='')=>v===null||v===undefined?'N/D':(typeof v==='number'?v.toLocaleString('es-ES',{maximumFractionDigits:2}):v)+suffix;
const esc=v=>String(v??'N/D').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
document.querySelector('#description').textContent=REPORT.run.description||'Sin descripción del tipo de backtest.';
const interpretacion=REPORT.interpretation||[]; document.querySelector('#interpretation').innerHTML=(interpretacion.length?interpretacion.map(p=>`<p>${esc(p)}</p>`).join(''):'<div class="empty">Sin interpretación automática disponible.</div>')+(REPORT.interpretation_ia?`<p class="ia-tag">🤖 Interpretación generativa (opcional): ${esc(REPORT.interpretation_ia)}</p>`:'');
const icon={"Retorno":"↗","Comprar y mantener":"◈","Tasa de acierto":"✓","Factor de beneficio":"◒","Ratio de Sharpe":"⌁","Drawdown máximo":"⌄","Operaciones":"◫","Exposición":"◌"};
document.querySelector('#metrics').innerHTML=REPORT.metrics.map(m=>`<article class="card"><div class="icon">${icon[m.label]||'◆'}</div><div class="metric-label">${m.label}</div><div class="metric-value ${m.value>=0?'positive':'negative'}">${fmt(m.value,m.key.includes('%')?'%':'')}</div></article>`).join('');
const findings=REPORT.findings||[]; document.querySelector('#findings').innerHTML=findings.length?findings.map(f=>`<article class="finding severity-${esc(f.severity)}"><h3>${esc(f.severity)} · ${esc(f.title)}</h3><p><b>Problema:</b> ${esc(f.problem)}</p><p><b>Causa raíz:</b> ${esc(f.root_cause)}</p><p><b>Mejora:</b> ${esc(f.improvement)}</p><p><b>Scripts:</b> ${esc(f.scripts)}</p></article>`).join(''):'<div class="empty">No se detectaron hallazgos automáticos.</div>';
document.querySelector('#correction-prompt').value=REPORT.correction_prompt||'No se generó prompt de corrección.';
document.querySelector('#copy-prompt').onclick=async()=>{await navigator.clipboard.writeText(REPORT.correction_prompt||'');document.querySelector('#copy-prompt').textContent='Prompt copiado';};
document.querySelector('#parameters').innerHTML=Object.entries(REPORT.parameters).map(([k,v])=>`<span class="chip"><b>${k}</b>: ${fmt(v)}</span>`).join('')||'<span class="empty">Sin parámetros adicionales</span>';
const trades=REPORT.trades.slice().reverse(); document.querySelector('#trades').innerHTML=trades.length?trades.map(t=>`<tr><td>${esc(t.EntryTime||t.Fecha)}</td><td>${esc(t.ExitTime||'N/D')}</td><td>${t.Size>0?'Largo':'Corto'}</td><td class="${(t.ReturnPct??0)>=0?'positive':'negative'}">${fmt(t.ReturnPct??t.PnL??null,'%')}</td><td>${fmt(t.PnL??null)}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">No hay operaciones registradas.</td></tr>';
function drawChart(){const el=document.querySelector('#equity-chart'), rows=REPORT.equity.filter(x=>x.Equity!=null); if(!rows.length){el.innerHTML='<div class="empty">No hay curva de capital disponible.</div>';return;} const w=900,h=270,p=22,values=rows.map(x=>Number(x.Equity)),min=Math.min(...values),max=Math.max(...values),range=max-min||1; const points=values.map((v,i)=>`${p+i*(w-2*p)/(values.length-1)},${h-p-(v-min)*(h-2*p)/range}`).join(' '); el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><line class="axis" x1="${p}" y1="${h-p}" x2="${w-p}" y2="${h-p}"/><line class="axis" x1="${p}" y1="${p}" x2="${p}" y2="${h-p}"/><polyline class="line" points="${points}"/><circle class="dot" cx="${points.split(' ').at(-1).split(',')[0]}" cy="${points.split(' ').at(-1).split(',')[1]}" r="5"/></svg>`} drawChart();
function renderHistory(rows){document.querySelector('#history').innerHTML=rows.slice().reverse().map(r=>`<tr><td>${new Date(r.fecha).toLocaleString('es-ES')}</td><td>${esc(r.label)}</td><td class="${(r.return_pct??0)>=0?'positive':'negative'}">${fmt(r.return_pct,'%')}</td><td>${fmt(r.win_rate_pct,'%')}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">Primera ejecución.</td></tr>'} renderHistory(REPORT.history); document.querySelector('#sort-history').onclick=()=>renderHistory(REPORT.history.slice().sort((a,b)=>(b.return_pct??-Infinity)-(a.return_pct??-Infinity)));
</script></body></html>'''
    current = json.loads(payload_json)
    replacements = {
        "__PAYLOAD__": payload_json,
        "__SYMBOL__": escape(str(current["run"]["symbol"])),
        "__LABEL__": escape(str(current["run"]["label"])),
        "__DATE__": escape(str(current["run"]["fecha"])),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta el pipeline institucional completo de backtesting de oro (diagnostico "
            "dentro de muestra, split train/val/test con calentamiento del indicador, "
            "walk-forward, chequeo por regimen, sensibilidad de SL/TP y de costes, y prueba "
            "final fuera de muestra) y genera los informes HTML correspondientes."
        )
    )
    parser.add_argument("--symbol", default="PAXG-USD")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--output-dir", default="informes_backtesting_oro")
    parser.add_argument("--n-folds", type=int, default=4, help="Numero de folds del walk-forward.")
    parser.add_argument(
        "--simple", action="store_true",
        help="Corre solo un backtest directo (comportamiento anterior), sin el pipeline institucional completo.",
    )
    parser.add_argument(
        "--usar-ia-generativa", action="store_true",
        help=(
            "Intenta enriquecer la interpretacion de cada informe con un modelo generativo "
            "(requiere el paquete 'anthropic' instalado y ANTHROPIC_API_KEY configurada). "
            "Si no estan disponibles, se omite en silencio y el informe usa solo la "
            "interpretacion determinista incluida por defecto."
        ),
    )
    args = parser.parse_args()

    import yfinance as yf

    # backtesting.py muestra una barra de progreso (tqdm) por cada backtest.run() y por cada
    # combinacion de optimize(); con el walk-forward y las sensibilidades del pipeline
    # completo eso son decenas de barras que solo ensucian la salida de la terminal.
    import backtesting.backtesting as _motor_backtesting
    _motor_backtesting._tqdm = lambda iterable, **_: iterable
    warnings.filterwarnings("ignore", message=".*multi-process optimization.*")

    data = yf.download(
        args.symbol,
        period=args.period,
        interval=args.interval,
        auto_adjust=True,
        progress=False,
    ).dropna()
    if data.empty:
        raise RuntimeError(f"No se descargaron datos para {args.symbol}.")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    if args.simple:
        ejecutar_backtest_oro(
            data,
            report_dir=args.output_dir,
            report_label="Backtest directo desde backtesting_oro.py",
            report_symbol=args.symbol,
            report_description=(
                f"Backtest histórico de la estrategia RSI sobre {args.symbol}, "
                f"con datos de {args.period} y velas {args.interval}."
            ),
            report_context={"is_in_sample": True, "tipo": "dentro de muestra"},
            usar_ia_generativa=args.usar_ia_generativa,
        )
    else:
        ejecutar_pipeline_completo_oro(
            data,
            symbol=args.symbol,
            report_dir=args.output_dir,
            n_folds=args.n_folds,
            usar_ia_generativa=args.usar_ia_generativa,
        )

    output_dir = Path(args.output_dir).resolve()
    generados = sorted(output_dir.glob("informe_oro_*.html"), key=lambda path: path.stat().st_mtime)
    n_nuevos = 1 if args.simple else 2
    print(f"\nInformes generados en: {output_dir}")
    for reporte in generados[-n_nuevos:]:
        print(f"  - {reporte.name}")


if __name__ == "__main__":
    main()
