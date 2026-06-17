# Product

## Register

product

## Users

Vitor Peçanha e, no futuro, quem instalar a skill `/reel-cut`. Editor de vídeo
de quem produz conteúdo, não programador. O contexto de uso é uma sessão local
de revisão, às vezes longa: a pessoa lê a legenda de cada corte enquanto ouve o
vídeo-fonte ao lado, caçando os erros que o Whisper cometeu (nome próprio,
jargão, frase mal ouvida) antes de queimar a legenda nos clipes verticais.

## Product Purpose

Tela local de revisão e correção de legenda. O Whisper transcreve; aqui a pessoa
corrige o texto **por bloco** (cada bloco = o punhado de palavras que aparece
junto na tela do clipe), com o vídeo-fonte sincronizado ao lado destacando o
bloco do momento, e uma substituição em lote pros erros repetidos. Sucesso é:
achar e corrigir o erro rápido, confiar no que vai ser queimado, e seguir pro
corte. Não é um editor de vídeo nem um processador de texto: é um passo de
conferência rápida no meio do pipeline.

## Brand Personality

Invisível, calma, eficiente. Em três palavras: quieta, densa, confiável. A tela
some na tarefa; o texto da legenda é o protagonista, o resto recua. Sem firula,
sem disputar atenção com o conteúdo.

## Anti-references

Dashboards de SaaS carregados; UIs de ferramenta over-decoradas (sombras
gratuitas, gradientes, motion de enfeite); qualquer coisa que dispute atenção
com o texto da legenda. Já tiramos o glossário desta tela justamente por
confundir: simplicidade ganha de funcionalidade exibida.

## Design Principles

- **O texto é o protagonista.** Os blocos de legenda dominam; controles e chrome
  recuam pro fundo.
- **Ler ouvindo.** Vídeo e blocos andam juntos; o bloco que está tocando é óbvio
  num relance.
- **Densa, mas calma.** Linhas compactas pra aguentar sessão longa, com
  hierarquia clara o bastante pra não virar ruído.
- **Controles familiares, zero affordance inventada.** Inputs, botões e play/pause
  padrão; nada de reinventar o básico.
- **Toda edição é visível e reversível.** Bloco alterado se vê; salvar é
  explícito; o original tem backup.

## Accessibility & Inclusion

Tema escuro com contraste WCAG AA no que importa ler numa sessão longa (texto da
legenda, timestamps, hints). Foco de teclado visível nos blocos editáveis e nos
inputs. Respeitar `prefers-reduced-motion`. Alvos de clique confortáveis nos ▶
de cada bloco.
