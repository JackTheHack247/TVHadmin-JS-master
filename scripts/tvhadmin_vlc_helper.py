#!/usr/bin/env python3
"""
TVHadmin local helper — launches VLC when the browser cannot (Pi / Pale Moon).

Listen on 127.0.0.1 only. TVHadmin calls:
  GET http://127.0.0.1:8765/play?url=<encoded-stream-url>

Usage:
  python3 tvhadmin_vlc_helper.py [port]
  ./tvhadmin_vlc_helper.py

Requires: vlc in PATH
"""
from __future__ import print_function

import json
import re
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_PORT = 8765
BIND = "127.0.0.1"

STREAM_PATH = re.compile(
    r"^/(?:play/ticket/(?:stream/|dvrfile/)|stream/(?:channel|file|channelid|channelnumber|channelname)/)",
    re.I,
)


def allowed_host(hostname):
    if not hostname:
        return False
    h = hostname.lower()
    if h in ("localhost", "127.0.0.1", "::1"):
        return True
    if re.match(r"^192\.168\.\d{1,3}\.\d{1,3}$", h):
        return True
    if re.match(r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$", h):
        return True
    if re.match(r"^172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}$", h):
        return True
    return False


def url_is_allowed(url):
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    if not allowed_host(u.hostname):
        return False
    path = u.path or ""
    return bool(STREAM_PATH.match(path))


def launch_vlc(url, title=None):
    cmd = [
        "vlc",
        "--fullscreen",
        "--one-instance",
        "--one-instance-when-started",
        "--no-playlist-enqueue",
    ]
    if title:
        safe = re.sub(r"[\r\n\x00]", " ", title).strip()[:200]
        if safe:
            cmd.append("--meta-title=" + safe)
    cmd.append(url)
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop_vlc():
    """Quit VLC (optional — TVHadmin keeps VLC running when opening the menu)."""
    try:
        subprocess.call(
            ["pkill", "-TERM", "vlc"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[tvhadmin-vlc-helper] %s\n" % (fmt % args))

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _read_url(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if qs.get("url"):
            return unquote(qs["url"][0])
        length = int(self.headers.get("Content-Length") or 0)
        if length and length < 8192:
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                return body.get("url") or ""
            except Exception:
                pass
        return ""

    def _play(self, url, title=None):
        url = (url or "").strip()
        if not url:
            self.send_response(400)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"missing url"}')
            return
        if not url_is_allowed(url):
            self.send_response(403)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"url not allowed"}')
            return
        try:
            launch_vlc(url, title=title)
        except FileNotFoundError:
            self.send_response(500)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"vlc not found in PATH"}')
            return
        except Exception as exc:
            self.send_response(500)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            msg = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self.wfile.write(msg)
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _read_play_args(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        url = ""
        if qs.get("url"):
            url = unquote(qs["url"][0])
        title = unquote(qs["title"][0]) if qs.get("title") else None
        return url, title

    def do_GET(self):
        if self.path.startswith("/play"):
            url, title = self._read_play_args()
            if not url:
                url = self._read_url()
            self._play(url, title=title)
            return
        if self.path.startswith("/stop"):
            stop_vlc()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        if self.path.startswith("/health"):
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"service":"tvhadmin-vlc-helper"}')
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path.startswith("/play"):
            url = ""
            title = None
            length = int(self.headers.get("Content-Length") or 0)
            if length and length < 8192:
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    url = body.get("url") or ""
                    title = body.get("title")
                except Exception:
                    pass
            self._play(url, title=title)
            return
        self.send_response(404)
        self.end_headers()


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    server = HTTPServer((BIND, port), Handler)
    print("TVHadmin VLC helper on http://%s:%s (Ctrl+C to stop)" % (BIND, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


if __name__ == "__main__":
    main()
