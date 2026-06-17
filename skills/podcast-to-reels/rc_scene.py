"""rc_scene.py — detecção de cortes de câmera dentro de um trecho.

Podcast multi-câmera: o plano troca dentro de um clipe. Aqui achamos os cortes
(via scene detection do FFmpeg) pra crop por plano em clip_live.
"""
from __future__ import annotations
import re
import subprocess


def detect_cuts(video: str, start: float, end: float, threshold: float = 0.2) -> list[float]:
    """Timestamps absolutos (s) dos cortes de câmera no intervalo [start, end]."""
    dur = end - start
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(dur), "-i", video,
         "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
        capture_output=True, text=True)
    cuts = []
    for m in re.finditer(r"pts_time:([\d.]+)", p.stderr or ""):
        t = float(m.group(1)) + start  # -ss antes do -i: pts relativo ao seek
        if start + 0.5 < t < end - 0.5:
            cuts.append(round(t, 3))
    return sorted(cuts)


def shots_from_cuts(start: float, end: float, cuts: list[float],
                    min_len: float = 0.8) -> list[tuple[float, float]]:
    """Quebra [start, end] em planos pelos cortes; funde planos curtos demais."""
    bounds = [start] + [c for c in cuts if start < c < end] + [end]
    shots = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    merged: list[list[float]] = []
    for a, b in shots:
        if merged and (b - a) < min_len:
            merged[-1][1] = b  # funde no anterior
        else:
            merged.append([a, b])
    # garante que o primeiro também não seja curto demais
    if len(merged) > 1 and (merged[0][1] - merged[0][0]) < min_len:
        merged[1][0] = merged[0][0]
        merged.pop(0)
    return [(a, b) for a, b in merged]
