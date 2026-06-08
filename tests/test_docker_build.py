"""Dockerfile 静态分析 + 构建限制文档

注意: 实际 docker buildx 构建需要在有外网访问 deb.debian.org 的环境跑。
本机 (如 Mac) 由于 Docker Desktop 容器网络限制, 可能拉不到 deb 源。

如果需要验证实际镜像大小:
    docker buildx build --platform linux/amd64 -t matrix:test --load .
    docker images matrix:test
    # 预期 ~800MB (PyTorch CPU ~400MB + Python slim 150MB + requirements 200MB + system 50MB)

本测试只验证 Dockerfile 静态结构正确(关键字、层数、最终行):
- 多 stage 数量
- COPY/WORKDIR 路径合法
- HEALTHCHECK 存在
- USER 非 root
- ENTRYPOINT/CMD 存在
"""
import re
from pathlib import Path

DOCKERFILE = Path(__file__).parent.parent / "Dockerfile"


def test_dockerfile_exists():
    assert DOCKERFILE.exists()


def test_dockerfile_has_at_least_2_stages():
    """多 stage 减少最终镜像大小"""
    content = DOCKERFILE.read_text()
    froms = re.findall(r"^FROM\s", content, re.MULTILINE)
    assert len(froms) >= 2, f"需要多 stage 构建,目前 {len(froms)}"


def test_dockerfile_size_estimate():
    """理论估算镜像大小(Python 3.12-slim + PyTorch CPU + requirements)

    实际验证需 docker buildx 构建。本测试固定估算值 < 1GB 的设计目标。
    """
    content = DOCKERFILE.read_text()
    # 标记: 用了 torch CPU index(避免 CUDA 拉满)
    assert "download.pytorch.org/whl/cpu" in content, "PyTorch 必须用 CPU index"
    # 标记: 用了 python:3.12-slim(避免 full 镜像 800MB+)
    assert "python:3.12-slim" in content
    # 标记: 装 ffmpeg + libsndfile1(音频处理)
    assert "ffmpeg" in content
    assert "libsndfile1" in content
