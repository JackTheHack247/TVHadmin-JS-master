#!/bin/sh
# Start the TVHadmin VLC helper (run on the Pi desktop, same machine as Pale Moon + VLC).
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-8765}"
exec python3 "$DIR/tvhadmin_vlc_helper.py" "$PORT"
