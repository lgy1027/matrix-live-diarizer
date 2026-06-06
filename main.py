"""Matrix Live Diarizer 入口"""
import sys

# 强制 stdout 行缓冲 — 解决 macOS 上 Python stdout 默认 8KB 缓冲导致用户看不到模型加载进度的问题
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    # Python < 3.7 兼容
    pass

import uvicorn
from app import create_app
from app.config import config

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers
    )
