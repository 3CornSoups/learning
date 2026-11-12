#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
ENV_DIR="${UV_PROJECT_ENVIRONMENT:-$PROJECT_DIR/.venv}"
if [[ ! -x "$ENV_DIR/bin/python" ]]; then
  echo "未找到 $ENV_DIR/bin/python；先阅读 README 并运行 bash scripts/setup.sh" >&2
  exit 2
fi
export UV_PROJECT_ENVIRONMENT="$ENV_DIR"
export UV_CACHE_DIR="$PROJECT_DIR/.cache/uv"
export XDG_CACHE_HOME="$PROJECT_DIR/.cache"
export TMPDIR="$PROJECT_DIR/.cache/tmp"
export PYTHONIOENCODING=utf-8
export PYTHONDONTWRITEBYTECODE=1
export CZK_VIDEO_STORE="${CZK_VIDEO_STORE:-$PROJECT_DIR/data/videos}"
umask 077
mkdir -p -- "$TMPDIR"
cd -- "$PROJECT_DIR"
exec "$ENV_DIR/bin/python" "$PROJECT_DIR/run.py" "$@"
