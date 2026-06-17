r"""rc_glossary.py — glossário de correções por canal/programa (parte da peça 2).

O Whisper erra sempre os mesmos nomes próprios/jargão de um programa. As correções
que o Vitor faz no editor de legenda viram um glossário POR CANAL, e do 2º episódio
em diante isso paga em dois pontos:

  1) antes de transcrever: os termos certos vão como `initial_prompt` pro Whisper
     (ele erra menos na origem);
  2) depois de transcrever: as trocas errado->certo se auto-aplicam nas words.

Um arquivo por canal em `glossaries/<slug>.json`:
  {"channel": "...", "slug": "...",
   "replacements": [{"from": "Pesanha", "to": "Peçanha"}, ...],
   "terms": ["Peçanha", ...]}            # = lados 'to' únicos (p/ initial_prompt)

Guardado por palavra única e sem pontuação nas pontas (find-replace confiável).
"""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path

GLOSS_DIR = Path(__file__).resolve().parent / "glossaries"
_PUNCT = " \t\r\n.,;:!?\"'()[]{}…“”‘’«»¿¡-—"


def slug(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^\w\s-]", "", n).strip().lower()
    n = re.sub(r"[\s_-]+", "-", n)
    return n or "canal"


def path(name: str) -> Path:
    return GLOSS_DIR / f"{slug(name)}.json"


def load(name: str) -> dict | None:
    p = path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _core(s: str) -> str:
    """Tira pontuação das pontas; sobra o miolo (a palavra de fato)."""
    return (s or "").strip(_PUNCT)


def _norm_pairs(pairs: list[dict]) -> list[dict]:
    """Limpa: vira (miolo errado -> miolo certo), dedup, descarta vazio/igual/multi-palavra."""
    out, seen = [], set()
    for pr in pairs:
        a, b = _core(pr.get("from", "")), _core(pr.get("to", ""))
        if not a or not b or a == b or " " in a or a in seen:
            continue
        seen.add(a)
        out.append({"from": a, "to": b})
    return out


def save(name: str, pairs: list[dict]) -> dict:
    """Funde `pairs` (errado->certo) no glossário do canal e grava. Mesma 'from' sobrescreve."""
    GLOSS_DIR.mkdir(parents=True, exist_ok=True)
    g = load(name) or {"channel": name, "slug": slug(name), "replacements": []}
    by_from = {r["from"]: r["to"] for r in g.get("replacements", [])}
    for pr in _norm_pairs(pairs):
        by_from[pr["from"]] = pr["to"]
    g["channel"] = name
    g["slug"] = slug(name)
    g["replacements"] = [{"from": k, "to": v} for k, v in sorted(by_from.items())]
    g["terms"] = sorted(set(by_from.values()))
    path(name).write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")
    return g


def terms(g: dict | None) -> list[str]:
    if not g:
        return []
    return g.get("terms") or sorted({r["to"] for r in g.get("replacements", [])})


def initial_prompt(g: dict | None) -> str | None:
    """String de contexto pro Whisper (os nomes certos), ou None."""
    t = terms(g)
    return ", ".join(t) if t else None


def apply_to_words(words: list[dict], g: dict | None) -> int:
    """Aplica as trocas do glossário nas words (casa pelo miolo, preserva pontuação). Devolve nº trocado."""
    if not g:
        return 0
    m = {r["from"]: r["to"] for r in g.get("replacements", [])}
    n = 0
    for w in words:
        core = _core(w["word"])
        if core in m and core != m[core]:
            w["word"] = w["word"].replace(core, m[core], 1)
            n += 1
    return n
