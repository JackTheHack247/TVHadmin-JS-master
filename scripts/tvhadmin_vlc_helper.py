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
import os
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


def launch_vlc(url, title=None, fullscreen=True):
    cmd = [
        "vlc",
        "--one-instance",
        "--one-instance-when-started",
        "--no-playlist-enqueue",
    ]
    if fullscreen:
        cmd.append("--fullscreen")
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


def raise_browser_window():
    """Bring the TVHadmin browser window to the front (VLC fullscreen hides it otherwise)."""
    titles = [
        "TVHadmin",
        "Pale Moon",
        "pale moon",
        "Firefox",
        "Chromium",
        "TVHeadend",
    ]
    extra = os.environ.get("TVHADMIN_WM_TITLE", "").strip()
    if extra:
        titles.insert(0, extra)
    for title in titles:
        try:
            if (
                subprocess.call(
                    ["wmctrl", "-a", title],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                == 0
            ):
                return True
        except FileNotFoundError:
            break
        except Exception:
            pass
    try:
        if (
            subprocess.call(
                [
                    "xdotool",
                    "search",
                    "--name",
                    "TVHadmin",
                    "windowactivate",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            == 0
        ):
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return False


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

    def _play(self, url, title=None, fullscreen=True):
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
            launch_vlc(url, title=title, fullscreen=fullscreen)
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
        fs = qs.get("fullscreen", ["1"])[0]
        fullscreen = fs not in ("0", "false", "no")
        return url, title, fullscreen

    def do_GET(self):
        if self.path.startswith("/play"):
            url, title, fullscreen = self._read_play_args()
            if not url:
                url = self._read_url()
            self._play(url, title=title, fullscreen=fullscreen)
            return
        if self.path.startswith("/stop"):
            stop_vlc()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        if self.path.startswith("/raise"):
            ok = raise_browser_window()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            msg = json.dumps({"ok": ok}).encode("utf-8")
            self.wfile.write(msg)
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


class ReuseHTTPServer(HTTPServer):
    allow_reuse_address = True


def port_in_use_error(err):
    if getattr(err, "errno", None) in (98, 48):
        return True
    if getattr(err, "winerror", None) == 10048:
        return True
    return False


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    try:
        server = ReuseHTTPServer((BIND, port), Handler)
    except OSError as exc:
        if port_in_use_error(exc):
            sys.stderr.write(
                "[tvhadmin-vlc-helper] Port %s is already in use on %s.\n"
                % (port, BIND)
            )
            sys.stderr.write(
                "  If the helper is already running, you do not need to start it again.\n"
                "  Check: curl -s http://127.0.0.1:%s/health\n"
                % port
            )
            sys.stderr.write(
                "  To restart after an update: pkill -f tvhadmin_vlc_helper.py\n"
                "  then run start-vlc-helper.sh again, or: sh start-vlc-helper.sh --restart\n"
            )
            raise SystemExit(1)
        raise
    print("TVHadmin VLC helper on http://%s:%s (Ctrl+C to stop)" % (BIND, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


if __name__ == "__main__":
    main()
