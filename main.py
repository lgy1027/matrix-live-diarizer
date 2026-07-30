"""Matrix Live Diarizer 入口"""
import os
import sys

# 进程级收紧文件权限掩码:上传录音、实时录音、SQLite、SSL 证书等所有后续
# 创建的文件默认 0600、目录 0700。本地优先 + 多用户主机场景下,避免其他
# 本地用户可读敏感音频/转写/声纹。必须在任何文件创建前设置。
os.umask(0o077)

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

# 可选 HTTPS:跨机器访问时浏览器要求安全上下文(否则 http://IP 下 getUserMedia 被禁)。
# 设 ENABLE_HTTPS=1 用 data/ssl/ 自签证书直接跑 HTTPS
# (证书用 python scripts/gen_self_cert.py 跨平台生成)。
# 本机 127.0.0.1 访问不需要,默认不开。
_ssl_kwargs: dict = {}
if os.environ.get("ENABLE_HTTPS", "").lower() in ("1", "true", "yes"):
    from pathlib import Path

    cert = Path(os.environ.get("SSL_CERT", "data/ssl/selfsigned.crt"))
    key = Path(os.environ.get("SSL_KEY", "data/ssl/selfsigned.key"))
    if not cert.is_file() or not key.is_file():
        print(
            "[main] ENABLE_HTTPS=1 但证书不存在,请先运行: "
            "python scripts/gen_self_cert.py"
        )
        sys.exit(1)
    _ssl_kwargs = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers,
        **_ssl_kwargs,
    )
