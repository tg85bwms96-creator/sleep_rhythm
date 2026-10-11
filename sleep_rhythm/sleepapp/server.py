"""Stateless WSGI app: allow-listed static files plus a small JSON API.

No sleep data are stored server-side and request bodies are never logged.
Deploy behind HTTPS (e.g. Render) with the Waitress server started by run.py.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .analysis import analysis
from .model import InputError, iso, recommend, research, summary, validate_dataset

ROOT = Path(__file__).resolve().parent.parent / "web"
LIMIT = 524288  # bytes; matches the 512 KB backup limit in the browser
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/utils.js": ("utils.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}
SHELL_TOKEN = b"__SHELL_VERSION__"


def shell_version():
    """Hash of every cached app-shell file, injected into sw.js so that any change to
    them makes browsers install a new service worker and re-cache the whole shell."""
    digest = hashlib.sha256()
    for path in sorted(STATIC):
        if path not in ("/", "/sw.js"):
            digest.update(path.encode() + b"\0" + (ROOT / STATIC[path][0]).read_bytes())
    return digest.hexdigest()[:12]


CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; "
       "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


class ClientError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _validate(payload):
    profile, _, records, observations = validate_dataset(payload, datetime.now(timezone.utc))
    return {"valid": True, "profile": profile,
            "records": [{"id": r.id, "start": iso(r.start), "end": iso(r.end), "kind": r.kind,
                         "sleepiness_wake": r.sleepiness_wake, "light_minutes": r.light_minutes}
                        for r in records],
            "observations": [{"id": r["id"], "at": iso(r["at"]), "sleepiness": r["sleepiness"]}
                             for r in observations]}


API = {"/api/summary": summary, "/api/validate": _validate, "/api/recommend": recommend,
       "/api/research": research, "/api/analysis": analysis}


def response(start_response, status, body, ctype="application/json; charset=utf-8",
             head=False, https=False, extra=()):
    if not isinstance(body, bytes):
        body = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    headers = [
        ("Content-Type", ctype), ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
        ("Content-Security-Policy", CSP), *extra,
    ]
    if https:
        headers.append(("Strict-Transport-Security", "max-age=31536000"))
    start_response(status, headers)
    return [b"" if head else body]


def hostname(host):
    """Host header without the port; keeps IPv6 literals such as [::1] intact."""
    host = host.strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _read_json(environ, host):
    origin = environ.get("HTTP_ORIGIN")
    if (environ.get("HTTP_SEC_FETCH_SITE") == "cross-site"
            or (origin and urlparse(origin).netloc.lower() != host.lower())):
        raise ClientError("403 Forbidden", "같은 앱 화면에서만 요청할 수 있습니다.")
    if environ.get("CONTENT_TYPE", "").split(";")[0].strip() != "application/json":
        raise ClientError("415 Unsupported Media Type", "JSON 형식이 필요합니다.")
    try:
        size = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        size = -1
    if size <= 0:
        raise ClientError("411 Length Required", "요청 본문의 길이가 필요합니다.")
    if size > LIMIT:
        raise ClientError("413 Content Too Large", "입력 파일은 512KB 이하여야 합니다.")
    raw = environ["wsgi.input"].read(size)
    if len(raw) != size:
        raise ClientError("400 Bad Request", "요청이 끝까지 도착하지 않았습니다.")

    def reject_constant(_):
        raise ValueError("non-finite JSON number")

    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ClientError("400 Bad Request", "읽을 수 없는 JSON입니다.") from None


def application(environ, start_response):
    method, path = environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO", "/")
    host = environ.get("HTTP_HOST", "")
    https = (environ.get("wsgi.url_scheme") == "https"
             or environ.get("HTTP_X_FORWARDED_PROTO", "").split(",")[0].strip() == "https")

    def send(status, body, ctype="application/json; charset=utf-8", extra=()):
        return response(start_response, status, body, ctype, method == "HEAD", https, extra)

    # Optional host allow-list; the health check stays reachable for platform probes.
    allowed = {hostname(h) for h in os.environ.get("RHYTHM_ALLOWED_HOSTS", "").split(",") if h.strip()}
    if allowed and path != "/healthz" and hostname(host) not in allowed:
        return send("400 Bad Request", {"error": "허용되지 않은 호스트입니다."})
    if path == "/healthz" or path in STATIC:
        if method not in ("GET", "HEAD"):
            return send("405 Method Not Allowed", {"error": "GET 요청만 허용됩니다."},
                        extra=[("Allow", "GET, HEAD")])
        if path == "/healthz":
            return send("200 OK", {"status": "ok", "version": __version__})
        file, ctype = STATIC[path]
        body = (ROOT / file).read_bytes()
        if path == "/sw.js":
            body = body.replace(SHELL_TOKEN, shell_version().encode())
        return send("200 OK", body, ctype)
    if path not in API:
        return send("404 Not Found", {"error": "페이지를 찾을 수 없습니다."})
    if method != "POST":
        return send("405 Method Not Allowed", {"error": "POST 요청이 필요합니다."},
                    extra=[("Allow", "POST")])
    try:
        payload = _read_json(environ, host)
        result = API[path](payload)
        body = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    except ClientError as err:
        return send(err.status, {"error": str(err)})
    except InputError as err:
        return send("400 Bad Request", {"error": str(err)})
    except Exception as err:  # never echo or log request data; log only the error type and code location
        tb = err.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        where = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}" if tb else "unknown"
        print(f"[rhythm] {path} failed: {type(err).__name__} at {where}", file=sys.stderr, flush=True)
        return send("500 Internal Server Error",
                    {"error": f"계산 중 오류가 발생했습니다. 기록을 JSON으로 백업한 뒤, 앱 버전({__version__})과 함께 관리자에게 알려 주세요."})
    return send("200 OK", body)
