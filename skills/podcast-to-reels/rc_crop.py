"""rc_crop.py — monta o filtro 9:16 (1080x1920) a partir de um fonte 16:9.

Detecção de rosto via YuNet (cv2.FaceDetectorYN, funciona no Python 3.13) +
**locutor ativo** por movimento de boca:
  - 1 rosto            -> crop centrado nele
  - 2 rostos, 1 falando -> solo no que fala (regra do Vitor)
  - 2 rostos se revezando -> empilha vertical (meio a meio)
  - 0 rostos           -> panning de áudio -> centro
  - layout="pad"       -> letterbox (mantém o quadro; bom pra slide)

build_vertical_filter() devolve dict:
  {"complex": False, "chain": "<cadeia -vf>"}     (1 saída -> -vf)
  {"complex": True,  "chain": "...[vid]"}          (grafo -filter_complex, saída [vid])
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

TARGET_W, TARGET_H = 1080, 1920
MODEL_PATH = str(Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx")

# Enquadramento sensível ao tamanho do rosto (menor K = mais perto).
FACE_FILL_SINGLE = 3.8   # 9:16: altura do crop = altura_do_rosto * K
FACE_FILL_STACK = 3.2    # célula larga: largura do crop = largura_do_rosto * K
FACE_Y_SINGLE = 0.40
FACE_Y_STACK = 0.46
MIN_CROP_W = int(TARGET_W * 0.33)

# Locutor ativo
MOTION_FPS = 5
MOTION_WINDOW = 12.0     # s amostrados no meio do plano pra medir boca
CORR_MIN = 0.15          # correlação mínima boca-x-áudio pra contar como "falando"
CORR_MARGIN = 0.12       # vantagem de correlação de um sobre o outro -> solo
ZOOM_MIN_W = 0.05        # rosto menor que isso -> letterbox (zoom pixelaria); maior -> crop
# Auto-calibração do tamanho de rosto (mata o knob fixo entre estúdios):
ZOOM_K = 0.55            # limiar = mediana da largura de rosto do vídeo * K
ZOOM_FLOOR = 0.04        # piso absoluto: rosto menor pixeliza no zoom -> letterbox de qualquer jeito
ZOOM_CAP = 0.08          # teto: não exigir rosto gigante pra permitir solo
_ZMW = None              # override calibrado por vídeo; None = usa ZOOM_MIN_W


# ── Auto-calibração do tamanho de rosto ──────────────────────────────────────

def set_zoom_min_w(value):
    """Override calibrado do limiar de zoom (por vídeo). None volta ao default."""
    global _ZMW
    _ZMW = value


def _zmw() -> float:
    return ZOOM_MIN_W if _ZMW is None else _ZMW


def calibrate_zoom_min_w(video: str, src_w: int, src_h: int, duration: float, samples: int = 18) -> float:
    """Mede a largura típica (mediana) do MAIOR rosto ao longo do vídeo e devolve o
    limiar de 'pequeno demais' relativo a ela (clamp FLOOR..CAP). Assim o crop se ajusta
    ao enquadramento de cada estúdio, em vez do 0.05 fixo. Sem rosto/cv2 -> ZOOM_MIN_W."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return ZOOM_MIN_W
    if not os.path.exists(MODEL_PATH) or duration <= 0:
        return ZOOM_MIN_W

    n = max(6, samples)
    tmp = tempfile.mkdtemp(prefix="rc_cal_")
    det = cv2.FaceDetectorYN.create(MODEL_PATH, "", (src_w, src_h), 0.6, 0.3, 10)
    widths = []
    try:
        for i in range(n):
            t = duration * (i + 0.5) / n  # espalha amostras pelo vídeo todo
            fp = os.path.join(tmp, f"{i:03d}.jpg")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", video,
                            "-frames:v", "1", "-q:v", "3", fp], capture_output=True)
            img = cv2.imread(fp)
            if img is None:
                continue
            h, w = img.shape[:2]
            det.setInputSize((w, h))
            _, faces = det.detect(img)
            if faces is None:
                continue
            # maior rosto de frente da cena (ignora plateia/fundo minúsculo)
            cand = [float(f[2]) / w for f in faces if float(f[2]) / w > 0.025]
            if cand:
                widths.append(max(cand))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if len(widths) < 3:
        return ZOOM_MIN_W
    median = float(np.median(widths))
    return round(max(ZOOM_FLOOR, min(ZOOM_CAP, median * ZOOM_K)), 4)


