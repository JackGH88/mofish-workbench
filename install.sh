#!/usr/bin/env bash
set -euo pipefail
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
project_dir="$(cd "$(dirname "$0")" && pwd)"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "此安装入口用于 macOS；Windows 请使用 install.ps1。" >&2
  exit 1
fi
cd "$project_dir"
# Execute each candidate: an alias or a newer Python is not a usable environment.
probe='import sys,struct,venv,ensurepip; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) and struct.calcsize("P")==8 else 1)'
python=""
if [[ -e .venv || -L .venv ]]; then
  if .venv/bin/python -c "$probe" >/dev/null 2>&1; then
    python="$project_dir/.venv/bin/python"
  else
    echo "已有 .venv 不是可用的 Python 3.11/3.12 64 位环境，已保留原环境；请 Agent 先检查迁移方案。" >&2
    exit 1
  fi
else
  bootstrap_args=(--root "$project_dir")
  checking=false
  for arg in "$@"; do [[ "$arg" != --check ]] || checking=true; done
  $checking && bootstrap_args+=(--check)
  status=0
  python="$(/bin/bash "$project_dir/scripts/source-runtime.sh" "${bootstrap_args[@]}")" || status=$?
  case "$status" in
    0) [[ -n "$python" ]] || { echo 'Runtime bootstrap returned no Python path.' >&2; exit 1; };;
    3) ;; # No published entry: official system-Python fallback is allowed.
    4) $checking || exit 4;; # Read-only check may use an existing system Python.
    *) exit "$status";;
  esac
  if [[ -z "$python" ]]; then
    for candidate in python3.12 python3.11 /opt/homebrew/opt/python@3.12/bin/python3.12 /opt/homebrew/opt/python@3.11/bin/python3.11 python3; do
      if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "$probe" >/dev/null 2>&1; then
        python="$(command -v "$candidate")"
        break
      fi
    done
  fi
fi
if [[ -z "$python" ]]; then
  echo "未找到可用的 Python 3.11/3.12（含 venv、pip）。请 Agent 按公开 README 从官方来源准备 Python 后重跑；不需删除任何配置。" >&2
  exit 1
fi
exec "$python" scripts/source_install.py "$@"
