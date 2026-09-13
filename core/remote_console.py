from __future__ import annotations

import json
import errno
import secrets
import socket
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, Optional
from urllib.parse import parse_qs, urlparse


REMOTE_CONSOLE_HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Raphel Remote Console</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #0f172a; color: #e2e8f0; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 18px; }
    .grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 16px; }
    .panel { background: #111827; border: 1px solid #334155; border-radius: 10px; padding: 14px; }
    h1, h2 { margin: 0 0 12px; font-weight: 600; }
    h1 { font-size: 20px; }
    h2 { font-size: 15px; color: #93c5fd; }
    .muted { color: #94a3b8; font-size: 13px; }
    textarea, input, button { font: inherit; }
    textarea { width: 100%; min-height: 74px; resize: vertical; border-radius: 8px; border: 1px solid #475569; background: #020617; color: #e2e8f0; padding: 10px; }
    input[type="text"] { width: 100%; border-radius: 8px; border: 1px solid #475569; background: #020617; color: #e2e8f0; padding: 8px 10px; }
    button { border: 0; border-radius: 8px; background: #2563eb; color: white; padding: 10px 12px; cursor: pointer; }
    button.secondary { background: #334155; }
    button:disabled { opacity: 0.6; cursor: default; }
    .row { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
    .pill { display: inline-block; padding: 3px 8px; border-radius: 999px; background: #1e293b; color: #bfdbfe; font-size: 12px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #020617; border-radius: 8px; padding: 10px; border: 1px solid #334155; min-height: 88px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #1e293b; vertical-align: top; }
    th { color: #93c5fd; font-weight: 600; }
    .log { max-height: 420px; overflow: auto; font-size: 12px; }
    .log-item { padding: 8px 0; border-bottom: 1px solid #1e293b; }
    .good { color: #86efac; }
    .warn { color: #facc15; }
    .bad { color: #fca5a5; }
    @media (max-width: 920px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Raphel Remote Console</h1>
    <div class="muted">Consola remota para otra computadora o acceso online via LAN/tunel.</div>
    <div class="grid" style="margin-top: 16px;">
      <div class="panel">
        <h2>Comando</h2>
        <textarea id="command" placeholder="Escribe un comando, por ejemplo: input-training-status"></textarea>
        <div class="row">
          <button id="send">Enviar</button>
          <button id="trainingStart" class="secondary">Iniciar loop</button>
          <button id="trainingStop" class="secondary">Detener loop</button>
          <label class="muted"><input id="autoConfirm" type="checkbox"> auto confirmar</label>
        </div>
        <h2 style="margin-top:16px;">Resultado</h2>
        <pre id="result">Esperando comando...</pre>
      </div>
      <div class="panel">
        <h2>Estado</h2>
        <div id="status" class="muted">Cargando...</div>
        <div class="row" style="margin-top:12px;">
          <span class="pill" id="loopState">loop: ?</span>
          <span class="pill" id="remoteState">remoto: ?</span>
        </div>
        <h2 style="margin-top:16px;">Perfiles</h2>
        <div style="overflow:auto;"><table id="profiles"><thead><tr><th>Skill</th><th>Legacy</th><th>Exp</th><th>Tendencia</th><th>Gate</th></tr></thead><tbody></tbody></table></div>
      </div>
    </div>
    <div class="panel" style="margin-top:16px;">
      <h2>Eventos recientes</h2>
      <div id="events" class="log"></div>
    </div>
  </div>
  <script>
    const token = new URLSearchParams(window.location.search).get("token") || "";
    async function api(path, options = {}) {
      const headers = Object.assign({"Content-Type": "application/json"}, options.headers || {});
      if (token) headers["Authorization"] = "Bearer " + token;
      const response = await fetch(path, Object.assign({}, options, {headers}));
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || ("HTTP " + response.status));
      }
      return response.json();
    }
    function renderProfiles(payload) {
      const tbody = document.querySelector("#profiles tbody");
      tbody.innerHTML = "";
      for (const profile of (payload.profiles || []).slice(0, 12)) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${profile.display_name}</td><td>${profile.current_level}</td><td>${profile.exponential_level}/6</td><td>${profile.trend}</td><td>${profile.next_gate_status}</td>`;
        tbody.appendChild(tr);
      }
    }
    function renderEvents(payload) {
      const root = document.getElementById("events");
      root.innerHTML = "";
      for (const event of (payload.events || []).slice().reverse()) {
        const div = document.createElement("div");
        div.className = "log-item";
        div.innerHTML = `<div><strong>${event.level}</strong> <span class="muted">${event.timestamp}</span></div><div>${event.message}</div>`;
        root.appendChild(div);
      }
    }
    async function refresh() {
      const payload = await api("/api/state");
      const remoteUrls = payload.remote.access_urls || [payload.remote.primary_url || payload.remote.listen_url];
      document.getElementById("status").textContent = (
        payload.training.running
          ? payload.training.last_result
          : "Loop detenido. " + payload.training.last_result
      ) + "\\n" + remoteUrls.join(" | ");
      document.getElementById("loopState").textContent = "loop: " + (payload.training.running ? "corriendo" : "detenido");
      document.getElementById("remoteState").textContent = "remoto: " + (payload.remote.running ? "activo" : "detenido");
      renderProfiles(payload.progress);
      renderEvents(payload);
    }
    async function sendCommand(command) {
      const payload = await api("/api/command", {
        method: "POST",
        body: JSON.stringify({
          command,
          auto_confirm: document.getElementById("autoConfirm").checked
        })
      });
      document.getElementById("result").textContent = payload.result || "";
      await refresh();
    }
    document.getElementById("send").onclick = () => sendCommand(document.getElementById("command").value.trim());
    document.getElementById("trainingStart").onclick = () => sendCommand("input-training-start");
    document.getElementById("trainingStop").onclick = () => sendCommand("input-training-stop");
    refresh().catch(err => document.getElementById("result").textContent = String(err));
    setInterval(() => refresh().catch(() => {}), 2500);
  </script>
</body>
</html>
"""


class RemoteConsoleServer:
    def __init__(
        self,
        assistant: Any,
        logger: Optional[Any] = None,
        state_path: Optional[Path] = None,
    ) -> None:
        self.assistant = assistant
        self.logger = logger
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._command_lock = threading.Lock()
        self._event_lock = threading.Lock()
        self._events: Deque[Dict[str, Any]] = deque(maxlen=200)
        self._token: str = ""
        self._host = "127.0.0.1"
        self._port = 8765
        self._started_at = 0.0
        self._state_path = Path(state_path) if state_path else Path(__file__).resolve().parent.parent / "data" / "remote_console_state.json"
        self._restore_persisted_state()
        self.assistant.add_status_listener(self._record_status_event)

    def start(self, host: str = "127.0.0.1", port: int = 8765, token: Optional[str] = None) -> Dict[str, Any]:
        requested_host = str(host or "127.0.0.1")
        requested_port = int(port or 8765)
        requested_token = str(token or self._token or secrets.token_urlsafe(24))
        if self.is_running():
            if (
                self._host == requested_host
                and int(self._port) == requested_port
                and self._token == requested_token
            ):
                return self.status_payload()
            self.stop()
        self._host = requested_host
        self._port = requested_port
        self._token = requested_token
        self._httpd = ThreadingHTTPServer((self._host, self._port), self._make_handler())
        self._port = int(self._httpd.server_address[1])
        self._httpd.daemon_threads = True
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="raphel-remote-console")
        self._thread.start()
        self._persist_state()
        self._record_event("info", f"Consola remota activa en {self.listen_url}")
        return self.status_payload()

    def stop(self) -> Dict[str, Any]:
        httpd = self._httpd
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
        self._httpd = None
        self._thread = None
        self._token = ""
        self._clear_persisted_state()
        self._record_event("info", "Consola remota detenida.")
        return self.status_payload()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._httpd)

    @property
    def listen_url(self) -> str:
        return f"http://{self._host}:{self._port}/?token={self._token}" if self._token else f"http://{self._host}:{self._port}/"

    def status_payload(self) -> Dict[str, Any]:
        access_urls = self._access_urls()
        return {
            "running": self.is_running(),
            "host": self._host,
            "port": self._port,
            "token": self._token,
            "listen_url": self.listen_url,
            "primary_url": access_urls[0] if access_urls else self.listen_url,
            "access_urls": access_urls,
            "token_hint": f"{self._token[:4]}..." if self._token else "",
            "started_at": self._started_at,
        }

    def _restore_persisted_state(self) -> None:
        try:
            if not self._state_path.exists():
                return
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        token = str(payload.get("token", "") or "").strip()
        if token:
            self._token = token
        try:
            self._host = str(payload.get("host") or self._host)
            self._port = int(payload.get("port") or self._port)
        except Exception:
            self._host = self._host or "127.0.0.1"
            self._port = int(self._port or 8765)

    def _persist_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(
                    {
                        "host": self._host,
                        "port": int(self._port),
                        "token": self._token,
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            if self.logger:
                self.logger.exception("No se pudo persistir remote_console_state.json")

    def _clear_persisted_state(self) -> None:
        try:
            if self._state_path.exists():
                self._state_path.unlink()
        except Exception:
            if self.logger:
                self.logger.exception("No se pudo limpiar remote_console_state.json")

    @staticmethod
    def _is_client_disconnect_error(exc: BaseException) -> bool:
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return True
        if isinstance(exc, OSError):
            if exc.errno in {errno.EPIPE, errno.ECONNABORTED, errno.ECONNRESET}:
                return True
            if getattr(exc, "winerror", None) in {10053, 10054}:
                return True
        return False

    def state_payload(self) -> Dict[str, Any]:
        return {
            "remote": self.status_payload(),
            "training": self.assistant.training_runtime_snapshot(),
            "progress": self.assistant.learning_skill_engine.training_progress_snapshot(),
            "events": list(self._events),
        }

    def execute_command(self, command: str, auto_confirm: bool = False) -> Dict[str, Any]:
        command = str(command or "").strip()
        if not command:
            return {"ok": False, "result": "Comando vacio."}
        with self._command_lock:
            previous = getattr(self.assistant, "_confirmation_provider", None)
            self.assistant.set_confirmation_provider(lambda _prompt: bool(auto_confirm))
            started_at = time.time()
            try:
                result = self.assistant.handle_command(command)
                payload = {"ok": True, "result": result}
                self._record_event("info", f"Remote command: {command}")
                return payload
            except Exception as exc:
                self._record_event("error", f"Remote command fallo: {command} :: {exc}")
                return {"ok": False, "result": str(exc)}
            finally:
                self.assistant.set_confirmation_provider(previous) if previous else self.assistant.set_confirmation_provider(None)
                elapsed_ms = round((time.time() - started_at) * 1000.0, 1)
                self._record_event("debug", f"Remote command tiempo: {command} :: {elapsed_ms}ms")

    def _record_status_event(self, message: str, level: str = "info") -> None:
        self._record_event(level, message)

    def _record_event(self, level: str, message: str) -> None:
        with self._event_lock:
            self._events.append(
                {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": str(level),
                    "message": str(message),
                }
            )

    def _authorized(self, handler: BaseHTTPRequestHandler) -> bool:
        if not self._token:
            return True
        auth_header = handler.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if token == self._token:
                return True
        parsed = urlparse(handler.path)
        query = parse_qs(parsed.query)
        return str(query.get("token", [""])[0]) == self._token

    def _access_urls(self) -> list[str]:
        token_suffix = f"?token={self._token}" if self._token else ""
        hosts: list[str] = []
        if self._host in {"0.0.0.0", "::"}:
            hosts.extend(["127.0.0.1", "localhost"])
            discovered: list[str] = []
            try:
                hostname = socket.gethostname()
                for candidate in socket.gethostbyname_ex(hostname)[2]:
                    if candidate and not candidate.startswith("127.") and candidate not in discovered:
                        discovered.append(candidate)
            except Exception:
                pass
            try:
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                probe.connect(("8.8.8.8", 80))
                candidate = str(probe.getsockname()[0] or "")
                probe.close()
                if candidate and not candidate.startswith("127.") and candidate not in discovered:
                    discovered.insert(0, candidate)
            except Exception:
                pass
            hosts.extend(discovered)
        else:
            hosts.append(self._host)
            if self._host in {"127.0.0.1", "localhost"}:
                sibling = "localhost" if self._host == "127.0.0.1" else "127.0.0.1"
                hosts.append(sibling)

        ordered_hosts: list[str] = []
        for host in hosts:
            if host and host not in ordered_hosts:
                ordered_hosts.append(host)
        return [f"http://{host}:{self._port}/{token_suffix}" for host in ordered_hosts]

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "RaphelRemoteConsole/1.0"

            def do_GET(self) -> None:
                if not outer._authorized(self):
                    self._json({"ok": False, "error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                parsed = urlparse(self.path)
                if parsed.path in {"/", "/index.html"}:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self._write_body(REMOTE_CONSOLE_HTML.encode("utf-8"))
                    return
                if parsed.path == "/api/state":
                    self._json(outer.state_payload())
                    return
                if parsed.path == "/api/health":
                    self._json({"ok": True, "running": True})
                    return
                self._json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                if not outer._authorized(self):
                    self._json({"ok": False, "error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except Exception:
                    payload = {}
                if parsed.path == "/api/command":
                    result = outer.execute_command(
                        command=str(payload.get("command", "")),
                        auto_confirm=bool(payload.get("auto_confirm", False)),
                    )
                    self._json(result)
                    return
                self._json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

            def log_message(self, fmt: str, *args: Any) -> None:
                if outer.logger:
                    outer.logger.debug("RemoteConsole: " + fmt, *args)

            def _json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self._write_body(body)

            def _write_body(self, body: bytes) -> None:
                try:
                    self.wfile.write(body)
                except Exception as exc:
                    if outer._is_client_disconnect_error(exc):
                        outer._record_event("debug", f"Cliente remoto cerro la conexion: {exc}")
                        return
                    raise

        return Handler