# ── Detecção + locutor ativo ─────────────────────────────────────────────────

def _mouth_patch(gray, f, w, h):
    import cv2
    import numpy as np
    rmx, rmy, lmx, lmy = f[10], f[11], f[12], f[13]
    mcx, mcy = (rmx + lmx) / 2, (rmy + lmy) / 2
    mw = max(8.0, abs(lmx - rmx) * 1.8)
    x0, x1 = int(mcx - mw / 2), int(mcx + mw / 2)
    y0, y1 = int(mcy - mw * 0.4), int(mcy + mw * 0.6)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    crop = gray[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    patch = cv2.resize(crop, (32, 20)).astype(np.float32) / 255.0
    return patch - patch.mean()  # tira brilho; sobra estrutura (boca mexendo)


def analyze_people(video: str, start: float, dur: float, src_w: int, src_h: int):
    """Pessoas no plano: [{cx,cy,w,h,n,talk,corr}], ordenado por cx.

    corr = correlação do movimento de boca de cada pessoa com a loudness do áudio
    (locutor ativo: quem fala casa boca com som; quem só reage, não).
    """
    try:
        import cv2
        import numpy as np
        import wave
    except ImportError:
        return []
    if not os.path.exists(MODEL_PATH):
        return []

    win = min(dur, MOTION_WINDOW)
    ws = start + max(0.0, (dur - win) / 2)
    tmp = tempfile.mkdtemp(prefix="rc_mot_")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(ws), "-t", str(win),
                    "-i", video, "-vf", f"fps={MOTION_FPS}", "-q:v", "3",
                    os.path.join(tmp, "%04d.jpg")], capture_output=True)
    wav = os.path.join(tmp, "a.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(ws), "-t", str(win),
                    "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav], capture_output=True)
    frames = sorted(Path(tmp).glob("*.jpg"))
    n_frames = len(frames)

    # loudness do áudio alinhada aos frames
    audio_series = []
    try:
        wf = wave.open(wav, "rb")
        a = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)
        wf.close()
        if n_frames and a.size:
            spf = a.size / n_frames
            audio_series = [float(np.sqrt(np.mean(a[int(i * spf):int((i + 1) * spf)] ** 2)) or 0.0)
                            if a[int(i * spf):int((i + 1) * spf)].size else 0.0 for i in range(n_frames)]
    except Exception:
        audio_series = []

    det = cv2.FaceDetectorYN.create(MODEL_PATH, "", (src_w, src_h), 0.6, 0.3, 10)
    dets = []  # (cx, cy, wr, hr, patch, frame_idx)
    for idx, fp in enumerate(frames):
        img = cv2.imread(str(fp))
        if img is None:
            continue
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        if faces is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for f in faces:
            x, y, fw, fh = f[0], f[1], f[2], f[3]
            cx, cy, wr, hr = (x + fw / 2) / w, (y + fh / 2) / h, fw / w, fh / h
            # floor exclui rostos de fundo/plateia (gente andando no evento); tira bordas (TV topo, plateia base)
            if wr < 0.04 or not (0.045 <= cx <= 0.955) or not (0.06 <= cy <= 0.72):
                continue
            dets.append((cx, cy, wr, hr, _mouth_patch(gray, f, w, h), idx))
    shutil.rmtree(tmp, ignore_errors=True)
    if not dets:
        return []

    dets.sort(key=lambda d: d[0])
    xs = [d[0] for d in dets]
    max_gap, split = 0.0, None
    for i in range(1, len(xs)):
        g = xs[i] - xs[i - 1]
        if g > max_gap:
            max_gap, split = g, i
    groups = [dets[:split], dets[split:]] if max_gap > 0.22 and split else [dets]

    people = []
    min_det = max(3, int(n_frames * 0.2))  # persistência: descarta rosto transitório (plateia/TV)
    for g in groups:
        if len(g) < min_det:
            continue
        gg = sorted(g, key=lambda d: d[5])
        diffs, mser, aser = [], [], []
        for i in range(1, len(gg)):
            p0, p1 = gg[i - 1][4], gg[i][4]
            if p0 is None or p1 is None or p0.shape != p1.shape:
                continue
            m = float(np.mean(np.abs(p0 - p1)))
            diffs.append(m)
            idx = gg[i][5]
            if idx < len(audio_series):
                mser.append(m)
                aser.append(audio_series[idx])
        talk = float(np.mean(diffs)) if diffs else 0.0
        corr = 0.0
        if len(mser) >= 4:
            M, A = np.array(mser), np.array(aser)
            if M.std() > 1e-6 and A.std() > 1e-6:
                corr = float(np.corrcoef(M, A)[0, 1])
        people.append({"cx": sum(d[0] for d in g) / len(g), "cy": sum(d[1] for d in g) / len(g),
                       "w": sum(d[2] for d in g) / len(g), "h": sum(d[3] for d in g) / len(g),
                       "n": len(g), "talk": round(talk, 4), "corr": round(corr, 3)})
    people.sort(key=lambda p: p["cx"])
    return people


