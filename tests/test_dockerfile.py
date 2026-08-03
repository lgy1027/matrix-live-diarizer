"""Dockerfile 静态检查 — 无需 docker 即可跑"""
import re
import os
import stat
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"


def test_dockerfile_exists():
    assert DOCKERFILE.exists(), "Dockerfile 缺失"


def test_dockerfile_has_multi_stage():
    """至少 2 个 FROM(多阶段)"""
    content = DOCKERFILE.read_text(encoding="utf-8")
    froms = re.findall(r"^FROM\s", content, re.MULTILINE)
    assert len(froms) >= 2, f"需要多阶段构建,目前只有 {len(froms)} 个 FROM"


def test_dockerfile_builds_vue_frontend():
    """Docker 镜像应内置 Vue build 产物,否则 / 前端不可访问"""
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM node:20-alpine AS frontend-builder" in content
    assert "npm ci" in content
    assert "npm run build" in content
    assert "COPY --from=frontend-builder" in content
    assert "/app/web/dist" in content


def test_dockerfile_installs_requirements_after_copy():
    """运行时安装 requirements 前必须先复制并生成 Docker 专用依赖清单"""
    content = DOCKERFILE.read_text(encoding="utf-8")
    copy_pos = content.find("COPY requirements.txt /app/requirements.txt")
    filter_pos = content.find("/app/requirements.docker.txt")
    install_pos = content.find("pip install --find-links /wheels -r /app/requirements.docker.txt")
    assert copy_pos != -1, "runtime stage 应先 COPY requirements.txt"
    assert filter_pos != -1, "runtime stage 应生成 requirements.docker.txt"
    assert install_pos != -1, "runtime stage 应安装 Docker 专用 requirements"
    assert copy_pos < install_pos, "不能在 requirements.txt 不存在时执行 pip install -r"
    assert "pip install --no-cache-dir --find-links /wheels -r /app/requirements.txt 2>/dev/null || true" not in content
    assert "torch|torchvision|torchaudio" in content, "Docker 应过滤 torch 三件套,避免重复解析 CUDA 依赖"


def test_dockerfile_uses_non_root_user():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "USER " in content, "应以非 root 用户运行"


def test_dockerfile_pins_torch_family_versions():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "ARG TORCH_VERSION=2.11.0" in content
    assert "ARG TORCHVISION_VERSION=0.26.0" in content
    assert "ARG TORCHAUDIO_VERSION=2.11.0" in content
    assert '"torch==${TORCH_VERSION}"' in content
    assert '"torchvision==${TORCHVISION_VERSION}"' in content
    assert '"torchaudio==${TORCHAUDIO_VERSION}"' in content


def test_dockerfile_has_healthcheck():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "HEALTHCHECK" in content, "需要健康检查"


def test_dockerfile_targets_amd64_and_arm64():
    """Native dependency wheels must be built for the target architecture."""
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "ARG TARGETARCH" in content, "需要 ARG TARGETARCH 让 buildx 多架构构建"
    assert "FROM --platform=$TARGETPLATFORM python:3.12-slim AS builder" in content
    assert "FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder" not in content


def test_dockerfile_exposes_8000():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "EXPOSE 8000" in content, "需要 EXPOSE 8000"


# ========== compose / entrypoint / dockerignore ==========

COMPOSE = REPO_ROOT / "docker-compose.yml"
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.sh"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


def test_compose_file_exists():
    assert COMPOSE.exists()


def test_compose_has_named_volumes():
    """至少 3 个 matrix-* named volume"""
    content = COMPOSE.read_text(encoding="utf-8")
    volume_uses = re.findall(r"^\s+-\s+matrix-\w+:", content, re.MULTILINE)
    assert len(volume_uses) >= 3, f"需要 >= 3 个 named volumes,目前 {len(volume_uses)}"


def test_compose_exposes_port_8000():
    content = COMPOSE.read_text(encoding="utf-8")
    assert "${PORT:-8000}:${PORT:-8000}" in content


def test_docs_explain_multi_platform_buildx():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (REPO_ROOT / "README.en.md").read_text(encoding="utf-8")
    combined = f"{readme}\n{readme_en}"
    assert "linux/amd64,linux/arm64" in combined
    assert "docker buildx build" in combined


def test_compose_avoids_default_multi_platform_build():
    """普通 docker compose up 不应默认触发 buildx 多架构构建"""
    content = COMPOSE.read_text(encoding="utf-8")
    assert "platforms:" not in content
    assert "linux/amd64" not in content
    assert "linux/arm64" not in content


def test_entrypoint_exists_and_executable():
    assert ENTRYPOINT.exists()
    if os.name == "nt":
        pytest.skip("Windows 不保留 POSIX 可执行位")
    mode = ENTRYPOINT.stat().st_mode
    assert mode & stat.S_IXUSR, "entrypoint.sh 需要可执行"


def test_dockerignore_exists():
    assert DOCKERIGNORE.exists()


def test_dockerignore_excludes_data():
    content = DOCKERIGNORE.read_text(encoding="utf-8")
    assert "data/" in content
    assert "uploads/" in content
    assert "engine/speaker/speaker_db/" not in content
    assert "models/" in content
    assert ".venv/" in content
    assert "graphify-out/" in content


def test_healthcheck_supports_http_and_https():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "ENABLE_HTTPS" in content
    assert "https://127.0.0.1:${PORT:-8000}/health" in content
    assert "http://127.0.0.1:${PORT:-8000}/health" in content
