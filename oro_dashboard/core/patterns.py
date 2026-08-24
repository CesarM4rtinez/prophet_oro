"""Deteccion de patrones tecnicos: picos/valles, ABCD simplificado y hombro-cabeza-hombro."""
from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks


def detect_peaks_valleys(close: np.ndarray, distance: int = 10):
    peaks, _ = find_peaks(close, distance=distance)
    valleys, _ = find_peaks(-close, distance=distance)
    return peaks, valleys


def detect_head_and_shoulders(close: np.ndarray, peaks: np.ndarray) -> list[tuple[int, int, int]]:
    patterns = []
    for i in range(1, len(peaks) - 1):
        l_, h_, r_ = peaks[i - 1], peaks[i], peaks[i + 1]
        if close[h_] > close[l_] and close[h_] > close[r_]:
            patterns.append((int(l_), int(h_), int(r_)))
    return patterns


def detect_abcd_patterns(close: np.ndarray, valleys: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Patron armonico ABCD simplificado: sobre valles consecutivos X-A-B-D, exige que
    las razones AB/XA y BD/AB caigan en la banda Fibonacci amplia 0.618-1.618."""
    patterns = []
    for i in range(len(valleys) - 3):
        x_, a_, b_, d_ = valleys[i : i + 4]
        xa = abs(close[a_] - close[x_])
        ab = abs(close[b_] - close[a_])
        bd = abs(close[d_] - close[b_])
        if xa == 0 or ab == 0:
            continue
        ratio1, ratio2 = ab / xa, bd / ab
        if 0.618 < ratio1 < 1.618 and 0.618 < ratio2 < 1.618:
            patterns.append((int(x_), int(a_), int(b_), int(d_)))
    return patterns
