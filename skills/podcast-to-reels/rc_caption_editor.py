r"""rc_caption_editor.py — editor local de legenda dos cortes escolhidos (Fase 1).

Sobe um mini-servidor HTTP (só stdlib) e abre o navegador. Mostra UMA aba por
corte (de segments.json), cada aba só com as palavras daquele clipe (de
transcript.json). Edição por token (cada palavra é um chip editável), find-replace
GLOBAL (vale em todas as abas) e Salvar, que grava as correções de volta no
transcript.json preservando o timing.

Por que word-level: a legenda queimada vem de transcript.json["words"] — o
rc_captions filtra por intervalo. Editar o texto das words e manter start/end =
legenda certa, e o `cut` relê isso sem mais nada.

Regras de save (server-side, a partir do texto editado de cada word):
  - texto igual       -> mantém
  - texto trocado     -> renomeia (mesmo start/end)
  - texto com espaço  -> divide em N words, fatiando [start,end] proporcional ao
                         tamanho de cada pedaço (conserta segmentação)
  - texto vazio       -> remove a word
Words fora dos cortes não são tocadas. Faz backup transcript.json.bak na 1ª gravação.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import rc_captions as cap


# ── lógica de reconstrução das words ─────────────────────────────────────────

def _split_times(start: float, end: float, parts: list[str]) -> list[dict]:
    """Fatia [start,end] entre `parts`, proporcional ao nº de chars de cada um."""
    lens = [max(1, len(p)) for p in parts]
    total = sum(lens)
    span = max(0.0, end - start)
    out, t = [], start
    for p, ln in zip(parts, lens):
        seg = span * ln / total
        out.append({"word": p, "start": round(t, 3), "end": round(t + seg, 3)})
        t += seg
    out[-1]["end"] = round(end, 3)  # cola o fim exato (sem drift de arredondamento)
    return out


def rebuild_from_blocks(words: list[dict], blocks: list[dict]) -> list[dict]:
    """Reconstrói as words a partir do texto editado de cada BLOCO (campo único).

    Cada bloco cobre o range de índices [i0, i1] das words originais; o texto novo
    (qualquer nº de palavras) é re-alinhado no tempo do bloco — o intervalo
    [start de i0, end de i1] é fatiado proporcional ao tamanho de cada palavra nova.
    Cobre 1→2, 2→1, juntar, separar, e remover (texto vazio). Words fora de blocos
    (entre cortes) ficam intocadas.
    """
    bymap = {}
    for b in blocks:
        try:
            bymap[int(b["i0"])] = (int(b["i1"]), b.get("text", ""))
        except (KeyError, ValueError, TypeError):
            continue
    new: list[dict] = []
    j, n = 0, len(words)
    while j < n:
        if j in bymap:
            i1, text = bymap[j]
            i1 = min(max(i1, j), n - 1)
            orig = " ".join(w["word"] for w in words[j:i1 + 1])
            text = " ".join((text or "").split())
            if text == " ".join(orig.split()):
                new.extend(words[j:i1 + 1])  # bloco inalterado: mantém os tempos exatos do Whisper
            elif text:
                span_s, span_e = float(words[j]["start"]), float(words[i1]["end"])
                toks = text.split(" ")
                if len(toks) == 1:
                    new.append({"word": toks[0], "start": round(span_s, 3), "end": round(span_e, 3)})
                else:
                    new.extend(_split_times(span_s, span_e, toks))  # só o bloco editado é re-alinhado
            # text vazio -> bloco removido
            j = i1 + 1
        else:
            new.append(words[j])
            j += 1
    return new


def rebuild_words(words: list[dict], edits: dict[int, str]) -> list[dict]:
    """Aplica `edits` (índice global -> texto novo) e devolve a lista nova de words."""
    new: list[dict] = []
    for i, w in enumerate(words):
        if i not in edits:
            new.append(w)
            continue
        text = " ".join(edits[i].split())  # normaliza espaços
        if not text:
            continue  # delete
        parts = text.split(" ")
        if len(parts) == 1:
            new.append({"word": parts[0], "start": w["start"], "end": w["end"]})
        else:
            new.extend(_split_times(float(w["start"]), float(w["end"]), parts))
    return new


# ── HTML (estático; todos os dados vêm de /data via fetch) ───────────────────

_PAGE = r"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>reel-cut — editar legenda</title>
<link rel="icon" href="data:,">
<style>
  :root{
    --bg:#15171c; --panel:#1e2128; --panel-2:#23262e; --edge:#2c2f38; --edge-2:#383c46;
    --ink:#e9eaee; --mut:#9aa0ab; --mut-2:#b8bec9;
    --hl:#ffd34d; --hl-bg:#3a331c; --acc:#5b8cff; --acc-ink:#0b1020; --acc-bg:#1a2336;
    --ok:#46c08a; --ok-ink:#06210f;
    --r1:6px; --r2:8px; --r3:11px; --s1:4px; --s2:8px; --s3:12px; --s4:16px;
    --dur:140ms; --ease:cubic-bezier(.22,1,.36,1);
  }
  *{box-sizing:border-box}
  body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased}
  ::selection{background:rgba(91,140,255,.32)}

  input[type=text]{background:#121419;border:1px solid var(--edge);color:var(--ink);
       border-radius:var(--r1);padding:7px 9px;font-size:14px;min-width:0;
       transition:border-color var(--dur) var(--ease),box-shadow var(--dur) var(--ease)}
  input[type=text]::placeholder{color:var(--mut)}
  input[type=text]:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px rgba(91,140,255,.22)}

  button{background:var(--panel-2);color:var(--ink);border:1px solid var(--edge-2);border-radius:var(--r1);
       padding:6px 12px;font-size:14px;cursor:pointer;
       transition:background-color var(--dur) var(--ease),border-color var(--dur) var(--ease),
                  transform var(--dur) var(--ease),filter var(--dur) var(--ease)}
  button:hover{background:#2a2e38}
  button:active{transform:translateY(1px)}
  button:focus-visible{outline:none;box-shadow:0 0 0 3px rgba(91,140,255,.4)}
  button.primary{background:var(--acc);border-color:var(--acc);color:var(--acc-ink);font-weight:600}
  button.primary:hover{background:var(--acc);filter:brightness(1.08)}

  #tabs{display:flex;flex-wrap:wrap;gap:4px;padding:14px 16px 0;border-bottom:1px solid #444b57}
  .tab{padding:7px 12px;border:1px solid transparent;border-bottom:none;border-radius:var(--r2) var(--r2) 0 0;
       background:transparent;color:var(--mut);cursor:pointer;font-size:13px;margin-bottom:-1px;
       transition:background-color var(--dur) var(--ease),color var(--dur) var(--ease),border-color var(--dur) var(--ease)}
  .tab:hover{color:var(--ink);background:var(--panel)}
  .tab.on{background:var(--bg);color:var(--ink);border-color:#444b57;border-bottom-color:var(--bg);font-weight:600}
  .tab small{color:var(--mut);font-weight:400;margin-left:6px;font-variant-numeric:tabular-nums}

  .wrap{display:flex;gap:var(--s4);align-items:flex-start;padding:0 16px}
  main{flex:1 1 auto;min-width:0;max-width:720px;padding:var(--s4) 0 64px}
  .clip{display:none}
  .clip.on{display:block}
  .meta{color:var(--mut);font-size:12.5px;margin:0 0 var(--s3)}

  /* legenda = protagonista: lista limpa, cor só no que toca agora e no que foi editado */
  .blocks{display:flex;flex-direction:column;gap:2px}
  .block{display:flex;gap:var(--s2);align-items:center;padding:4px 8px;border-radius:var(--r2);
         border:1px solid transparent;
         transition:background-color var(--dur) var(--ease),border-color var(--dur) var(--ease)}
  .block:hover{background:var(--panel)}
  .block.active{background:var(--acc-bg);border-color:rgba(91,140,255,.45)}
  .block .play{flex:none;width:22px;height:22px;border-radius:50%;padding:0;font-size:9px;line-height:1;
       background:transparent;border:1px solid transparent;color:var(--mut);
       transition:color var(--dur) var(--ease),background-color var(--dur) var(--ease),border-color var(--dur) var(--ease)}
  .block:hover .play{color:var(--ink);border-color:var(--edge-2)}
  .block .play:hover{background:var(--panel-2);color:var(--acc);border-color:var(--acc)}
  .block.active .play{color:var(--acc);border-color:rgba(91,140,255,.55)}
  .block .ts{flex:none;color:var(--mut);font-size:11px;font-variant-numeric:tabular-nums;min-width:34px}
  .block.active .ts{color:var(--mut-2)}
  .block .btext{flex:1;font-size:14px;line-height:1.5;outline:none;padding:3px 7px;border-radius:var(--r1);
        border:1px solid transparent;white-space:pre-wrap;cursor:text;
        transition:background-color var(--dur) var(--ease),border-color var(--dur) var(--ease)}
  .block .btext:focus{background:var(--panel-2);border-color:var(--acc);box-shadow:0 0 0 2px rgba(91,140,255,.2)}
  .block .btext.changed{background:var(--hl-bg);border-color:rgba(255,211,77,.5)}

  .side{flex:none;width:380px;position:sticky;top:12px;display:flex;flex-direction:column;gap:var(--s3);margin-top:14px}
  #vidbox,#subbox,#savebox{background:var(--panel);border:1px solid var(--edge);border-radius:var(--r3);padding:var(--s3)}
  .boxtitle{font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.5px;margin-bottom:var(--s2)}
  #subbox .subrow{display:flex;gap:7px;align-items:center;margin-bottom:var(--s2)}
  #subbox .subrow input{flex:1}
  #subbox .arrow{color:var(--mut);flex:none}
  #subbox button{width:100%;padding:7px 0;font-size:14px;font-weight:600}
  #subStatus{color:var(--mut);font-size:12px;display:block;margin-top:7px;text-align:center;min-height:1em}

  #vidbox.hidden{display:none}
  #vidbox video{width:100%;border-radius:var(--r2);background:#000;display:block}
  #vidbox .transport{display:flex;gap:var(--s2);margin-top:10px}
  #vidbox .transport button{flex:1;padding:9px 0;font-size:14px;font-weight:600}
  #ppBtn{background:var(--acc);border-color:var(--acc);color:var(--acc-ink)}
  #ppBtn:hover{background:var(--acc);filter:brightness(1.08)}

  #savebox{display:flex;flex-direction:column;gap:var(--s2)}
  #savebox button{padding:8px 0;font-size:14px;font-weight:600}
  /* "Salvar e concluir" é a ação que ENCERRA o projeto: verde, mais destacada */
  #saveClose{background:var(--ok);border-color:var(--ok);color:var(--ok-ink);font-weight:700;padding:12px 0;font-size:15px}
  #saveClose:hover{background:var(--ok);filter:brightness(1.08)}
  .boxhint{color:var(--mut);font-size:12px;line-height:1.5;margin:2px 0 0}
  #status,#subStatus{color:var(--mut)}
  #status.ok,#subStatus.ok{color:var(--ok);font-weight:600}
  #status{font-size:12px;text-align:center;min-height:1em}

  @media (prefers-reduced-motion: reduce){ *{transition:none !important} }
</style></head>
<body>
<div id="tabs"></div>
<div class="wrap">
  <main id="main"></main>
  <aside class="side">
    <div id="vidbox"></div>
    <div id="subbox">
      <div class="boxtitle">SUBSTITUIÇÃO EM LOTE</div>
      <div class="subrow">
        <input id="find" type="text" placeholder="de">
        <span class="arrow">→</span>
        <input id="repl" type="text" placeholder="para">
      </div>
      <button id="doRepl" class="primary">Aplicar</button>
      <p class="boxhint">Troca todas as ocorrências de um texto pelo outro.</p>
      <span id="subStatus"></span>
    </div>
    <div id="savebox">
      <button id="save" class="primary">Salvar legenda</button>
      <button id="saveClose">Salvar e concluir</button>
      <p class="boxhint">“Salvar legenda” grava as correções no arquivo. “Salvar e concluir” grava e encerra esta etapa (o programa segue pro corte).</p>
      <span id="status"></span>
    </div>
  </aside>
</div>

<script>
let CLIPS = [], VIDEO = false, CUR = 0;

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function render(){
  const tabs = document.getElementById('tabs');
  const main = document.getElementById('main');
  tabs.innerHTML = ''; main.innerHTML = '';
  CLIPS.forEach((c, ci) => {
    const t = document.createElement('div');
    t.className = 'tab' + (ci===CUR?' on':'');
    t.innerHTML = esc(c.title) + ' <small>' + fmt(c.start) + '–' + fmt(c.end) + '</small>';
    t.onclick = () => switchTab(ci);
    tabs.appendChild(t);

    const d = document.createElement('div');
    d.className = 'clip' + (ci===CUR?' on':'');
    d.dataset.ci = ci;
    let html = '<p class="meta">Clique no bloco e edite livremente, depois lembre-se de salvar.</p><div class="blocks">';
    html += c.blocks.map(bl => {
      const bs = bl[0].start, be = bl[bl.length-1].end;
      const i0 = bl[0].i, i1 = bl[bl.length-1].i;
      const text = bl.map(w => w.word).join(' ');
      return '<div class="block" data-bs="' + bs + '" data-be="' + be + '" data-i0="' + i0 + '" data-i1="' + i1 + '">' +
             (VIDEO ? '<button class="play" onclick="playFrom('+bs+')" title="tocar a partir daqui">▶</button>' : '') +
             '<span class="ts">' + fmt(bs) + '</span>' +
             '<div class="btext" contenteditable="true" spellcheck="false" data-orig="' + esc(text) + '">' +
             esc(text) + '</div></div>';
    }).join('');
    html += '</div>';
    d.innerHTML = html;
    main.appendChild(d);
  });
  document.querySelectorAll('.btext').forEach(el => {
    el.addEventListener('input', () => {
      el.classList.toggle('changed', el.textContent !== el.dataset.orig);
    });
  });
}

function fmt(s){s=Math.round(s);const m=(s/60)|0,x=s%60;return m+':'+String(x).padStart(2,'0');}

function switchTab(ci){
  CUR = ci;
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('on',i===ci));
  document.querySelectorAll('.clip').forEach((d,i)=>d.classList.toggle('on',i===ci));
}

function playFrom(a){
  const v=document.getElementById('vid'); if(!v) return;
  try{ v.currentTime=a; }catch(e){}
  v.play();
}

// destaca o bloco e a palavra do momento (igual a legenda); NÃO para nos blocos
function onTick(){
  const v=document.getElementById('vid'); if(!v) return;
  const t=v.currentTime;
  document.querySelectorAll('.clip.on .block').forEach(b=>{
    b.classList.toggle('active', t>=(+b.dataset.bs) && t<(+b.dataset.be));
  });
}

function doReplace(){
  const f = document.getElementById('find').value;
  if (!f) return;
  const r = document.getElementById('repl').value;
  let n = 0;
  document.querySelectorAll('.btext').forEach(el => {
    if (el.textContent.includes(f)){
      el.textContent = el.textContent.split(f).join(r);
      el.classList.toggle('changed', el.textContent !== el.dataset.orig); n++;
    }
  });
  const ss = document.getElementById('subStatus');
  ss.textContent = n ? ('trocado em ' + n + ' bloco' + (n>1?'s':'') + ' · revise e salve') : 'nada encontrado';
  ss.classList.toggle('ok', n>0);
}

function blocksPayload(){
  const out = [];
  document.querySelectorAll('.block').forEach(b => {
    const el = b.querySelector('.btext');
    out.push({i0:+b.dataset.i0, i1:+b.dataset.i1, text: el ? el.textContent : ''});
  });
  return out;
}
function setStatus(s, ok){ const el=document.getElementById('status'); el.textContent = s; el.classList.toggle('ok', !!ok); }

async function save(close){
  setStatus('salvando…');
  const res = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
                                    body: JSON.stringify({blocks: blocksPayload()})});
  const data = await res.json();
  if (close){
    await fetch('/close', {method:'POST'});
    document.body.innerHTML = '<p style="padding:40px;color:var(--mut)">Salvo. Pode fechar esta aba.</p>';
    return;
  }
  CLIPS = data.clips; render();
  setStatus('salvo ✓', true);
}

async function boot(){
  const data = await (await fetch('/data')).json();
  CLIPS = data.clips; VIDEO = data.video;
  render();
  if (VIDEO){
    document.getElementById('vidbox').innerHTML =
      '<video id="vid" preload="metadata" controls></video>' +
      '<div class="transport"><button id="ppBtn">▶ Play</button><button id="restartBtn">↻ Voltar ao início</button></div>';
    const v=document.getElementById('vid'); v.src='/video'; v.ontimeupdate=onTick;
    const pp=document.getElementById('ppBtn');
    const upPP=()=>{ pp.textContent = v.paused ? '▶ Play' : '⏸ Pause'; };
    pp.onclick=()=>{
      if (v.paused){
        const c=CLIPS[CUR];
        if (c && (v.currentTime < c.start || v.currentTime > c.end)){ try{ v.currentTime=c.start; }catch(e){} }
        v.play();
      } else { v.pause(); }
    };
    document.getElementById('restartBtn').onclick=()=>{
      const c=CLIPS[CUR]; if (c){ try{ v.currentTime=c.start; }catch(e){} }
    };
    v.onplay=upPP; v.onpause=upPP; upPP();
  } else {
    document.getElementById('vidbox').classList.add('hidden');
  }
  document.getElementById('doRepl').onclick = doReplace;
  document.getElementById('save').onclick = () => save(false);
  document.getElementById('saveClose').onclick = () => save(true);
  document.getElementById('repl').addEventListener('keydown', e => { if(e.key==='Enter') doReplace(); });
}
boot();
</script>
</body></html>
"""


