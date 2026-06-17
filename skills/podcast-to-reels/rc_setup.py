"""rc_setup.py — setup multiplataforma do podcast-to-reels.

Idempotente: roda quantas vezes quiser. Faz o mínimo pra outra máquina (Win/Mac/
Linux) conseguir transcrever e cortar:

  - pip install -r requirements.txt  (e requirements-cuda.txt se achar GPU NVIDIA)
  - baixa o modelo YuNet pra models/ se faltar (normalmente já vem versionado no repo)
  - checa ffmpeg no PATH (orienta instalar por OS se faltar)
  - checa Deno (só preciso pra baixar do YouTube); orienta instalar
  - reporta CUDA vs CPU

Uso: `python reel_cut.py setup`  (ou `--check` só pra diagnosticar, sem instalar).
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
YUNET = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def _ok(msg): print(f"  ✓ {msg}", flush=True)
def _warn(msg): print(f"  ! {msg}", flush=True)
def _info(msg): print(msg, flush=True)


# ── detecção ────────────────────────────────────────────────────────────────

def detect_cuda() -> bool:
    """GPU NVIDIA disponível? nvidia-smi é o proxy portável (não exige ct2 instalado)."""
    if IS_MAC:
        return False
    return shutil.which("nvidia-smi") is not None


def _ffmpeg_hint() -> str:
    if IS_WIN:
        return "winget install Gyan.FFmpeg   (ou choco install ffmpeg)"
    if IS_MAC:
        return "brew install ffmpeg"
    return "sudo apt install ffmpeg   (ou o gerenciador da sua distro)"


def _deno_hint() -> str:
    if IS_WIN:
        return "winget install DenoLand.Deno"
    if IS_MAC:
        return "brew install deno"
    return "curl -fsSL https://deno.land/install.sh | sh"


def find_deno() -> str | None:
    """Deno no PATH, ou no local conhecido do winget (Windows não herda o PATH novo)."""
    p = shutil.which("deno")
    if p:
        return p
    if IS_WIN:
        guess = (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" /
                 "Packages" / "DenoLand.Deno_Microsoft.Winget.Source_8wekyb3d8bbwe" / "deno.exe")
        if guess.exists():
            return str(guess)
    return None


def ensure_deno_on_path() -> bool:
    """Best-effort: garante `deno` achável pelo yt-dlp em runtime. Retorna True se achou."""
    if shutil.which("deno"):
        return True
    found = find_deno()
    if found:
        os.environ["PATH"] = str(Path(found).parent) + os.pathsep + os.environ.get("PATH", "")
        return True
    return False


# ── ações ───────────────────────────────────────────────────────────────────

def pip_install(req: Path) -> bool:
    if not req.exists():
        _warn(f"{req.name} não encontrado, pulando")
        return False
    _info(f"  pip install -r {req.name} ...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)])
    (_ok if r.returncode == 0 else _warn)(f"{req.name} {'instalado' if r.returncode == 0 else 'FALHOU'}")
    return r.returncode == 0


def ensure_yunet() -> bool:
    if YUNET.exists():
        _ok(f"modelo YuNet presente ({YUNET.stat().st_size // 1024} KB)")
        return True
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    _info(f"  baixando YuNet de {YUNET_URL} ...")
    try:
        urllib.request.urlretrieve(YUNET_URL, YUNET)
        _ok("YuNet baixado")
        return True
    except Exception as e:
        _warn(f"download do YuNet falhou: {e}. Baixe manualmente pra {YUNET}")
        return False


def run(check_only: bool = False) -> int:
    _info("=" * 60)
    _info(f"podcast-to-reels setup  ({'diagnóstico' if check_only else 'instalação'})  ·  {sys.platform}, Python {sys.version.split()[0]}")
    _info("=" * 60)

    cuda = detect_cuda()
    _info(f"\nGPU NVIDIA: {'sim (vai usar CUDA)' if cuda else 'não detectada (vai usar CPU)'}")

    if not check_only:
        _info("\n[1/4] dependências Python")
        pip_install(ROOT / "requirements.txt")
        if cuda:
            pip_install(ROOT / "requirements-cuda.txt")
        else:
            _info("  (sem GPU: pulando libs CUDA)")
    else:
        _info("\n[1/4] dependências Python (diagnóstico)")
        for mod, pkg in (("faster_whisper", "faster-whisper"), ("cv2", "opencv-python"), ("numpy", "numpy")):
            try:
                __import__(mod); _ok(f"{pkg}")
            except ImportError:
                _warn(f"{pkg} ausente — rode `setup` sem --check")

    _info("\n[2/4] modelo de rosto (YuNet)")
    ensure_yunet()

    _info("\n[3/4] ffmpeg")
    if shutil.which("ffmpeg"):
        _ok("ffmpeg no PATH")
    else:
        _warn(f"ffmpeg NÃO encontrado. Instale: {_ffmpeg_hint()}")

    _info("\n[4/4] Deno (só pra baixar do YouTube — opcional se você usa --file)")
    deno = find_deno()
    if deno:
        _ok(f"deno em {deno}")
    else:
        _warn(f"deno não encontrado. Pra baixar do YouTube: {_deno_hint()}")

    _info("\n" + "=" * 60)
    _info("Setup concluído. Teste:  python reel_cut.py transcribe --file <video> --out work/teste")
    _info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run(check_only="--check" in sys.argv))
