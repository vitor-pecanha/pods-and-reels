---
name: podcast-to-reels
description: "Transforma uma gravação longa (podcast, live, aula, vídeo falado) em clipes verticais com legenda, prontos pra Reels, Shorts e TikTok."
metadata:
  category: "video"
  requires:
    bins: [python, ffmpeg]
---

# podcast-to-reels

Transforma uma gravação longa talking-head em clipes verticais 9:16 com legenda. A **segmentação
(escolha dos trechos) é feita por mim (Claude) na sessão**, sem API paga. Entrypoint único
OS-agnóstico: `reel_cut.py`, ao lado deste SKILL.md.

**Os scripts ficam na pasta deste skill.** Sempre invocar pelo caminho `${CLAUDE_SKILL_DIR}` (o Claude Code
resolve em qualquer OS), nunca caminho fixo. **Mas a mídia (jobs) NÃO vai pra dentro do plugin:** `${CLAUDE_SKILL_DIR}`
fica num cache recriado a cada atualização do plugin, então a mídia sumiria. Os jobs ficam numa **pasta do usuário**,
por OS: Windows `%USERPROFILE%\Videos\pods-and-reels\<slug>`, macOS `~/Movies/pods-and-reels/<slug>`, Linux
`~/Videos/pods-and-reels/<slug>` (cai pra `~/pods-and-reels` se não houver Videos). Notas de dev: `README.md` /
`PLAN-distribuir.md` na raiz do plugin.

> Encoding utf-8, CUDA→CPU e PATH do Deno são tratados dentro do Python — não precisa de `PYTHONIOENCODING`
> nem mexer no PATH. Logs técnicos só aparecem com `RC_VERBOSE=1` (não ligar no uso normal).

## Setup (primeira vez numa máquina, ou pra diagnosticar)

```
python "${CLAUDE_SKILL_DIR}/reel_cut.py" setup           # instala deps, baixa YuNet, checa ffmpeg/Deno/CUDA
python "${CLAUDE_SKILL_DIR}/reel_cut.py" setup --check    # só diagnostica, não instala
```

## Ambiente (referência rápida)

- Transcrição: **faster-whisper** (pip), modelo `large-v3-turbo`, CUDA em Win/Linux (cai
  pra CPU sozinho). Modelo override por env `RC_WHISPER_MODEL`.
- FFmpeg no PATH. yt-dlp via `python -m yt_dlp` (Fase 1 com `--url`); o `setup`/runtime
  acham o Deno (YouTube exige runtime JS) sozinhos.
- Rosto: **opencv-python YuNet** (modelo versionado em `models/`). Crop **ciente de cena**
  (`rc_scene.py`) com **locutor ativo** (correlação boca×áudio): 1 falando -> solo nele;
  2 se revezando -> empilha; plano aberto/rosto pequeno -> **letterbox** (nunca crop cego
  na TV/fundo).

## Fase 1 — gravação longa -> clipes verticais (default)

Quando o Vitor pedir clipes de uma gravação longa (URL do YouTube ou arquivo).

**UX (vale o fluxo todo):** as mensagens pro usuário são **curtas, em destaque** (emoji + linha em branco antes/depois),
sem jargão interno (nada de `layout:auto`, `sig`, caminhos de dev, comandos crus). Os scripts já imprimem mensagens
limpas em PT; **logs técnicos ficam atrás de `RC_VERBOSE=1`** (não ligar no uso normal). Cada **portão** é uma pergunta
simples; páginas de revisão (legenda, enquadramento) **só abrem se o usuário disser sim**. Erros que o próprio sistema
(Whisper) cometeu, corrigir **por baixo dos panos** — não expor ao usuário (não foi erro dele, confunde).

1. **Pasta do job:** uma pasta **do usuário** (NUNCA dentro do plugin/`${CLAUDE_SKILL_DIR}`, que vive num cache
   recriado a cada atualização do plugin: a mídia sumiria). Base por OS: Windows `%USERPROFILE%\Videos\pods-and-reels`,
   macOS `~/Movies/pods-and-reels`, Linux `~/Videos/pods-and-reels` (cai pra `~/pods-and-reels` se não houver Videos).
   O job é `<base>/<slug-do-título>`, slug curto do **título do vídeo** (kebab-case, sem data), ex.:
   `.../pods-and-reels/o-mae-podcast`. Tudo do job (download, transcrição, prévias, clipes) fica nessa pasta; os clipes
   finais em `<JOB>/clipes/`. (Daqui pra frente, `<JOB>` = essa pasta.) Se o usuário quiser outro lugar, ele manda.
2. **Confirmar o vídeo:**
   ```
   python "${CLAUDE_SKILL_DIR}/reel_cut.py" probe --url "<URL>"  --out "<JOB>"     #  ou:  probe --file "C:\...\v.mp4" --out "<JOB>"
   ```
   URL: só metadados (não baixa; prévia = thumbnail). Arquivo: ffprobe + 1 frame do miolo. **Mostrar a prévia pro usuário**
   (`![](<JOB>/poster.jpg)` inline renderiza no Claude Desktop; se não, `Start-Process` abre no visualizador) + título e
   duração, e perguntar: **"É esse vídeo? Posso baixar e transcrever?"**. Só seguir no sim (evita baixar GBs do vídeo errado).