# ── servidor ─────────────────────────────────────────────────────────────────

def serve(work_dir: str, port: int = 0, open_browser: bool = True) -> None:
    work = Path(work_dir)
    tj, sj, mj = work / "transcript.json", work / "segments.json", work / "meta.json"
    if not tj.exists():
        sys.exit(f"transcript.json não encontrado em {work}. Rode `transcribe` primeiro.")
    if not sj.exists():
        sys.exit(f"segments.json não encontrado em {work}. Faça a seleção (escreva os cortes) antes de editar legenda.")

    parsed = json.loads(tj.read_text(encoding="utf-8"))
    clips_meta = json.loads(sj.read_text(encoding="utf-8"))
    meta = json.loads(mj.read_text(encoding="utf-8")) if mj.exists() else {}
    words = parsed["words"]  # editado in-place a cada save
    video = meta.get("source")
    video_ok = bool(video) and os.path.exists(video)
    state = {"saved": False}
    stop = threading.Event()

    def build_clips() -> list[dict]:
        out = []
        ch = max(1, cap.CHUNK_SIZE)  # mesmo agrupamento da legenda queimada (rc_captions)
        for ci, c in enumerate(clips_meta):
            cs, ce = float(c["start"]), float(c["end"])
            cw = [{"i": i, "word": w["word"], "start": w["start"], "end": w["end"]}
                  for i, w in enumerate(words) if w["end"] > cs and w["start"] < ce]
            blocks = [cw[k:k + ch] for k in range(0, len(cw), ch)]  # blocos = o que aparece junto na tela
            out.append({"title": c.get("title", f"clip{ci + 1}"), "start": cs, "end": ce,
                        "words": cw, "blocks": blocks})
        return out

    def do_save(blocks_payload: list) -> list[dict]:
        if not state["saved"]:  # backup uma vez
            (work / "transcript.json.bak").write_text(tj.read_text(encoding="utf-8"), encoding="utf-8")
        new_words = rebuild_from_blocks(words, blocks_payload)
        parsed["words"] = new_words
        tj.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        words[:] = new_words  # refresca índices pra próximos saves
        state["saved"] = True
        print(f"[captions] salvo: {len(new_words)} palavras -> {tj}", flush=True)
        return build_clips()

    def serve_video(handler: BaseHTTPRequestHandler):
        fs = os.path.getsize(video)
        rng = handler.headers.get("Range")
        try:
            if rng and rng.startswith("bytes="):
                s, _, e = rng[6:].partition("-")
                start = int(s) if s else 0
                end = int(e) if e else fs - 1
                end = min(end, fs - 1)
                length = end - start + 1
                handler.send_response(206)
                handler.send_header("Content-Type", "video/mp4")
                handler.send_header("Accept-Ranges", "bytes")
                handler.send_header("Content-Range", f"bytes {start}-{end}/{fs}")
                handler.send_header("Content-Length", str(length))
                handler.end_headers()
                with open(video, "rb") as f:
                    f.seek(start)
                    rem = length
                    while rem > 0:
                        chunk = f.read(min(262144, rem))
                        if not chunk:
                            break
                        handler.wfile.write(chunk)
                        rem -= len(chunk)
            else:
                handler.send_response(200)
                handler.send_header("Content-Type", "video/mp4")
                handler.send_header("Accept-Ranges", "bytes")
                handler.send_header("Content-Length", str(fs))
                handler.end_headers()
                with open(video, "rb") as f:
                    shutil.copyfileobj(f, handler.wfile)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # browser cancelou/seekou (no Windows vem como ConnectionAbortedError): normal

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):
            route = urlparse(self.path)
            if route.path == "/":
                self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif route.path == "/data":
                self._json(200, {"clips": build_clips(), "video": video_ok})
            elif route.path.startswith("/video") and video_ok:
                serve_video(self)
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b"{}"
            if self.path == "/save":
                data = json.loads(raw or b"{}")
                self._json(200, {"ok": True, "clips": do_save(data.get("blocks", []))})
            elif self.path == "/close":
                self._json(200, {"ok": True})
                stop.set()
            else:
                self._send(404, b"not found", "text/plain")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    real_port = httpd.server_address[1]
    url = f"http://127.0.0.1:{real_port}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    print("=" * 60)
    print(f"[captions] editor de legenda em  {url}")
    print(f"[captions] {len(clips_meta)} corte(s)" + ("  · vídeo ao lado: on" if video_ok else "  · sem vídeo"))
    print("[captions] edite, clique Salvar; 'Salvar e fechar' encerra o servidor (ou Ctrl+C).")
    print("=" * 60)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    httpd.shutdown()
    print("[captions] fechado." + (" Alterações salvas em transcript.json." if state["saved"] else " (nada salvo)"))


if __name__ == "__main__":
    serve(sys.argv[1] if len(sys.argv) > 1 else "work/teste")
