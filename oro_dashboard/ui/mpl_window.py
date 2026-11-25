"""Graficos matplotlib del Pronostico por Ventana + Supertrend (pedido explicito del
usuario: graficos matplotlib, no Plotly, en esta pagina)."""
from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .theme import COLORS

BG = COLORS["bg_surface"]
GREEN = "#26a69a"   # mismos tonos que el Supertrend por defecto de TradingView
RED = "#ef5350"


def _style(ax, fig) -> None:
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(COLORS["axis"])
    ax.tick_params(colors=COLORS["text_muted"], labelsize=8)
    ax.grid(color=COLORS["grid"], linewidth=0.6, alpha=0.8)
    ax.yaxis.label.set_color(COLORS["text_secondary"])
    ax.title.set_color(COLORS["text_primary"])


def _candles(ax, df: pd.DataFrame, bar_hours: float) -> None:
    x = mdates.date2num(df.index.to_pydatetime())
    width = bar_hours / 24 * 0.62
    up = df["close"] >= df["open"]
    colors = np.where(up, COLORS["bull"], COLORS["bear"])
    ax.vlines(x, df["low"], df["high"], colors=colors, linewidth=0.8, zorder=2)
    body_low = np.minimum(df["open"], df["close"])
    body_h = np.maximum(np.abs(df["close"] - df["open"]), 1e-6)
    ax.bar(x, body_h, width=width, bottom=body_low, color=colors, edgecolor=colors, linewidth=0.5, zorder=3)


def _supertrend_line(ax, idx: pd.DatetimeIndex, st: pd.DataFrame) -> None:
    """Linea verde debajo del precio en tendencia alcista, roja encima en bajista;
    cortada en cada cambio de color (como en TradingView)."""
    line = st["supertrend"].to_numpy()
    trend = st["trend"].to_numpy()
    for color, val in ((GREEN, 1), (RED, -1)):
        y = np.where(trend == val, line, np.nan)
        ax.plot(idx, y, color=color, linewidth=1.6, zorder=4)
    buys, sells = st["buy"].to_numpy(), st["sell"].to_numpy()
    offset = np.nanmedian(np.abs(np.diff(line))) if len(line) > 2 else 0
    ax.scatter(idx[buys], line[buys] - offset, marker="^", s=70, color=GREEN, zorder=6, label="Compra (pasa a verde)")
    ax.scatter(idx[sells], line[sells] + offset, marker="v", s=70, color=RED, zorder=6, label="Venta (pasa a rojo)")


def window_fan_chart(hist: pd.DataFrame, st_hist: pd.DataFrame, fc, x_future: pd.DatetimeIndex,
                     window_start, window_end, title: str) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(12, 5.6))
    _style(ax, fig)
    ax.axvspan(window_start, window_end, color=COLORS["series_zone"], alpha=0.10, zorder=0, label="Ventana")
    _candles(ax, hist, 1)
    _supertrend_line(ax, hist.index, st_hist)
    from core.window_forecast import BAND_Q  # evitar import circular a nivel de modulo
    b = {q: fc.bands[i] for i, q in enumerate(BAND_Q)}
    fcol = COLORS["series_forecast"]
    ax.fill_between(x_future, b[0.10], b[0.90], color=fcol, alpha=0.18, linewidth=0, label="80 % probable", zorder=1)
    ax.fill_between(x_future, b[0.25], b[0.75], color=fcol, alpha=0.38, linewidth=0, label="50 % probable", zorder=1)
    ax.plot(x_future, b[0.5], color=fcol, linewidth=2, label="Mediana", zorder=5)
    ax.axhline(fc.price_now, color=COLORS["text_muted"], linestyle="--", linewidth=1)
    ax.text(hist.index[0], fc.price_now, f" Ahora ${fc.price_now:,.2f}", va="bottom", fontsize=8,
            color=COLORS["text_secondary"])
    for q, txt in ((0.90, "P90"), (0.5, "Mediana"), (0.10, "P10")):
        ax.annotate(f"{txt} ${b[q][-1]:,.0f}", (x_future[-1], b[q][-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9, color=COLORS["text_primary"] if q == 0.5 else COLORS["text_secondary"],
                    annotation_clip=False)
    ax.set_xlim(hist.index[0] - pd.Timedelta(minutes=40), x_future[-1] + pd.Timedelta(minutes=40))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m\n%I %p"))
    ax.set_ylabel("Precio (USD)")
    ax.set_title(title, fontsize=12, fontweight="bold", loc="left")
    leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=6, fontsize=8, frameon=False)
    for t in leg.get_texts():
        t.set_color(COLORS["text_secondary"])
    fig.tight_layout()
    return fig


def touch_ladder_chart(levels: list, price_now: float, title: str) -> plt.Figure:
    labels = [f"${lv:,.0f}  ({lv - price_now:+,.0f})" for lv, _ in levels]
    probs = np.array([p * 100 for _, p in levels])
    colors = [COLORS["bull"] if lv > price_now else COLORS["bear"] for lv, _ in levels]
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    _style(ax, fig)
    y = np.arange(len(levels))
    ax.barh(y, probs, color=colors, height=0.66)
    for yi, p in zip(y, probs):
        ax.text(p + 1.5, yi, f"{p:.0f} %", va="center", fontsize=9, color=COLORS["text_secondary"])
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9, color=COLORS["text_secondary"])
    ax.invert_yaxis()
    ax.set_xlim(0, 105)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.grid(axis="y", visible=False)
    ax.set_title(title, fontsize=11, fontweight="bold", loc="left")
    fig.tight_layout()
    return fig


def supertrend_chart(df: pd.DataFrame, st: pd.DataFrame, bar_hours: float, title: str) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(12, 5.2))
    _style(ax, fig)
    _candles(ax, df, bar_hours)
    _supertrend_line(ax, df.index, st)
    # Relleno suave entre precio y linea, como el "fill" del indicador de TradingView.
    mid = (df["open"] + df["close"]) / 2
    for color, val in ((GREEN, 1), (RED, -1)):
        mask = st["trend"].to_numpy() == val
        ax.fill_between(df.index, mid, st["supertrend"], where=mask, color=color, alpha=0.08, linewidth=0)
    ax.set_xlim(df.index[0] - pd.Timedelta(hours=bar_hours), df.index[-1] + pd.Timedelta(hours=bar_hours))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m\n%I %p"))
    ax.set_ylabel("Precio (USD)")
    ax.set_title(title, fontsize=12, fontweight="bold", loc="left")
    leg = ax.legend(loc="upper left", fontsize=8, frameon=False)
    for t in leg.get_texts():
        t.set_color(COLORS["text_secondary"])
    fig.tight_layout()
    return fig


def equity_chart(equity: np.ndarray, times: pd.DatetimeIndex, title: str) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(12, 3.2))
    _style(ax, fig)
    ax.plot(times, equity, color=COLORS["series_hist"], linewidth=1.6)
    ax.axhline(0, color=COLORS["text_muted"], linewidth=0.8)
    ax.fill_between(times, equity, 0, where=equity >= 0, color=COLORS["bull"], alpha=0.12, linewidth=0)
    ax.fill_between(times, equity, 0, where=equity < 0, color=COLORS["bear"], alpha=0.12, linewidth=0)
    ax.set_ylabel("USD por 1 oz")
    ax.set_title(title, fontsize=11, fontweight="bold", loc="left")
    fig.tight_layout()
    return fig
