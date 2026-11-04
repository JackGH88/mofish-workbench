#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")" && pwd)"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "此安装入口用于 macOS；Windows 请使用 install.ps1。" >&2
  exit 1
fi
cd "$project_dir"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -e .env ]]; then cp .env.example .env; fi
exec .venv/bin/python scripts/service.py install "$@"