# ── Crop builders ─────────────────────────────────────────────────────────────

def _crop_box(src_w, src_h, person, target_ar, fill, face_y):
    """Caixa (cw, ch, x, y) centrada no rosto. 9:16 alto: altura manda; célula larga: largura."""
    face_w = max(1.0, person["w"] * src_w)
    face_h = max(1.0, person.get("h", person["w"] * 1.3) * src_h)
    if target_ar < 1.0:
        ch = face_h * fill
        cw = ch * target_ar
    else:
        cw = face_w * fill
        ch = cw / target_ar
    cw = min(float(src_w), max(MIN_CROP_W, cw))
    ch = cw / target_ar
    if ch > src_h:
        ch = float(src_h)
        cw = ch * target_ar
    cx, cy = person["cx"] * src_w, person["cy"] * src_h
    x = max(0.0, min(src_w - cw, cx - cw / 2))
    y = max(0.0, min(src_h - ch, cy - ch * face_y))
    return int(cw), int(ch), int(x), int(y)


def _single_face_chain(src_w, src_h, person):
    cw, ch, x, y = _crop_box(src_w, src_h, person, TARGET_W / TARGET_H, FACE_FILL_SINGLE, FACE_Y_SINGLE)
    return f"crop={cw}:{ch}:{x}:{y},scale={TARGET_W}:{TARGET_H}"


def _two_stack_graph(src_w, src_h, a, b):
    cell_ar = TARGET_W / (TARGET_H / 2)  # 1.125
    parts = []
    for label, p in (("top", a), ("bot", b)):
        cw, ch, x, y = _crop_box(src_w, src_h, p, cell_ar, FACE_FILL_STACK, FACE_Y_STACK)
        parts.append(f"[0:v]crop={cw}:{ch}:{x}:{y},scale={TARGET_W}:{TARGET_H // 2},setsar=1[{label}]")
    parts.append("[top][bot]vstack=inputs=2[vid]")
    return ";".join(parts)


# ── Fallback por áudio ────────────────────────────────────────────────────────

def analyze_audio_panning(video, start, dur):
    def rms(ch):
        p = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start), "-t", str(dur), "-i", video,
             "-af", f"pan=mono|c0={ch},astats=metadata=1:reset=1", "-f", "null", "-"],
            capture_output=True, text=True)
        m = re.findall(r"RMS level dB:\s*(-?inf|[-\d.]+)", p.stderr or "")
        if not m:
            return -60.0
        try:
            v = float(m[-1])
            return v if v != float("-inf") else -60.0
        except ValueError:
            return -60.0
    diff = rms("c0") - rms("c1")
    return "left" if diff > 3 else "right" if diff < -3 else "center"


