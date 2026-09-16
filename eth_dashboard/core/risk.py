"""Calculo de tamaño de posicion sugerido por porcentaje de riesgo (regla '1111')."""
from __future__ import annotations


def suggested_size(balance: float, risk_pct: float, entry: float, stop: float) -> float | None:
    """Tamaño aproximado para arriesgar `risk_pct`% del saldo dada la distancia al SL.

    Aproximacion: asume 1 unidad de tamaño ~= 1 unidad de la moneda de cotizacion por
    punto de movimiento. El valor monetario real por punto varia segun el instrumento
    (forex/indices/materias primas/cripto) en Capital.com y no se consulta aqui — es
    una referencia para el usuario, no un calculo exacto de riesgo.
    """
    distance = abs(entry - stop)
    if balance <= 0 or distance <= 0:
        return None
    return (balance * risk_pct / 100) / distance
