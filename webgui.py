#!/usr/bin/env python3
"""
GUI web — multi-email-catcher (source: Google Sheets)
Ouvrir dans le navigateur : http://localhost:5050

Lancement :
  python webgui.py
"""
import sys
import os
import subprocess
import threading
import queue
from flask import Flask, Response, render_template_string, jsonify

app = Flask(__name__)

# ── État global ───────────────────────────────────────────────────────────────
_proc: subprocess.Popen | None = None
_log_queue: queue.Queue = queue.Queue()
_running = False

# ── HTML inline ───────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>multi-email-catcher</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0;
           display: flex; height: 100vh; overflow: hidden; }

    /* LEFT */
    #sidebar { width: 220px; min-width: 220px; background: #16213e;
               display: flex; flex-direction: column; align-items: center;
               justify-content: center; gap: 16px; padding: 24px; }
    #sidebar h1 { font-size: 14px; color: #888; text-align: center;
                  border-bottom: 1px solid #333; padding-bottom: 12px; width: 100%; }
    button { width: 100%; padding: 12px; border: none; border-radius: 6px;
             font-size: 15px; font-weight: bold; cursor: pointer; transition: opacity .2s; }
    button:hover { opacity: .85; }
    #btn-start { background: #0e7a0d; color: white; }
    #btn-stop  { background: #8b0000; color: white; }
    button:disabled { opacity: .4; cursor: not-allowed; }
    #status { font-size: 12px; color: #888; text-align: center; }

    /* RIGHT */
    #logpanel { flex: 1; display: flex; flex-direction: column; padding: 12px; gap: 8px; }
    #log-header { display: flex; align-items: center; gap: 12px; }
    #log-header span { font-size: 13px; color: #aaa; }
    #btn-clear { width: auto; padding: 4px 14px; background: #333; color: #ccc;
                 font-size: 12px; font-weight: normal; border-radius: 4px; }
    #logs { flex: 1; background: #0d0d0d; border-radius: 6px; padding: 12px;
            font-family: 'Consolas', monospace; font-size: 12px; line-height: 1.5;
            overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
  </style>
</head>
<body>
  <div id="sidebar">
    <h1>multi-email-catcher</h1>
    <button id="btn-start" onclick="startAgent()">▶ Lancer</button>
    <button id="btn-stop"  onclick="stopAgent()" disabled>■ Arrêter</button>
    <div id="status">Prêt</div>
  </div>

  <div id="logpanel">
    <div id="log-header">
      <span>Logs</span>
      <button id="btn-clear" onclick="document.getElementById('logs').innerHTML=''">Effacer</button>
    </div>
    <div id="logs"></div>
  </div>

  <script>
    let es = null;

    function color(line) {
      const lo = line.toLowerCase();
      if (/✅|📧|found|terminé|ok/.test(lo))   return '#4ec9b0';
      if (/❌|error|erreur|failed/.test(lo))    return '#f44747';
      if (/⚠️|warn|skip/.test(lo))             return '#ce9178';
      return '#d4d4d4';
    }

    function appendLog(text) {
      const box = document.getElementById('logs');
      text.split('\\n').forEach(line => {
        if (!line) return;
        const span = document.createElement('span');
        span.style.color = color(line);
        span.textContent = line + '\\n';
        box.appendChild(span);
      });
      box.scrollTop = box.scrollHeight;
    }

    function setStatus(txt) { document.getElementById('status').textContent = txt; }

    function startAgent() {
      fetch('/start', {method:'POST'}).then(r => r.json()).then(d => {
        if (!d.ok) { appendLog('❌ ' + d.msg); return; }
        document.getElementById('btn-start').disabled = true;
        document.getElementById('btn-stop').disabled  = false;
        setStatus('⏳ En cours…');
        appendLog('=== Démarrage ===\\n');
        listenLogs();
      });
    }

    function stopAgent() {
      fetch('/stop', {method:'POST'});
    }

    function listenLogs() {
      if (es) es.close();
      es = new EventSource('/stream');
      es.onmessage = e => {
        const data = JSON.parse(e.data);
        if (data.type === 'log')  appendLog(data.text);
        if (data.type === 'done') {
          document.getElementById('btn-start').disabled = false;
          document.getElementById('btn-stop').disabled  = true;
          setStatus(data.code === 0 ? '✅ Terminé' : '❌ Erreur (' + data.code + ')');
          appendLog('=== Terminé — code ' + data.code + ' ===\\n');
          es.close();
        }
      };
    }
  </script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/start", methods=["POST"])
def start():
    global _proc, _running
    if _running:
        return jsonify(ok=False, msg="Déjà en cours.")
    _running = True

    # Vide la queue
    while not _log_queue.empty():
        try: _log_queue.get_nowait()
        except queue.Empty: break

    env = os.environ.copy()

    def run():
        global _proc, _running
        _proc = subprocess.Popen(
            [sys.executable, "agent.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        for line in _proc.stdout:
            _log_queue.put({"type": "log", "text": line.rstrip("\n")})
        _proc.wait()
        _log_queue.put({"type": "done", "code": _proc.returncode})
        _running = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify(ok=True)


@app.route("/stop", methods=["POST"])
def stop():
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
    return jsonify(ok=True)


@app.route("/stream")
def stream():
    def generate():
        import json
        while True:
            try:
                item = _log_queue.get(timeout=30)
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("type") == "done":
                    break
            except queue.Empty:
                yield "data: {\"type\":\"ping\"}\n\n"
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    port = int(os.getenv("WEBGUI_PORT", 5050))
    print(f"🌐 GUI disponible sur http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
