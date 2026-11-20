#!/bin/sh
set -eu
export PATH="${PATH:-/usr/bin:/bin}:/opt/homebrew/bin:/usr/local/bin"
here=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
step=${1:-}; shift || :
case "$step" in collect|media|package) ;; *) echo 'usage: sh run.sh collect|media|package ...' >&2; exit 2;; esac
for py in "$here/../.venv/bin/python" python3 "$HOME/anaconda3/bin/python3" "$HOME/miniconda3/bin/python3"; do
    if command -v "$py" >/dev/null && "$py" -c 'import playwright.sync_api, PIL' >/dev/null 2>&1; then
        exec "$py" -B "$here/$step.py" "$@"
    fi
done
echo '需要同一个 Python 环境包含 playwright 和 Pillow，并安装 ffmpeg 与 ffprobe。' >&2
exit 1
