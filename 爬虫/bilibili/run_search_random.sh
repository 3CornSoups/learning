#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
exec .venv/bin/python -u search_random_bilibili.py --api-mode "$@"
