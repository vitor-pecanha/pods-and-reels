# Fase 2 — detector de retake + corte limpo

Estado: **design travado** (Vitor detalhou em 2026-06-15). Infra compartilhada
(transcrição word-level, FFmpeg) já validada na Fase 1. Falta um **sample real** pra
calibrar e construir o `assemble`.

## O fluxo do Vitor (palavras dele)

Grava um Reel talking-head falando. Às vezes erra, para, respira, e volta
**repetindo o trecho** que disse logo antes. A tool deve:

1. Pegar o vídeo, extrair o áudio, transcrever (word-level).
2. Identificar onde ele **falou a mesma coisa duas vezes seguidas** (o erro + a regravação).
3. Em cada par, **descartar a take errada e manter a corrigida** (a que vem **depois**).
4. **Quando estiver ambíguo qual é a boa, perguntar ao Vitor** (não chutar).
5. Tirar **todos os silêncios**.
6. Tirar **sons de hesitação** (é, ã, hmm) pra deixar ágil pra Reels.
7. Montar o corte limpo.

> Esse corte limpo é a **base** pra, depois, tirar o fundo com matting (RobustVideoMatting /
> SAM2). Matting fica pra **fase posterior** (Vitor quer testar o modelo). Não construir agora.

## Pipeline

```
gravação bruta
  → transcrição word-level (rc_whisper, pronto)
  → utterances (quebra por pausa + pontuação)
  → clusters de retake (utterances quase-iguais em sequência)        [retake_detect, 1ª versão]
  → keeper de cada cluster: a ÚLTIMA take (corrigida) por default;
    perguntar ao Vitor quando a similaridade/qualidade for ambígua    [sessão Claude]
  → remover hesitações (é, ã, hmm) + silêncios (gaps entre palavras)  [TODO]
  → montar via FFmpeg concat só com os spans mantidos                 [TODO assemble]
```

## Decisões resolvidas (2026-06-15)

- **Keeper:** última take do cluster (a regravação corrigida). ✅
- **UX:** híbrido — decidir sozinho quando claro, **perguntar quando ambíguo**. ✅
- **Limpeza extra:** silêncios **+ sons de hesitação** (é, ã, hmm). (Respiração e gagueira de
  palavra NÃO foram pedidos; deixar de fora por ora.)
- **Matting:** downstream, fase posterior. ✅

## A construir (próxima rodada, precisa do sample)

1. `assemble`: a partir dos clusters + escolhas, montar a lista de spans a manter
   (dropando takes erradas, silêncios > limiar, e palavras de hesitação) e concatenar com FFmpeg
   (re-encode nos limites pra não dar glitch).
2. Lista de tokens de hesitação PT (é, éé, ã, ãã, hmm, tipo, ...) — calibrar com fala real.
3. Calibrar `PAUSE_GAP` e `SIM_THRESHOLD` (em `retake_detect.py`) num bruto de verdade.

## Gating

Precisa de **uma gravação curta real** (30-90s) onde o Vitor erra de propósito 1-2 trechos
e regrava. Com ela: rodar `detect`, ver os clusters, calibrar limiares, construir e testar
o `assemble`, e entregar o corte limpo pra ele avaliar.
