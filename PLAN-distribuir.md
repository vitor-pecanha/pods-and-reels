# #3 — reel-cut como skill multiplataforma instalável

Objetivo: outra pessoa instala o `reel-cut` no Claude Code dela (Win/Mac/Linux) e roda.
A **seleção de clipes continua sendo o Claude da sessão de quem instalou** (sem API paga, sem
heurística). O crop ciente de cena + "rosto pequeno → letterbox" já generaliza (testado em 3
estúdios). O trabalho é tirar as amarras da máquina do Vitor.

## Sequência

1. **Whisper portável (keystone) — ✅ VALIDADO 2026-06-16.** `faster-whisper` 1.2.1 (pip, wheel cp313) +
   `ctranslate2` 4.8 rodou na CUDA do Vitor: 20s em 1,6s, PT, word timestamps corretos. **Receita CUDA portável:**
   `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` + adicionar os dirs `site-packages/nvidia/*/bin` ao loader
   (`os.add_dll_directory` no Win, `LD_LIBRARY_PATH` no Linux); Mac cai pra CPU. Modelo: por nome `large-v3-turbo`
   (auto-download HF na 1ª vez) ou apontar dir existente. ✅ **Feito 2026-06-16:** `rc_whisper.py` virou módulo real
   (API Python, fallback cuda→cpu, `_ensure_cuda_libs` embutido), fiado no `clip_live.py`, testado e2e (CUDA, PT ok).
