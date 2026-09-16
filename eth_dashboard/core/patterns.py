"""Deteccion de patrones tecnicos: picos/valles y hombro-cabeza-hombro."""
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
