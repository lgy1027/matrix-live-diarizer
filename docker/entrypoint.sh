#!/bin/sh
# 首次启动检测 + 模型下载提示
set -e

MS_CACHE_DIR="${MODELSCOPE_CACHE:-/home/matrix/.cache/modelscope}"
TORCH_CACHE_DIR="${TORCH_HOME:-/home/matrix/.cache/torch}"
HF_CACHE_DIR="${HF_HOME:-/home/matrix/.cache/huggingface}"
mkdir -p "$MS_CACHE_DIR" "$TORCH_CACHE_DIR" "$HF_CACHE_DIR"

if [ ! -d "$MS_CACHE_DIR" ] || [ -z "$(ls -A "$MS_CACHE_DIR" 2>/dev/null)" ]; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║  首次启动: 即将下载 ASR 模型 (~1.8GB)                      ║"
    echo "║  下载过程会持续 5-20 分钟,取决于网速                        ║"
    echo "║  完成后会缓存到 volume,后续启动秒起                        ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
fi

exec "$@"
