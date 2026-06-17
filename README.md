# pods-and-reels

Plugin do Claude Code pra transformar **gravações longas talking-head** (podcast, live, aula) em
**clipes verticais 9:16 com legenda queimada**, prontos pra Reels / Shorts / TikTok.

A **escolha dos trechos é feita pelo Claude na sua sessão** (sem API paga): ele lê a transcrição,
sugere os melhores cortes, você aprova. O crop é **ciente de cena e de quem está falando** (solo /
empilhado / letterbox) e se auto-calibra ao enquadramento de cada estúdio.

> `podcast-to-reels` é a primeira skill do plugin; outras virão.

## Pré-requisitos

- **Python 3.10+**
- **ffmpeg** no PATH (`winget install Gyan.FFmpeg` / `brew install ffmpeg` / `apt install ffmpeg`)
- Opcional: **GPU NVIDIA** (transcrição na CUDA; sem ela cai pra CPU) e **Deno** (só pra baixar do YouTube)

## Instalar (Claude Code)

Como plugin, a partir do repositório:

```
/plugin marketplace add vitor-pecanha/pods-and-reels
/plugin install pods-and-reels@pods-and-reels
```

Ou, pra testar local durante o desenvolvimento:

```
claude --plugin-dir /caminho/para/pods-and-reels
```

## Setup (uma vez)

Instala as dependências Python, baixa o modelo de rosto (YuNet) e checa ffmpeg/Deno/CUDA:

```
/podcast-to-reels         (e peça "rode o setup")
# ou direto:
python "<plugin>/skills/podcast-to-reels/reel_cut.py" setup
```

## Usar

Chame **`/podcast-to-reels`** e mande um vídeo (link do YouTube ou arquivo local). O Claude conduz:
confirmar o vídeo → transcrever → sugerir e aprovar os cortes → (opcional) revisar a legenda no
navegador → (opcional) conferir o enquadramento → cortar. Os clipes saem em
`skills/podcast-to-reels/output/<título-do-vídeo>/clipes/`.

## Estrutura

```
pods-and-reels/
├── .claude-plugin/plugin.json     manifesto do plugin
├── skills/podcast-to-reels/       a skill: SKILL.md + scripts Python + models/ + output/
├── PLAN-distribuir.md             roadmap
└── README.md
```
