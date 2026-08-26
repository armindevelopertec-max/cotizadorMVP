import json
import os
import time
import urllib.parse
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8000
HOST = "0.0.0.0"

API_TOKEN = os.environ.get("API_TOKEN", "armin2DEV")

ALLOWED_DOMAINS = [
    "dicabolivia.com",
    "www.dicabolivia.com",
]

_rate_limit = {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def _check_rate_limit(self):
        ip = self.client_address[0]
        now = time.time()
        if ip in _rate_limit:
            timestamps = [t for t in _rate_limit[ip] if now - t < 60]
            if len(timestamps) >= 60:
                return False
            _rate_limit[ip] = timestamps
        else:
            _rate_limit[ip] = []
        _rate_limit[ip].append(now)
        return True

    def _get_token(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return ""

    def do_GET(self):
        if self.path.startswith("/api/img"):
            self._proxy_image()
            return
        super().do_GET()

    def _proxy_image(self):
        if not self._check_rate_limit():
            self._json_response(429, {"ok": False, "error": "demasiadas peticiones"})
            return

        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url = (qs.get("url") or [""])[0]
        if not url.startswith(("http://", "https://")):
            self._json_response(400, {"ok": False, "error": "url invalida"})
            return

        try:
            host = urllib.parse.urlparse(url).hostname or ""
        except Exception:
            self._json_response(400, {"ok": False, "error": "url invalida"})
            return

        if host not in ALLOWED_DOMAINS:
            self._json_response(403, {"ok": False, "error": "dominio no permitido"})
            return

        try:
            parts = urllib.parse.urlsplit(url)
            url = urllib.parse.urlunsplit((
                parts.scheme,
                parts.netloc,
                urllib.parse.quote(parts.path, safe="/%"),
                parts.query,
                "",
            ))
        except Exception:
            pass

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
        except Exception as exc:
            self._json_response(502, {"ok": False, "error": str(exc)})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._check_rate_limit():
            self._json_response(429, {"ok": False, "error": "demasiadas peticiones"})
            return

        if self.path.rstrip("/") != "/api/save":
            self._json_response(404, {"ok": False, "error": "ruta no encontrada"})
            return

        if self._get_token() != API_TOKEN:
            self._json_response(401, {"ok": False, "error": "no autorizado"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 10 * 1024 * 1024:
                raise ValueError("payload demasiado grande (max 10MB)")
            payload = json.loads(self.rfile.read(length))
            filename = os.path.basename(payload.get("file", ""))
            data = payload.get("data")

            if not filename.endswith(".json") or "/" in filename or "\\" in filename:
                raise ValueError("nombre de archivo invalido")
            if not isinstance(data, list):
                raise ValueError("data debe ser una lista de productos")

            target = os.path.join(ROOT, filename)
            backup = target + ".bak"
            if os.path.exists(target):
                os.replace(target, backup)

            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, target)

            self._json_response(200, {"ok": True, "file": filename, "items": len(data)})
        except Exception as exc:
            self._json_response(400, {"ok": False, "error": str(exc)})

    def _json_response(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"Servidor corriendo en http://{HOST}:{PORT}/panel.html")
    print(f"Token API: {'***' + API_TOKEN[-4:] if len(API_TOKEN) > 4 else '(no configurado)'}")
    HTTPServer((HOST, PORT), Handler).serve_forever()
