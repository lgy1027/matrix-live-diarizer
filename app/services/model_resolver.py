"""本地模型目录解析器。

所有模型(ASR / VAD / 声纹 / pyannote)统一放在 ``config.models.models_dir`` 下,
按分类建子目录、每个模型一个目录:

    models/
      asr/Qwen3-ASR-0.6B/
      asr/Qwen3-ForcedAligner-0.6B/
      asr/SenseVoiceSmall/          # FunASR(modelscope 缓存结构)
      vad/silero-vad/
      speaker/camplus/
      speaker/eres2net/
      speaker/wespeaker/
      pyannote/speaker-diarization-community-1/

策略(本地优先):
1. 本地目录存在且非空 → 直接返回,纯离线加载。
2. 本地空 → 下载到本地目录(HF 用 local_dir 产出干净命名目录;modelscope
   下载到其缓存后 copytree 进本地;torch.hub 同理)。各库的现有缓存
   (~/.cache/...)会被复用,所以"自动迁移 copy" = 首次 resolve 时把缓存
   里的模型物化到 models/<cat>/<name>/,之后断网可用,无需重新下载。
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger("Matrix_Models")

_COMPLETE_MARKER = ".matrix-model-complete"
_SILERO_VAD_REVISION = "76e3dc408eb2a5c655c34e230d2d5459b4439daa"


def models_root() -> str:
    """返回模型根目录的绝对路径(默认 ./models,可由 MODELS_DIR 覆盖)。"""
    return os.path.abspath(_cfg().models.models_dir)


def _cfg():
    from app.config import config  # 延迟 import,避免循环
    return config


def local_path(category: str, name: str) -> str:
    return os.path.join(models_root(), category, name)


def has_local(category: str, name: str) -> bool:
    p = local_path(category, name)
    return os.path.isdir(p) and bool(os.listdir(p))


def _ensure_parent(category: str, name: str) -> None:
    os.makedirs(os.path.dirname(local_path(category, name)), exist_ok=True)


def _new_staging_dir(dst: str) -> str:
    """Create a same-filesystem staging directory for an atomic publish."""
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    return tempfile.mkdtemp(prefix=f".{os.path.basename(dst)}.partial-", dir=parent)


def _publish_staging(staging: str, dst: str, *, source: str) -> None:
    """Publish a fully materialized model without exposing partial downloads."""
    marker = Path(staging) / _COMPLETE_MARKER
    marker.write_text(f"source={source}\n", encoding="utf-8")
    if os.path.exists(dst):
        # Callers only publish after has_local() returned false, so an existing
        # destination is empty or an abandoned pre-atomic directory.
        if os.path.isdir(dst) and not os.listdir(dst):
            os.rmdir(dst)
        else:
            raise FileExistsError(f"refusing to replace non-empty model directory: {dst}")
    os.replace(staging, dst)


def _atomic_copytree(
    src: str,
    dst: str,
    *,
    source: str,
    required_files: tuple[str, ...],
) -> None:
    """Copy a cached model into place atomically, resolving symlinks."""
    staging = _new_staging_dir(dst)
    try:
        shutil.copytree(src, staging, dirs_exist_ok=True, symlinks=False)
        _require_model_files(staging, candidates=required_files)
        _publish_staging(staging, dst, source=source)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _require_model_files(root: str, *, candidates: tuple[str, ...]) -> None:
    """Reject an apparently successful download that lacks required metadata."""
    if not any((Path(root) / candidate).is_file() for candidate in candidates):
        raise RuntimeError(
            f"model download incomplete: none of {candidates!r} found under {root}"
        )


def _validate_local_revision(root: str, revision: str | None) -> None:
    """Reject a managed local model published for a different revision.

    Legacy/manual model directories have no marker and remain supported.  All
    directories published by this resolver carry provenance and can therefore
    be checked when an operator changes a revision pin.
    """
    if not revision:
        return
    marker = Path(root) / _COMPLETE_MARKER
    if marker.is_file() and f"@{revision}" not in marker.read_text(encoding="utf-8"):
        raise RuntimeError(
            f"local model revision does not match requested revision {revision}: {root}"
        )


# ---------- HF 模型(ASR / ForcedAligner / pyannote) ----------

def resolve_hf(repo_id: str, category: str, name: str, revision: str | None = None) -> str:
    """解析 HF 模型到 models/<category>/<name>/。

    本地存在 → 返回;否则 snapshot_download(local_dir=...) 物化到本地
    (HF 会复用 ~/.cache/huggingface 里的缓存,不重新下载,实现自动迁移)。
    """
    dst = local_path(category, name)
    if has_local(category, name):
        _require_model_files(dst, candidates=("config.json",))
        _validate_local_revision(dst, revision)
        logger.info("[MODELS] HF %s/%s 已就绪(本地)", category, name)
        return dst
    _ensure_parent(category, name)
    from huggingface_hub import snapshot_download
    logger.info("[MODELS] 解析 HF %s → %s (复用缓存,物化到本地)", repo_id, dst)
    staging = _new_staging_dir(dst)
    try:
        snapshot_download(repo_id, revision=revision, local_dir=staging)
        _require_model_files(staging, candidates=("config.json",))
        _publish_staging(
            staging,
            dst,
            source=f"huggingface:{repo_id}@{revision or 'UNPINNED'}",
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return dst


# ---------- ModelScope 模型(声纹) ----------

def _modelscope_cache_dir(model_id: str) -> str | None:
    """若 modelscope 缓存里已有该 model_id,返回其目录路径(干净 org/model)。

    缓存根尊重 MODELSCOPE_CACHE 环境变量(默认 ~/.cache/modelscope)。
    """
    root = os.path.expanduser(
        os.environ.get("MODELSCOPE_CACHE", "~/.cache/modelscope") + "/hub/models"
    )
    org, _, model = model_id.partition("/")
    if not model:
        return None
    # modelscope 把 repo id 里的 '.' 替换成 '___'(如 Qwen3-ASR-0.6B → Qwen3-ASR-0___6B)
    cand = os.path.join(root, org, model.replace(".", "___"))
    return cand if os.path.isdir(cand) else None


def resolve_modelscope(model_id: str, category: str, name: str, revision: str | None = None) -> str:
    """解析 ModelScope 模型到 models/<category>/<name>/。

    本地存在 → 返回;复用 modelscope 缓存 copytree 到本地;缓存没有则下载
    (modelscope snapshot_download 返回缓存目录,再 copy 进本地)。

    容错:任何阶段失败(如测试环境 fake modelscope、网络问题)都返回 dst,
    让上层 Model.from_pretrained 决定是否降级,而不是抛异常中断引擎初始化。
    """
    dst = local_path(category, name)
    if has_local(category, name):
        _require_model_files(dst, candidates=("configuration.json", "config.json"))
        _validate_local_revision(dst, revision)
        logger.info("[MODELS] MS %s/%s 已就绪(本地)", category, name)
        return dst
    # 1) 优先从已有缓存 copytree(自动迁移)
    # A ModelScope repo cache path does not prove which revision it contains.
    # For pinned models use snapshot_download(revision=...), which still reuses
    # the library cache but verifies/resolves the requested revision itself.
    cached = _modelscope_cache_dir(model_id) if revision is None else None
    if cached:
        try:
            logger.info("[MODELS] 迁移 MS %s ← %s(缓存)", name, cached)
            _atomic_copytree(
                cached,
                dst,
                source=f"modelscope-cache:{model_id}@{revision or 'UNPINNED'}",
                required_files=("configuration.json", "config.json"),
            )
            return dst
        except Exception as e:
            logger.warning("[MODELS] 迁移 MS %s 失败,回退到下载: %s", name, e)
    # 2) 缓存没有/迁移失败 → 下载到 modelscope 缓存,再 copy
    _ensure_parent(category, name)
    try:
        from modelscope import snapshot_download as ms_dl
        logger.info("[MODELS] 下载 MS %s (revision=%s)", model_id, revision)
        downloaded = ms_dl(model_id, revision=revision) if revision else ms_dl(model_id)
        if isinstance(downloaded, str) and os.path.isdir(downloaded):
            _atomic_copytree(
                downloaded,
                dst,
                source=f"modelscope:{model_id}@{revision or 'UNPINNED'}",
                required_files=("configuration.json", "config.json"),
            )
    except Exception as e:
        # 测试环境 fake modelscope / 网络失败:返回 dst(可能空),上层降级
        logger.warning("[MODELS] %s 下载失败,返回空本地目录让上层处理: %s", name, e)
    return dst


# ---------- Silero VAD(torch.hub) ----------

def _torch_hub_vad_cache(revision: str) -> str | None:
    """Return only the torch-hub checkout for the requested revision."""
    torch_home = os.path.expanduser(
        os.environ.get("TORCH_HOME", os.path.join("~", ".cache", "torch"))
    )
    normalized = revision.replace("/", "_")
    candidate = os.path.join(
        torch_home, "hub", f"snakers4_silero-vad_{normalized}"
    )
    return candidate if os.path.isfile(os.path.join(candidate, "hubconf.py")) else None


def resolve_silero_vad(name: str = "silero-vad") -> str:
    """解析 Silero VAD 到 models/vad/<name>/。

    本地存在 → 返回;复用 torch hub 缓存 copytree;缓存没有则 torch.hub
    在线下载后 copy(可能撞 GitHub 限流,但仅首次)。
    """
    category = "vad"
    dst = local_path(category, name)
    revision = os.environ.get("SILERO_VAD_REVISION", _SILERO_VAD_REVISION)
    if has_local(category, name):
        _require_model_files(dst, candidates=("hubconf.py",))
        _validate_local_revision(dst, revision)
        logger.info("[MODELS] VAD %s 已就绪(本地)", name)
        return dst
    cached = _torch_hub_vad_cache(revision)
    if cached:
        logger.info("[MODELS] 迁移 VAD ← %s(缓存)", cached)
        _atomic_copytree(
            cached,
            dst,
            source=f"torch-hub-cache:silero-vad@{revision}",
            required_files=("hubconf.py",),
        )
        return dst
    # 缓存没有 → 在线下载到 torch hub,再 copy
    logger.info("[MODELS] VAD 本地与缓存均无,联网下载 silero-vad")
    import torch
    _ensure_parent(category, name)
    # 下载到默认 torch hub 缓存后取出路径
    torch.hub.load(
        repo_or_dir=f"snakers4/silero-vad:{revision}",
        model="silero_vad", trust_repo=True,
    )
    cached2 = _torch_hub_vad_cache(revision)
    if cached2:
        _atomic_copytree(
            cached2,
            dst,
            source=f"torch-hub:silero-vad@{revision}",
            required_files=("hubconf.py",),
        )
    return dst
