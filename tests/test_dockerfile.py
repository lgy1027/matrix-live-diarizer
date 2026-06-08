"""Dockerfile 静态检查 — 无需 docker 即可跑"""
import re
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"


def test_dockerfile_exists():
    assert DOCKERFILE.exists(), "Dockerfile 缺失"


def test_dockerfile_has_multi_stage():
    """至少 2 个 FROM(多阶段)"""
    content = DOCKERFILE.read_text()
    froms = re.findall(r"^FROM\s", content, re.MULTILINE)
    assert len(froms) >= 2, f"需要多阶段构建,目前只有 {len(froms)} 个 FROM"


def test_dockerfile_uses_non_root_user():
    content = DOCKERFILE.read_text()
    assert "USER " in content, "应以非 root 用户运行"


def test_dockerfile_has_healthcheck():
    content = DOCKERFILE.read_text()
    assert "HEALTHCHECK" in content, "需要健康检查"


def test_dockerfile_targets_amd64_and_arm64():
    """buildx 兼容双架构(检查有 ARG TARGETARCH)"""
    content = DOCKERFILE.read_text()
    assert "ARG TARGETARCH" in content, "需要 ARG TARGETARCH 让 buildx 多架构构建"
    assert "$BUILDPLATFORM" in content, "需要用 $BUILDPLATFORM 做 buildx 多架构"


def test_dockerfile_exposes_8000():
    content = DOCKERFILE.read_text()
    assert "EXPOSE 8000" in content, "需要 EXPOSE 8000"


# ========== compose / entrypoint / dockerignore ==========

COMPOSE = REPO_ROOT / "docker-compose.yml"
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.sh"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


def test_compose_file_exists():
    assert COMPOSE.exists()


def test_compose_has_named_volumes():
    """至少 3 个 matrix-* named volume"""
    content = COMPOSE.read_text()
    volume_uses = re.findall(r"^\s+-\s+matrix-\w+:", content, re.MULTILINE)
    assert len(volume_uses) >= 3, f"需要 >= 3 个 named volumes,目前 {len(volume_uses)}"


def test_compose_exposes_port_8000():
    content = COMPOSE.read_text()
    assert "8000:8000" in content


def test_compose_supports_multi_platform():
    content = COMPOSE.read_text()
    assert "linux/amd64" in content
    assert "linux/arm64" in content


def test_entrypoint_exists_and_executable():
    assert ENTRYPOINT.exists()
    mode = ENTRYPOINT.stat().st_mode
    assert mode & stat.S_IXUSR, "entrypoint.sh 需要可执行"


def test_dockerignore_exists():
    assert DOCKERIGNORE.exists()


def test_dockerignore_excludes_data():
    content = DOCKERIGNORE.read_text()
    assert "data/" in content
    assert "uploads/" in content
    assert "engine/speaker/speaker_db/" in content
