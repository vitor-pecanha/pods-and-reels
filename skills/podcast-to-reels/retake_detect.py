"""retake_detect.py — Fase 2 (núcleo): achar trechos repetidos (retakes).

⚠️ Status: primeira versão das funções puras (split/similaridade/cluster). Sem
dependência nova (só stdlib). AINDA NÃO testado num bruto real com retakes — os
limiares (PAUSE_GAP, SIM_THRESHOLD) precisam ser calibrados com uma gravação de
verdade. Ver PLAN-retake.md.

Entrada: lista de palavras [{"word","start","end"}] (de rc_whisper).
"""
from __future__ import annotations
import re
from difflib import SequenceMatcher

PAUSE_GAP = 0.7          # s de silêncio que encerra uma "fala"
SIM_THRESHOLD = 0.65     # similaridade p/ considerar duas falas a mesma (retake)
LOOKAHEAD = 3            # quantas falas seguintes comparar


def _norm(text: str) -> list[str]:
    return re.sub(r"[^\w\sÀ-ÿ]", "", text.lower()).split()


def split_utterances(words: list[dict]) -> list[dict]:
    """Quebra a sequência de palavras em falas por pausa ou pontuação forte."""
    utts, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 0.0
        ends_sentence = w["word"].endswith((".", "!", "?"))
        if gap >= PAUSE_GAP or ends_sentence:
            utts.append(_pack(cur))
            cur = []
    if cur:
        utts.append(_pack(cur))
    return utts


def _pack(ws: list[dict]) -> dict:
    text = " ".join(w["word"] for w in ws).strip()
    return {"start": ws[0]["start"], "end": ws[-1]["end"], "text": text,
            "tokens": _norm(text)}


def similarity(a: dict, b: dict) -> float:
    if not a["tokens"] or not b["tokens"]:
        return 0.0
    return SequenceMatcher(None, a["tokens"], b["tokens"]).ratio()


def find_retake_clusters(utts: list[dict]) -> list[list[dict]]:
    """Agrupa falas consecutivas parecidas (tentativas do mesmo trecho).

    Retorna só os clusters com 2+ takes. Heurística: a última take do cluster é o
    keeper provável — mas a escolha final é do Claude/Vitor (ver retake_editor).
    """
    clusters, i = [], 0
    while i < len(utts):
        group = [utts[i]]
        j = i + 1
        while j < len(utts) and j <= i + LOOKAHEAD:
            if similarity(utts[i], utts[j]) >= SIM_THRESHOLD:
                group.append(utts[j])
                j += 1
            else:
                break
        if len(group) >= 2:
            clusters.append(group)
            i = j
        else:
            i += 1
    return clusters


# TODO (próxima sessão, depende de decisão de UX + sample real):
#  - score_take(utt, audio): marcadores de hesitação, completude, ritmo/energia
#  - build_keep_spans(utts, clusters, choices): lista de [start,end] a manter
#  - (corte de silêncio: dropar gaps > limiar usando os mesmos timestamps)
