r"""retake_editor.py — Fase 2 (entry point, 🚧 em construção).

Estágios:
  transcribe : gravação bruta -> transcript.json/txt (reusa rc_whisper)
  detect     : acha clusters de retake -> retakes.json + retakes.txt (p/ revisão)
  assemble   : [TODO] monta o corte limpo com as takes escolhidas + sem silêncio

Handshake (igual à Fase 1): o `detect` para e gera um relatório; o Claude (ou o
Vitor) decide o keeper de cada cluster; o `assemble` consome essa decisão.

Uso:
  python retake_editor.py transcribe --file "C:\bruto.mp4" --out work\reel1
  python retake_editor.py detect --work work\reel1
  # (assemble: a definir — ver PLAN-retake.md)
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import rc_ffmpeg as ff
import rc_whisper as fw
import retake_detect as rd


def cmd_transcribe(args):
    work = Path(args.out)
    work.mkdir(parents=True, exist_ok=True)
    source = str(Path(args.file).resolve())
    w, h = ff.get_dimensions(source)
    dur = ff.get_duration(source)
    parsed = fw.transcribe(source, str(work), lang=args.lang)
    (work / "transcript.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "transcript.txt").write_text(fw.transcript_to_text(parsed["segments"]), encoding="utf-8")
    (work / "meta.json").write_text(json.dumps(
        {"source": source, "width": w, "height": h, "duration": dur}, indent=2), encoding="utf-8")
    print(f"OK -> {work}\\transcript.txt   ({dur/60:.1f} min). Próximo: detect --work {work}")


def cmd_detect(args):
    work = Path(args.work)
    parsed = json.loads((work / "transcript.json").read_text(encoding="utf-8"))
    utts = rd.split_utterances(parsed["words"])
    clusters = rd.find_retake_clusters(utts)

    report = []
    lines = [f"{len(clusters)} cluster(s) de retake encontrados (limiar sim={rd.SIM_THRESHOLD}).\n"]
    for ci, group in enumerate(clusters, 1):
        takes = [{"take": ti + 1, "start": round(u["start"], 2), "end": round(u["end"], 2),
                  "text": u["text"]} for ti, u in enumerate(group)]
        report.append({"cluster": ci, "takes": takes, "suggested_keeper": len(takes)})
        lines.append(f"== Cluster {ci} ({len(takes)} takes) ==")
        for t in takes:
            lines.append(f"  take {t['take']} [{t['start']:.1f}-{t['end']:.1f}s]: {t['text']}")
        lines.append("")

    (work / "retakes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "retakes.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"-> {work}\\retakes.txt  e  retakes.json")
    print("PRÓXIMO: Claude/Vitor escolhe o keeper de cada cluster; depois 'assemble' (TODO).")


def cmd_assemble(args):
    sys.exit("assemble ainda não implementado — ver PLAN-retake.md (decisões de UX pendentes).")


def main():
    p = argparse.ArgumentParser(description="Retake editor (Fase 2, em construção)")
    sub = p.add_subparsers(dest="stage", required=True)

    t = sub.add_parser("transcribe")
    t.add_argument("--file", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--lang", default="pt")
    t.set_defaults(func=cmd_transcribe)

    d = sub.add_parser("detect")
    d.add_argument("--work", required=True)
    d.set_defaults(func=cmd_detect)

    a = sub.add_parser("assemble")
    a.add_argument("--work", required=True)
    a.set_defaults(func=cmd_assemble)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