2. **De-hardcodar.** ✅ **Feito (efeito colateral do #1).** Os `.py` de produção já estão limpos: modelo por nome
   (`RC_WHISPER_MODEL`), YuNet via `Path(__file__).parent/models`, zero `C:\Users\pecan` (só sobra no `_fwtest.py`,
   descartável). Idioma é `--lang` (default pt); estilo de legenda são consts no `rc_captions.py`; device é auto.
3. **Comandos OS-agnósticos.** ✅ **Feito 2026-06-16:** `reel_cut.py` é o entrypoint único (`setup|transcribe|cut`),
   chamado igual em qualquer OS. Encoding utf-8 forçado dentro do Python (sem `PYTHONIOENCODING`). PATH do Deno
   resolvido em runtime (`ensure_deno_on_path`). SKILL.md + README reescritos neutros. `clip_live.py` segue funcionando.
4. **Setup automático.** ✅ **Feito 2026-06-16:** `python reel_cut.py setup` (+ `--check`): `pip install -r
   requirements.txt`, instala `requirements-cuda.txt` só se achar GPU, baixa YuNet se faltar, checa ffmpeg/Deno,
   reporta CUDA vs CPU. `rc_setup.py`. Testado `--check` no Win (tudo verde).
5. **Auto-calibração do tamanho de rosto. ✅ FEITO 2026-06-17.** `rc_crop.calibrate_zoom_min_w()` amostra ~18
   frames pelo vídeo, mede a mediana da largura do MAIOR rosto e seta o limiar de zoom = `mediana * 0.55`,
   clamp entre `ZOOM_FLOOR=0.04` e `ZOOM_CAP=0.08` (em vez do `ZOOM_MIN_W=0.05` fixo). `set_zoom_min_w()`/`_zmw()`
   aplicam o override por vídeo; `rc_framing.plan` calibra uma vez (grava em `framing.json`), `apply_override` e
   `cut` reusam. Mata o knob frágil entre estúdios. Testado: close-up (mediana ~0.115) → 0.063; super aberto → piso 0.04.
6. **Empacotar.** ⬜ Repo próprio (sair de dentro de `reel-editor/`): SKILL.md + rc_*.py + reel_cut.py
   + models/ + requirements.txt + README de install. Distribuível via `npx skills add <repo>` ou plugin.

## Fluxo de aprovação guiado (pedido do Vitor — próxima fase)

Pipeline em etapas, cada uma com OK do usuário. **Ordem:** confirmar vídeo → transcrever → aprovar seleção
→ editar legenda (só dos cortes escolhidos) → preview de enquadramento → cortar.

> **Decisão 2026-06-16 (Vitor):** o preview de enquadramento (peça 4) fica DEPOIS da edição de legenda
> (posição original), logo antes do cut, pra pré-visualizar só os cortes já escolhidos (barato). O requisito
> central é **clareza pro usuário**: pra cada cena, mostrar o frame ORIGINAL ao lado de COMO VAI FICAR no
> 9:16 com o crop planejado, e perguntar explícito "esse enquadramento aqui vai ficar assim, ok?". Foco nas
> cenas onde o layout é decidido pela regra de locutor ativo (uma ou mais pessoas ao mesmo tempo:
> solo/empilhado/letterbox); enquadramento trivial (rosto único óbvio) pode passar sem portão.

1. **Confirmar o vídeo (PRÉ-download) — ✅ FEITO 2026-06-16.** `python reel_cut.py probe --url|--file --out <W>`
   mostra título/duração/resolução/prévia (`poster.jpg`) e PARA, antes de baixar/transcrever. URL: metadados
   só via `yt-dlp --dump-json` (não baixa o vídeo — poster = thumbnail). Arquivo: ffprobe + 1 frame do miolo.
   Claude lê o `poster.jpg`, mostra ao Vitor, e só com OK roda o `transcribe`. (Correção do plano: confirmar
   ANTES do download, não depois — senão baixa 2.6 GB do vídeo errado à toa.) `cmd_probe` no `clip_live.py`.
2. **Editar legenda (opcional, perguntar) — DEPOIS da seleção. Editor local ✅ + glossário ✅ FEITO 2026-06-16.**
   Whisper erra nomes próprios/jargão. ⚠️ O usuário só descobre o erro DEPOIS de ler — editar-depois é o caminho
   principal (glossário-na-origem não resolve a 1ª vez). Como roda após a seleção, edita **só o texto dos cortes
   escolhidos** (não o vídeo todo) = muito mais rápido. Comando: `python reel_cut.py captions --work <W>`.
   - **Editor local ✅ (`rc_caption_editor.py`) — superfície PRINCIPAL de leitura+edição.** Mini-servidor stdlib
     (`http.server` + handler POST), abre o navegador, **uma aba por corte** (de segments.json) só com as palavras
     daquele clipe (de transcript.json). **Find-replace GLOBAL** (vale em todas as abas) embutido no header. Edição
     por **token** (cada palavra é um chip editável): texto trocado = renomeia (mantém start/end); espaço dentro =
     divide a word fatiando o tempo proporcional; vazio = remove. Botão Salvar reconstrói os `words` no
     transcript.json (backup `.bak` na 1ª vez); o `cut` relê isso direto. **Vídeo ao lado** (opcional, range-request)
     pra conferir contexto. Find-replace via chat com o Claude fica como atalho pros casos simples.
   - **Glossário ✅ (`rc_glossary.py`) = aprende-uma-vez-reusa — NA MESMA PÁGINA do editor (pedido do Vitor).**
     No header do editor: campo **Canal** (prefilled do `meta.channel`/uploader), botão **Salvar no glossário**
     (pega as correções de 1 palavra desta sessão, vira `glossaries/<slug>.json`) e **Aplicar glossário** (roda as
     trocas já aprendidas em todas as abas). Paga do 2º episódio: no `transcribe --channel` (ou herdando o uploader
     do `probe.json`) os termos vão como `initial_prompt` pro Whisper E as trocas se auto-aplicam nas words. Casa
     pelo miolo (preserva pontuação); só palavra única (correção multi-palavra vira pares por palavra no editor).
3. **Aprovar a seleção (pré-corte):** Claude propõe trechos (timestamps + por quê) → aprova/edita/descarta.
4. **Preview de enquadramento por cena — ✅ FEITO 2026-06-16 (`rc_framing.py`).** `python reel_cut.py preview --work <W>`,
   DEPOIS da edição de legenda, sobre os cortes JÁ escolhidos. Pra cada corte detecta os planos (`rc_scene`) e decide
   o crop de cada um (`rc_crop.plan_vertical_filter`, mesma regra de locutor ativo do cut). **Dedup por tipo de plano**
   (ideia do Vitor: num podcast a câmera repete, então solo-A/solo-B/empilhado/letterbox são poucos): agrupa por
   assinatura (`sig`) e renderiza só **1 preview before/after por plano único** (frame original | como vai ficar no
   9:16), pro usuário confirmar cada plano UMA vez (vale pra todas as ocorrências). Persiste em `framing.json`; o `cut`
   consome esse arquivo e renderiza exatamente o aprovado (não recalcula). Ajuste por plano: `rc_framing.apply_override(
   work, sig, layout)` (pad/solo_left/solo_right/two_stack/auto) reescreve as ocorrências e re-renderiza o preview.
   ⚠️ Validado e2e só com mídia sintética (letterbox/dedup/cut/override); a classificação por rosto é o `rc_crop` já
   validado, mas falta um teste com **podcast real** pra confirmar solo-A/solo-B/empilhado no preview.
5. **Cut/render** só do que foi aprovado (lê `framing.json` se existir; senão decide na hora, como antes).

Nota: 1, 2 (editor + glossário), 3 e 4 já existem (probe + editor de legenda + portão de revisão + preview de
enquadramento). Todo o fluxo guiado está implementado; falta validar as peças 2 (glossário no 2º episódio) e 4
(planos por rosto) com vídeo real.

## Já pronto (não mexer, só portar)
- Crop ciente de cena (`rc_scene` + `rc_crop`): solo/empilhado/letterbox, locutor ativo, `solo_left/right`.
- Legenda ASS contínua (`rc_captions`).
- Handshake transcribe → Claude escreve segments.json → cut.

## Riscos
- **cuDNN/CUDA no Windows** pro faster-whisper pip (DLLs). Subtitle Edit já roda CTranslate2 na GPU dele,
  então o suporte existe; pode precisar apontar libs.
- **yt-dlp/YouTube** endurecendo (challenge solver). Encapsular e documentar; download de YouTube é o elo frágil.
- ffmpeg como dep de sistema (não-pip): o setup tem que orientar instalar por OS.