def _pan_chain(src_w, src_h, pos):
    scaled_h = int(TARGET_H * 1.05)
    scaled_w = int(scaled_h * src_w / src_h)
    max_x = max(0, scaled_w - TARGET_W)
    crop_x = int(max_x * 0.25) if pos == "left" else int(max_x * 0.75) if pos == "right" else max_x // 2
    return f"scale=-2:{scaled_h},crop={TARGET_W}:{TARGET_H}:{crop_x}:0"


# ── Decisão ───────────────────────────────────────────────────────────────────

def _lado(cx: float) -> str:
    return "esquerda" if cx < 0.4 else "direita" if cx > 0.6 else "centro"


def plan_vertical_filter(video, start, dur, src_w, src_h, layout="auto"):
    """Decide o crop do plano. Igual ao build_vertical_filter, mas devolve também
    `sig`/`kind`/`label` (assinatura do plano) pra dedup + preview da peça 4.

    sig: chave estável pra agrupar planos repetidos (num podcast a câmera repete).
    """
    pad = {"complex": False,
           "chain": f"scale={TARGET_W}:-2,pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black",
           "sig": "letterbox", "kind": "letterbox", "label": "letterbox (plano aberto)"}
    if layout == "pad":
        return pad

    people = analyze_people(video, start, dur, src_w, src_h)
    if not people:
        if os.environ.get("RC_VERBOSE"): print("   [crop] sem rosto utilizavel -> letterbox", flush=True)
        return pad

    def big(p):
        return p["w"] >= _zmw()

    def solo(p):
        if big(p):
            return {"complex": False, "chain": _single_face_chain(src_w, src_h, p),
                    "sig": f"solo-{_lado(p['cx'])}", "kind": "solo",  # agrupa por lado, não por cx exato
                    "label": f"solo ({_lado(p['cx'])})"}
        if os.environ.get("RC_VERBOSE"): print("   [crop] rosto pequeno demais p/ zoom -> letterbox", flush=True)
        return pad

    def stack(a, b):
        return {"complex": True, "chain": _two_stack_graph(src_w, src_h, a, b),
                "sig": "stack", "kind": "stack", "label": "empilhado (os dois)"}

    if layout in ("single_face", "solo_left"):  # monólogo: pessoa mais à esquerda
        return solo(people[0])
    if layout == "solo_right":                   # monólogo: pessoa mais à direita
        return solo(people[-1])
    if layout == "two_stack" and len(people) >= 2:
        ab = sorted(people, key=lambda p: p["cx"])[:2]
        return stack(ab[0], ab[1]) if big(ab[0]) and big(ab[1]) else pad

    # auto / talking_head
    if len(people) >= 2:
        top2 = sorted(people, key=lambda p: p["n"], reverse=True)[:2]
        hi, lo = sorted(top2, key=lambda p: p["corr"], reverse=True)
        if os.environ.get("RC_VERBOSE"): print(f"   [crop] 2 rostos corr={hi['corr']}/{lo['corr']} w={round(hi['w'],3)}/{round(lo['w'],3)}", flush=True)
        if hi["corr"] >= CORR_MIN and (hi["corr"] - lo["corr"]) >= CORR_MARGIN:
            if os.environ.get("RC_VERBOSE"): print("   [crop] locutor ativo -> solo", flush=True)
            return solo(hi)
        ab = sorted(top2, key=lambda p: p["cx"])
        if big(ab[0]) and big(ab[1]):
            if os.environ.get("RC_VERBOSE"): print("   [crop] os dois falam -> empilhado", flush=True)
            return stack(ab[0], ab[1])
        if os.environ.get("RC_VERBOSE"): print("   [crop] empilhar pixelaria -> solo no maior / letterbox", flush=True)
        return solo(max(top2, key=lambda p: p["w"]))

    if os.environ.get("RC_VERBOSE"): print("   [crop] 1 rosto -> solo", flush=True)
    return solo(people[0])


def build_vertical_filter(video, start, dur, src_w, src_h, layout="auto"):
    """Filtro 9:16 pro cut (só {complex, chain}). Wrapper fino de plan_vertical_filter."""
    d = plan_vertical_filter(video, start, dur, src_w, src_h, layout)
    return {"complex": d["complex"], "chain": d["chain"]}
