#!/bin/zsh
set -eu
BASE=${0:A:h}
cd "$BASE"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  print '请在 Apple Silicon Mac 的原生终端中运行此构建入口。'
  exit 2
fi
BREW=/opt/homebrew/bin/brew
if [[ ! -x "$BREW" ]]; then
  print '构建需要 Homebrew：https://brew.sh/ 。安装后重新运行本入口。'
  exit 2
fi
"$BREW" install python@3.14 python-tk@3.14 ffmpeg@6 gpac
PYTHON="$("$BREW" --prefix python@3.14)/bin/python3.14"
"$PYTHON" -m venv "$BASE/.venv"
"$BASE/.venv/bin/python" -m pip install -r "$BASE/requirements-macos.txt"
"$BASE/.venv/bin/python" "$BASE/build_macos.py"
print "构建完成：$BASE/dist"
open "$BASE/dist"
