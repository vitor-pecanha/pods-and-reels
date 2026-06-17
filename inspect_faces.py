"""inspect_faces.py — amostra frames de um vídeo e roda YuNet (debug de layout).

Uso: python inspect_faces.py <video> <out_dir> <t1> <t2> ...
"""
import subprocess
import sys
from pathlib import Path

import cv2

VID = sys.argv[1]
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
MODEL = str(Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx")
times = [float(t) for t in sys.argv[3:]]

det = cv2.FaceDetectorYN.create(MODEL, "", (1920, 1080), 0.6, 0.3, 10)
for i, t in enumerate(times):
    fp = str(OUT / f"f{i:02d}_{int(t)}s.jpg")
    subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", VID, "-frames:v", "1", "-q:v", "2", fp],
                   capture_output=True)
    img = cv2.imread(fp)
    if img is None:
        print(f"{int(t)}s: sem frame")
        continue
    h, w = img.shape[:2]
    det.setInputSize((w, h))
    _, faces = det.detect(img)
    n = 0 if faces is None else len(faces)
    cs = [] if faces is None else [(round((f[0] + f[2] / 2) / w, 2), round((f[1] + f[3] / 2) / h, 2),
                                    round(f[2] / w, 3)) for f in faces]
    print(f"{int(t)}s ({w}x{h}): {n} rosto(s)  [cx,cy,wr]={cs}")
