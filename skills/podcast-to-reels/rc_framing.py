r"""rc_framing.py — Peça 4: preview de enquadramento por cena, ANTES do cut.

Roda DEPOIS da seleção (e da edição de legenda), sobre os cortes JÁ escolhidos.
Pra cada corte detecta os planos (rc_scene) e decide o crop de cada um (rc_crop,
mesma regra de locutor ativo do cut), DEDUPLICA por tipo de plano (num podcast a
câmera repete: solo-A, solo-B, empilhado e letterbox são poucos), e renderiza UM
preview **before/after** por plano único (frame original | como vai ficar no 9:16).

Persiste o plano em `framing.json`. O `cut` consome esse arquivo e renderiza
exatamente o que foi aprovado (não recalcula o crop). Assim o portão "esse
enquadramento aqui vai ficar assim, ok?" tem efeito real no corte.

framing.json:
  {"clips": [{"seg_index", "title", "start", "end",
              "shots": [{"start","end","sig","label","kind","complex","chain","override"}]}],
   "framings": [{"sig","label","kind","occurrences","layout","preview"}]}   # dedup p/ o usuário
"""
from __future__ import annotations
import json
import os
import shutil
import tempfile
from pathlib import Path

import rc_ffmpeg as ff
import rc_scene as scene
import rc_crop as crop


# ── render do preview before/after ───────────────────────────────────────────

def _render_preview(video: str, rep: dict, out_a: Path, out_b: Path) -> None:
    """Renderiza DOIS frames: out_a = original 16:9; out_b = resultado 9:16 do crop.

    Separados (não mais colados) pra a página mostrar com espaço + seta no meio.
    """
    t = (rep["start"] + rep["end"]) / 2.0
    ff.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", video,
            "-frames:v", "1", "-q:v", "3", str(out_a)])
    if rep["complex"]:
        ff.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", video,
                "-frames:v", "1", "-filter_complex", rep["chain"], "-map", "[vid]",
                "-q:v", "3", str(out_b)])
    else:
        ff.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", video,
                "-frames:v", "1", "-vf", rep["chain"], "-q:v", "3", str(out_b)])


# ── planejamento + dedup ─────────────────────────────────────────────────────

def plan(work_dir: str, render: bool = True) -> dict:
    """Planeja o enquadramento de todos os cortes, deduplica e grava framing.json."""
    work = Path(work_dir)
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    segments = json.loads((work / "segments.json").read_text(encoding="utf-8"))
    video, src_w, src_h = meta["source"], meta["width"], meta["height"]

    prev_dir = work / "preview"
    prev_dir.mkdir(parents=True, exist_ok=True)

    # Auto-calibra o limiar de zoom pelo tamanho típico de rosto DESTE vídeo (uma vez).
    zmw = crop.calibrate_zoom_min_w(video, src_w, src_h, float(meta.get("duration", 0)))
    crop.set_zoom_min_w(zmw)
    if os.environ.get("RC_VERBOSE"):
        print(f"[framing] limiar de zoom auto-calibrado: {zmw} (default era {crop.ZOOM_MIN_W})", flush=True)

    clips: list[dict] = []
    framings: dict[str, dict] = {}  # sig -> grupo (com rep = plano mais longo, p/ renderizar)
    for si, seg in enumerate(segments):
        start, end = float(seg["start"]), float(seg["end"])
        layout = seg.get("layout", "auto")
        cuts = [] if layout == "pad" else scene.detect_cuts(video, start, end)
        shots = scene.shots_from_cuts(start, end, cuts)
        print(f"[framing] corte {si + 1} '{seg.get('title', '')}': {len(shots)} plano(s)", flush=True)

        shot_plans = []
        for a, b in shots:
            d = crop.plan_vertical_filter(video, a, b - a, src_w, src_h, layout)
            shot_plans.append({"start": a, "end": b, "sig": d["sig"], "label": d["label"],
                               "kind": d["kind"], "complex": d["complex"], "chain": d["chain"],
                               "override": None})
            g = framings.setdefault(d["sig"], {"sig": d["sig"], "label": d["label"], "kind": d["kind"],
                                               "occurrences": 0, "layout": layout,
                                               "preview_a": None, "preview_b": None, "_rep": None})
            g["occurrences"] += 1
            if g["_rep"] is None or (b - a) > (g["_rep"]["end"] - g["_rep"]["start"]):
                g["_rep"] = {"start": a, "end": b, "complex": d["complex"], "chain": d["chain"]}
        clips.append({"seg_index": si, "title": seg.get("title", f"clip{si + 1}"),
                      "start": start, "end": end, "shots": shot_plans})

    framing_list = list(framings.values())
    if render:
        for i, g in enumerate(framing_list):
            a, b = prev_dir / f"framing{i:02d}_a.jpg", prev_dir / f"framing{i:02d}_b.jpg"
            try:
                _render_preview(video, g["_rep"], a, b)
                g["preview_a"], g["preview_b"] = str(a), str(b)
            except Exception as e:
                print(f"[framing] falha ao renderizar preview de '{g['sig']}': {e}", flush=True)
    for g in framing_list:
        g.pop("_rep", None)

    out = {"clips": clips, "framings": framing_list, "zoom_min_w": zmw}
    (work / "framing.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ── override (o usuário troca o layout de um plano; vale pra todas as ocorrências) ─

def apply_override(work_dir: str, sig: str, layout: str, render: bool = True) -> dict:
    """Força `layout` em todos os planos com assinatura `sig` e regrava framing.json.

    layout: 'pad' (letterbox), 'solo_left', 'solo_right', 'two_stack' ou 'auto'.
    """
    work = Path(work_dir)
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    video, src_w, src_h = meta["source"], meta["width"], meta["height"]
    data = json.loads((work / "framing.json").read_text(encoding="utf-8"))
    if data.get("zoom_min_w") is not None:
        crop.set_zoom_min_w(data["zoom_min_w"])  # mesmo limiar calibrado do plano

    rep = None
    new_label = new_kind = None
    for clip in data["clips"]:
        for s in clip["shots"]:
            if s["sig"] == sig:
                d = crop.plan_vertical_filter(video, s["start"], s["end"] - s["start"], src_w, src_h, layout)
                s.update({"complex": d["complex"], "chain": d["chain"], "override": layout,
                          "kind": d["kind"], "label": d["label"]})
                new_label, new_kind = d["label"], d["kind"]
                if rep is None or (s["end"] - s["start"]) > (rep["end"] - rep["start"]):
                    rep = {"start": s["start"], "end": s["end"], "complex": d["complex"], "chain": d["chain"]}
    if rep is None:
        raise ValueError(f"assinatura '{sig}' não encontrada no framing.json")

    # atualiza o grupo de dedup correspondente (layout + label/kind do novo enquadramento)
    for i, g in enumerate(data["framings"]):
        if g["sig"] == sig:
            g["layout"] = layout
            if new_label:
                g["label"], g["kind"] = new_label, new_kind
            if render:
                a = work / "preview" / f"framing_ovr_{i:02d}_a.jpg"
                b = work / "preview" / f"framing_ovr_{i:02d}_b.jpg"
                try:
                    _render_preview(video, rep, a, b)
                    g["preview_a"], g["preview_b"] = str(a), str(b)
                except Exception as e:
                    print(f"[framing] falha ao renderizar override de '{sig}': {e}", flush=True)
            break

    (work / "framing.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
