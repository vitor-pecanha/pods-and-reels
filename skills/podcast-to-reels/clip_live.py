r"""clip_live.py — Phase 1: long video (live) -> vertical captioned clips.

Stages, on purpose, so the *segmentation* happens in the Claude Code
session (no paid API):

  0) probe      : confirm the video BEFORE the heavy work — title/duration/poster.
                  URL -> metadata only (yt-dlp --dump-json, no full download);
                  file -> ffprobe + 1 mid frame. Then STOP for the user's OK.
  1) transcribe : download (or take a local file) -> Whisper -> transcript.txt
                  Then STOP. Claude reads transcript.txt and writes segments.json.
  -) captions   : (optional, after selection) local editor — one tab per clip —
                  to fix the words Whisper got wrong before burning them in.
  -) preview    : (optional, before cut) framing preview per shot, deduped by
                  shot type — before/after, approve once per unique framing.
                  Writes framing.json, which `cut` then renders verbatim.
  2) cut        : read segments.json (+ framing.json if present) -> cut + 9:16
                  crop + burn captions.

segments.json schema (a JSON array):
  [{"start": 73.5, "end": 118.0, "title": "hook do curso",
    "layout": "auto"}, ...]    # start/end in SECONDS; layout optional

Usage:
  python clip_live.py transcribe --url "https://youtu.be/ID" --out work\live
  python clip_live.py transcribe --file "C:\\path\\video.mp4" --out work\live
  python clip_live.py cut --work work\live
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import rc_ffmpeg as ff
import rc_whisper as fw
import rc_captions as cap
import rc_crop as crop
import rc_scene as scene


# ── stage: probe (confirmar o vídeo ANTES do trabalho pesado) ────────────────

def _fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def probe_url(url: str) -> dict:
    """Metadados do YouTube SEM baixar o vídeo (yt-dlp --dump-json)."""
    from rc_setup import ensure_deno_on_path  # alguns extractors exigem runtime JS
    ensure_deno_on_path()
    cmd = [sys.executable, "-m", "yt_dlp", "--dump-json", "--no-warnings", "--no-playlist", url]
    if os.environ.get("RC_VERBOSE"):
        print("[yt-dlp] $ " + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp --dump-json falhou:\n{(proc.stderr or '')[-600:]}")
    info = json.loads(proc.stdout.splitlines()[0])  # 1ª linha = o vídeo (--no-playlist)
    return {
        "kind": "url", "url": url,
        "title": info.get("title") or url,
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": float(info.get("duration") or 0.0),
        "width": info.get("width"), "height": info.get("height"),
        "thumbnail": info.get("thumbnail"),
    }


def cmd_probe(args):
    work = Path(args.out)
    work.mkdir(parents=True, exist_ok=True)
    poster = work / "poster.jpg"

    if args.url:
        info = probe_url(args.url)
        if info.get("thumbnail"):
            try:
                ff.extract_frame(info["thumbnail"], None, str(poster))
            except Exception as e:
                print(f"[probe] thumbnail falhou ({e}); seguindo sem prévia.", flush=True)
    else:
        source = str(Path(args.file).resolve())
        w, h = ff.get_dimensions(source)
        dur = ff.get_duration(source)
        info = {"kind": "file", "source": source, "title": Path(source).name,
                "uploader": "", "duration": dur, "width": w, "height": h}
        t = min(max(dur * 0.5, 0.0), max(dur - 0.1, 0.0))  # miolo: evita frame 0 preto
        try:
            ff.extract_frame(source, t, str(poster))
        except Exception as e:
            print(f"[probe] frame falhou ({e}); seguindo sem prévia.", flush=True)

    info["poster"] = str(poster) if poster.exists() else None
    (work / "probe.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    dim = f"{info['width']}x{info['height']}" if info.get("width") else "?"
    print("\n" + "=" * 60)
    print("CONFIRMAR O VÍDEO  (antes de baixar/transcrever)")
    print(f"  Título:    {info['title']}")
    if info.get("uploader"):
        print(f"  Canal:     {info['uploader']}")
    print(f"  Duração:   {_fmt_dur(info['duration'])}  ({info['duration']/60:.1f} min)")
    print(f"  Resolução: {dim}")
    if info.get("poster"):
        print(f"  Prévia:    {info['poster']}")
    print(f"  Origem:    {info.get('url') or info.get('source')}")
    print("-" * 60)
    if args.url:
        print("É esse vídeo? Se sim, baixar e transcrever:")
        print(f'  python reel_cut.py transcribe --url "{args.url}" --out {args.out}')
    else:
        print("É esse vídeo? Se sim, transcrever:")
        print(f'  python reel_cut.py transcribe --file "{info["source"]}" --out {args.out}')
    print("=" * 60)


# ── stage: transcribe ───────────────────────────────────────────────────────

def download(url: str, dl_dir: Path) -> str:
    dl_dir.mkdir(parents=True, exist_ok=True)
    from rc_setup import ensure_deno_on_path  # YouTube exige runtime JS (Deno)
    ensure_deno_on_path()
    verbose = bool(os.environ.get("RC_VERBOSE"))
    cmd = [sys.executable, "-m", "yt_dlp",
           "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
           "--merge-output-format", "mp4", "--no-warnings",
           "-o", str(dl_dir / "%(title)s.%(ext)s"), url]
    if not verbose:
        cmd += ["--quiet", "--no-progress"]  # sem barra de progresso floodando o terminal
    print("Baixando o vídeo...", flush=True)
    proc = subprocess.run(cmd) if verbose else subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (getattr(proc, "stderr", "") or "")[-500:]
        raise RuntimeError("download falhou" + (f":\n{tail}" if tail else ""))
    mp4s = sorted(dl_dir.glob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
    if not mp4s:
        raise RuntimeError("no mp4 after download")
    print("Download concluído.", flush=True)
    return str(mp4s[0])


def cmd_transcribe(args):
    work = Path(args.out)
    work.mkdir(parents=True, exist_ok=True)

    verbose = bool(os.environ.get("RC_VERBOSE"))
    source = download(args.url, work / "download") if args.url else str(Path(args.file).resolve())
    if verbose:
        print(f"[transcribe] source: {source}", flush=True)

    # Canal (peça 2 — glossário): do --channel, ou herda o uploader do probe.json.
    channel = getattr(args, "channel", None) or ""
    if not channel and (work / "probe.json").exists():
        channel = json.loads((work / "probe.json").read_text(encoding="utf-8")).get("uploader", "") or ""
    import rc_glossary as gloss
    g = gloss.load(channel) if channel else None
    if g and verbose:
        print(f"[transcribe] glossário do canal '{channel}': {len(g['replacements'])} regra(s)", flush=True)

    print("Transcrevendo (pode levar alguns minutos)...", flush=True)
    w, h = ff.get_dimensions(source)
    dur = ff.get_duration(source)
    parsed = fw.transcribe(source, str(work), lang=args.lang, initial_prompt=gloss.initial_prompt(g))

    n_fix = gloss.apply_to_words(parsed["words"], g)  # auto-aplica as trocas já aprendidas
    if n_fix and verbose:
        print(f"[transcribe] glossário corrigiu {n_fix} palavra(s) automaticamente", flush=True)

    (work / "transcript.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "transcript.txt").write_text(fw.transcript_to_text(parsed["segments"]), encoding="utf-8")
    (work / "meta.json").write_text(json.dumps(
        {"source": source, "width": w, "height": h, "duration": dur, "channel": channel}, indent=2), encoding="utf-8")

    print(f"Transcrição pronta: {dur/60:.0f} min, {len(parsed['words'])} palavras.", flush=True)


# ── stage: cut ──────────────────────────────────────────────────────────────

def _safe(name: str) -> str:
    return re.sub(r"[^\w\s-]", "", name).strip()[:50].replace(" ", "_") or "clip"


_ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k"]


def _ffmpeg_cmd(video: str, start: float, dur: float, fdict: dict,
                ass_path: str | None, out_path: Path) -> list:
    base = ["ffmpeg", "-y", "-ss", str(start), "-i", video, "-t", str(dur)]
    if fdict["complex"]:
        graph = fdict["chain"]  # termina em [vid]
        if ass_path:
            graph += f";[vid]ass='{ff.ass_filter_path(ass_path)}'[vout]"
            out = "[vout]"
        else:
            out = "[vid]"
        return base + ["-filter_complex", graph, "-map", out, "-map", "0:a?"] + _ENC + [str(out_path)]
    vf = fdict["chain"]
    if ass_path:
        vf += f",ass='{ff.ass_filter_path(ass_path)}'"
    return base + ["-vf", vf] + _ENC + [str(out_path)]


def _render_range(video: str, a: float, b: float, src_w: int, src_h: int,
                  layout: str, ass_path: str | None, out_path: Path,
                  fdict: dict | None = None) -> bool:
    if fdict is None:  # sem plano aprovado (framing.json): decide na hora, como antes
        fdict = crop.build_vertical_filter(video, a, b - a, src_w, src_h, layout)
    proc = ff.run(_ffmpeg_cmd(video, a, b - a, fdict, ass_path, out_path), check=False)
    if proc.returncode == 0:
        return True
    if ass_path:  # caption pass falhou: tenta sem legenda (isola crop x ass)
        print(f"   [cut] falha com legenda, retry limpo. tail:\n{(proc.stderr or '')[-300:]}", flush=True)
        return ff.run(_ffmpeg_cmd(video, a, b - a, fdict, None, out_path), check=False).returncode == 0
    return False


def make_clip(video: str, words: list, seg: dict, src_w: int, src_h: int,
              out_path: Path, shot_plans: list | None = None, burn: bool = True) -> bool:
    start, end = float(seg["start"]), float(seg["end"])
    layout = seg.get("layout", "auto")
    ass_path = str(out_path.with_suffix(".ass"))
    # O .ass é sempre gerado (entregue ao lado do vídeo); só queimamos se burn=True.
    has_caption = cap.create_ass_captions(words, start, end, ass_path) is not None
    cap_arg = ass_path if (has_caption and burn) else None

    if shot_plans:  # plano aprovado na peça 4 (framing.json): usa shots + crops prontos
        shots = [(s["start"], s["end"]) for s in shot_plans]
        fdicts = [{"complex": s["complex"], "chain": s["chain"]} for s in shot_plans]
    else:           # sem preview: detecta e decide na hora, como antes
        cuts = [] if layout == "pad" else scene.detect_cuts(video, start, end)
        shots = scene.shots_from_cuts(start, end, cuts)
        fdicts = [None] * len(shots)

    # Plano único: uma passada só (crop + legenda juntos).
    if len(shots) <= 1:
        return _render_range(video, start, end, src_w, src_h, layout, cap_arg, out_path,
                             fdict=fdicts[0] if fdicts else None)

    # Multi-câmera: renderiza cada plano (sem legenda), concatena, depois queima a legenda.
    if os.environ.get("RC_VERBOSE"):
        print(f"   [scene] {len(shots)} planos -> crop por plano", flush=True)
    tmp = Path(tempfile.mkdtemp(prefix="rc_shots_"))
    try:
        parts = []
        for i, (a, b) in enumerate(shots):
            sp = tmp / f"shot{i:02d}.mp4"
            if _render_range(video, a, b, src_w, src_h, layout, None, sp, fdict=fdicts[i]):
                parts.append(sp)
        if not parts:
            return False
        listf = tmp / "list.txt"
        listf.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        nocap = tmp / "nocap.mp4"
        if ff.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf)] + _ENC + [str(nocap)],
                  check=False).returncode != 0:
            return False
        if has_caption and burn and ff.run(
            ["ffmpeg", "-y", "-i", str(nocap), "-vf", f"ass='{ff.ass_filter_path(ass_path)}'",
             "-c:a", "copy", str(out_path)], check=False).returncode == 0:
            return True
        shutil.copy2(nocap, out_path)  # modo "arquivo à parte" (burn=False) ou fallback: vídeo sem legenda
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_captions(args):
    """Editor local de legenda (abas por corte). Roda APÓS a seleção, ANTES do cut."""
    import rc_caption_editor as ed
    ed.serve(args.work, port=getattr(args, "port", 0), open_browser=not getattr(args, "no_browser", False))


def cmd_preview(args):
    """Peça 4: preview de enquadramento por plano (dedup), ANTES do cut.

    Planeja o crop dos cortes escolhidos, agrupa planos repetidos e renderiza 1
    before/after por plano único em work/preview/. Claude lê os previews, mostra
    ao Vitor ('esse enquadramento vai ficar assim, ok?') e ajusta por plano.
    """
    import rc_framing
    work = Path(args.work)
    if not (work / "segments.json").exists():
        sys.exit(f"segments.json não encontrado em {work}. Faça a seleção antes do preview de enquadramento.")
    plan = rc_framing.plan(args.work, render=not getattr(args, "no_render", False))

    print("\n" + "=" * 60)
    print(f"PREVIEW DE ENQUADRAMENTO — {len(plan['clips'])} corte(s), {len(plan['framings'])} plano(s) único(s)")
    print("(num podcast a câmera repete: você confirma cada plano UMA vez, vale pra todas as ocorrências)")
    for i, g in enumerate(plan["framings"]):
        oc = g["occurrences"]
        print(f"  [{i}] {g['label']}  ·  {oc} ocorrência{'s' if oc > 1 else ''}")
    print("=" * 60)

    if getattr(args, "no_serve", False):
        print("PRÓXIMO: confira os work/<...>/preview/framing0N.jpg; ajuste por plano via")
        print("rc_framing.apply_override(work, sig, layout). Depois: python reel_cut.py cut --work " + str(work))
        return

    import rc_framing_editor
    rc_framing_editor.serve(args.work, port=getattr(args, "port", 0),
                            open_browser=not getattr(args, "no_browser", False))


def cmd_cut(args):
    work = Path(args.work)
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    parsed = json.loads((work / "transcript.json").read_text(encoding="utf-8"))
    seg_file = work / "segments.json"
    if not seg_file.exists():
        sys.exit(f"segments.json não encontrado em {work}. Claude precisa criá-lo a partir de transcript.txt.")
    segments = json.loads(seg_file.read_text(encoding="utf-8"))

    out_dir = work / "clipes"  # clipes finais numa subpasta limpa do job
    out_dir.mkdir(parents=True, exist_ok=True)
    words, video = parsed["words"], meta["source"]
    src_w, src_h = meta["width"], meta["height"]

    verbose = bool(os.environ.get("RC_VERBOSE"))
    # Plano de enquadramento aprovado na peça 4 (opcional): seg_index -> shots prontos.
    framing = None
    fp = work / "framing.json"
    if fp.exists():
        fdata = json.loads(fp.read_text(encoding="utf-8"))
        framing = {c["seg_index"]: c["shots"] for c in fdata["clips"]}
        if fdata.get("zoom_min_w") is not None:
            crop.set_zoom_min_w(fdata["zoom_min_w"])  # mesmo limiar calibrado do preview
    else:
        # cut direto (sem preview): auto-calibra o limiar de zoom pra este vídeo
        crop.set_zoom_min_w(crop.calibrate_zoom_min_w(video, src_w, src_h, float(meta.get("duration", 0))))

    # Legenda: queimada (default) ou em arquivo .ass à parte (escolha da página de enquadramento).
    burn = True
    opt = work / "cut_options.json"
    if opt.exists():
        burn = json.loads(opt.read_text(encoding="utf-8")).get("captions", "burn") != "file"

    print(f"Gerando {len(segments)} clipe(s)" + (" com legenda queimada..." if burn else " (legenda em arquivo .ass)..."), flush=True)
    results = []
    for i, seg in enumerate(segments, 1):
        title = seg.get("title", f"clip{i}")
        out_path = out_dir / f"{i:02d}_{_safe(title)}.mp4"
        if verbose:
            print(f"\n--- Clip {i}: {title} ({seg['start']:.1f}s -> {seg['end']:.1f}s) ---", flush=True)
        shot_plans = framing.get(i - 1) if framing else None
        if make_clip(video, words, seg, src_w, src_h, out_path, shot_plans=shot_plans, burn=burn):
            w, h = ff.get_dimensions(str(out_path))
            results.append((title, str(out_path), w, h, ff.get_duration(str(out_path))))
        elif verbose:
            print(f"   FALHOU: {title}", flush=True)

    print(f"Pronto: {len(results)}/{len(segments)} clipes em {out_dir}" + ("" if burn else " (+ .ass ao lado de cada um)"), flush=True)


def main():
    p = argparse.ArgumentParser(description="Live -> vertical captioned clips (Phase 1)")
    sub = p.add_subparsers(dest="stage", required=True)

    pr = sub.add_parser("probe")
    gp = pr.add_mutually_exclusive_group(required=True)
    gp.add_argument("--url")
    gp.add_argument("--file")
    pr.add_argument("--out", required=True)
    pr.set_defaults(func=cmd_probe)

    t = sub.add_parser("transcribe")
    g = t.add_mutually_exclusive_group(required=True)
    g.add_argument("--url")
    g.add_argument("--file")
    t.add_argument("--out", required=True)
    t.add_argument("--lang", default="pt")
    t.add_argument("--channel", default=None)
    t.set_defaults(func=cmd_transcribe)

    ec = sub.add_parser("captions")
    ec.add_argument("--work", required=True)
    ec.add_argument("--port", type=int, default=0)
    ec.add_argument("--no-browser", action="store_true")
    ec.set_defaults(func=cmd_captions)

    pv = sub.add_parser("preview")
    pv.add_argument("--work", required=True)
    pv.add_argument("--no-render", action="store_true")
    pv.add_argument("--no-serve", action="store_true")
    pv.add_argument("--no-browser", action="store_true")
    pv.add_argument("--port", type=int, default=0)
    pv.set_defaults(func=cmd_preview)

    c = sub.add_parser("cut")
    c.add_argument("--work", required=True)
    c.set_defaults(func=cmd_cut)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