3. **Transcrever** (no sim):
   ```
   python "${CLAUDE_SKILL_DIR}/reel_cut.py" transcribe --url "<URL>"  --out "<JOB>"   #  ou --file "..."
   ```
   Mostra só "Baixando o vídeo..." → "Download concluído." → "Transcrição pronta: X min, Y palavras". (URL privada: pedir o
   arquivo e usar `--file`.)
4. **Ler `<JOB>\transcript.txt` inteiro** e escolher os melhores momentos (hook nos primeiros segundos, ideia completa).
   Default **3-5 clipes** (5 ≈ uma semana de posts); se o usuário quiser mais, ele pede. Reel pode ir **até 90s** se o
   conteúdo for bom — não sinalizar duração ≤90s; só avisar se passar de 90s. Por trecho: `start`/`end` em segundos
   (snap em **fronteira limpa de fala**, sem cortar palavra), `title` curto. Layout é interno (`auto` decide; `solo_left`/
   `solo_right` pra monólogo; `pad` pra slide) — **não mostrar layout pro usuário**.
5. **Portão de seleção:** apresentar a proposta como tabela limpa (**nº, título, trecho `MM:SS-MM:SS`, por quê** — sem layout)
   e perguntar: **corto esses, ou quer ajustar?**. Nunca cortar em batch silencioso sem essa escolha.
6. **Escrever `<JOB>\segments.json`** (com os cortes aprovados): `[{ "start": 73.5, "end": 118.0, "title": "hook", "layout": "auto" }]`.
7. **Portão da legenda (opcional).** Mensagem limpa: **"✅ Cortes mapeados. Quer revisar e corrigir as legendas
   manualmente? Se sim, abro uma página no navegador."** **Só no sim**, rodar `python "${CLAUDE_SKILL_DIR}/reel_cut.py" captions --work "<JOB>"`
   (abre o navegador sozinho; mostrar a URL `http://127.0.0.1:<porta>/` em destaque). Página: abas por corte, blocos
   editáveis (cada bloco = o que aparece junto na tela), vídeo sincronizado ao lado, **Substituição em lote** (de→para em
   todos os cortes). Botão **"Salvar e concluir" (verde)** encerra → grava no `transcript.json` (faz `.bak`) e fecha o
   servidor (eu sou avisado). Find-replace simples (nome repetido) também posso fazer direto na conversa. *(O glossário por
   canal saiu da UI por ora; o `cut` relê o `transcript.json` corrigido sozinho.)*
8. **Portão do enquadramento (opcional).** `python "${CLAUDE_SKILL_DIR}/reel_cut.py" preview --work "<JOB>"` **planeja** o crop por plano,
   agrupa planos repetidos (dedup por lado: solo centro/esq/dir, empilhado, letterbox) e renderiza before/after. Mensagem
   limpa: **"✅ Modelos de recorte prontos (N planos). Quer revisar o enquadramento no navegador?"** **Só no sim** ele abre
   a página (before/after com seta `→`; trocar layout por plano re-renderiza na hora). No fim, **2 CTAs**: **"Legenda
   queimada" (verde)** ou **"Arquivo .ass à parte"** — grava `cut_options.json` e fecha (eu sou avisado). Se o usuário pular
   a revisão, perguntar só queimada vs arquivo.
9. **Cortar:** `python "${CLAUDE_SKILL_DIR}/reel_cut.py" cut --work "<JOB>"` (lê `framing.json` + `cut_options.json`; "queimada" queima a
   legenda, "arquivo" entrega o `.mp4` limpo + o `.ass` ao lado). Mostra "Gerando N clipe(s)..." → "Pronto: N/N clipes".
10. **Entregar com mensagem EVIDENTE** (emoji + separadores), listando os clipes como **links clicáveis** + a pasta como link:
    ```
    ## 🎬 N clipes prontos!
    1. [Título do corte](<JOB>/clipes/01_....mp4) · 43s
    ...
    📁 Pasta: [<JOB>/clipes](<JOB>/clipes)
    ```
    Oferecer abrir a pasta (`Start-Process explorer "<JOB>\clipes"`).

Ajustes de legenda (font, margem, palavras por vez, cor): topo de `rc_captions.py`.

## Fase 2 — limpar gravação de corrido (retakes) — EM CONSTRUÇÃO

Quando o Vitor gravar de corrido (errando e regravando) e quiser o corte limpo:

```
python "${CLAUDE_SKILL_DIR}/retake_editor.py" transcribe --file "<bruto>" --out "<WORK>"
python "${CLAUDE_SKILL_DIR}/retake_editor.py" detect --work "<WORK>"
```
`detect` gera `retakes.txt`/`retakes.json` com os clusters de takes repetidas. Eu (ou o Vitor)
escolho o keeper de cada cluster. O `assemble` (montar o corte final) **ainda não está pronto**:
ver decisões abertas em `PLAN-retake.md` na raiz do plugin (UX da escolha; corte de silêncio nativo vs Auto-Editor;
precisa de um sample real pra calibrar).

## Ideias futuras anotadas

- Layout `screen_share_overlay` (slide em cima + webcam embaixo): NÃO útil hoje (decisão do Vitor).
- "Talking head sobre outra imagem": matting por IA (RobustVideoMatting na GPU, ou SAM2 do Kdenlive)
  gera o alpha, FFmpeg compõe. FFmpeg sozinho só faz chroma key (fundo verde). Candidato a modo futuro.
