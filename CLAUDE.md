# reel-cut — contexto pra Claude

Tool local de edição de vídeo do Vitor Peçanha. **Este repositório é o código da tool**
(desenvolvimento). O uso no dia a dia é via skill nível-usuário `/reel-cut`
(`~/.claude/skills/reel-cut/SKILL.md`), que aponta pra cá.

Mudou pra `claude_projects\reel-cut\` em 2026-06-16 (antes ficava em `reel-editor\reel-cut\`,
fora do Dropbox). O backup antigo segue intacto até validação.

## O que é

Gravação longa talking-head (live/aula/podcast) → clipes verticais 9:16 com legenda
queimada. **A segmentação (escolha dos trechos) é feita pelo Claude na sessão**, sem API
paga — é decisão de design do Vitor, não trocar por heurística/API.

- **Fase 1 — `clip_live.py`** (✅ validada): long → clipes verticais. Crop **ciente de cena**
  (`rc_scene`) + **locutor ativo** (`rc_crop`): 1 falando = solo; 2 se revezando = empilha;
  rosto pequeno/plano aberto = letterbox. Legenda ASS word-highlight (`rc_captions`).
- **Fase 2 — `retake_editor.py`** (🚧 esqueleto): gravação de corrido → detecta retakes →
  mantém a take boa. Falta `assemble` + sample real. Ver `PLAN-retake.md`.

## Como rodar (entrypoint único, OS-agnóstico)

```
python reel_cut.py setup                              # deps, modelos, ffmpeg/Deno/CUDA
python reel_cut.py transcribe --file v.mp4 --out work/x   # (ou --url ...)
#  Claude lê work/x/transcript.txt, escreve work/x/segments.json
python reel_cut.py cut --work work/x                 # clipes em work/x/output/
```

`reel_cut.py` força encoding utf-8 e resolve CUDA→CPU e PATH do Deno sozinho — **não**
precisa de `PYTHONIOENCODING` nem mexer no PATH manualmente.

## Estrutura

| Arquivo | Papel |
|---|---|
| `reel_cut.py` | entrypoint (`setup`/`probe`/`transcribe`/`captions`/`preview`/`cut`) |
| `clip_live.py` | lógica da Fase 1 |
| `rc_whisper.py` | transcrição (faster-whisper pip, CUDA→CPU; `initial_prompt` do glossário) |
| `rc_scene.py` / `rc_crop.py` | detecção de cena + crop 9:16 ciente de rosto (`plan_vertical_filter` expõe a assinatura do plano) |
| `rc_captions.py` | legenda ASS word-highlight (tunables no topo) |
| `rc_caption_editor.py` | editor local de legenda (peça 2): servidor stdlib, abas por corte, find-replace, glossário |
| `rc_framing.py` | preview de enquadramento (peça 4): planeja crop por plano, dedup, before/after, `framing.json` |
| `rc_glossary.py` | glossário de correções por canal (peça 2): `glossaries/<slug>.json` |
| `rc_ffmpeg.py` / `rc_setup.py` | wrappers ffmpeg + setup |
| `retake_*.py` | Fase 2 (esqueleto) |
| `models/` | YuNet (versionado) |
| `glossaries/` | glossário por canal (criado sob demanda pelo editor) |
| `output/` | container dos jobs: uma pasta por título (`output/<slug>/`), clipes finais em `output/<slug>/clipes/`. **gitignored E ignorado do Dropbox** (mídia pesada). (`work/` é legado de teste.) |

## Regras (ignorar = erro)

- **Mídia só dentro de `output/`.** Cada job vira `output/<slug-do-título>/` (sem data); clipes finais
  em `output/<slug>/clipes/`. A pasta `output/` é ignorada do Dropbox (`com.dropbox.ignored`) e do git.
  Nunca colocar `.mp4`/`.wav` fora dela (sincroniza GBs sem querer). (`work/` é só legado de teste.)
- **Portão de revisão editorial (sempre).** Antes de cortar, informar **quantos** clipes e
  perguntar: cortar automático ou revisar cada um? Nunca cortar em batch silencioso.
- **Roadmap em `PLAN-distribuir.md` (fonte de verdade, ler antes de retomar).** Tem DOIS trilhos:
  - **Produtizar** (seção `## Sequência`): virar plugin instalável em qualquer OS. Steps 1-5 feitos
    (inclui auto-calibrar tamanho de rosto + a passada de UX/verbosidade); sobra só 6 (empacotar/git init).
  - **Fluxo de aprovação guiado** (seção `## Fluxo de aprovação guiado`, **pedido do Vitor**): pipeline
    em etapas com OK a cada passo — confirmar vídeo (pós-download) → transcrever → aprovar seleção →
    **editar legenda dos cortes escolhidos** (find-replace global + glossário por canal + editor local
    em abas, 1 por corte) → preview de enquadramento (1 frame por plano) → cortar. Hoje só o passo
    "aprovar seleção" existe (o portão de revisão); 1, 2 e 4 são novos. É a UX do dia a dia, não esquecer.
- **Ao evoluir a tool, atualizar junto** o `SKILL.md` nível-usuário e a memória
  `project_reel_editor_tool.md` (no diretório de memória do Second Brain).
- Sem em-dash em texto (regra geral do Vitor).
