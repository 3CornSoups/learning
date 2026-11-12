#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
if [[ $# -gt 0 && "$1" == '--help' ]]; then
  echo '在当前项目目录创建独立环境；可用 UV_PROJECT_ENVIRONMENT 覆盖默认的 .venv。'
  exit 0
fi
ENV_DIR="${UV_PROJECT_ENVIRONMENT:-$PROJECT_DIR/.venv}"
if ! command -v uv >/dev/null 2>&1; then echo '未找到 uv；请安装 uv 后重试。' >&2; exit 2; fi
export UV_PROJECT_ENVIRONMENT="$ENV_DIR"
export UV_CACHE_DIR="$PROJECT_DIR/.cache/uv"
export XDG_CACHE_HOME="$PROJECT_DIR/.cache"
export TMPDIR="$PROJECT_DIR/.cache/tmp"
export UV_PYTHON_DOWNLOADS=never
export UV_LINK_MODE=symlink
export PYTHONDONTWRITEBYTECODE=1
umask 077
mkdir -p -- "$TMPDIR"
cd -- "$PROJECT_DIR"
if [[ -x "$ENV_DIR/bin/python" ]]; then PYTHON_BIN="$ENV_DIR/bin/python"; else PYTHON_BIN="$(command -v python3.12 || true)"; fi
if [[ -z "$PYTHON_BIN" ]]; then echo '需要已安装的 Python 3.12' >&2; exit 2; fi
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3,12), "需要 Python 3.12"'
echo "项目：$PROJECT_DIR"
echo "独立环境：$UV_PROJECT_ENVIRONMENT"
echo "缓存：$UV_CACHE_DIR"
uv sync --frozen --inexact --python "$PYTHON_BIN"
bash "$PROJECT_DIR/run.sh" doctor --no-cookie
