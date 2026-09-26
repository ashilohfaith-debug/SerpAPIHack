"""Vercel entrypoint serving the RELAY accessible web showcase and panel."""

from __future__ import annotations

import mimetypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def app(environ, start_response):
    raw_path = environ.get("PATH_INFO", "/") or "/"
    clean_path = raw_path.lstrip("/")

    if not clean_path or clean_path == "/":
        target = FRONTEND / "index.html"
    else:
        target = FRONTEND / clean_path
        if not target.exists() or not target.is_file():
            target = FRONTEND / "index.html"

    if target.exists() and target.is_file():
        ctype, _ = mimetypes.guess_type(str(target))
        if not ctype:
            if target.suffix == ".css":
                ctype = "text/css"
            elif target.suffix == ".js":
                ctype = "application/javascript"
            elif target.suffix == ".html":
                ctype = "text/html"
            else:
                ctype = "application/octet-stream"

        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"

        body = target.read_bytes()
        start_response("200 OK", [
            ("Content-Type", ctype),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "public, max-age=3600"),
        ])
        return [body]

    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    return [b"Not Found"]
