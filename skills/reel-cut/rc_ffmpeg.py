"""rc_ffmpeg.py — thin wrappers around ffmpeg/ffprobe.

System ffmpeg (8.x) is assumed on PATH. All paths are absolute strings.
"""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path

# Log técnico (comandos ffmpeg) só com RC_VERBOSE=1; por padrão, silencioso.
VERBOSE = bool(os.environ.get("RC_VERBOSE"))


def run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    if VERBOSE:
        print("[ffmpeg] $ " + " ".join(str(c) for c in cmd), flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        tail = (proc.stderr or "")[-800:]
        raise RuntimeError(f"command failed ({proc.returncode}):\n{tail}")
    return proc


def get_dimensions(video_path: str) -> tuple[int, int]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", video_path],
        capture_output=True, text=True,
    )
    try:
        s = json.loads(proc.stdout)["streams"][0]
        return int(s["width"]), int(s["height"])
    except Exception:
        return 1920, 1080


def get_duration(video_path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", video_path],
        capture_output=True, text=True,
    )
    return float(json.loads(proc.stdout)["format"]["duration"])


def extract_frame(src: str, t: float | None, out_jpg: str) -> str:
    """Grava 1 frame de `src` (arquivo OU URL http de imagem) em out_jpg.

    `t=None` pega o 1º frame decodável (use pra thumbnail remota); um `t` em
    segundos faz seek antes de capturar (use pra pegar o miolo de um arquivo,
    evitando o frame 0 que costuma ser preto)."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if t is not None:
        cmd += ["-ss", str(t)]
    cmd += ["-i", src, "-frames:v", "1", "-q:v", "3", out_jpg]
    run(cmd)
    return out_jpg


def extract_audio(video_path: str, wav_path: str) -> str:
    """Extract 16 kHz mono PCM wav (what Whisper wants)."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_path,
         "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_path])
    return wav_path


def ass_filter_path(ass_path: str) -> str:
    """Escape a Windows path for use inside an ffmpeg -vf ass='...' filter."""
    return ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
