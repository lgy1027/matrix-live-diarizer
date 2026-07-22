#!/usr/bin/env bash
# Backward-compatible wrapper. The Python script handles macOS and Linux;
# Windows users should run: python scripts/gen_self_cert.py
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[cert] 未找到 Python。请安装 Python 3 并确保命令位于 PATH 中。" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/gen_self_cert.py"
