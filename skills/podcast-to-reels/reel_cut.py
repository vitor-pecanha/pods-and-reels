"""reel_cut.py — entrypoint único, OS-agnóstico, do reel-cut.

Chamado igual em qualquer OS (sem PowerShell, sem PYTHONIOENCODING manual, sem
paths fixos):

  python reel_cut.py setup                       # instala deps, baixa modelos, checa ffmpeg/Deno
  python reel_cut.py probe --url <URL> --out work/x        # (ou --file ...) confirmar o vídeo antes
  python reel_cut.py transcribe --file v.mp4 --out work/x   # (ou --url ...)
  python reel_cut.py cut --work work/x

Fase 1 (clipes verticais) vive em clip_live.py; este arquivo só é a porta de entrada
neutra + o `setup`. Encoding utf-8 é forçado aqui pra acento não virar mojibake no
console (Windows herda cp1252).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# Console em utf-8 em qualquer plataforma (substitui o $env:PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

# Roda de qualquer CWD: garante que os módulos rc_*/clip_live sejam importáveis.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _cmd_setup(args):
    import rc_setup
    return rc_setup.run(check_only=args.check)


def main():
    p = argparse.ArgumentParser(prog="reel_cut", description="reel-cut — gravação longa -> clipes verticais 9:16")
    sub = p.add_subparsers(dest="stage", required=True)

    s = sub.add_parser("setup", help="instala deps, baixa modelos, checa ffmpeg/Deno")
    s.add_argument("--check", action="store_true", help="só diagnostica, não instala")
    s.set_defaults(func=_cmd_setup)

    pr = sub.add_parser("probe", help="confirmar o vídeo (título/duração/prévia) ANTES de baixar/transcrever")
    gp = pr.add_mutually_exclusive_group(required=True)
    gp.add_argument("--url")
    gp.add_argument("--file")
    pr.add_argument("--out", required=True)

    t = sub.add_parser("transcribe", help="baixar/abrir vídeo -> Whisper -> transcript.txt")
    g = t.add_mutually_exclusive_group(required=True)
    g.add_argument("--url")
    g.add_argument("--file")
    t.add_argument("--out", required=True)
    t.add_argument("--lang", default="pt")
    t.add_argument("--channel", default=None, help="canal/programa (usa o glossário: initial_prompt + auto-correção)")

    ec = sub.add_parser("captions", help="editor local de legenda dos cortes (abas por corte, find-replace, salva no transcript.json)")
    ec.add_argument("--work", required=True)
    ec.add_argument("--port", type=int, default=0, help="porta do servidor local (0 = livre)")
    ec.add_argument("--no-browser", action="store_true", help="não abrir o navegador automaticamente")

    pv = sub.add_parser("preview", help="preview de enquadramento por plano (before/after, dedup) numa página, antes do cut")
    pv.add_argument("--work", required=True)
    pv.add_argument("--no-render", action="store_true", help="só planeja/dedup, não renderiza as imagens")
    pv.add_argument("--no-serve", action="store_true", help="não abrir a página; só gera os previews e o framing.json")
    pv.add_argument("--no-browser", action="store_true", help="sobe a página mas não abre o navegador")
    pv.add_argument("--port", type=int, default=0, help="porta do servidor local (0 = livre)")

    c = sub.add_parser("cut", help="segments.json -> clipes verticais com legenda")
    c.add_argument("--work", required=True)

    args = p.parse_args()
    if args.stage == "setup":
        sys.exit(args.func(args))

    import clip_live  # lazy: setup não deve exigir as libs pesadas instaladas ainda
    {"probe": clip_live.cmd_probe,
     "transcribe": clip_live.cmd_transcribe,
     "captions": clip_live.cmd_captions,
     "preview": clip_live.cmd_preview,
     "cut": clip_live.cmd_cut}[args.stage](args)


if __name__ == "__main__":
    main()
