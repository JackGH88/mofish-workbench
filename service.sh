#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")" && pwd)"
python_command="$project_dir/.venv/bin/python"
if [[ ! -x "$python_command" ]]; then python_command="python3"; fi
exec "$python_command" "$project_dir/scripts/service.py" "$@"
