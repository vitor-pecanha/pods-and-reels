"""rc_whisper.py — transcrição portável via faster-whisper (pip), multiplataforma.

Usa a API Python do faster-whisper (CTranslate2). GPU em Win/Linux via libs CUDA
instaladas por pip (nvidia-cublas-cu12 / nvidia-cudnn-cu12); cai pra CPU (Mac, ou
sem GPU). Mesmo schema de saída {words, segments} do resto do pipeline.

Modelo: env RC_WHISPER_MODEL (nome HF tipo 'large-v3-turbo' que baixa na 1ª vez,
ou caminho pra um modelo CTranslate2 local). Default: large-v3-turbo.
"""
from __future__ import annotations
import os
import sys

from rc_ffmpeg import extract_audio

DEFAULT_MODEL = os.environ.get("RC_WHISPER_MODEL", "large-v3-turbo")


def _ensure_cuda_libs():
    """Torna as libs CUDA dos pacotes pip (nvidia-*-cu12) encontráveis pelo loader."""
    for base in list(sys.path):
        nvdir = os.path.join(base, "nvidia")
        if not os.path.isdir(nvdir):
            continue
        for pkg in os.listdir(nvdir):
            bindir = os.path.join(nvdir, pkg, "bin")
            if os.path.isdir(bindir):
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(bindir)  # Windows
                    except OSError:
                        pass
                os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
                os.environ["LD_LIBRARY_PATH"] = bindir + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")  # Linux


def transcribe(media_path: str, out_dir: str, lang: str = "pt",
               initial_prompt: str | None = None) -> dict:
    """Transcreve -> {words, segments}. Tenta CUDA, cai pra CPU.

    initial_prompt: contexto (nomes próprios/jargão certos) pro Whisper errar menos
    na origem; vem do glossário do canal (peça 2).
    """
    from faster_whisper import WhisperModel  # lazy: o estágio 'cut' não precisa disso

    os.makedirs(out_dir, exist_ok=True)
    wav = os.path.join(out_dir, "audio.wav")
    if not os.path.exists(wav):
        extract_audio(media_path, wav)

    _ensure_cuda_libs()
    _v = bool(os.environ.get("RC_VERBOSE"))
    if _v and initial_prompt:
        print(f"[whisper] initial_prompt do glossário: {initial_prompt[:80]}...", flush=True)
    last_err = None
    for device, compute in (("cuda", "float16"), ("cpu", "int8")):
        try:
            if _v:
                print(f"[whisper] carregando {DEFAULT_MODEL} em {device}/{compute}...", flush=True)
            model = WhisperModel(DEFAULT_MODEL, device=device, compute_type=compute)
            segs, info = model.transcribe(wav, language=lang, word_timestamps=True,
                                          initial_prompt=initial_prompt)
            words, segments = [], []
            for s in segs:  # consumir o gerador dispara a inferência (e qualquer erro CUDA)
                segments.append({"start": float(s.start), "end": float(s.end), "text": s.text.strip()})
                for w in (s.words or []):
                    words.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
            if _v:
                print(f"[whisper] {device}/{compute}: {len(words)} palavras, {len(segments)} segmentos", flush=True)
            return {"words": words, "segments": segments}
        except Exception as e:
            last_err = e
            if _v:
                print(f"[whisper] {device} falhou: {repr(e)[:160]}", flush=True)
            if device == "cuda":
                continue
            raise RuntimeError(f"Whisper falhou em CUDA e CPU: {last_err}")
    raise RuntimeError(f"Whisper falhou: {last_err}")


def _mmss(s: float) -> str:
    return f"{int(s) // 60:02d}:{int(s) % 60:02d}"


def transcript_to_text(segments: list[dict]) -> str:
    """Transcrição legível: uma linha '[MM:SS] texto' por segmento."""
    return "\n".join(f"[{_mmss(s['start'])}] {s['text']}" for s in segments)
