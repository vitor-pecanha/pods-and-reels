"""rc_captions.py — TikTok/Reels-style word-highlighted ASS captions.

Style is embedded in the .ass (the validated workaround for the PowerShell
'&H...' force_style breakage). Tunables live in the constants below; we eyeball
on a real clip and adjust. Font sizing assumes PlayRes 1080x1920 (pixels real).
"""
from __future__ import annotations
from pathlib import Path

# ── Tunables (Reels 9:16) ──────────────────────────────────────────────────
FONT_NAME = "Arial Black"
FONT_SIZE = 64            # legível em phone; 80 = mais agressivo estilo creator
OUTLINE = 4
SHADOW = 0
MARGIN_V = 360            # acima da UI do IG/TikTok no rodapé
CHUNK_SIZE = 3            # palavras visíveis por vez
HIGHLIGHT = r"&H0000D4FF"  # amarelo-âmbar (BGR) para a palavra atual
PRIMARY = r"&H00FFFFFF"    # branco para as demais


def _ass_header() -> str:
    return f"""[Script Info]
Title: Reel Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{FONT_SIZE},{PRIMARY},&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{OUTLINE},{SHADOW},2,40,40,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(word: str) -> str:
    return word.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def create_ass_captions(words: list[dict], clip_start: float, clip_end: float,
                        ass_path: str) -> str | None:
    """Write an .ass file with 3-words-at-a-time, current word highlighted.

    `words` carry ABSOLUTE times; we rebase to the clip start.
    """
    clip_words = [w for w in words if w["end"] > clip_start and w["start"] < clip_end]
    if not clip_words:
        return None

    chunks = [clip_words[i:i + CHUNK_SIZE] for i in range(0, len(clip_words), CHUNK_SIZE)]
    events = []
    for ci, chunk in enumerate(chunks):
        # O grupo fica visível continuamente: do 1º som até o início do próximo grupo
        # (sem buracos = sem piscar). O destaque anda palavra a palavra dentro disso.
        disp_start = max(0.0, chunk[0]["start"] - clip_start)
        if ci < len(chunks) - 1:
            disp_end = max(disp_start + 0.1, chunks[ci + 1][0]["start"] - clip_start)
        else:
            disp_end = max(disp_start + 0.3, chunk[-1]["end"] - clip_start + 0.3)

        for wi, w in enumerate(chunk):
            seg_start = disp_start if wi == 0 else max(disp_start, w["start"] - clip_start)
            seg_end = (chunk[wi + 1]["start"] - clip_start) if wi < len(chunk) - 1 else disp_end
            seg_end = min(max(seg_start + 0.05, seg_end), disp_end)
            if seg_end <= seg_start:
                continue
            parts = [
                (f"{{\\c{HIGHLIGHT}&}}{_esc(w2['word'])}{{\\c{PRIMARY}&}}" if wj == wi else _esc(w2["word"]))
                for wj, w2 in enumerate(chunk)
            ]
            events.append(f"Dialogue: 0,{_ass_time(seg_start)},{_ass_time(seg_end)},Default,,0,0,0,,{' '.join(parts)}")

    Path(ass_path).write_text(_ass_header() + "\n".join(events) + "\n", encoding="utf-8")
    return ass_path
