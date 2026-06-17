r"""rc_framing_editor.py — página local de conferência do enquadramento (peça 4).

Igual em espírito ao rc_caption_editor: sobe um mini-servidor stdlib e abre o
navegador mostrando, pra cada plano ÚNICO (dedup do rc_framing), o before/after
(frame original | como vai ficar no 9:16) + quantas vezes aquele plano aparece.
O usuário confirma com o olho e, se quiser, troca o layout de um plano ali mesmo
(vale pra todas as ocorrências) — chama rc_framing.apply_override e re-renderiza.

Lê/escreve work/framing.json (que o `preview` já gerou). Ao concluir, o `cut`
consome esse framing.json e corta exatamente o aprovado.
"""
from __future__ import annotations
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import rc_framing


_PAGE = r"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>podcast-to-reels: conferir enquadramento</title>
<link rel="icon" href="data:,">
<style>
  :root{
    --bg:#15171c; --panel:#1e2128; --panel-2:#23262e; --edge:#2c2f38; --edge-2:#383c46;
    --ink:#e9eaee; --mut:#9aa0ab; --acc:#5b8cff; --acc-ink:#0b1020; --acc-bg:#1a2336;
    --r1:6px; --r2:8px; --r3:11px; --s2:8px; --s3:12px; --s4:16px;
    --dur:140ms; --ease:cubic-bezier(.22,1,.36,1);
  }
  *{box-sizing:border-box}
  body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased}
  button{background:var(--panel-2);color:var(--ink);border:1px solid var(--edge-2);border-radius:var(--r1);
       padding:7px 12px;font-size:13px;cursor:pointer;
       transition:background-color var(--dur) var(--ease),border-color var(--dur) var(--ease),
                  transform var(--dur) var(--ease),filter var(--dur) var(--ease)}
  button:hover{background:#2a2e38}
  button:active{transform:translateY(1px)}
  button:focus-visible{outline:none;box-shadow:0 0 0 3px rgba(91,140,255,.4)}
  button.primary{background:var(--acc);border-color:var(--acc);color:var(--acc-ink);font-weight:600}
  button.primary:hover{background:var(--acc);filter:brightness(1.08)}
  button.on{border-color:var(--acc);color:#fff;background:var(--acc-bg)}

  header{position:sticky;top:0;z-index:5;background:rgba(21,23,28,.86);backdrop-filter:blur(8px);
         border-bottom:1px solid #444b57;padding:12px 20px;display:flex;align-items:center;gap:14px}
  header h1{font-size:14px;margin:0;font-weight:600;letter-spacing:.2px}
  header .sub{color:var(--mut);font-size:12.5px}
  .spacer{flex:1}
  #done{color:var(--mut);font-size:12.5px}
  .flabel{color:var(--mut);font-size:13px;margin-right:2px}
  #finishBurn{background:var(--acc);border-color:var(--acc);color:var(--acc-ink);font-weight:700}
  #finishBurn:hover{background:var(--acc);filter:brightness(1.08)}

  main{max-width:1000px;margin:0 auto;padding:18px 20px 80px}
  .legend{color:var(--mut);font-size:12.5px;margin:0 0 16px}
  .legend b{color:var(--ink);font-weight:600}

  .fr{background:var(--panel);border:1px solid var(--edge);border-radius:var(--r3);
      padding:14px;margin-bottom:16px}
  .fr.busy{opacity:.55;pointer-events:none}
  .frhead{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}
  .frlabel{font-size:15px;font-weight:600}
  .frcount{color:var(--mut);font-size:12.5px}
  .ba{display:flex;align-items:center;justify-content:center;gap:20px;margin:4px 0 14px}
  .ba figure{margin:0;display:flex;flex-direction:column;align-items:center;gap:7px}
  .frimg{height:340px;width:auto;max-width:100%;border-radius:var(--r2);display:block;background:#000}
  .frimg.ph{width:200px;height:340px}
  .ba figcaption{color:var(--mut);font-size:11.5px}
  .arrow{flex:none;font-size:30px;color:var(--mut);margin-bottom:26px}
  .frctl{display:flex;flex-wrap:wrap;gap:7px;align-items:center}
  .frctl .lbl{color:var(--mut);font-size:12.5px;margin-right:2px}
</style></head>
<body>
<header>
  <h1>Conferir enquadramento</h1>
  <span class="sub" id="hsub"></span>
  <div class="spacer"></div>
  <span id="done"></span>
  <span class="flabel">Concluir e cortar:</span>
  <button id="finishBurn" class="primary">Legenda queimada</button>
  <button id="finishFile">Arquivo .ass à parte</button>
</header>
<main id="main">
  <p class="legend">Pra cada plano: <b>esquerda</b> = frame original do vídeo, <b>direita</b> = como vai
  ficar no clipe vertical 9:16. Num podcast a câmera repete, então você confere cada plano <b>uma vez</b>
  (vale pra todas as ocorrências). Se algum estiver errado, escolha outro layout que ele re-renderiza na hora.</p>
  <div id="list"></div>
</main>

<script>
let FR = [];
const LAYOUTS = [
  {k:'auto', t:'auto'},
  {k:'two_stack', t:'empilhar os dois'},
  {k:'solo_left', t:'solo esquerda'},
  {k:'solo_right', t:'solo direita'},
  {k:'pad', t:'letterbox'},
];
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function render(){
  const list = document.getElementById('list');
  list.innerHTML = '';
  FR.forEach((g, i) => {
    const sec = document.createElement('section');
    sec.className = 'fr'; sec.dataset.sig = g.sig;
    const oc = g.occurrences;
    let html = '<div class="frhead"><span class="frlabel">' + esc(g.label) + '</span>' +
               '<span class="frcount">' + oc + ' ocorrência' + (oc>1?'s':'') + '</span></div>';
    const img = (f) => f
      ? '<img class="frimg" src="/img?f=' + encodeURIComponent(f) + '&v=' + (g._v||0) + '" alt="">'
      : '<div class="frimg ph"></div>';
    html += '<div class="ba">' +
      '<figure>' + img(g.preview_a) + '<figcaption>original (16:9)</figcaption></figure>' +
      '<span class="arrow">&rarr;</span>' +
      '<figure>' + img(g.preview_b) + '<figcaption>vai ficar assim (9:16)</figcaption></figure>' +
      '</div>';
    html += '<div class="frctl"><span class="lbl">Mudar pra:</span>';
    html += LAYOUTS.map(l =>
      '<button data-layout="' + l.k + '"' + (l.k===g.layout?' class="on"':'') + '>' + l.t + '</button>').join('');
    html += '</div>';
    sec.innerHTML = html;
    sec.querySelectorAll('.frctl button').forEach(b => {
      b.onclick = () => override(g.sig, b.dataset.layout, sec);
    });
    list.appendChild(sec);
  });
  document.getElementById('hsub').textContent = FR.length + ' plano(s) único(s)';
}

async function override(sig, layout, sec){
  sec.classList.add('busy');
  const res = await fetch('/override', {method:'POST', headers:{'Content-Type':'application/json'},
                                        body: JSON.stringify({sig, layout})});
  const g = await res.json();
  sec.classList.remove('busy');
  const idx = FR.findIndex(x => x.sig === sig);
  if (idx >= 0 && g && g.sig){ g._v = (FR[idx]._v||0) + 1; FR[idx] = g; render(); }
}

async function finish(mode){
  await fetch('/close', {method:'POST', headers:{'Content-Type':'application/json'},
                         body: JSON.stringify({captions: mode})});
  const txt = mode==='file' ? 'legenda em arquivo .ass à parte' : 'legenda queimada no vídeo';
  document.body.innerHTML = '<p style="padding:48px;color:#9aa0ab;font:15px sans-serif">' +
    'Enquadramento confirmado (' + txt + '). Pode fechar esta aba; os clipes começam a ser gerados.</p>';
}

async function boot(){
  FR = (await (await fetch('/data')).json()).framings || [];
  render();
  document.getElementById('finishBurn').onclick = () => finish('burn');
  document.getElementById('finishFile').onclick = () => finish('file');
}
boot();
</script>
</body></html>
"""


def serve(work_dir: str, port: int = 0, open_browser: bool = True) -> None:
    # utf-8 no stdout/stderr: o nome do vídeo pode ter chars fullwidth (：｜) que o
    # ff.run imprime; sem isso, o print quebra a render do override no Windows (cp1252).
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    work = Path(work_dir)
    fp = work / "framing.json"
    prev_dir = work / "preview"
    if not fp.exists():
        sys.exit(f"framing.json não encontrado em {work}. Rode o planejamento do preview antes.")

    stop = threading.Event()
    state = {"done": False}

    def framings_payload() -> list:
        data = json.loads(fp.read_text(encoding="utf-8"))
        out = []
        for g in data["framings"]:
            out.append({"sig": g["sig"], "label": g["label"], "kind": g.get("kind"),
                        "occurrences": g["occurrences"], "layout": g.get("layout", "auto"),
                        "preview_a": Path(g["preview_a"]).name if g.get("preview_a") else None,
                        "preview_b": Path(g["preview_b"]).name if g.get("preview_b") else None})
        return out

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):
            route = urlparse(self.path)
            if route.path == "/":
                self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif route.path == "/data":
                self._json(200, {"framings": framings_payload()})
            elif route.path == "/img":
                name = (parse_qs(route.query).get("f") or [""])[0]
                f = prev_dir / Path(name).name  # basename only (evita path traversal)
                if name and f.exists():
                    self._send(200, f.read_bytes(), "image/jpeg")
                else:
                    self._send(404, b"not found", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b"{}"
            if self.path == "/override":
                data = json.loads(raw or b"{}")
                try:
                    rc_framing.apply_override(str(work), data["sig"], data.get("layout", "auto"))
                except Exception as e:
                    print(f"[framing] override falhou: {e}", flush=True)
                # devolve o grupo atualizado
                g = next((x for x in framings_payload() if x["sig"] == data.get("sig")), {})
                self._json(200, g)
            elif self.path == "/close":
                try:
                    opts = json.loads(raw or b"{}")
                except Exception:
                    opts = {}
                caps = "file" if opts.get("captions") == "file" else "burn"
                (work / "cut_options.json").write_text(json.dumps({"captions": caps}), encoding="utf-8")
                state["done"] = True
                self._json(200, {"ok": True})
                stop.set()
            else:
                self._send(404, b"not found", "text/plain")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    real_port = httpd.server_address[1]
    url = f"http://127.0.0.1:{real_port}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    print("=" * 60)
    print(f"[framing] conferência de enquadramento em  {url}")
    print("[framing] confira cada plano; ajuste o layout se quiser; clique 'Concluir e cortar'.")
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
    print("[framing] enquadramento confirmado." if state["done"] else "[framing] fechado.")
