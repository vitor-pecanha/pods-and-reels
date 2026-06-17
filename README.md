# Pods and Reels

Plugin do Claude Code para edição de podcasts e Reels. Os princípios:

- **Seleção de cortes por IA.** O próprio Claude lê a transcrição e escolhe os melhores trechos direto na sua sessão, você só aprova.
- **Vídeo 100% local, via FFmpeg.** Corte, crop 9:16, concatenação e legenda queimada rodam na sua máquina.
- **Áudio e legendas 100% locais.** Transcrição com Whisper (faster-whisper) e geração de legenda rodam offline, sem mandar seu vídeo pra lugar nenhum.
- **Sem API paga.** Tudo acontece com a sua assinatura do Claude. Nenhuma chamada à API da Anthropic nem a serviços externos.

> Projeto criado para o curso **Gestão de Agentes de Marketing** da [PbyP School](https://pbyp.com.br).

## Skills

### podcast-to-reels (a primeira skill)

Pega uma gravação longa (um podcast, uma live, uma aula, qualquer vídeo talking-head), **seleciona
automaticamente os melhores trechos**, corta, edita e transforma em vídeos **verticais 9:16** prontos pra
**Reels, Shorts e TikTok**, com legenda queimada. O enquadramento é ciente de cena e de quem está falando:
foca em quem fala (solo), empilha quando dois se revezam, ou usa letterbox em plano aberto. Você aprova a
seleção e pode revisar legenda e enquadramento no navegador antes do corte final.

(Outras skills virão; por isso o plugin se chama Pods and Reels e a skill, podcast-to-reels.)

## Pré-requisitos

O que você precisa garantir antes é o **Python**. O resto o setup resolve, ou o Claude instala pra você de
dentro da sessão.

Dependências de sistema:

- **Python 3.10+** (é o que roda tudo por baixo, precisa existir antes)
- **ffmpeg** (corta, faz o crop e queima a legenda). Instala com `winget install Gyan.FFmpeg` no Windows, `brew install ffmpeg` no Mac, `apt install ffmpeg` no Linux. Se faltar, o Claude roda esse comando pra você.
- **Deno**, pra baixar vídeos do YouTube. O download é feito pelo yt-dlp, que hoje precisa de um runtime JS (Deno). Mesma coisa: se faltar, o Claude instala pra você.

O `setup` instala sozinho (via pip), você não precisa se preocupar:

- **faster-whisper** (transcrição e legenda, local), **yt-dlp** (download) e **opencv-python** (detecção de rosto pro enquadramento), além do modelo de rosto YuNet.
- Com **GPU NVIDIA** a transcrição roda na CUDA; sem ela, cai pra CPU automaticamente. A GPU é o único item de fato opcional.

## Instalar

A forma de instalar muda conforme onde você usa o Claude. O `/plugin` existe só no terminal.

**No terminal (CLI):**

```
/plugin marketplace add vitor-pecanha/pods-and-reels
/plugin install pods-and-reels@pods-and-reels
```

**No app desktop do Claude:** não tem `/plugin`; use o gerenciador visual. Clique no botão **+** ao lado da
caixa de mensagem, abra **Manage plugins**, clique no **+** de novo e escolha **Add marketplace**, colando a
URL do repositório (`https://github.com/vitor-pecanha/pods-and-reels`). Depois instale o plugin
**pods-and-reels** a partir desse marketplace. (Funciona em sessões locais; sessões na nuvem não suportam plugins.)

**Em qualquer superfície (editando o `settings.json`):** adicione ao `~/.claude/settings.json` (ou ao
`.claude/settings.json` do projeto) e reinicie o Claude:

```json
{
  "extraKnownMarketplaces": {
    "pods-and-reels": { "source": { "source": "github", "repo": "vitor-pecanha/pods-and-reels" } }
  },
  "enabledPlugins": { "pods-and-reels@pods-and-reels": true }
}
```

## Setup (uma vez)

Chame **`/podcast-to-reels`** e peça pra rodar o **setup**. Você faz tudo de dentro do Claude, sem mexer no
terminal. O setup instala os pacotes Python (Whisper, yt-dlp, opencv) e baixa o modelo de rosto. Pra ffmpeg e
Deno, ele confere se estão instalados e, se faltar, te passa o comando de instalação (e o Claude pode rodar
pra você na hora). O Python já precisa estar na máquina, já que é ele que roda tudo por baixo.

## Usar

Chame **`/podcast-to-reels`** e mande um vídeo (link do YouTube ou arquivo local). O Claude conduz o fluxo:
confirmar o vídeo, transcrever, sugerir e aprovar os cortes, revisar a legenda (opcional, no navegador),
conferir o enquadramento (opcional), cortar. Os clipes saem em
`skills/podcast-to-reels/output/<título-do-vídeo>/clipes/`.

## Tecnologias

Tudo roda na sua máquina:

- **Claude (Claude Code)** faz a seleção dos cortes na sua sessão, sem API paga.
- **Whisper** (faster-whisper) transcreve o áudio e gera as legendas, offline.
- **FFmpeg** corta, faz o crop 9:16, concatena e queima a legenda.
- **OpenCV + YuNet** detectam rosto pro enquadramento ciente de quem está falando.
- **yt-dlp + Deno** baixam o vídeo do YouTube (o Deno é o runtime JS que o yt-dlp usa).

## Estrutura

```
pods-and-reels/
├── .claude-plugin/
│   ├── plugin.json        manifesto do plugin
│   └── marketplace.json   catálogo (pro /plugin marketplace add)
├── skills/podcast-to-reels/   a skill: SKILL.md + scripts Python + models/ + output/
├── PLAN-distribuir.md         roadmap
└── README.md
```
